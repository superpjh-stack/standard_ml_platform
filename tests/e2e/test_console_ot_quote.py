"""화면 9 — ot 견적 흐름이 **회사 등록부 · 팩 데이터만으로** 동작한다 (G2-S01 · goal2 §1-5 · 웨이브 A2, 개발2).

회사 화면 코드 0 — 같은 `web/src/screens/Quotes.tsx` 가 등록부(`tenants/ot.yaml` + `tenants/ot/tasks/*.yaml`)와
팩 `rollform-quote`(features · 과제 recognized · rates · 단가표)만 읽어 폼 · 인식값 · 금액을 그린다:
  도면 업로드(cad_objects: 기하 규칙 + 객체 분류 모델) → 인식값(홀 · 슬롯 · 길이 · 폭)이 폼 초기값 →
  견적 초안(machining_minutes production 예측 → Decimal 견적식) → 사람 수정 revision(overrides 표) →
  확정 요청(pending_confirm) → approver 결정(B13) → 확정 · 잠금. 금액은 서버 문자열 그대로(브라우저 계산 0) · 1024px 가로 스크롤 0.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

import _dev2 as h
from conftest import Server
from test_console import no_hscroll

pytestmark = pytest.mark.gate("G2-S01")
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "packs" / "rollform-quote" / "samples" / "sample.dxf"


@pytest.fixture(scope="module")
def ot(tmp_path_factory):
    if not (ROOT / "tenants" / "ot.yaml").is_file():
        pytest.fail("회사 등록부 tenants/ot.yaml 없음 — 개발3(웨이브 A2)")
    overrides = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
                 for p in sorted((ROOT / "tenants" / "ot" / "tasks").glob("*.yaml"))}
    m = h.make_tenant("ot", tmp_path_factory.mktemp("e2e-ot"), overrides=overrides)
    code = m.tenant.code
    h.real_production(m, f"{code}.machining_minutes")             # 견적 uses
    h.real_production(m, f"{code}.cad_objects")                   # 객체 분류 모델(추출기 kind model)
    s = Server(m, h.keys(m), {})
    yield s
    s.close()


def test_ot_quote_flow_from_registry_data_only(browser, ot):
    code, keys = ot.code, ot.keys
    ctx = browser.new_context(viewport={"width": 1024, "height": 768}, locale="ko-KR")
    ctx.add_init_script("localStorage.setItem('mlp.console.connection', JSON.stringify(%s));"
                        % json.dumps({"tenant": code, "key": keys["admin"]}))
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        resp = page.goto(f"{ot.base}/app/quotes")
        assert resp is not None and resp.status == 200
        page.locator("main h1").wait_for()
        assert page.locator("main h1").inner_text().startswith("9.")
        # ── 과제 고르개 = 등록부가 켠 과제(유형 extract · quote) ──────────────────────────────────────
        pickers = page.locator("label.picker select")
        pickers.first.wait_for()
        page.wait_for_function("(() => { const s = [...document.querySelectorAll('label.picker select')];"
                               " return s.length >= 2 && s.every(x => x.value !== ''); })()", timeout=15000)
        assert pickers.nth(0).input_value() == f"{code}.cad_objects"
        assert pickers.nth(1).input_value() == f"{code}.quote"
        # ── 1. 도면 업로드 → 추출(객체 분류 모델) ───────────────────────────────────────────────────
        page.set_input_files("input[aria-label='DXF 파일']", str(SAMPLE))
        page.get_by_role("button", name="업로드 · 추출").click()
        page.get_by_role("heading", name="추출 결과").wait_for(timeout=15000)
        # ── 2. 견적 폼 = 팩 features 라벨 · 과제 inputs · 인식값 초기값 ─────────────────────────────
        editor = page.get_by_test_id("quote-editor")
        editor.wait_for()
        info = h.client(ot.m).get(f"/api/v1/tenants/{code}/tasks/{code}.quote", headers=h.hdr(keys["viewer"])).json()
        feats = {f["name"]: f for f in info["features"]}
        for n in info["inputs"]:
            field = editor.locator(f"[data-field='{n}']")
            assert field.count() == 1, n
            if n in feats:
                assert feats[n]["label"] in field.locator("label").inner_text()
        page.wait_for_function("document.querySelector(\"[data-field='hole_count'] input\").value !== ''")
        doc = h.client(ot.m).get(f"/api/v1/tenants/{code}/tasks/{code}.cad_objects/documents",
                                 headers=h.hdr(keys["operator"])).json()["items"][0]
        assert editor.locator("[data-field='hole_count'] input").input_value() == str(doc["counts"]["hole"])
        assert "인식값" in editor.locator("[data-field='hole_count']").inner_text()
        grade = info["features"][[f["name"] for f in info["features"]].index("steel_grade")]["values"][0]
        profile = feats["section_profile"]["values"][0]
        editor.locator("[data-field='steel_grade'] select").select_option(grade)
        editor.locator("[data-field='section_profile'] select").select_option(profile)
        for n in ("sheet_thickness_mm", "bend_count", "quantity"):
            inp = editor.locator(f"[data-field='{n}'] input")
            if inp.input_value() == "":
                inp.fill({"quantity": "1"}.get(n, str(feats.get(n, {}).get("default", 1))))
        # ── 3. 견적 초안 — 금액은 서버 문자열 그대로 ─────────────────────────────────────────────────
        page.get_by_role("button", name="견적 초안 만들기").click()
        detail = page.locator("[data-testid='quote-detail'][data-status='draft']")
        detail.wait_for(timeout=15000)
        qid = re.search(r"qte_[0-9A-Z]{26}", detail.locator("h2").inner_text()).group(0)
        q = h.client(ot.m).get(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes/{qid}", headers=h.hdr(keys["operator"])).json()
        total_txt = f"{int(q['total']):,}"
        assert total_txt in detail.inner_text()                                  # 천 단위 구분만 — 값은 서버 문자열
        assert q["overrides"] == [] and q["predictions"][0]["task"] == f"{code}.machining_minutes"
        assert "수정한 칸 없음" in detail.inner_text()
        # ── 4. 사람 수정 → revision · overrides 표 ────────────────────────────────────────────────
        hole = editor.locator("[data-field='hole_count'] input")
        hole.fill(str(int(hole.input_value()) + 1))
        page.get_by_role("button", name="이 견적 수정본(revision) 만들기").click()
        page.get_by_test_id("quote-overrides").wait_for(timeout=15000)
        assert "hole_count" in page.get_by_test_id("quote-overrides").inner_text()
        detail = page.get_by_test_id("quote-detail")
        assert "revision 2" in detail.inner_text()
        qid2 = re.search(r"qte_[0-9A-Z]{26}", detail.locator("h2").inner_text()).group(0)
        # ── 5. 확정 요청 → pending_confirm → approver 결정(B13) → 확정 · 잠금 ───────────────────────
        detail.locator("input[type='checkbox']").check()
        detail.locator("textarea").fill("홀 수 현장 확인 후 수정")
        detail.get_by_role("button", name="확정 요청").click()
        page.locator("[data-testid='quote-detail'][data-status='pending_confirm']").wait_for(timeout=15000)
        assert page.get_by_role("button", name="이 견적 수정본(revision) 만들기").is_disabled()
        tc = h.client(ot.m)
        appr = tc.get(f"/api/v1/tenants/{code}/approvals", headers=h.hdr(keys["approver"]), params={"state": "pending"}).json()
        (a,) = [x for x in appr["items"] if x.get("kind") == "quote"]
        r = tc.post(f"/api/v1/approvals/{a['approval_id']}/decide", headers=h.hdr(keys["approver"]),
                    json={"decision": "approve", "reason": "e2e 견적 확정"})
        assert r.status_code == 200, r.text
        conf = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes/{qid2}", headers=h.hdr(keys["operator"])).json()
        rev2 = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers=h.hdr(keys["operator"]),
                      params={"status": "confirmed"}).json()["items"]
        assert conf["status"] == "confirmed" and [x["quote_id"] for x in rev2] == [conf["quote_id"]]
        page.reload()
        page.get_by_role("heading", name="견적 이력").wait_for()
        row = page.locator("tr", has_text=conf["quote_id"])                    # 확정 = 같은 계열의 새 행(추가만)
        row.get_by_role("button", name="보기").click()
        page.locator("[data-testid='quote-detail'][data-status='confirmed']").wait_for(timeout=15000)
        assert f"{int(conf['total']):,}" in page.get_by_test_id("quote-detail").inner_text()
        assert "확정 · 잠금" in page.get_by_test_id("quote-detail").inner_text()
        # ── 화면 규칙 ─────────────────────────────────────────────────────────────────────────────
        assert "_placeholder" not in page.content() and page.locator("[data-placeholder]").count() == 0
        ok, sw, cw = no_hscroll(page)
        assert ok, f"화면 9 (ot) 가로 스크롤 {sw} > {cw}"
        assert errors == [], errors
    finally:
        ctx.close()
