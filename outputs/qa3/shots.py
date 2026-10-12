"""QA3 — 실제 chromium 으로 화면 1~6 을 1024 · 390 폭에서 열고 스크린샷 · 콘솔 오류 · 가로 스크롤 · 표지 문구를 잰다.
사용: python shots.py <label> <tenant> <role> [screens...]  → outputs/e2e/qa3-<label>-<screen>-<w>.png · 결과 JSON 한 줄씩."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from qa_lib import BASE, KEYS

OUT = Path(__file__).resolve().parents[1] / "e2e"
label, tenant, role = sys.argv[1:4]
screens = sys.argv[4:] or ["overview", "predict", "optimize", "models", "approvals", "monitor"]
WORDS = ["운영 모델 없음", "model_not_ready", "미연결", "합성", "실측 없음", "목표 없음", "_placeholder", "오류", "권한"]

with sync_playwright() as p:
    b = p.chromium.launch()
    for w, hgt in ((1024, 768), (390, 844)):
        for s in screens:
            ctx = b.new_context(viewport={"width": w, "height": hgt}, locale="ko-KR")
            if role != "none":
                ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
                                    % json.dumps({"tenant": tenant, "key": KEYS[tenant][role]}))
            pg = ctx.new_page()
            errs, cons = [], []
            pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
            pg.on("console", lambda m: cons.append(f"{m.type}: {m.text[:160]}") if m.type in ("error", "warning") else None)
            resp = pg.goto(f"{BASE}/app/{s}")
            pg.wait_for_timeout(1800)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            cw = pg.evaluate("document.documentElement.clientWidth")
            text = pg.inner_text("body")
            fn = OUT / f"qa3-{label}-{s}-{w}.png"
            pg.screenshot(path=str(fn), full_page=True)
            print(json.dumps({"label": label, "screen": s, "w": w, "http": resp.status if resp else None,
                              "hscroll": sw > cw, "scrollWidth": sw, "clientWidth": cw, "pageerrors": errs,
                              "console": cons, "words": {k: (k in text) for k in WORDS}, "chars": len(text),
                              "png": fn.name}, ensure_ascii=False), flush=True)
            ctx.close()
    b.close()
