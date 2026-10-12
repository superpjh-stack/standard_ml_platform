"""QA2 재검증(r2) — #29 경미 6건 + C2 회귀(실서버 8214 · ml_qa2r2_db · Playwright 1024px).
  002 health/overview model_required · 화면 1 '모델 불필요 (규칙)' / '의존 …'
  003 records NaT → null
  004 화면 8 can_decide(operator · viewer · approver · approver_other) · 버튼 숨김
  005 409 문구
  006 doctor 권한(operator · viewer 403 · approver 200) · 화면 6 안내
  007 비학습 과제 train → 422 not_trainable · mlp_train_run 0 행
결과 → rows_ui_api_r2.txt · 스크린샷 outputs/qa2-r2/e2e/"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from qa_lib import BASE, KEYS, Server, call, check, code_of, dump
from mlcore.db.conn import connect

OUT = Path(__file__).resolve().parents[1] / "e2e"
OUT.mkdir(exist_ok=True)
G = "r2"


def page_for(b, t, role):
    ctx = b.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR")
    ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));" % json.dumps({"tenant": t, "key": KEYS[t][role]}))
    pg = ctx.new_page(); pg.errs = []
    pg.on("pageerror", lambda e: pg.errs.append(str(e)))
    return ctx, pg


for t in ("kd", "krs"):
    s = Server(t)
    try:
        st, hl = call("GET", "/api/v1/health", t=t, role=None)
        rows = {x["task"]: x for x in hl["tasks"]}
        check(G, f"{t} health 항목 type · model_required · uses 키", all({"type", "model_required", "uses"} <= set(x) for x in rows.values()),
              str({k: (v.get("type"), v.get("model_required"), v.get("model_ready")) for k, v in rows.items()}))
        exp_nomodel = {k for k, v in rows.items() if v.get("type") in ("quote", "review_queue", "optimize") or k.endswith("drawing_regions")}
        check(G, f"{t} model_required false = 규칙 extract · quote · review_queue · optimize", all(rows[k]["model_required"] is False for k in exp_nomodel)
              and all(v["model_required"] is True for k, v in rows.items() if k not in exp_nomodel), str(sorted(exp_nomodel)))
        for k in rows:
            st, ov = call("GET", f"/api/v1/tenants/{t}/tasks/{k}/overview", t=t, role="viewer")
            check(G, f"{t} overview {k} model_required · uses", st == 200 and "model_required" in ov,
                  f"HTTP {st} mr={ov.get('model_required') if isinstance(ov, dict) else None} uses={ov.get('uses') if isinstance(ov, dict) else None}")
        # records NaT
        for k, v in rows.items():
            if v.get("type") in ("regression",):
                st, rec = call("GET", f"/api/v1/tenants/{t}/tasks/{k}/records?limit=50", t=t, role="viewer")
                ts = [r.get("ts") for r in rec.get("items", [])] if isinstance(rec, dict) else []
                check(G, f"{t} records {k} ts 에 'NaT' 문자열 0", st == 200 and "NaT" not in ts, f"HTTP {st} n={len(ts)} null={sum(x is None for x in ts)}")
        # doctor 권한
        for role, want in (("viewer", 403), ("operator", 403), ("approver", 200), ("admin", 200)):
            st, b = call("GET", f"/api/v1/tenants/{t}/doctor", t=t, role=role)
            check(G, f"{t} doctor {role} → {want}", st == want, f"HTTP {st} {code_of(b) or ''}")
        # 비학습 과제 train
        for k, v in rows.items():
            if v.get("model_required") is False:
                with connect() as c:
                    n0 = c.execute("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s", (t, k)).fetchone()["n"]
                st, b = call("POST", f"/api/v1/tenants/{t}/tasks/{k}/train", t=t, role="admin", json_body={})
                with connect() as c:
                    n1 = c.execute("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s", (t, k)).fetchone()["n"]
                det = (b.get("error") or {}).get("detail") if isinstance(b, dict) else None
                check(G, f"{t} train {k}({v['type']}) → 422 not_trainable · run 0", st == 422 and (det or {}).get("rule") == "not_trainable" and n1 == n0,
                      f"HTTP {st} {code_of(b)} {det} runs {n0}->{n1}")
        if t == "krs":
            R = f"/api/v1/tenants/{t}/tasks/{t}.residual_review/review"
            for role, want in (("operator", False), ("approver", True), ("approver_other", False), ("admin", True), ("viewer", None)):
                st, b = call("GET", R, t=t, role=role)
                got = b.get("can_decide") if isinstance(b, dict) and st == 200 else None
                check(G, f"krs review can_decide · {role}", (st == 403 and want is None) or got is want, f"HTTP {st} can_decide={got}")
        with sync_playwright() as p:
            br = p.chromium.launch()
            try:
                if t == "kd":
                    ctx, pg = page_for(br, t, "viewer")
                    pg.goto(BASE + "/app/overview"); pg.wait_for_timeout(2500)
                    cells = pg.locator("td[data-model-required]")
                    vals = [cells.nth(i).get_attribute("data-model-required") for i in range(cells.count())]
                    txt = pg.locator("table").first.inner_text()
                    check(G, "kd 화면 1 drawing_regions '모델 불필요 (규칙)' · quote '의존 kd.labor_hours: v1'",
                          "모델 불필요" in txt and "의존 kd.labor_hours" in txt, f"cells={vals}")
                    check(G, "kd 화면 1 대상 데이터 NaT 표시 0", "NaT" not in pg.content(), "")
                    pg.screenshot(path=str(OUT / "r2-kd-overview-1024.png"), full_page=True)
                    for role in ("operator", "approver"):
                        ctx, pg = page_for(br, t, role)
                        pg.goto(BASE + "/app/monitor"); pg.wait_for_timeout(2500)
                        has = pg.locator("[data-testid=doctor-forbidden]").count()
                        tbl = pg.locator("[data-testid=doctor]").count()
                        check(G, f"kd 화면 6 {role} doctor", (has == 1 and tbl == 0) if role == "operator" else (has == 0 and tbl == 1),
                              f"forbidden_note={has} table={tbl} errs={pg.errs[:2]}")
                        pg.screenshot(path=str(OUT / f"r2-kd-monitor-{role}-1024.png"), full_page=True)
                else:
                    for role in ("operator", "approver"):
                        ctx, pg = page_for(br, t, role)
                        pg.goto(BASE + "/app/review"); pg.wait_for_timeout(1500)
                        sel = pg.locator("select").first
                        try:
                            sel.select_option(f"{t}.residual_review"); pg.wait_for_timeout(2000)
                        except Exception:  # noqa: BLE001
                            pass
                        ro = pg.locator("[data-testid=review-readonly]").count()
                        btn = pg.get_by_role("button", name="문제 확인").count() + pg.get_by_role("button", name="오탐").count()
                        check(G, f"krs 화면 8 {role} 버튼 · 조회 전용 안내", (ro == 1 and btn == 0) if role == "operator" else (ro == 0 and btn > 0),
                              f"readonly={ro} buttons={btn} errs={pg.errs[:2]}")
                        pg.screenshot(path=str(OUT / f"r2-krs-review-{role}-1024.png"), full_page=True)
                        w = pg.evaluate("document.documentElement.scrollWidth")
                        check(G, f"krs 화면 8 {role} 가로 스크롤 0", w <= 1024, f"scrollWidth={w}")
                    # 409 문구 — approver 두 탭: 같은 항목을 한 탭이 먼저 결정
                    c1, p1 = page_for(br, t, "approver"); c2, p2 = page_for(br, t, "approver")
                    for pg in (p1, p2):
                        pg.goto(BASE + "/app/review"); pg.wait_for_timeout(1200)
                        try:
                            pg.locator("select").first.select_option(f"{t}.residual_review"); pg.wait_for_timeout(1500)
                        except Exception:  # noqa: BLE001
                            pass
                    for pg in (p1, p2):
                        tb = pg.locator("textarea, input[type=text]").first
                        if tb.count():
                            tb.fill("r2 재검증 메모")
                    p1.get_by_role("button", name="오탐").first.click(); p1.wait_for_timeout(1500)
                    p2.get_by_role("button", name="오탐").first.click(); p2.wait_for_timeout(1500)
                    body = p2.locator("body").inner_text()
                    check(G, "krs 화면 8 두 탭 · 뒤 탭 409 문구", "이미 검토가 끝난 항목" in body and "이미 결정된 승인" not in body,
                          [l for l in body.splitlines() if "이미" in l][:2])
                    p2.screenshot(path=str(OUT / "r2-krs-review-409-1024.png"), full_page=True)
            finally:
                br.close()
    finally:
        s.close()
dump("rows_ui_api_r2.txt")
