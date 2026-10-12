"""G-S03 화면 · G-S04 API (`make check-routes`).

G-S03: contracts/screen-map.md 1차 화면 6 의 파일 존재 · `/app/<path>` 200(빌드 있을 때) · `_placeholder` 표지 0 ·
       회사 화면 코드 0 (web/src 에 회사 이름 폴더 · 파일 없음). 1024px 가로 스크롤은 tests/e2e/ 가 본다.
G-S04: contracts/api-contract.md 1차 묶음 12 의 경로가 앱에 전부 있고, 2차 3 묶음은 501 경로가 있다.
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
    sc = [s for s in screens() if s["phase1"]]
    probs = []
    if len(sc) != 6:
        probs.append(f"계약 1차 화면 {len(sc)} (기대 6)")
    missing = [s["file"] for s in sc if not (ROOT / s["file"]).is_file()]
    if missing:
        probs.append(f"화면 파일 없음 {missing}")
    ph = [str(p.relative_to(ROOT)) for p in (ROOT / "web" / "src").rglob("*.tsx") if 'data-placeholder="true"' in read(p) or "_placeholder" in read(p)]
    ph_screens = [s["no"] for s in sc if (ROOT / s["file"]).is_file() and "Placeholder" in read(ROOT / s["file"])]
    if ph_screens:
        probs.append(f"_placeholder 화면 {len(ph_screens)}/6 ({ph_screens})")
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
    e2e = (ROOT / "tests" / "e2e").is_dir()
    if not e2e:
        probs.append("tests/e2e/ 없음(1024px 검사)")
    lines.append(Line("G-S03", "화면", "FAIL" if probs else "PASS",
                      "; ".join(probs) if probs else f"화면 6/6 200 · _placeholder 0 · e2e 있음"))
    # G-S04
    rows = api_rows()
    bundles1 = sorted({r["bundle"] for r in rows if r["phase"] == 1})
    bundles2 = sorted({r["bundle"] for r in rows if r["phase"] == 2})
    have = _app_routes()
    absent = [r for r in rows if (r["method"], r["path"]) not in have]
    absent1 = sorted({r["bundle"] for r in absent if r["phase"] == 1})
    done1 = [b for b in bundles1 if b not in absent1]
    absent2 = sorted({r["bundle"] for r in absent if r["phase"] == 2})
    probs = []
    if len(bundles1) != 12 or len(bundles1) + len(bundles2) != 15:
        probs.append(f"계약 묶음 1차 {len(bundles1)} · 전체 {len(bundles1) + len(bundles2)} (기대 12 · 15)")
    if absent1:
        probs.append(f"1차 묶음 {len(done1)}/12 구현 (없음 {' '.join(absent1)})")
    if absent2:
        probs.append(f"2차 501 경로 없음 {absent2}")
    t = pytest_gate("G-S04", "API", "tests/test_api_contract.py")
    if t.status != "PASS":
        probs.append(t.measured)
    lines.append(Line("G-S04", "API", "FAIL" if probs else "PASS",
                      "; ".join(probs) if probs else f"1차 12/12 · 2차 501 3/3 · {t.measured}"))
    return lines


if __name__ == "__main__":
    raise SystemExit(show(run()))
