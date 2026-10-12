"""화면 8 · 9 · 10 e2e (G2-S01 준비, 개발2) — 1차 회사 사본(ks · sw)에서: 2차 과제가 없어도 HTTP 200 · 제목 · 페이지 오류 0 ·
1024px 가로 스크롤 0 · `_placeholder` 0 · "과제 없음" 을 그대로 보인다. 연결 정보는 conftest 의 page 장치(예전 형식 localStorage)
를 그대로 쓴다 — 콘솔이 키를 sessionStorage 로 옮긴 뒤에도 API 호출이 되는지(F16-9) 함께 본다.
(screen-map 7~10 을 아키텍트가 ○ 로 바꾸면 test_console.py 가 같은 화면을 6개사로 판정한다.)
"""
from __future__ import annotations

import pytest

from test_console import no_hscroll

pytestmark = pytest.mark.gate("G2-S01")

PHASE2 = [(8, "review", "검토 대기열 과제가 없습니다"), (9, "quotes", "견적 과제가 없습니다"), (10, "trace", None)]


@pytest.mark.parametrize("no,path,empty", PHASE2, ids=[p for _, p, _ in PHASE2])
def test_phase2_screen_renders(page, server, no, path, empty):
    resp = page.goto(f"{server.base}/app/{path}")
    assert resp is not None and resp.status == 200, (path, resp and resp.status)
    h1 = page.locator("main h1")
    h1.wait_for()
    assert h1.inner_text().startswith(f"{no}."), h1.inner_text()
    page.wait_for_load_state("networkidle")
    if empty:
        page.get_by_text(empty).first.wait_for(timeout=10000)
    assert "_placeholder" not in page.content()
    assert page.locator("[data-placeholder]").count() == 0
    ok, sw, cw = no_hscroll(page)
    assert ok, f"화면 {no} 가로 스크롤 {sw} > {cw}"
    # 키는 영구 저장소에 남지 않는다(F16-9) — 세션에만
    stored = page.evaluate("[localStorage.getItem('mlp.console.connection'), sessionStorage.getItem('mlp.console.key')]")
    assert server.keys["admin"] not in (stored[0] or "") and stored[1] == server.keys["admin"]
    assert page.errors == [], page.errors


def test_trace_screen_follows_prediction(page, server):
    """화면 2 의 예측 ID → 화면 10 추적: 모델 · run · 스냅숏이 보인다(B15 admin)."""
    import _dev2 as h
    tc = h.client(server.m)
    task = server.tasks["predict"]
    lock_inputs = tc.get(f"/api/v1/tenants/{server.code}/tasks/{task}", headers=h.hdr(server.keys["admin"])).json()
    assert lock_inputs["task"] == task
    from mlcore.registry.models import Registry
    ref = Registry().get(server.code, task)
    inputs = h.mid_inputs(h.lock_of(ref), h.lock_of(ref)["order"])
    r = tc.post(f"/api/v1/tenants/{server.code}/tasks/{task}/predict", headers=h.hdr(server.keys["operator"]), json={"inputs": inputs})
    assert r.status_code == 200, r.text
    pid = r.json()["prediction_id"]
    page.goto(f"{server.base}/app/trace?prediction_id={pid}")
    res = page.get_by_test_id("trace-result")
    res.wait_for(timeout=10000)
    text = res.inner_text()
    assert pid in text and ref.version in text and ref.snapshot_id in text
    ok, sw, cw = no_hscroll(page)
    assert ok, f"화면 10 가로 스크롤 {sw} > {cw}"
    assert page.errors == [], page.errors
