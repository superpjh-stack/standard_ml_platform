"""QA2-3 공용 — 실제 uvicorn(포트 8213)에 HTTP 요청 · 판정 행. 키 평문은 scratchpad keys.json 에서만."""
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8213"
SP = os.environ["QA_SP"]
KEYS = json.load(open(f"{SP}/keys.json"))
ROWS: list[str] = []


def h(t, role):
    return {"X-API-Key": KEYS[t][role]} if role else {}


def call(method, path, *, t, role="admin", json_body=None, files=None, data=None, content=None, headers=None, raw=False):
    hd = h(t, role); hd.update(headers or {})
    r = httpx.request(method, BASE + path, json=json_body, files=files, data=data, content=content, headers=hd, timeout=120)
    if raw:
        return r
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = r.text
    return r.status_code, body


def code_of(body):
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("code")
    return None


def check(gid, item, ok, measured, warn=False):
    v = "PASS" if ok else ("WARN" if warn else "FAIL")
    row = f"{gid}  {item}  {v}  {measured}"
    ROWS.append(row); print(row, flush=True)
    return ok


def expect(gid, item, st, body, want_status, want_code=None, extra_ok=True, extra=""):
    c = code_of(body)
    ok = st == want_status and (want_code is None or c == want_code) and extra_ok
    return check(gid, item, ok, f"HTTP {st} code={c} (기대 {want_status} {want_code or ''}) {extra}".strip())


def dump(name):
    p = Path(__file__).parent / name
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n".join(ROWS) + "\n")


class Server:
    def __init__(self, tenant, tenants_dir=None, log=None):
        env = {**os.environ, "MLP_TENANT": tenant, "OMP_NUM_THREADS": "1"}
        if tenants_dir:
            env["MLP_TENANTS_DIR"] = str(tenants_dir)
        self.log = open(log or f"{SP}/server-{tenant}.log", "w")
        self.p = subprocess.Popen([sys.executable, "-m", "uvicorn", "mlcore.api.main:app", "--host", "127.0.0.1", "--port", "8213"],
                                  cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(150):
            if self.p.poll() is not None:
                raise RuntimeError(f"기동 실패 rc={self.p.returncode}")
            try:
                if httpx.get(BASE + "/api/v1/health", timeout=1).status_code == 200:
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
        raise RuntimeError("health 없음")

    def close(self):
        self.p.terminate()
        try: self.p.wait(10)
        except Exception: self.p.kill()
        self.log.close()
