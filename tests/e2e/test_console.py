"""G-S03 화면 e2e — contracts/screen-map.md 1차 화면 1~6 (실제 브라우저 · 실제 앱 프로세스 · 시험 DB).

1. 화면 1~6 이 HTTP 200 · 제목이 그 화면 · `_placeholder` 표지 0 · 페이지 오류 0 (회사 ks · sw 사본 각각).
2. 화면 2 · 3 은 1024px 에서 가로 스크롤 0 (입력 폼 · 결과가 그려진 뒤).
3. 입력 폼은 features.yaml 에서 생성된다 — 폼 칸 = 과제 YAML 의 변수 목록(화면 3 은 fixed), 라벨 = features.yaml label,
   범주 선택지 = 회사 등록부 categories(values_from: tenant). 기대값은 앱 코드가 아니라 YAML 파일에서 직접 읽는다.
같은 화면 코드가 두 회사(업종 2)에 다른 폼을 그리는 것으로 "회사 화면 코드 0" 을 확인한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.gate("G-S03")

ROOT = Path(__file__).resolve().parents[2]


def _screens() -> list[tuple[int, str]]:
    rows = []
    for line in (ROOT / "contracts" / "screen-map.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (\d+) \| [^|]+ \| `/app/([a-z]+)` \| `[^`]+` \|.*\| ○[^|]*\|$", line)
        if m:
            rows.append((int(m.group(1)), m.group(2)))
    return rows


SCREENS = _screens()


def _yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def expected_form(server, task_id: str, key: str = "features") -> list[tuple[str, str, list | None]]:
    """(변수, 라벨, 범주 선택지) — packs/<pack>/features.yaml · tasks/<task>.yaml · 회사 등록부에서 직접."""
    cfg = _yaml(server.m.tenant.path)
    pack = ROOT / "packs" / cfg["pack"]
    feats = _yaml(pack / "features.yaml")
    task = _yaml(pack / "tasks" / f"{task_id.split('.', 1)[1]}.yaml")
    out = []
    for name in task[key]:
        f = feats[name]
        vals = None
        if f.get("dtype") == "category":
            vals = [str(v) for v in ((cfg.get("categories") or {}).get(name) if f.get("values_from") == "tenant" else f.get("values"))]
        out.append((name, f.get("label") or name, vals))
    return out


def no_hscroll(page) -> tuple[bool, int, int]:
    sw, cw = page.evaluate("[Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),"
                           " document.documentElement.clientWidth]")
    return sw <= cw, sw, cw


def rendered_form(page, scope: str = ".card") -> list[tuple[str, str, list | None]]:
    out = []
    for field in page.locator(f"{scope} .feature-form").first.locator("[data-field]").all():
        name = field.get_attribute("data-field")
        label = field.locator("label").first.inner_text().split("(")[0].replace("*", "").strip()
        sel = field.locator("select")
        vals = [o for o in sel.locator("option").all_inner_texts() if not o.startswith("(비움")] if sel.count() else None
        out.append((name, label, vals))
    return out


def choose(page, task_id: str) -> None:
    sel = page.locator("label.picker select")
    sel.wait_for()
    page.wait_for_function("t => [...document.querySelectorAll('label.picker option')].some(o => o.value === t)", arg=task_id)
    sel.select_option(task_id)
    page.locator(".card .feature-form [data-field]").first.wait_for()


def test_screens_200_no_placeholder(page, server):
    assert len(SCREENS) == 10, SCREENS          # 1차 6 + 2차 7~10 (screen-map ○ — 웨이브 P 마감)
    for no, path in SCREENS:
        resp = page.goto(f"{server.base}/app/{path}")
        assert resp is not None and resp.status == 200, (path, resp and resp.status)
        h1 = page.locator("main h1")
        h1.wait_for()
        assert h1.inner_text().startswith(f"{no}."), (path, h1.inner_text())
        page.wait_for_load_state("networkidle")
        assert "_placeholder" not in page.content(), path
        assert page.locator("[data-placeholder]").count() == 0, path
        ok, sw, cw = no_hscroll(page)
        assert ok, f"화면 {no} 가로 스크롤 {sw} > {cw}"   # 1024px — 화면 7~10 포함
    assert page.errors == [], page.errors


def test_predict_form_from_yaml_and_1024(page, server):
    task = server.tasks["predict"]
    page.goto(f"{server.base}/app/predict")
    choose(page, task)
    assert rendered_form(page) == expected_form(server, task)
    ok, sw, cw = no_hscroll(page)
    assert ok, f"화면 2 폼 가로 스크롤 {sw} > {cw}"
    page.get_by_role("button", name="예측", exact=True).click()
    res = page.get_by_test_id("predict-result")
    res.wait_for(timeout=15000)
    status = res.locator("[data-status]").first.get_attribute("data-status")
    assert status in ("ok", "watch", "review", "out_of_range"), status   # production 모델의 실제 답(503 아님)
    assert task in res.inner_text()
    ok, sw, cw = no_hscroll(page)
    page.screenshot(path=str(ROOT / "var" / f"e2e-{server.source}-predict-1024.png"), full_page=True)
    assert ok, f"화면 2 결과 가로 스크롤 {sw} > {cw}"
    assert page.errors == [], page.errors


def test_optimize_form_from_yaml_and_1024(page, server):
    task = server.tasks["optimize"]
    page.goto(f"{server.base}/app/optimize")
    choose(page, task)
    assert rendered_form(page) == expected_form(server, task, key="fixed")
    ok, sw, cw = no_hscroll(page)
    assert ok, f"화면 3 폼 가로 스크롤 {sw} > {cw}"
    page.get_by_role("button", name="추천 조건 찾기", exact=True).click()
    res = page.get_by_test_id("optimize-result")
    res.wait_for(timeout=20000)
    assert res.locator("[data-status]").first.get_attribute("data-status") in ("needs_approval", "review")
    ok, sw, cw = no_hscroll(page)
    page.screenshot(path=str(ROOT / "var" / f"e2e-{server.source}-optimize-1024.png"), full_page=True)
    assert ok, f"화면 3 결과 가로 스크롤 {sw} > {cw}"
    assert page.errors == [], page.errors


def test_same_screen_code_draws_different_forms(server):
    """회사 화면 코드 0 — web/src 에 회사 코드 · 이름이 없고, 폼 기대값은 회사 등록부 · 팩에서만 온다."""
    cfg = _yaml(server.m.tenant.path)
    words = [w for w in [server.source, cfg.get("name"), *(cfg.get("aliases") or [])] if w]
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web" / "src").rglob("*.ts*"))
    for w in words:
        assert not re.search(rf"(?<![A-Za-z0-9_]){re.escape(w)}(?![A-Za-z0-9_])", src), w
