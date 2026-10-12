"""화면 e2e 공용 (G-S03 · D-40) — Playwright(Python, `playwright==1.63.0` 고정) + 실제 uvicorn 프로세스.

- 시험 DB(ml_test_db)에 회사 사본(새 코드)을 만들고, 화면 2 · 3 이 실제 응답을 받도록 의존 과제를 실제 학습기로
  학습 → 승인해 production 으로 둔다(tests/_dev2.py — 다른 시험과 같은 도우미 · 같은 모듈 객체).
- 앱은 `web/dist` 를 `/app/*` 로 제공한다. dist 가 없거나 web/src 보다 오래됐으면 `npm run build` 를 한 번 한다.
- 브라우저는 Playwright 기본 캐시의 chromium(1.63.0 = r1243). 없으면 `uv run playwright install chromium` 1회.
  설치 · 실행이 안 되면 시험은 **실패**한다(건너뛰지 않는다 — 가짜 PASS 금지).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import _dev2 as h  # noqa: E402  (시험 DB · 임시 산출물 폴더 환경을 먼저 잡는다)

WEB = ROOT / "web"
DIST = WEB / "dist" / "index.html"
# 회사별 화면 2 · 3 에 쓸 과제(접미) — 의존 과제는 실제 학습 → 승인
CASES = {
    "ks": {"predict": "remaining_hours", "optimize": "maintenance_timing", "train": ["remaining_hours"]},
    "sw": {"predict": "delta_e", "optimize": "print_setpoint", "train": ["delta_e", "defect_risk"]},
}


def _ensure_build() -> None:
    newest = max(p.stat().st_mtime for p in (WEB / "src").rglob("*") if p.is_file())
    if DIST.is_file() and DIST.stat().st_mtime >= newest:
        return
    r = subprocess.run(["npm", "run", "build"], cwd=WEB, capture_output=True, text=True)
    assert r.returncode == 0, f"npm run build 실패: {r.stderr[-400:]}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, m, keys: dict[str, str], tasks: dict[str, str]):
        self.m, self.keys, self.tasks = m, keys, tasks
        self.code = m.tenant.code
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {**os.environ, "MLP_TENANT": self.code, "MLP_TENANTS_DIR": str(h.tenants_base(m)), "OMP_NUM_THREADS": "1"}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mlcore.api.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"앱 기동 실패: {self.proc.stderr.read().decode()[-400:]}")
            try:
                with urllib.request.urlopen(self.base + "/api/v1/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("앱이 30초 안에 health 200 을 내지 않았다")

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    _ensure_build()
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="session", params=sorted(CASES))
def server(request, tmp_path_factory):
    if not h.db_ok():
        pytest.fail("시험 DB(ml_test_db) 에 연결할 수 없다 — make setup")
    source = request.param
    m = h.make_tenant(source, tmp_path_factory.mktemp(f"e2e-{source}"))
    code = m.tenant.code
    for short in CASES[source]["train"]:
        h.real_production(m, f"{code}.{short}")
    s = Server(m, h.keys(m), {k: f"{code}.{v}" for k, v in CASES[source].items() if k != "train"})
    s.source = source
    yield s
    s.close()


@pytest.fixture()
def page(browser, server):
    """1024 × 768(현장 태블릿 폭) · 연결 정보는 localStorage 에만(콘솔 규칙). 페이지 오류는 모아 시험이 본다."""
    ctx = browser.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR")
    ctx.add_init_script(
        "localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
        % ('{"tenant": "%s", "key": "%s"}' % (server.code, server.keys["admin"])))
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()
