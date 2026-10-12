"""G-M11(배포) — docker-compose.yml: DB 포트 외부 비공개 · 앱 포트 하나 · 헬스체크 · 768MB/CPU 1 · OMP_NUM_THREADS=1 ·
이미지 태그 = 커밋 SHA 변수. CORS 는 설정 목록만(코드 정적). 키 해시 · 역할 4 · 다른 회사 404 는 tests/test_auth.py.
1차는 로컬 compose 설정 검사까지 — 실제 VPS 배포는 범위 밖(goal §2.4)."""
import re

import yaml

from gatelib import ROOT, Line, pytest_gate, read, show


def run() -> list[Line]:
    f = ROOT / "docker-compose.yml"
    problems = []
    if not f.is_file():
        auth = pytest_gate("G-M11", "", "tests/test_auth.py")
        return [Line("G-M11", "보안·배포", "FAIL", f"docker-compose.yml 없음 · {auth.measured}")]
    dc = yaml.safe_load(read(f)) or {}
    svcs = dc.get("services") or {}
    app = svcs.get("app") or {}
    db = svcs.get("db") or {}
    if db.get("ports"):
        problems.append("DB 포트가 노출됨")
    ports = app.get("ports") or []
    if len(ports) != 1:
        problems.append(f"앱 포트 {len(ports)}개")
    if not app.get("healthcheck"):
        problems.append("앱 헬스체크 없음")
    if str(app.get("mem_limit", "")).lower() not in ("768m", "768mb") or float(app.get("cpus", 0) or 0) != 1.0:
        problems.append("768MB · CPU 1 제한 아님")
    env = app.get("environment") or {}
    env = env if isinstance(env, dict) else dict(e.split("=", 1) for e in env)
    if str(env.get("OMP_NUM_THREADS")) != "1":
        problems.append("OMP_NUM_THREADS=1 아님")
    if not re.search(r"\$\{[A-Z_]*SHA[A-Z_]*", str(app.get("image", ""))):
        problems.append("이미지 태그가 커밋 SHA 변수 아님")
    main = read(ROOT / "src" / "mlcore" / "api" / "main.py")
    if re.search(r'allow_origins\s*=\s*\[\s*"\*"', main):
        problems.append("CORS *")
    auth = pytest_gate("G-M11", "", "tests/test_auth.py")
    if auth.status != "PASS":
        problems.append(auth.measured)
    return [Line("G-M11", "보안·배포", "FAIL" if problems else "PASS", "; ".join(problems) if problems else f"compose 규약 충족 · {auth.measured}")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
