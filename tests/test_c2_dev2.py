"""웨이브 C2 개발2 — QA 2차 결함 회귀 시험 (코어 재진입 · D2-90 ~).

- DEF-QA22-002 (#31 중대): 견적 품목 `lines` 값 검증 — 과제 `line_limits`(원천 BomRow `KyungDong ML AI/api/main.py:33-43`)
  와, 그것이 없어도 코어가 지키는 기본(음수 · 비유한 · 중첩 · 형식 오류 422, 음수 금액 0, 500 0).
- #30 코어 부분(DEF-QA22-001): 추출 결과 JSON 크기 · 배열 항목 수 상한 · 추출기 실행 시간 상한 → 413 document_too_large,
  거부된 문서는 원본 · 행을 남기지 않는다.
- #32 DEF-QA22-003 CSV `safe_cell` 앞 공백 · 줄바꿈 뒤 수식, DEF-QA22-004 NUL → 422 + 원본 저장 0.
- #29 DEF-QA23-002 health · overview 의 유형별 모델 상태(model_required · uses), DEF-QA23-004 대기열 `can_decide`.
"""
from __future__ import annotations

import hashlib
import json
import textwrap

import pytest

import _dev2 as h
import _phase2 as p2
from mlcore.db.conn import connect
from mlcore.serve import quotes

pytestmark = [pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

# 원천 BomRow (KyungDong ML AI/api/main.py:33-43) · QuoteInput.bom 1~100행(:50) 을 과제 line_limits 모양으로
KD_LINE_LIMITS = {
    "min_items": 1, "max_items": 100,
    "fields": {
        "name": {"type": "string", "required": True, "min_length": 1, "max_length": 80},
        "material": {"type": "category", "required": True, "values_from": "main_material"},
        "quantity": {"type": "number", "required": True, "min": 1, "max": 1000, "integer": True},
        "mass_kg": {"type": "number", "required": True, "min": 0.01, "max": 10000},
        "price_kg": {"type": "number", "required": True, "min": 0, "max": 1000000},
    },
}


# ── 견적 품목 (#31) ─────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def kd(tmp_path_factory):
    m = h.make_tenant("kd", tmp_path_factory.mktemp("c2kd"))
    code = m.tenant.code
    h.real_production(m, f"{code}.labor_hours")
    k = h.keys(m)
    tc = h.client(m)
    mats = m.tenant.config["categories"]["main_material"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("eto_sample_dxf_c2", h.ROOT / "packs" / "eto" / "synth" / "sample_dxf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": ("sample.dxf", mod.sample_bytes(mats), "application/dxf")})
    assert r.status_code == 201, r.text
    return m, k, tc, r.json()


def _lines(doc, price="6500"):
    return [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
             "price_kg": price} for b in doc["bom_rows"]]


def _post(kd, lines, *, raw_lines: str | None = None):
    m, k, tc, doc = kd
    code = m.tenant.code
    inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
              "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
    body = json.dumps({"doc_id": doc["doc_id"], "inputs": inputs, "lines": "__L__", "reviewed": False}, ensure_ascii=False)
    body = body.replace('"__L__"', raw_lines if raw_lines is not None else json.dumps(lines, ensure_ascii=False))
    return tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes",
                   headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=body.encode("utf-8"))


def _quote_rows(m) -> int:
    return h.count("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id = %s", (m.tenant.code,))


def _with_line_limits(kd, limits):
    m = kd[0]
    raw = m.tasks[f"{m.tenant.code}.quote"].raw
    old = raw.get("line_limits")
    raw["line_limits"] = limits
    return raw, old


def _restore(raw, old):
    if old is None:
        raw.pop("line_limits", None)
    else:
        raw["line_limits"] = old


def _mut(doc, i, **kw):
    lines = _lines(doc)
    lines[i] = {**lines[i], **kw}
    for k_, v in list(lines[i].items()):
        if v is ...:
            del lines[i][k_]
    return lines


@pytest.mark.parametrize("change, rule", [
    ({"price_kg": -6500}, "range"),
    ({"price_kg": "-6500"}, "negative_amount"),
    ({"price_kg": "abc"}, "line_value"),
    ({"price_kg": True}, "number"),
    ({"price_kg": {"x": 1}}, "type"),
    ({"name": ...}, "line_value"),
    ({"name": "x" * 201}, "length"),
])
def test_default_line_rules_without_line_limits(kd, change, rule):
    """과제에 line_limits 가 없어도 코어 기본: 숫자는 0 이상 유한 · 문자열 숫자는 10진 표기만 · 중첩 값 거부 ·
    견적식이 계산할 수 없는 품목(이름 없음 등)은 422 — 500 0 · 행 0 (DEF-QA22-002 의 500 두 가지 · 음수 견적)."""
    m, k, tc, doc = kd
    raw, old = _with_line_limits(kd, None)
    raw.pop("line_limits", None)
    try:
        before = _quote_rows(m)
        r = _post(kd, _mut(doc, 0, **change))
        assert r.status_code == 422, r.text
        e = r.json()["error"]
        assert e["code"] == "invalid_input", e
        if rule:
            assert e["detail"]["rule"] == rule, e
        assert _quote_rows(m) == before
    finally:
        _restore(raw, old)


@pytest.mark.parametrize("change, field, rule", [
    ({"price_kg": -6500}, "price_kg", "range"),
    ({"price_kg": 1e12}, "price_kg", "range"),
    ({"price_kg": "abc"}, "price_kg", "number"),
    ({"quantity": 1.5}, "quantity", "integer"),
    ({"quantity": 0}, "quantity", "range"),
    ({"quantity": 1001}, "quantity", "range"),
    ({"mass_kg": 0}, "mass_kg", "range"),
    ({"mass_kg": 10000.5}, "mass_kg", "range"),
    ({"material": "UNOBTAINIUM"}, "material", "category"),
    ({"material": 7}, "material", "type"),
    ({"discount": 100}, "discount", "extra_forbidden"),
    ({"name": ...}, "name", "required"),
    ({"name": "   "}, "name", "length"),
    ({"name": "x" * 81}, "name", "length"),
])
def test_line_limits_follow_source_bomrow(kd, change, field, rule):
    """원천 BomRow 판정 그대로 — 전부 422 invalid_input · detail.field = lines.<i>.<키> · 입력값을 되풀이하지 않는다."""
    m, k, tc, doc = kd
    raw, old = _with_line_limits(kd, KD_LINE_LIMITS)
    try:
        before = _quote_rows(m)
        r = _post(kd, _mut(doc, 1, **change))
        assert r.status_code == 422, r.text
        e = r.json()["error"]
        assert e["code"] == "invalid_input" and e["detail"]["field"] == f"lines.1.{field}" and e["detail"]["rule"] == rule, e
        assert "UNOBTAINIUM" not in r.text and "abc" not in r.text
        assert _quote_rows(m) == before
    finally:
        _restore(raw, old)


def test_line_limits_item_count_and_alias(kd):
    m, k, tc, doc = kd
    raw, old = _with_line_limits(kd, KD_LINE_LIMITS)
    try:
        r = _post(kd, [])
        assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "lines", "rule": "min_items"}, r.text
        r = _post(kd, _lines(doc) * 26)                                    # 104 > 100
        assert r.status_code == 422 and r.json()["error"]["detail"]["rule"] == "max_items", r.text
        # 재질 별칭(회사 material_aliases) · 대소문자 · 앞뒤 공백 → 정규 값으로 저장 (추출기 bom_text 와 같은 통합)
        aliases = {str(a).upper(): v for a, v in (m.tenant.config.get("material_aliases") or {}).items()}
        alias, canon = next(iter(aliases.items()))
        lines = _lines(doc)
        lines[0] = {**lines[0], "material": f"  {alias.lower()} ", "name": f"  {lines[0]['name']}  "}
        r = _post(kd, lines)
        assert r.status_code == 201, r.text
        q = r.json()
        assert q["lines"][0]["material"] == canon and q["lines"][0]["name"] == lines[0]["name"].strip()
        # 정상 품목은 그대로 — 문자열 10진 단가("6500")도 받는다(원천 pydantic 숫자 판정)
        r = _post(kd, _lines(doc))
        assert r.status_code == 201 and int(r.json()["total"]) > 0, r.text
    finally:
        _restore(raw, old)


def test_negative_amount_never_saved(kd):
    """견적식 결과의 합계 · 품목 금액이 음수면 422 — 음수 견적 행 0 (코어 불변식, 과제 설정과 무관)."""
    m, k, tc, doc = kd
    from mlcore.serve.quotes import InvalidInput, check_amounts
    with pytest.raises(InvalidInput):
        check_amounts({"total": -1, "lines": [], "costs": {}})
    with pytest.raises(InvalidInput):
        check_amounts({"total": 10, "lines": [{"amount": -5}], "costs": {}})
    check_amounts({"total": 0, "lines": [{"amount": 0}], "costs": {}})
    neg = h.count("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id = %s AND total < 0", (m.tenant.code,))
    assert neg == 0


def test_validate_line_limits_shape():
    ok = quotes.validate_line_limits("t.quote", KD_LINE_LIMITS, inputs=["main_material", "quantity"],
                                     categories={"main_material"})
    assert ok == []
    bad = [
        {"fields": {"x": {"type": "float"}}},
        {"fields": {"x": {"type": "number", "min": -1}}},
        {"fields": {"x": {"type": "number", "min": 5, "max": 1}}},
        {"fields": {"x": {"type": "category"}}},
        {"fields": {"x": {"type": "category", "values_from": "nope"}}},
        {"fields": {"x": {"type": "string", "bogus": 1}}},
        {"max_items": 1000, "fields": {}},
        {"fields": {"Bad-Key": {"type": "string"}}},
        "x",
    ]
    for b in bad:
        assert quotes.validate_line_limits("t.quote", b, inputs=["main_material"], categories={"main_material"}), b


def test_eto_pack_declares_line_limits():
    import yaml
    t = yaml.safe_load((h.ROOT / "packs" / "eto" / "tasks" / "quote.yaml").read_text(encoding="utf-8"))
    assert t.get("line_limits") == KD_LINE_LIMITS


# ── 추출 결과 상한 · 시간 상한 (#30 코어) · NUL (#32 004) ──────────────────────────────────
BOMB = '''
import time
from mlcore.tasks import dxf

NAME = "test_rects"
VERSION = "9.0.0"
KIND = "rule"


def extract(raw, filename, *, unit, limits, model=None):
    doc = dxf.read(raw, max_entities=limits["max_entities"])
    texts = [e.get(1, "") for e in doc.entities if e.type == "TEXT"]
    regions = []
    if "SLOW" in texts:
        while True:
            pass
    if "BIG" in texts:
        regions = [{"id": f"R{i}", "label": "other", "bbox": [0, 0, 1, 1], "texts": ["x" * 2000] * 5} for i in range(800)]
    if "MANY" in texts:
        regions = [{"id": f"R{i}", "label": "other", "bbox": [0, 0, 1, 1], "texts": []} for i in range(5001)]
    if "NUL" in texts:
        regions = [{"id": "R1", "label": "other", "bbox": [0, 0, 1, 1], "texts": ["a\\x00b"]}]
    if "OK" in texts:
        regions = [{"id": "R1", "label": "other", "bbox": [0, 0, 1, 1], "texts": ["OK"]}]
    return {"regions": regions, "objects": [], "bom_rows": [], "confidence": None, "counts": {}, "dimensions": None,
            "warnings": []}
'''


@pytest.fixture(scope="module")
def bomb(tmp_path_factory):
    m = p2.make_world(tmp_path_factory.mktemp("c2bomb"))
    (m.pack.path / "extractors" / "test_rects.py").write_text(textwrap.dedent(BOMB), encoding="utf-8")
    return m, h.keys(m), h.client(m)


def _doc_rows(m) -> int:
    return h.count("SELECT count(*) AS n FROM mlp_document WHERE tenant_id = %s", (m.tenant.code,))


def _assert_rejected(m, r, status, code, rule, raw):
    assert r.status_code == status, (r.status_code, r.text)
    e = r.json()["error"]
    assert e["code"] == code and e["detail"]["rule"] == rule, e
    assert not (p2.DOC_DIR / m.tenant.code / f"{hashlib.sha256(raw).hexdigest()}.dxf").exists()


def test_extract_ok_runs_isolated(bomb):
    m, k, tc = bomb
    raw = p2.dxf_bytes(texts=(("OK", 1, 1),))
    r = p2.upload(tc, m, k["operator"], raw)
    assert r.status_code == 201 and r.json()["regions"][0]["texts"] == ["OK"], r.text


@pytest.mark.parametrize("marker, rule", [("BIG", "result_bytes"), ("MANY", "items")])
def test_extract_result_caps_413(bomb, marker, rule):
    m, k, tc = bomb
    raw = p2.dxf_bytes(texts=((marker, 1, 1),))
    before = _doc_rows(m)
    _assert_rejected(m, p2.upload(tc, m, k["operator"], raw), 413, "document_too_large", rule, raw)
    assert _doc_rows(m) == before


def test_extract_time_limit_413(bomb, monkeypatch):
    import time
    m, k, tc = bomb
    monkeypatch.setenv("MLP_EXTRACT_MAX_SECONDS", "1")
    raw = p2.dxf_bytes(texts=(("SLOW", 1, 1),))
    t0 = time.monotonic()
    _assert_rejected(m, p2.upload(tc, m, k["operator"], raw), 413, "document_too_large", "time", raw)
    assert time.monotonic() - t0 < 10


def test_extract_nul_in_result_422_and_not_stored(bomb):
    m, k, tc = bomb
    raw = p2.dxf_bytes(texts=(("NUL", 1, 1),))
    before = _doc_rows(m)
    _assert_rejected(m, p2.upload(tc, m, k["operator"], raw), 422, "invalid_document", "nul", raw)
    assert _doc_rows(m) == before


def test_raw_nul_after_header_422(bomb):
    m, k, tc = bomb
    raw = p2.dxf_bytes(texts=(("OK", 1, 1), ("x" * 1500, 2, 2), ("y" * 1500, 3, 3), ("z" * 1500, 4, 4), ("a\x00b", 5, 5)))
    assert raw.index(b"\x00") > 4096
    _assert_rejected(m, p2.upload(tc, m, k["operator"], raw), 422, "invalid_document", "nul", raw)


def test_extract_limits_from_contract():
    from mlcore.tasks.extract import SPEC_LIMITS, limits_for
    import re
    text = (h.ROOT / "contracts" / "task-contract.md").read_text(encoding="utf-8")
    block = re.search(r"document_limits: (\{.*?\})", text).group(1)
    for k_, v in SPEC_LIMITS.items():
        assert re.search(rf"{k_}: {v}\b", block), (k_, block)
    lim = limits_for({"document": {"max_bytes": 100, "max_entities": 10, "max_result_bytes": 10 ** 12, "max_seconds": 1}})
    assert lim["max_result_bytes"] == SPEC_LIMITS["max_result_bytes"] and lim["max_seconds"] == 1


# ── CSV 수식 주입 (#32 003) ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", [" =1+1", "\n=1+1", "  @x", "\r\n+1", " \t-2", "=1", "\t1"])
def test_safe_cell_after_leading_space(v):
    assert quotes.safe_cell(v).startswith("'"), v


@pytest.mark.parametrize("v", ["abc", " abc", "1,000", "a=b"])
def test_safe_cell_plain_untouched(v):
    assert quotes.safe_cell(v) == v


# ── 화면 1 · health · overview 유형별 상태 (#29 002) · 대기열 can_decide (#29 004) ─────────
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = p2.make_world(tmp_path_factory.mktemp("c2world"))
    return m, h.keys(m), h.client(m)


def test_health_and_overview_by_type(world):
    m, k, tc = world
    code = m.tenant.code
    r = tc.get("/api/v1/health")
    by = {t["task"]: t for t in r.json()["tasks"]}
    assert by[p2.tid(m, "drawing")]["model_required"] is False and by[p2.tid(m, "drawing")]["model_ready"] is True
    est = by[p2.tid(m, "estimate")]
    assert est["model_required"] is False and est["model_ready"] is False
    assert est["uses"] == [{"task": p2.tid(m, "target_value"), "version": None}]
    assert by[p2.tid(m, "target_value")]["model_required"] is True
    for short, ready in (("drawing", True), ("estimate", False), ("value_review", False)):
        ov = tc.get(f"/api/v1/tenants/{code}/tasks/{p2.tid(m, short)}/overview", headers=h.hdr(k["viewer"])).json()
        assert ov["model_required"] is False and ov["model_ready"] is ready, ov
        if short != "drawing":
            assert ov["uses"] == [{"task": p2.tid(m, "target_value"), "version": None, "synthetic": None}], ov
    h.to_production(m, p2.tid(m, "target_value"))
    by = {t["task"]: t for t in tc.get("/api/v1/health").json()["tasks"]}
    assert by[p2.tid(m, "estimate")]["model_ready"] is True and by[p2.tid(m, "estimate")]["uses"][0]["version"]
    ov = tc.get(f"/api/v1/tenants/{code}/tasks/{p2.tid(m, 'value_review')}/overview", headers=h.hdr(k["viewer"])).json()
    assert ov["model_ready"] is True and ov["uses"][0]["version"]


def test_review_list_can_decide_by_role(world):
    m, k, tc = world
    code = m.tenant.code
    path = f"/api/v1/tenants/{code}/tasks/{p2.tid(m, 'value_review')}/review"
    assert tc.get(path, headers=h.hdr(k["operator"])).json()["can_decide"] is False
    assert tc.get(path, headers=h.hdr(k["approver"])).json()["can_decide"] is True
    assert tc.get(path, headers=h.hdr(k["admin"])).json()["can_decide"] is True
