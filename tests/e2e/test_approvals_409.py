"""G-M09 · G-S03 화면 5 — 두 탭이 같은 승인을 결정할 때 늦은 탭에 409 안내가 **남는다** (DEF-QA3-005). 소유 개발2.

재현(QA3 t05_ui.py): 탭 A(approver) · 탭 B(admin) 가 같은 대기 카드를 연 뒤 A 승인 → B 승인.
서버는 B 에 409 already_decided 를 내고, 화면은 목록을 다시 읽어 카드를 지운다 — 그래도 B 화면에는
"이미 결정된 승인" 안내가 보여야 한다(screen-map 5 "409 처리").
"""
from __future__ import annotations

import json
import urllib.request

import pytest

import _dev2 as h
from mlcore.registry.models import Registry

pytestmark = pytest.mark.gate("G-S03")


def _post(server, path: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(server.base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _pending_recommendation(server) -> str:
    """화면 3 과 같은 optimize 1회 → 추천 승인 요청(kind=recommendation, pending) 1건."""
    m = server.m
    opt = server.tasks["optimize"]
    td = m.tasks[opt]
    dep = next(t for t in m.tasks if t.split(".", 1)[1] == td.raw["uses"][0].split(".", 1)[1])
    lock = h.lock_of(Registry().get(server.code, dep))
    fixed = h.mid_inputs(lock, [n for n in td.raw["fixed"] if n in lock["features"]])
    out = _post(server, f"/api/v1/tenants/{server.code}/tasks/{opt.split('.', 1)[1]}/optimize", server.keys["operator"],
                {"fixed": fixed})
    rec = out["recommendation"]["rec_id"]
    with h.connect() as c:
        return c.execute("SELECT approval_id FROM mlp_approval WHERE tenant_id = %s AND ref_id = %s",
                         (server.code, rec)).fetchone()["approval_id"]


def _tab(browser, server, key: str):
    ctx = browser.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR")
    ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
                        % json.dumps({"tenant": server.code, "key": key}))
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    return ctx, pg


def test_two_tabs_late_decide_keeps_409_notice(browser, server):
    aid = _pending_recommendation(server)
    ca, a = _tab(browser, server, server.keys["approver"])
    cb, b = _tab(browser, server, server.keys["admin"])
    try:
        for pg in (a, b):
            pg.goto(f"{server.base}/app/approvals")
            pg.locator(f'.card[data-approval="{aid}"]').wait_for(timeout=15000)
        a.locator(f'.card[data-approval="{aid}"] button.primary').click()
        a.get_by_test_id("approval-outcome").wait_for(timeout=15000)
        assert "승인됨" in a.get_by_test_id("approval-outcome").inner_text()
        b.locator(f'.card[data-approval="{aid}"] button.primary').click()
        box = b.get_by_test_id("approval-outcome")
        box.wait_for(timeout=15000)
        b.locator(f'.card[data-approval="{aid}"]').wait_for(state="detached", timeout=15000)   # 목록은 다시 읽었다
        assert box.get_attribute("data-approval") == aid
        assert box.locator('[data-code="already_decided"]').count() == 1, box.inner_text()   # 카드가 사라져도 안내는 남는다
        assert "이미 결정" in box.inner_text()
        assert a.errors == [] and b.errors == [], (a.errors, b.errors)
    finally:
        ca.close()
        cb.close()
