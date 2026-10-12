"""G-M14 비기능 — `make bench` (spec §17 · goal G-M14). 기준을 낮추지 않는다.

기준: 단건 predict p95 ≤ 200ms(모델 적재 후) · batch 500 ≤ 3초 · 기동 ≤ 15초 · app RSS ≤ 768MB.
방법(회사 ks · sw 사본 각각, 시험 DB ml_test_db):
  1. 과제 YAML 그대로 실제 학습기로 학습 → stage → 승인(decide) → production (tests/_dev2.real_production — 시험과 같은 경로).
  2. uvicorn 1 프로세스(--workers 1, OMP_NUM_THREADS=1)를 띄워 **기동 = 프로세스 시작 → health 200 · 과제 전부 model_ready →
     과제 전부 첫 예측(산출물 적재 · 해시 대조) 완료**까지(health 200 시각도 따로 적는다).
  3. 적재 뒤 단건 predict N회(합성 생성기 행 — 결측 포함 실제 분포) → p50 · p95 · max.
  4. 과제마다 batch 500(같은 행 500) 3회 → 최댓값.
  5. RSS = ps 로 앱 프로세스를 0.1초마다 표본 → 최댓값.
**한계(정직하게):** docker 데몬이 없으면 compose 제한(768MB · CPU 1) **아래 측정이 아니다** — 로컬 프로세스 · 무제한 CPU.
그 사실을 실측란에 적는다(판정은 같은 기준).
기본(auto): docker 데몬이 있으면 `--compose`(같은 docker-compose.yml 의 제한 아래, cgroup 768MB · CPU 1 확인), 없으면 `--local`.
결과: outputs/bench-latest.json · 표준 출력 `G-M14  비기능  PASS|FAIL  실측`.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from gatelib import ROOT, Line, show

sys.path.insert(0, str(ROOT / "tests"))

LIMITS = {"p95_ms": 200.0, "batch500_s": 3.0, "startup_s": 15.0, "rss_mb": 768.0}
TENANTS = ("ks", "sw")
N_SINGLE = 200
N_BATCH = 3


def _rss_kb(pid: int) -> int:
    r = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip() or 0)
    except ValueError:
        return 0


class _Sampler(threading.Thread):
    def __init__(self, pid: int):
        super().__init__(daemon=True)
        self.pid, self.peak, self.stop = pid, 0, threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, _rss_kb(self.pid))
            time.sleep(0.1)


def _rows(m, task_id: str, n: int) -> list[dict]:
    """합성 생성기 행(결측 포함 실제 분포) 중 필수 변수가 다 있는 앞 n 행."""
    from mlcore.data import jobs
    from mlcore.serve.catalog import TaskCatalog
    meta = TaskCatalog(m).get(m.tenant.code, task_id).features
    feats = list(meta)
    required = [k for k, f in meta.items() if f.get("required", True) is not False]
    _, _, frame, _, _ = jobs.read_frame(m.tenant.code, task_id, source_role="demo")
    frame = frame[feats].dropna(subset=required)    # 필수 결측 행은 422(정상 거부)라 지연 측정에서 뺀다 — 선택 변수 결측(보정)은 남긴다
    out = []
    for _, row in frame.head(n).iterrows():
        d = {}
        for k, v in row.items():
            v = v.item() if hasattr(v, "item") else v
            d[k] = None if isinstance(v, float) and math.isnan(v) else v
        out.append(d)
    return out


def bench_tenant(source: str, tmp: Path) -> dict:
    import httpx

    import _dev2 as h
    m = h.make_tenant(source, tmp)
    code = m.tenant.code
    learned = [t for t, td in m.tasks.items() if td.type != "optimize"]
    t0 = time.time()
    with h.use_tenants_dir(m):
        for t in learned:
            h.real_production(m, t)
        rows = {t: _rows(m, t, 500) for t in learned}
    train_s = time.time() - t0
    keys = h.keys(m)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "MLP_TENANT": code, "MLP_TENANTS_DIR": str(h.tenants_base(m)), "OMP_NUM_THREADS": "1"}
    start = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mlcore.api.main:app", "--host", "127.0.0.1",
                             "--port", str(port), "--workers", "1", "--log-level", "warning"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    sampler = _Sampler(proc.pid)
    sampler.start()
    out: dict = {"tenant_source": source, "tasks": learned, "train_s": round(train_s, 2)}
    try:
        startup = None
        with httpx.Client(base_url=base, timeout=30, headers={"X-API-Key": keys["operator"]}) as c:
            while time.perf_counter() - start < 60:
                if proc.poll() is not None:
                    raise RuntimeError("앱 기동 실패: " + proc.stderr.read().decode()[-300:])
                try:
                    r = c.get("/api/v1/health")
                    if r.status_code == 200 and all(x["model_ready"] for x in r.json()["tasks"] if x["task"] in learned):
                        startup = time.perf_counter() - start
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            out["health_s"] = round(startup, 3) if startup is not None else None
            first = {}
            for t in learned:   # 모델 적재(첫 예측) — 기동은 과제 전부 첫 예측까지로 잰다(더 엄격)
                t1 = time.perf_counter()
                r = c.post(f"/api/v1/tenants/{code}/tasks/{t}/predict", json={"inputs": rows[t][0]})
                assert r.status_code == 200, (t, r.status_code, r.text[:200])
                first[t] = time.perf_counter() - t1
            out["startup_s"] = round(time.perf_counter() - start, 3) if startup is not None else None
            per = {}
            for t in learned:
                path = f"/api/v1/tenants/{code}/tasks/{t}/predict"
                lat = []
                for i in range(N_SINGLE):
                    body = {"inputs": rows[t][i % len(rows[t])]}
                    t1 = time.perf_counter()
                    r = c.post(path, json=body)
                    lat.append((time.perf_counter() - t1) * 1000)
                    assert r.status_code == 200, (t, r.status_code, r.text[:200])
                lat.sort()
                batch = []
                for _ in range(N_BATCH):
                    items = [{"inputs": x} for x in rows[t][:500]]
                    t1 = time.perf_counter()
                    r = c.post(path + ":batch", json={"items": items})
                    batch.append(time.perf_counter() - t1)
                    assert r.status_code == 200, (t, r.status_code, r.text[:200])
                    n_ok = len(r.json().get("items") or r.json().get("results") or [])
                per[t.split(".", 1)[1]] = {
                    "type": m.tasks[t].type, "first_ms": round(first[t] * 1000, 1),
                    "p50_ms": round(statistics.median(lat), 2), "p95_ms": round(lat[int(math.ceil(0.95 * len(lat))) - 1], 2),
                    "max_ms": round(lat[-1], 2), "batch500_s": round(max(batch), 3), "batch_items": n_ok, "n": len(lat)}
            out["per_task"] = per
    finally:
        time.sleep(0.3)
        sampler.stop.set()
        sampler.join()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    out["rss_mb"] = round(sampler.peak / 1024, 1)
    return out


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _docker_up() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0


def measure() -> dict:
    os.environ["OMP_NUM_THREADS"] = "1"
    tmp = Path(tempfile.mkdtemp(prefix="mlp-bench-"))
    res = {"limits": LIMITS, "mode": "local-uvicorn", "compose_limited": False,
           "note": "compose 제한(768MB · CPU 1) 아래 측정 아님 — 로컬 uvicorn 1 프로세스 · OMP_NUM_THREADS=1",
           "docker_daemon": _docker_up(), "platform": sys.platform,
           "tenants": [bench_tenant(s, tmp) for s in TENANTS]}
    return _finish(res)


# ── compose 제한 아래 측정(--compose) — docker 데몬이 있을 때만. 저장소에 비밀 파일을 만들지 않는다 ────────────
SETUP_IN_CONTAINER = r"""
import json, sys
from mlcore.db import seed_std
from mlcore.db.conn import connect
from mlcore import approval, auth
from mlcore.data import jobs
from mlcore.registry.models import Registry
from mlcore.serve import training
code = sys.argv[1]
seed_std.seed()
m = jobs.load_merged(code)
learned = [t for t, td in m.tasks.items() if td.type != "optimize"]
reg = Registry()
for t in learned:
    out = training.submit(code, t, actor="bench-admin", source_role="demo", seed=None)
    result, ref = training.run_and_register(out["run_id"])
    reg.stage(code, t, ref.version, actor="bench-admin")
    aid = reg.request_promotion(code, t, ref.version, actor="bench-approver", action="promote", reason=None)
    approval.decide(aid, actor="bench-approver", actor_role="approver", approve=True, reason="bench")
raw, h = auth.new_key()
with connect() as c:
    c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer) "
              "VALUES (%s,%s,%s,'operator','[]'::jsonb,'bench')", (code, h, raw[:8]))
print(json.dumps({"key": raw, "tasks": learned}))
"""


def image_tag(sha: str) -> tuple[str, bool]:
    """측정 이미지 태그. 작업 트리가 커밋과 같으면 커밋 SHA, 다르면 `<sha>-wt<트리 해시 8>` — 미커밋 트리로 빌드한 이미지에
    커밋 SHA 를 붙이지 않는다(F7-5 · #7: 이미지가 미커밋 작업 트리로 빌드됨). 배포 이미지는 `make image`(깨끗한 트리만)."""
    st = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    if not st.strip():
        return sha, False
    import hashlib
    h = hashlib.sha256(subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=ROOT, capture_output=True).stdout)
    for f in sorted(subprocess.run(["git", "ls-files", "-o", "--exclude-standard"], cwd=ROOT, capture_output=True,
                                   text=True).stdout.splitlines()):
        p = ROOT / f
        if p.is_file():
            h.update(f.encode() + b"\0" + p.read_bytes())
    return f"{sha}-wt{h.hexdigest()[:8]}", True


def _dc(proj: str, override: Path, *args, check=True, timeout=600, env=None) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-p", proj, "-f", str(ROOT / "docker-compose.yml"), "-f", str(override), *args]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:2])} 실패: {r.stderr.strip()[-300:]}")
    return r


def bench_compose(source: str, work: Path) -> dict:
    """같은 docker-compose.yml(768MB · CPU 1 · OMP 1) 로 app · db 를 띄우고, 컨테이너 안에서 학습 · 승인 → 호스트에서 잰다.
    프로젝트 이름은 mlpbench-<회사>-<실행별 고유 접미>(운영 볼륨 · 동시 실행과 섞이지 않게 — D2-70), 끝나면 down -v."""
    import secrets as _s

    import httpx

    from mlcore.data import jobs
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    pw, app_pw = _s.token_urlsafe(18), _s.token_urlsafe(18)
    envf = work / f"bench-{source}.env"            # 저장소 밖(임시 폴더) · 실행 뒤 삭제
    # 앱은 소유자(mlp)가 아니라 mlp_app 구성원 LOGIN 역할로 붙는다 — 배포와 같은 계정 모양(D-123 · D2-34, docker/initdb/20-app-login.sh)
    envf.write_text(f"POSTGRES_DB=ml_db\nPOSTGRES_USER=mlp\nPOSTGRES_PASSWORD={pw}\n"
                    f"MLP_DB_APP_USER=mlp_bench_app\nMLP_DB_APP_PASSWORD={app_pw}\n"
                    f"MLP_DB_DSN=host=db dbname=ml_db user=mlp_bench_app password={app_pw}\nMLP_TENANT={source}\nMLP_MODE=demo\n")
    # 간헐 실패 원인(웨이브 P 마감 조사): 측정 컨테이너가 호스트 8200 을 고정으로 잡았다 — 개발 서버(make run) · 앞선 실행이
    # 남긴 mlpbench-* 컨테이너가 8200 을 쥐고 있으면 `up` 이 "ports are not available" 로 실패하고(FAIL), 그 실행의 finally 가
    # 남은 것을 내려 다음 실행은 PASS 였다(자기 치유형 간헐). 측정은 배포 포트와 무관하므로 빈 루프백 포트로 붙인다
    # (`!override` — compose 파일의 8200 · 루프백 규약은 그대로, G-M11 이 본다). 시작 전에 같은 이름의 남은 프로젝트도 내린다.
    port = _free_port()
    override = work / f"bench-{source}.override.yml"
    override.write_text(f"services:\n  db:\n    env_file: [{envf}]\n  app:\n    env_file: [{envf}]\n"
                        f"    ports: !override\n      - \"127.0.0.1:{port}:8200\"\n")
    # 실행별 고유 접미(pid + 난수) — 동시에 두 번 돌아도 컨테이너 · 네트워크 · 볼륨 이름이 겹치지 않는다(D2-70). 앞의 `down -v` 는
    # 같은 이름만 내리므로 다른 실행의 프로젝트를 건드리지 않는다. 남은 잔여물(비정상 종료)은 빈 포트라 다음 실행을 막지 않는다.
    proj = f"mlpbench-{source}-{os.getpid()}-{_s.token_hex(3)}"
    tag, dirty = image_tag(sha)
    env = {**os.environ, "MLP_GIT_SHA": tag}
    out: dict = {"tenant_source": source, "image": f"mlp-app:{tag}", "dirty_tree": dirty, "host_port": port}
    try:
        _dc(proj, override, "down", "-v", "--remove-orphans", check=False, env=env, timeout=120)   # 앞선 실행이 남긴 것
        _dc(proj, override, "build", "app", env=env, timeout=900)     # 지금 작업 트리로 — 측정 시간 · up 제한시간과 분리
        _dc(proj, override, "up", "-d", "--wait", env=env, timeout=300)
        t0 = time.time()
        r = _dc(proj, override, "exec", "-T", "app", "/app/.venv/bin/python", "-c", SETUP_IN_CONTAINER, source, env=env)
        info = json.loads(r.stdout.strip().splitlines()[-1])
        out["train_in_container_s"] = round(time.time() - t0, 2)
        learned = info["tasks"]
        m = jobs.load_merged(source)
        rows = {t: _rows(m, t, 500) for t in learned}
        # 기동: 컨테이너 재시작 → health 200 · model_ready → 과제 전부 첫 예측
        _dc(proj, override, "stop", "app", env=env)
        start = time.perf_counter()
        _dc(proj, override, "start", "app", env=env)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, headers={"X-API-Key": info["key"]}) as c:
            health = None
            while time.perf_counter() - start < 60:
                try:
                    rr = c.get("/api/v1/health")
                    if rr.status_code == 200 and all(x["model_ready"] for x in rr.json()["tasks"] if x["task"] in learned):
                        health = time.perf_counter() - start
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            out["health_s"] = round(health, 3) if health is not None else None
            for t in learned:
                rr = c.post(f"/api/v1/tenants/{source}/tasks/{t}/predict", json={"inputs": rows[t][0]})
                assert rr.status_code == 200, (t, rr.status_code, rr.text[:200])
            out["startup_s"] = round(time.perf_counter() - start, 3) if health is not None else None
            per = {}
            for t in learned:
                path = f"/api/v1/tenants/{source}/tasks/{t}/predict"
                lat = []
                for i in range(N_SINGLE):
                    t1 = time.perf_counter()
                    rr = c.post(path, json={"inputs": rows[t][i % len(rows[t])]})
                    lat.append((time.perf_counter() - t1) * 1000)
                    assert rr.status_code == 200, (t, rr.status_code)
                lat.sort()
                batch = []
                for _ in range(N_BATCH):
                    t1 = time.perf_counter()
                    rr = c.post(path + ":batch", json={"items": [{"inputs": x} for x in rows[t][:500]]})
                    batch.append(time.perf_counter() - t1)
                    assert rr.status_code == 200, (t, rr.status_code)
                per[t.split(".", 1)[1]] = {"type": m.tasks[t].type, "p50_ms": round(statistics.median(lat), 2),
                                           "p95_ms": round(lat[int(math.ceil(0.95 * len(lat))) - 1], 2),
                                           "max_ms": round(lat[-1], 2), "batch500_s": round(max(batch), 3), "n": len(lat)}
            out["per_task"] = per
        hwm = _dc(proj, override, "exec", "-T", "app", "sh", "-c",
                  "grep VmHWM /proc/1/status; cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/cpu.max", env=env).stdout.split()
        out["rss_mb"] = round(int(hwm[1]) / 1024, 1)                  # 앱 프로세스(PID 1 uvicorn) 최대 RSS
        out["cgroup_memory_max"] = hwm[3]
        out["cgroup_cpu_max"] = " ".join(hwm[4:6])
    finally:
        _dc(proj, override, "down", "-v", "--remove-orphans", check=False, env=env)
        envf.unlink(missing_ok=True)
        override.unlink(missing_ok=True)
    return out


def measure_compose() -> dict:
    work = Path(tempfile.mkdtemp(prefix="mlp-bench-compose-"))
    res = {"limits": LIMITS, "mode": "compose", "compose_limited": True,
           "note": "docker compose 제한 아래(app 768MB · CPU 1 · OMP_NUM_THREADS=1, 이미지 = 커밋 SHA · 미커밋 트리면 <sha>-wt<해시>, 빈 루프백 포트)",
           "platform": sys.platform, "tenants": [bench_compose(s, work) for s in TENANTS]}
    return _finish(res)


def _finish(res: dict) -> dict:
    agg = {"p95_ms": max(t["p95_ms"] for x in res["tenants"] for t in x["per_task"].values()),
           "batch500_s": max(t["batch500_s"] for x in res["tenants"] for t in x["per_task"].values()),
           "startup_s": max((x["startup_s"] if x["startup_s"] is not None else math.inf) for x in res["tenants"]),
           "rss_mb": max(x["rss_mb"] for x in res["tenants"])}
    res["worst"] = agg
    res["pass"] = {k: agg[k] <= LIMITS[k] for k in LIMITS}
    (ROOT / "outputs").mkdir(exist_ok=True)
    name = "bench-compose-latest.json" if res.get("compose_limited") else "bench-latest.json"
    (ROOT / "outputs" / name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def run(compose: bool = False) -> list[Line]:
    try:
        res = measure_compose() if compose else measure()
    except Exception as e:  # noqa: BLE001 — 측정 실패는 FAIL 로 보인다
        return [Line("G-M14", "비기능", "FAIL", f"bench 실패 {type(e).__name__}: {str(e)[:160]}")]
    w, ok = res["worst"], res["pass"]
    n_tasks = sum(len(x["per_task"]) for x in res["tenants"])
    bad = [k for k, v in ok.items() if not v]
    msg = (f"최악값(ks·sw 과제 {n_tasks}) 단건 p95 {w['p95_ms']}ms(≤200) · batch500 {w['batch500_s']}s(≤3) · "
           f"기동 {w['startup_s']}s(≤15) · RSS {w['rss_mb']}MB(≤768) — {res['note']}")
    if bad:
        msg = f"기준 초과 {bad} · " + msg
    return [Line("G-M14", "비기능", "FAIL" if bad else "PASS", msg)]


if __name__ == "__main__":
    mode = "compose" if "--compose" in sys.argv else "local" if "--local" in sys.argv else "auto"
    lines = run(compose=_docker_up() if mode == "auto" else mode == "compose")
    raise SystemExit(show(lines))
