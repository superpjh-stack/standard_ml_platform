"""QA2-3 — 실제 chromium 으로 화면 1~10 을 1024px 에서 열어 스크린샷 · 콘솔 오류 · 가로 스크롤 · 표지 문구.
사용: python shots.py <label> <tenant> <role> [screens...] → outputs/e2e/qa23-<label>-<tenant>-<screen>-1024.png, 결과 JSON 한 줄씩."""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from qa_lib import BASE, KEYS

OUT = Path(__file__).resolve().parents[1] / "e2e"
label, tenant, role = sys.argv[1:4]
screens = sys.argv[4:] or ["overview", "predict", "optimize", "models", "approvals", "monitor", "sources", "review", "quotes", "trace"]
WORDS = ["운영 모델 없음", "model_not_ready", "미연결", "합성", "실측 없음", "목표 없음", "labels: none", "정답 라벨 없음",
         "_placeholder", "오류", "권한", "검토할 항목 없음", "과제가 없습니다", "live 불가", "undefined", "NaN", "[object Object]"]
with sync_playwright() as p:
    b = p.chromium.launch()
    for s in screens:
        ctx = b.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR")
        if role != "none":
            ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
                                % json.dumps({"tenant": tenant, "key": KEYS[tenant][role]}))
        pg = ctx.new_page()
        errs, cons, bad = [], [], []
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        pg.on("console", lambda m: cons.append(f"{m.type}: {m.text[:160]}") if m.type == "error" else None)
        pg.on("response", lambda r: bad.append(f"{r.status} {r.url.split('8214')[-1][:90]}") if r.status >= 400 else None)
        resp = pg.goto(f"{BASE}/app/{s}")
        try: pg.wait_for_load_state("networkidle", timeout=8000)
        except Exception: pass
        pg.wait_for_timeout(800)
        sw, cw = pg.evaluate("[Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), document.documentElement.clientWidth]")
        text = pg.inner_text("body")
        h1 = pg.locator("main h1").first.inner_text() if pg.locator("main h1").count() else ""
        fn = OUT / f"qa23-{label}-{tenant}-{s}-1024.png"
        pg.screenshot(path=str(fn), full_page=True)
        print(json.dumps({"label": label, "tenant": tenant, "role": role, "screen": s, "http": resp.status if resp else None, "h1": h1,
                          "hscroll": sw > cw, "sw": sw, "cw": cw, "pageerrors": errs, "console": cons, "4xx5xx": bad,
                          "placeholder": pg.locator("[data-placeholder]").count(),
                          "words": [k for k in WORDS if k in text], "chars": len(text), "png": fn.name}, ensure_ascii=False), flush=True)
        ctx.close()
    b.close()
