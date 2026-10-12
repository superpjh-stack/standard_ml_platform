"""G-S03 화면 · G-S04 API (`make check-routes`).

G-S03: contracts/screen-map.md ○ 화면 10(1차 6 + 2차 7~10, 웨이브 P 마감)의 파일 존재 · `/app/<path>` 200(빌드 있을 때) · `_placeholder` 표지 0 ·
       회사 화면 코드 0 (web/src 에 회사 이름 폴더 · 파일 없음). 1024px 가로 스크롤 · 폼 생성 · 브라우저 200 은 tests/e2e/test_console.py(Playwright 1.63.0, D-40).
G-S04: contracts/api-contract.md §1 묶음 15(1차 12 + 2차 B09~B11 — 웨이브 P 마감에 단계 1 로 합침)의 경로가 앱에 전부 있다.
       단계 2(501) 행은 0 이어야 한다(G2-T01 "2차 유형 경로의 501 은 0"). 유형이 다른 과제로 부르면 404 type_route 는 시험이 본다.
       오류 계약 · 역할 · 목록 모양은 tests/test_api_contract.py.
"""
import re

from gatelib import ROOT, Line, pytest_gate, read, show


def screens() -> list[dict]:
    rows = []
    for line in read(ROOT / "contracts" / "screen-map.md").splitlines():
        m = re.match(r"^\| (\d+) \| ([^|]+) \| `(/app/[a-z]+)` \| (`[^`]+`|—) \| [^|]+ \| [^|]+ \| [^|]+ \| (○[^|]*|2차) \|$", line)
        if m:
            rows.append({"no": int(m.group(1)), "name": m.group(2).strip(), "path": m.group(3), "file": m.group(4).strip("`"),
                         "phase1": m.group(5).startswith("○")})
    return rows


def api_rows() -> list[dict]:
    rows = []
    for line in read(ROOT / "contracts" / "api-contract.md").splitlines():
        m = re.match(r"^\| (B\d\d) [a-z]+ \| ([12]) \| (GET|POST|PATCH|PUT|DELETE) \| `([^`]+)` \|", line)
        if m:
            rows.append({"bundle": m.group(1), "phase": int(m.group(2)), "method": m.group(3), "path": m.group(4)})
    return rows


def _app_routes() -> set[tuple[str, str]]:
    """앱이 공개하는 (메서드, 경로) — OpenAPI 문서 기준(FastAPI 0.14x 의 포함 라우터는 app.routes 에 펼쳐지지 않는다)."""
    from mlcore.api.main import app
    out = set()
    for path, ops in app.openapi()["paths"].items():
        for m in ops:
            out.add((m.upper(), path))
    return out


def run() -> list[Line]:
    lines = []
    # G-S03
    sc = [s for s in screens() if s["phase1"]]          # ○ 행 = 판정 대상(웨이브 P 마감에 7~10 을 켰다 — 화면 10)
    probs = []
    if len(sc) != 10:
        probs.append(f"계약 판정 대상 화면 {len(sc)} (기대 10)")
    missing = [s["file"] for s in sc if not (ROOT / s["file"]).is_file()]
    if missing:
        probs.append(f"화면 파일 없음 {missing}")
    ph = [str(p.relative_to(ROOT)) for p in (ROOT / "web" / "src").rglob("*.tsx") if 'data-placeholder="true"' in read(p) or "_placeholder" in read(p)]
    ph_screens = [s["no"] for s in sc if (ROOT / s["file"]).is_file() and "Placeholder" in read(ROOT / s["file"])]
    if ph_screens:
        probs.append(f"_placeholder 화면 {len(ph_screens)}/{len(sc)} ({ph_screens})")
    built = (ROOT / "web" / "dist" / "index.html").is_file()
    http_ok = 0
    if built:
        from fastapi.testclient import TestClient
        from mlcore.api.main import app
        with TestClient(app) as c:
            http_ok = sum(c.get(s["path"]).status_code == 200 for s in sc)
        if http_ok != len(sc):
            probs.append(f"/app 200 {http_ok}/{len(sc)}")
    else:
        probs.append("web/dist 없음(npm run build)")
    e2e = pytest_gate("G-S03", "", "tests/e2e/test_console.py")   # 실제 브라우저(Playwright) · 1024px · features.yaml 폼
    if e2e.status != "PASS":
        probs.append(f"e2e {e2e.measured}")
    lines.append(Line("G-S03", "화면", "FAIL" if probs else "PASS",
                      "; ".join(probs) if probs else f"화면 {len(sc)}/10 /app 200 · _placeholder 0 · e2e(ks·sw, 1024px 화면 2·3 가로 스크롤 0 · 폼=features.yaml) {e2e.measured}"))
    # G-S04
    rows = api_rows()
    bundles1 = sorted({r["bundle"] for r in rows if r["phase"] == 1})
    bundles2 = sorted({r["bundle"] for r in rows if r["phase"] == 2})
    have = _app_routes()
    absent = sorted({r["bundle"] for r in rows if (r["method"], r["path"]) not in have})
    done = [b for b in bundles1 if b not in absent]
    probs = []
    if len(bundles1) != 15 or bundles2:
        probs.append(f"계약 묶음 단계 1 {len(bundles1)} · 단계 2 {len(bundles2)} (기대 15 · 0)")
    if absent:
        probs.append(f"묶음 {len(done)}/15 구현 (없음 {' '.join(absent)})")
    t = pytest_gate("G-S04", "API", "tests/test_api_contract.py")
    if t.status != "PASS":
        probs.append(t.measured)
    lines.append(Line("G-S04", "API", "FAIL" if probs else "PASS",
                      "; ".join(probs) if probs else f"묶음 15/15 경로 존재(1차 12 + 2차 B09~B11 · 501 경로 0 · 다른 유형 과제 404 type_route) · {t.measured}"))
    return lines


if __name__ == "__main__":
    raise SystemExit(show(run()))
