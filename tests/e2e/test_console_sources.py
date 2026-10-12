"""화면 7 — 데이터 소스 · 스냅숏 e2e (G2-S01 준비, 개발1). 1차 회사 사본(ks · sw)에서:
HTTP 200 · 제목 `7.` · 소스별 doctor 결과(연결 · 미연결 · 대응률 · 목표 · 기간)가 API 응답 그대로 · 학습된 과제의 스냅숏
(행 · 기간 · sha256 · 합성 배지)이 등록부 · run 과 같다 · 1024px 가로 스크롤 0 · `_placeholder` 0 · 페이지 오류 0.
기대값은 화면 코드가 아니라 API(B14 doctor · B07 models · B08 runs) 응답에서 가져온다.
"""
from __future__ import annotations

import pytest

from test_console import no_hscroll

pytestmark = pytest.mark.gate("G2-S01")


def choose(page, task_id: str) -> None:
    sel = page.locator("label.picker select")
    sel.wait_for()
    page.wait_for_function("t => [...document.querySelectorAll('label.picker option')].some(o => o.value === t)", arg=task_id)
    sel.select_option(task_id)


def _get(server, path, role="admin"):
    import _dev2 as h
    r = h.client(server.m).get(path, headers=h.hdr(server.keys[role]))
    assert r.status_code == 200, r.text
    return r.json()


def test_sources_screen_shows_doctor_and_snapshots(page, server):
    doc = _get(server, f"/api/v1/tenants/{server.code}/doctor")
    resp = page.goto(f"{server.base}/app/sources")
    assert resp is not None and resp.status == 200
    h1 = page.locator("main h1")
    h1.wait_for()
    assert h1.inner_text().startswith("7."), h1.inner_text()
    table = page.get_by_test_id("doctor-sources")
    table.wait_for(timeout=10000)
    for s in doc["sources"]:
        row = table.locator(f"tr[data-role='{s['role']}']")
        assert row.count() == 1, s["role"]
        text = row.inner_text()
        assert s["status"] in text and (s["kind"] or "") in text
        if s.get("rows") is not None:
            assert f"{s['rows']:,}" in text
        if s.get("target"):
            assert s["target"] in text
        assert row.get_attribute("data-status") == s["status"]
    # 스냅숏 — 학습된 과제(production 있음)의 모델 버전이 쓴 스냅숏
    task = server.tasks["predict"]
    choose(page, task)
    models = _get(server, f"/api/v1/tenants/{server.code}/tasks/{task}/models")["items"]
    assert models
    snaps = page.get_by_test_id("snapshots")
    snaps.wait_for(timeout=10000)
    for m in models:
        run = _get(server, f"/api/v1/runs/{m['run_id']}")
        row = snaps.locator(f"tr[data-snapshot='{m['snapshot_id']}']")
        row.wait_for(timeout=10000)
        text = row.inner_text()
        assert f"{run['snapshot']['rows']:,}" in text and run["snapshot"]["sha256"][:12] in text and m["version"] in text
        assert ("합성" in text) == bool(run["snapshot"]["synthetic"])
    assert "_placeholder" not in page.content() and page.locator("[data-placeholder]").count() == 0
    ok, sw, cw = no_hscroll(page)
    assert ok, f"화면 7 가로 스크롤 {sw} > {cw}"
    assert page.errors == [], page.errors


def test_sources_screen_viewer_is_refused(page, server):
    """화면 7 은 admin · approver(조회) — viewer 키로는 API 가 403 을 내고 화면은 그대로 보인다(숨기지 않는다)."""
    page.goto(f"{server.base}/app/sources")
    page.locator("main h1").wait_for()
    page.get_by_test_id("doctor-sources").wait_for(timeout=10000)
    page.locator("form.conn input[type=password]").fill(server.keys["viewer"])     # 연결 막대에서 키를 바꾼다
    page.locator("main h1").wait_for()
    page.locator("[role=alert][data-code='forbidden']").first.wait_for(timeout=10000)
    assert page.errors == [], page.errors
