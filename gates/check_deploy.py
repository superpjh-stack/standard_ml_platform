"""G-M11(보안 · 배포) — `docker compose config` 기준 배포 규약 + Dockerfile + CORS + tests/test_auth.py.

compose(spec §17 배포 · goal G-M11):
  DB 포트 외부 비공개 · 앱 포트 하나(8200) · 헬스체크(app · db) · app 768MB · CPU 1 · OMP_NUM_THREADS=1 ·
  이미지 태그 = 커밋 SHA 변수(MLP_GIT_SHA, 기본값 없음 — 없으면 config 실패) · 비밀값은 env 파일 참조만(environment 에 값 0).
Dockerfile: 다단계(web 빌드 → python 런타임) · 베이스 이미지 정확한 태그(latest · 주 버전만 금지).
docker CLI 가 없으면 같은 항목을 YAML 정적 파싱으로 보고 그 사실을 실측란에 적는다(판정 기준은 같다).
키 해시 · 역할 4 · 다른 회사 404 · CORS 동작은 tests/test_auth.py. 실제 VPS 배포는 범위 밖(goal §2.4).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import yaml

from gatelib import ROOT, Line, pytest_gate, read, show

COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "docker" / "Dockerfile"
SHA_VAR = "MLP_GIT_SHA"
SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|_KEY$|DSN|WEBHOOK)", re.I)
MEM_768 = 768 * 1024 * 1024


def _git_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or "0000000"


def _compose_config(env_extra: dict) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != SHA_VAR}
    env.update(env_extra)
    r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "config", "--format", "json"], cwd=ROOT,
                       capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout if r.returncode == 0 else r.stderr


def _bytes(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)b?\s*", str(v).lower())
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)])


def _env_dict(env) -> dict:
    if isinstance(env, dict):
        return {k: ("" if v is None else str(v)) for k, v in env.items()}
    out = {}
    for e in env or []:
        k, _, v = str(e).partition("=")
        out[k] = v
    return out


def _limits(svc: dict) -> tuple[int | None, float | None]:
    lim = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
    mem = _bytes(svc.get("mem_limit")) or _bytes(lim.get("memory"))
    cpus = svc.get("cpus") or lim.get("cpus")
    return mem, (float(cpus) if cpus not in (None, "") else None)


def _check_services(cfg: dict, raw: dict, sha: str, how: str) -> list[str]:
    probs = []
    svcs = cfg.get("services") or {}
    app, db = svcs.get("app"), svcs.get("db")
    if not app or not db:
        return [f"서비스 app · db 필요 (있음 {sorted(svcs)})"]
    if set(svcs) - {"app", "db"}:
        probs.append(f"서비스가 app · db 밖에 더 있음 {sorted(set(svcs) - {'app', 'db'})}")
    for name, s in svcs.items():
        if s.get("network_mode") == "host":
            probs.append(f"{name}: network_mode host")
    if db.get("ports"):
        probs.append("DB 포트가 노출됨")
    ports = app.get("ports") or []
    if len(ports) != 1:
        probs.append(f"앱 포트 {len(ports)}개 (기대 1)")
    else:
        p = ports[0]
        target = str(p.get("target")) if isinstance(p, dict) else str(p).rsplit(":", 1)[-1].split("/")[0]
        if target != "8200":
            probs.append(f"앱 포트 대상 {target} (기대 8200)")
    for name, s in (("app", app), ("db", db)):
        hc = s.get("healthcheck") or {}
        if not hc.get("test") or hc.get("disable"):
            probs.append(f"{name} 헬스체크 없음")
    dep = (app.get("depends_on") or {})
    if isinstance(dep, dict) and (dep.get("db") or {}).get("condition") != "service_healthy":
        probs.append("app 이 db healthy 를 기다리지 않음")
    mem, cpus = _limits(app)
    if mem != MEM_768 or cpus != 1.0:
        probs.append(f"app 제한 {mem} B · CPU {cpus} (기대 768MB · 1)")
    env = _env_dict(app.get("environment"))
    if env.get("OMP_NUM_THREADS") != "1":
        probs.append("OMP_NUM_THREADS=1 아님")
    # 비밀값: 원본 YAML 의 environment 에 비밀 이름이 있으면 실패(값은 env 파일로만)
    for name, s in (raw.get("services") or {}).items():
        bad = [k for k in _env_dict((s or {}).get("environment")) if SECRET_KEY.search(k)]
        if bad:
            probs.append(f"{name}: environment 에 비밀 이름 {bad} — env 파일 참조만")
        if not (s or {}).get("env_file"):
            probs.append(f"{name}: env_file 참조 없음")
    raw_img = str(((raw.get("services") or {}).get("app") or {}).get("image", ""))
    if not re.search(r"\$\{" + SHA_VAR + r"(:\?|\?)", raw_img):
        probs.append(f"이미지 태그가 필수 변수 ${{{SHA_VAR}:?}} 아님 ({raw_img})")
    if how == "docker" and not str(app.get("image", "")).endswith(":" + sha):
        probs.append(f"config 결과 이미지 태그 {app.get('image')} ≠ 커밋 SHA")
    return probs


def _check_dockerfile() -> tuple[list[str], str]:
    if not DOCKERFILE.is_file():
        return ["docker/Dockerfile 없음"], ""
    txt = read(DOCKERFILE)
    froms = re.findall(r"(?im)^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", txt)
    probs = []
    if len(froms) < 2:
        probs.append(f"단계 {len(froms)} (다단계 아님)")
    for img, _ in froms:
        tag = img.rsplit(":", 1)[1] if ":" in img.split("/")[-1] else ""
        if not tag or tag == "latest" or not re.match(r"^\d+\.\d+(\.\d+)?", tag):
            probs.append(f"베이스 태그 고정 아님 {img}")
    if not re.search(r"npm (ci|run build)", txt) or not re.search(r"COPY --from=\S+ \S*dist", txt):
        probs.append("web 빌드 단계 · dist 복사 없음")
    if not re.search(r"uv sync --frozen", txt):
        probs.append("uv.lock 고정 설치(--frozen) 아님")
    if re.search(r"(?im)^\s*(ENV|ARG)\s+\S*(PASSWORD|SECRET|TOKEN|_KEY|DSN)\b", txt):
        probs.append("Dockerfile 에 비밀 ENV/ARG")
    return probs, f"Dockerfile {len(froms)}단계 [{' → '.join(i for i, _ in froms)}]"


def run() -> list[Line]:
    auth = pytest_gate("G-M11", "", "tests/test_auth.py")
    if not COMPOSE.is_file():
        return [Line("G-M11", "보안·배포", "FAIL", f"docker-compose.yml 없음 · {auth.measured}")]
    raw = yaml.safe_load(read(COMPOSE)) or {}
    sha = _git_sha()
    probs: list[str] = []
    if shutil.which("docker"):
        how = "docker"
        rc, out = _compose_config({SHA_VAR: sha})
        if rc != 0:
            return [Line("G-M11", "보안·배포", "FAIL", f"docker compose config 실패: {out.strip()[:160]}")]
        cfg = json.loads(out)
        rc2, _ = _compose_config({})
        if rc2 == 0:
            probs.append(f"{SHA_VAR} 없이도 config 성공 — 이미지 태그 기본값이 있다")
        basis = f"docker compose config(MLP_GIT_SHA={sha})"
    else:
        how = "yaml"
        cfg = raw
        basis = "docker CLI 없음 → YAML 정적 파싱(같은 항목)"
    probs += _check_services(cfg, raw, sha, how)
    dprobs, dmsg = _check_dockerfile()
    probs += dprobs
    main = read(ROOT / "src" / "mlcore" / "api" / "main.py")
    if re.search(r'allow_origins\s*=\s*\[\s*"\*"', main):
        probs.append("CORS *")
    if auth.status != "PASS":
        probs.append(auth.measured)
    ok = (f"{basis}: 서비스 app·db · DB 포트 0 · 앱 포트 1(8200) · 헬스체크 2/2 · 768MB·CPU 1 · OMP 1 · "
          f"태그=SHA 필수 변수 · 비밀 env_file 만 · {dmsg} · {auth.measured}")
    return [Line("G-M11", "보안·배포", "FAIL" if probs else "PASS", "; ".join(probs) if probs else ok)]


if __name__ == "__main__":
    raise SystemExit(show(run()))
