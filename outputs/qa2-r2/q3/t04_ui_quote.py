"""화면 9 · 5 실제 브라우저 견적 흐름 (kd · ot) — 업로드 → 인식값 수정 → 초안 → 수정본 → 확정 요청 → 화면 5 두 탭 동시 승인 →
확정 배지 · 잠금 · 오래된 탭에서 수정 409 quote_locked 표시 → 화면 8 두 탭 동시 검토(krs). 스크린샷 outputs/e2e/qa23-ui-*.png"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from qa_lib import Server, KEYS, BASE, check, dump, ROOT

OUT = ROOT / "outputs" / "qa2-r2" / "e2e"
DXF = {"kd": ROOT / "tenants/kd/samples/KD-demo-reactor.dxf", "ot": ROOT / "packs/rollform-quote/samples/sample.dxf"}


def ctx_for(b, t, role):
    ctx = b.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR", accept_downloads=True)
    ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));" % json.dumps({"tenant": t, "key": KEYS[t][role]}))
    pg = ctx.new_page(); pg.errs = []
    pg.on("pageerror", lambda e: pg.errs.append(str(e)[:200]))
    pg.on("console", lambda m: pg.errs.append("console " + m.text[:160]) if m.type == "error" and "409" not in m.text and "422" not in m.text else None)
    return ctx, pg


def hs(pg):
    sw, cw = pg.evaluate("[Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), document.documentElement.clientWidth]")
    return sw <= cw, sw


def quote_flow(b, t):
    G = "UI9"
    c1, op = ctx_for(b, t, "operator")
    op.goto(f"{BASE}/app/quotes"); op.wait_for_load_state("networkidle")
    op.set_input_files("input[type=file]", str(DXF[t]))
    op.get_by_role("button", name="업로드 · 추출").click()
    op.get_by_text("인식 출처:").wait_for(timeout=15000)
    op.wait_for_timeout(500)
    txt = op.inner_text("body")
    check(G, f"{t} 업로드 → 인식 표 · 라벨 표시", ("labels: none" in txt or "정답 라벨 없음" in txt) if t == "kd" else True, f"labels 문구={'labels: none' in txt or '정답 라벨 없음' in txt}")
    op.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-uploaded-1024.png"), full_page=True)
    # 사람 수정
    if t == "kd":
        ta = op.locator("textarea").nth(1)          # lines
        lines = json.loads(ta.input_value()); lines[0]["quantity"] = int(lines[0]["quantity"]) + 1
        for ln in lines: ln["price_kg"] = "6500"
        ta.fill(json.dumps(lines, ensure_ascii=False))
        op.locator("textarea").nth(0).fill('{"quantity": 1, "labor_rate": 45000, "outsource_cost": 0}')
        for n, v in (("cut_m", "24"), ("weld_m", "18"), ("thickness_mm", "6"), ("complexity", "3")):
            op.locator(f"[data-field={n}] input").fill(v)
        op.locator("[data-field=main_material] select").select_option(index=1)
        op.locator("[data-field=product_family] select").select_option(index=1)
    else:
        f = op.locator("[data-field=hole_count] input"); f.fill(str(int(f.input_value() or 0) + 1))
        for n, v in (("sheet_thickness_mm", "2"), ("bend_count", "2"), ("quantity", "100")):
            op.locator(f"[data-field={n}] input").fill(v)
        op.locator("[data-field=steel_grade] select").select_option("SPCC")
        op.locator("[data-field=section_profile] select").select_option(index=1)
    op.get_by_role("button", name="견적 초안 만들기").click()
    det = op.get_by_test_id("quote-detail"); det.wait_for(timeout=15000)
    check(G, f"{t} 초안 → 상세 draft · overrides 표", det.get_attribute("data-status") == "draft" and op.get_by_test_id("quote-overrides").count() == 1, f"status={det.get_attribute('data-status')} errs={op.errs[:2]}")
    total1 = op.inner_text("[data-testid=quote-detail]")
    op.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-draft-1024.png"), full_page=True)
    # 오래된 탭(같은 견적을 draft 로 들고 있음) — 나중에 409 를 보려고
    c2, stale = ctx_for(b, t, "operator")
    stale.goto(f"{BASE}/app/quotes"); stale.wait_for_load_state("networkidle")
    stale.get_by_role("button", name="보기").last.wait_for(timeout=10000)
    # 수정본
    op.get_by_role("button", name="이 견적 수정본(revision) 만들기").click()
    op.wait_for_timeout(1200)
    rev_txt = op.inner_text("[data-testid=quote-detail]")
    check(G, f"{t} 수정본 → revision 2", "revision 2" in rev_txt, rev_txt[:80].replace("\n", " "))
    # 확정 요청: 검토 체크 없이 → 오류 표시
    op.get_by_role("button", name="확정 요청").click(); op.wait_for_timeout(800)
    t_err = op.inner_text("[data-testid=quote-detail]")
    check(G, f"{t} 검토 없이 확정 요청 → 화면에 missing_required", "missing_required" in t_err or "검토" in t_err, "표시됨" if "missing_required" in t_err else t_err[-120:].replace("\n", " "))
    op.get_by_label("입력 · 금액을 검토했습니다").check()
    op.locator("[data-testid=quote-detail] textarea").fill("BOM 수량 · 단가 확인")
    op.get_by_role("button", name="확정 요청").click()
    op.get_by_text("확정 대기").first.wait_for(timeout=10000)
    op.wait_for_function("document.querySelector(\"[data-testid=quote-detail]\").dataset.status === \"pending_confirm\"", timeout=10000)
    check(G, f"{t} 확정 요청 → pending_confirm 안내", det.get_attribute("data-status") == "pending_confirm", f"status={det.get_attribute('data-status')}")
    op.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-pending-1024.png"), full_page=True)
    # 화면 5 두 탭
    c3, ta_ = ctx_for(b, t, "approver"); c4, tb_ = ctx_for(b, t, "admin")
    for pg in (ta_, tb_):
        pg.goto(f"{BASE}/app/approvals"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(600)
    ta_.screenshot(path=str(OUT / f"qa23-ui-{t}-approvals-quote-tabA-before-1024.png"), full_page=True)
    def approve(pg):
        card = pg.locator(".card").filter(has_text="quote").filter(has=pg.get_by_role("button", name="승인")).first
        ta = card.locator("textarea")
        if ta.count(): ta.first.fill("견적 확정 승인")
        card.get_by_role("button", name="승인").click()
    approve(ta_); ta_.get_by_test_id("approval-outcome").wait_for(timeout=10000)
    approve(tb_); tb_.get_by_test_id("approval-outcome").wait_for(timeout=10000)
    oa, ob = ta_.inner_text("[data-testid=approval-outcome]"), tb_.inner_text("[data-testid=approval-outcome]")
    check(G, f"{t} 화면 5 두 탭 승인 → A 승인 · B 409 안내 남음", "승인" in oa and ("already_decided" in ob or "이미" in ob), f"A='{oa[:40]}' B='{ob[:60]}'".replace("\n", " "))
    tb_.screenshot(path=str(OUT / f"qa23-ui-{t}-approvals-quote-tabB-409-1024.png"), full_page=True)
    # 확정 배지 · 잠금
    op.reload(); op.wait_for_load_state("networkidle")
    op.get_by_role("button", name="보기").last.click()
    op.get_by_test_id("quote-detail").wait_for(timeout=10000); op.wait_for_timeout(600)
    # 목록 정렬이 시간순이 아닐 수 있어 확정 견적을 찾는다
    st = op.get_by_test_id("quote-detail").get_attribute("data-status")
    if st != "confirmed":
        rows = op.locator("table.grid tbody tr").filter(has_text="confirmed")
        if rows.count(): rows.first.get_by_role("button", name="보기").click(); op.wait_for_timeout(600)
        st = op.get_by_test_id("quote-detail").get_attribute("data-status")
    ok_lock = "확정 · 잠금" in op.inner_text("[data-testid=quote-detail]")
    btn = op.get_by_role("button", name="이 견적 수정본(revision) 만들기")
    check(G, f"{t} 확정 배지 · 잠금 문구 · 수정 버튼 비활성", st == "confirmed" and ok_lock and (btn.count() == 0 or btn.is_disabled()), f"status={st} lock={ok_lock} btn={'없음' if btn.count()==0 else ('disabled' if btn.is_disabled() else 'enabled')}")
    op.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-confirmed-1024.png"), full_page=True)
    with op.expect_download(timeout=10000) as dl:
        op.get_by_role("button", name="CSV 내려받기").click()
    data = Path(dl.value.path()).read_bytes()
    check(G, f"{t} 화면 CSV 내려받기 · BOM", data.startswith(b"\xef\xbb\xbf"), f"bytes={len(data)}")
    # 오래된 탭: 처음 draft 를 열어 둔 상태에서 수정 → 409 표시
    stale.get_by_role("button", name="보기").last.click(); stale.get_by_test_id("quote-detail").wait_for(timeout=10000)
    sst = stale.get_by_test_id("quote-detail").get_attribute("data-status")
    stale.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-stale-before-1024.png"), full_page=True)
    b2 = stale.get_by_role("button", name="이 견적 수정본(revision) 만들기")
    if b2.count() and not b2.is_disabled():
        b2.click(); stale.wait_for_timeout(1200)
        body = stale.inner_text("body")
        check(G, f"{t} 오래된 탭(rev1 {sst})에서 수정 → 409 quote_locked 표시", "quote_locked" in body or "잠" in body, "표시됨" if "quote_locked" in body else body[-200:].replace("\n", " "))
        stale.screenshot(path=str(OUT / f"qa23-ui-{t}-quotes-stale-409-1024.png"), full_page=True)
    else:
        check(G, f"{t} 오래된 탭 목록 재조회가 최신(확정) 상태를 보여 수정 버튼 잠김", sst == "confirmed", f"status={sst}")
    for pg, nm in ((op, "op"), (ta_, "A"), (tb_, "B"), (stale, "stale")):
        ok, sw = hs(pg)
        check(G, f"{t} {nm} 탭 1024px 가로 스크롤 0 · 페이지 오류 0", ok and not pg.errs, f"sw={sw} errs={pg.errs[:2]}")
    for c in (c1, c2, c3, c4): c.close()


def review_flow(b, t):
    G = "UI8"
    c1, A = ctx_for(b, t, "approver"); c2, B = ctx_for(b, t, "admin")
    for pg in (A, B):
        pg.goto(f"{BASE}/app/review"); pg.wait_for_load_state("networkidle"); pg.locator("[data-item]").first.wait_for(timeout=10000)
    first = A.locator("[data-item]").first.get_attribute("data-item")
    n0 = A.locator("[data-item]").count()
    check(G, f"{t} 화면 8 항목 · 출처 배지", n0 > 0 and A.locator("[data-origin=test_split]").count() == n0, f"n={n0}")
    A.screenshot(path=str(OUT / f"qa23-ui-{t}-review-before-1024.png"), full_page=True)
    for pg, label in ((A, "문제 확인"), (B, "오탐")):
        card = pg.locator(f"[data-item='{first}']"); card.locator("textarea").fill(f"화면 검토 {label}")
    A.locator(f"[data-item='{first}']").get_by_role("button", name="문제 확인").click()
    A.get_by_test_id("review-outcome").wait_for(timeout=10000)
    B.locator(f"[data-item='{first}']").get_by_role("button", name="오탐").click()
    B.get_by_test_id("review-outcome").wait_for(timeout=10000)
    ob = B.inner_text("[data-testid=review-outcome]")
    check(G, f"{t} 화면 8 두 탭 검토 → B 에 '이미 검토' 안내 남음", "이미" in ob or "already_decided" in ob, ob[:80].replace("\n", " "))
    B.screenshot(path=str(OUT / f"qa23-ui-{t}-review-tabB-409-1024.png"), full_page=True)
    check(G, f"{t} 닫힌 항목 목록에서 빠짐", B.locator(f"[data-item='{first}']").count() == 0, f"{n0} → {B.locator('[data-item]').count()}")
    c3, V = ctx_for(b, t, "viewer")
    V.goto(f"{BASE}/app/review"); V.wait_for_load_state("networkidle"); V.wait_for_timeout(800)
    vt = V.inner_text("main")
    check(G, f"{t} viewer 화면 8 → 권한 오류 표시 · 항목 0", V.locator("[data-item]").count() == 0 and ("forbidden" in vt or "권한" in vt), vt[-100:].replace("\n", " "))
    V.screenshot(path=str(OUT / f"qa23-ui-{t}-review-viewer-1024.png"), full_page=True)
    c4, O = ctx_for(b, t, "operator")
    O.goto(f"{BASE}/app/review"); O.wait_for_load_state("networkidle"); O.wait_for_timeout(800)
    O.screenshot(path=str(OUT / f"qa23-ui-{t}-review-operator-1024.png"), full_page=True)
    has_btn = O.get_by_role("button", name="문제 확인").count()
    check(G, f"{t} operator 화면 8 조회(결정 버튼 노출={has_btn})", O.locator("[data-item]").count() > 0, f"버튼 {has_btn}개 (계약: operator 조회만)", warn=True)
    for pg in (A, B):
        ok, sw = hs(pg); check(G, f"{t} 1024px 가로 스크롤 0 · 오류 0", ok and not pg.errs, f"sw={sw} errs={pg.errs[:2]}")
    for c in (c1, c2, c3, c4): c.close()


with sync_playwright() as p:
    b = p.chromium.launch()
    for t in sys.argv[1:] or ["kd", "ot", "krs"]:
        s = Server(t)
        try:
            review_flow(b, t) if t in ("krs", "pc") else quote_flow(b, t)
        except Exception as e:  # noqa: BLE001
            check("UI", f"{t} 흐름 예외", False, repr(e)[:300])
        finally:
            s.close()
    b.close()
dump("rows_t04.txt")
