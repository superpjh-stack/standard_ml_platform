"""QA3 t05 — 실제 chromium 으로 화면 2 · 3 · 5 조작(서버 MLP_TENANT=ks). 두 탭 동시 승인 · 오류 · 범위 밖 · 불가능 제약 · 역할 표시.
스크린샷 → outputs/e2e/qa3-ui-*.png"""
import json
import sys
from pathlib import Path

import psycopg
from playwright.sync_api import sync_playwright

from qa_lib import BASE, KEYS, call, check, dump

OUT = Path(__file__).resolve().parents[1] / "e2e"
DSN = "dbname=ml_qa3_db host=/tmp"


def prod(task):
    with psycopg.connect(DSN) as c:
        return [r[0] for r in c.execute("SELECT version FROM mlp_model_version WHERE task_id=%s AND stage='production'", (task,))]


def ctx_for(b, role, w=1024, h=768, tenant="ks"):
    ctx = b.new_context(viewport={"width": w, "height": h}, locale="ko-KR")
    ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
                        % json.dumps({"tenant": tenant, "key": KEYS[tenant][role]}))
    pg = ctx.new_page()
    pg.errs = []
    pg.on("pageerror", lambda e: pg.errs.append(str(e)[:200]))
    pg.on("console", lambda m: pg.errs.append(f"console.{m.type}: {m.text[:150]}") if m.type == "error" else None)
    return ctx, pg


def hscroll(pg):
    return pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")


with sync_playwright() as p:
    b = p.chromium.launch()
    # ── 화면 2 ──
    for w in (1024, 390):
        ctx, pg = ctx_for(b, "operator", w=w, h=844 if w == 390 else 768)
        pg.goto(f"{BASE}/app/predict"); pg.wait_for_selector("#f-press_force")
        pg.click("button.primary"); pg.wait_for_selector("[data-testid=predict-result]")
        t = pg.inner_text("[data-testid=predict-result]")
        pg.screenshot(path=str(OUT / f"qa3-ui-predict-ok-{w}.png"), full_page=True)
        check("G-S03", f"화면2 예측({w}px) 값 · 상태 · 모델 버전 · 합성 배지", "예측값" in t and "v1" in t and "합성" in t and "synthetic_model" in t,
              f"합성={'합성' in t} 버전v1={'v1' in t} 가로스크롤={hscroll(pg)} 오류={pg.errs}")
        check("G-S03", f"화면2 {w}px 가로 스크롤 0", not hscroll(pg), f"{hscroll(pg)}", warn=(w == 390))
        pg.fill("#f-press_force", "181"); pg.click("button.primary"); pg.wait_for_selector("[data-testid=predict-result]")
        t = pg.inner_text("[data-testid=predict-result]")
        oor_cls = pg.eval_on_selector("#f-press_force", "e => e.closest('.field').className")
        pg.screenshot(path=str(OUT / f"qa3-ui-predict-oor-{w}.png"), full_page=True)
        check("G-S03", f"화면2 학습 범위 밖 표시({w}px)", "out_of_range" in t and "press_force" in t and "field-oor" in oor_cls, f"cls={oor_cls}")
        pg.fill("#f-press_force", "999"); pg.click("button.primary"); pg.wait_for_timeout(800)
        e = pg.query_selector("div.error[data-code]")
        code = e.get_attribute("data-code") if e else None
        pg.screenshot(path=str(OUT / f"qa3-ui-predict-oob-{w}.png"), full_page=True)
        check("G-S03", f"화면2 min/max 밖 → 오류 상자 out_of_bounds({w}px)", code == "out_of_bounds", f"code={code} 결과카드={bool(pg.query_selector('[data-testid=predict-result]'))}")
        check("G-S03", f"화면2 콘솔 · 페이지 오류({w}px)", not [x for x in pg.errs if "422" not in x and "Failed to load resource" not in x], f"{pg.errs}")
        ctx.close()
    # viewer — 예측 403
    ctx, pg = ctx_for(b, "viewer")
    pg.goto(f"{BASE}/app/predict"); pg.wait_for_selector("#f-press_force")
    pg.click("button.primary"); pg.wait_for_timeout(800)
    e = pg.query_selector("div.error[data-code]")
    pg.screenshot(path=str(OUT / "qa3-ui-predict-viewer-1024.png"), full_page=True)
    check("G-S03", "화면2 viewer → 403 forbidden 표시", e is not None and e.get_attribute("data-code") == "forbidden", f"{e.get_attribute('data-code') if e else None}")
    ctx.close()
    # ── 화면 3 ──
    ctx, pg = ctx_for(b, "operator")
    pg.goto(f"{BASE}/app/optimize"); pg.wait_for_selector("button.primary"); pg.wait_for_timeout(800)
    notice = pg.inner_text("body")
    pg.click("button.primary"); pg.wait_for_timeout(1500)
    t = pg.inner_text("body")
    pg.screenshot(path=str(OUT / "qa3-ui-optimize-ok-1024.png"), full_page=True)
    check("G-S03", "화면3 추천 · '설비로 내려가지 않음' · 가로 스크롤 0", "설비로 내려가지 않습니다" in notice and "needs_approval" in t and not hscroll(pg),
          f"needs_approval={'needs_approval' in t} hscroll={hscroll(pg)} 오류={pg.errs}")
    for name, val in (("reserve_hours", "150"), ("max_cost_index", "1")):
        pg.fill(f"#p-{name}", val)
    pg.click("button.primary"); pg.wait_for_timeout(1500)
    t = pg.inner_text("body")
    pg.screenshot(path=str(OUT / "qa3-ui-optimize-infeasible-1024.png"), full_page=True)
    check("G-S03", "화면3 불가능 제약 → least_violation · 검토 필요 표시", "least_violation" in t and "검토" in t and "needs_approval" not in t.split("추천 조건 찾기")[-1],
          f"least={'least_violation' in t}")
    ctx.close()
    ctx, pg = ctx_for(b, "operator", w=390, h=844)
    pg.goto(f"{BASE}/app/optimize"); pg.wait_for_selector("button.primary"); pg.wait_for_timeout(600)
    pg.click("button.primary"); pg.wait_for_timeout(1500)
    pg.screenshot(path=str(OUT / "qa3-ui-optimize-ok-390.png"), full_page=True)
    check("G-S03", "화면3 390px 가로 스크롤", not hscroll(pg), f"hscroll={hscroll(pg)} sw={pg.evaluate('document.documentElement.scrollWidth')}", warn=True)
    ctx.close()
    # ── 화면 5 두 탭 동시 승인 ──
    P = "/api/v1/tenants/ks/tasks/remaining_hours"
    st, bd = call("GET", f"{P}/models", role="admin")
    v = [i["version"] for i in bd["items"] if i["stage"] == "candidate"][0]
    call("POST", f"{P}/models/{v}/stage", role="admin")
    st, bd = call("POST", f"{P}/models/{v}/promote", role="approver", json_body={"reason": "qa3 두 탭"})
    aid = bd["approval_id"]
    before = prod("ks.remaining_hours")
    c1, a = ctx_for(b, "approver")
    c2, bb = ctx_for(b, "admin")
    for pg in (a, bb):
        pg.goto(f"{BASE}/app/approvals"); pg.wait_for_selector(f"[data-approval='{aid}']")
    a.screenshot(path=str(OUT / "qa3-ui-approvals-tabA-before-1024.png"), full_page=True)
    a.click(f"[data-approval='{aid}'] button.primary"); a.wait_for_timeout(1200)
    after_a = prod("ks.remaining_hours")
    bb.click(f"[data-approval='{aid}'] button.primary"); bb.wait_for_timeout(1200)
    e = bb.query_selector("div.error[data-code]")
    codeb = e.get_attribute("data-code") if e else None
    bb.screenshot(path=str(OUT / "qa3-ui-approvals-tabB-409-1024.png"), full_page=True)
    a.screenshot(path=str(OUT / "qa3-ui-approvals-tabA-after-1024.png"), full_page=True)
    check("G-M09", "화면5 두 탭: A 승인 → B 승인 클릭 409 already_decided 표시", codeb == "already_decided" and after_a == [v] and prod("ks.remaining_hours") == [v],
          f"이전 production={before} A 뒤={after_a} B 오류={codeb} 최종={prod('ks.remaining_hours')}")
    left = bb.query_selector(f"[data-approval='{aid}'] button.primary")
    check("G-M09", "화면5 409 뒤 B 탭 목록 새로 고침(대기 카드 사라짐)", left is None, f"버튼 남음={left is not None}", warn=True)
    check("G-S03", "화면5 콘솔 · 페이지 오류", not [x for x in a.errs + bb.errs if "409" not in x and "Failed to load resource" not in x], f"{a.errs + bb.errs}")
    c1.close(); c2.close()
    # operator 조회만 · viewer
    ctx, pg = ctx_for(b, "operator")
    st, bd = call("POST", "/api/v1/tenants/ks/tasks/maintenance_timing/optimize", role="operator",
                  json_body={"fixed": {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39,
                                       "cycle_time": 9.5, "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}})
    pg.goto(f"{BASE}/app/approvals"); pg.wait_for_timeout(1500)
    btn = pg.query_selector("[data-kind=recommendation] button.primary")
    if btn:
        btn.click(); pg.wait_for_timeout(800)
    e = pg.query_selector("[data-kind=recommendation] div.error[data-code]")
    pg.screenshot(path=str(OUT / "qa3-ui-approvals-operator-1024.png"), full_page=True)
    check("G-S03", "화면5 operator(조회만) — 승인 버튼 노출 여부 · 누르면 403", (btn is None) or (e is not None and e.get_attribute("data-code") == "forbidden"),
          f"버튼 노출={btn is not None} 결과={e.get_attribute('data-code') if e else None}", warn=True)
    ctx.close()
    ctx, pg = ctx_for(b, "viewer")
    pg.goto(f"{BASE}/app/approvals"); pg.wait_for_timeout(1200)
    e = pg.query_selector("div.error[data-code]")
    pg.screenshot(path=str(OUT / "qa3-ui-approvals-viewer-1024.png"), full_page=True)
    check("G-S03", "화면5 viewer → forbidden 표시", e is not None and e.get_attribute("data-code") == "forbidden", f"{e.get_attribute('data-code') if e else None}")
    ctx.close()
    # 미연결 — 키 없음
    ctx = b.new_context(viewport={"width": 1024, "height": 768}); pg = ctx.new_page()
    pg.goto(f"{BASE}/app/overview"); pg.wait_for_timeout(1000)
    t = pg.inner_text("body")
    pg.screenshot(path=str(OUT / "qa3-ui-overview-nokey-1024.png"), full_page=True)
    check("G-S03", "키 없는 첫 방문 안내", "API 키를 넣으세요" in t, f"{'API 키를 넣으세요' in t}")
    ctx.close()
    b.close()
dump(sys.argv[1])
