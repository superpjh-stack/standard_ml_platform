"""kd.quote — 실제 팩 eto · 회사 kd 로 도면 업로드 → BOM 인식 → 견적 초안 (D2-31 결정 뒤 과제 quote 켜짐 · D2-45).

- 과제 이름 `quote` = 유형 코드 — G-M01 은 std 어휘 과제 이름(자기 유형)을 코어 금지어에서 뺀다(gates/check_core_terms.py).
- 코어가 추출기에 회사 범주 · 재질 별칭(context)을 넘긴다 → bom_text 의 '재질 목록 없음' 경고가 사라지고 재질이 정규 값.
- 견적 금액 = 팩 견적식(Decimal · HALF_UP)을 같은 입력으로 직접 부른 값과 원 단위 일치 · 예측 채널 'quote'.
- 인식 BOM 과 확정 BOM 이 공통 키에서 같으면 overrides 0(단가 칸은 확정에만 있다), 바꾸면 1.
"""
from __future__ import annotations

import importlib.util
import json
from decimal import Decimal

import pytest

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
PACK = h.ROOT / "packs" / "eto"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PACK / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = h.make_tenant("kd", tmp_path_factory.mktemp("kdq"))
    code = m.tenant.code
    ref, _ = h.real_production(m, f"{code}.labor_hours")
    k = h.keys(m)
    tc = h.client(m)
    mats = m.tenant.config["categories"]["main_material"]
    raw = _load("synth/sample_dxf.py", "eto_sample_dxf_q").sample_bytes(mats)
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": ("sample.dxf", raw, "application/dxf")})
    assert r.status_code == 201, r.text
    return m, k, tc, r.json()


def _lines(doc, price="6500"):
    return [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
             "price_kg": price} for b in doc["bom_rows"]]


def _body(doc, lines, **kw):
    inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
              "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
    inputs.update(kw)
    return {"doc_id": doc["doc_id"], "inputs": inputs, "lines": lines, "reviewed": True, "review_note": "시험 견적 검토"}


def test_extractor_gets_tenant_context(world):
    m, k, tc, doc = world
    mats = set(m.tenant.config["categories"]["main_material"])
    assert doc["bom_rows"] and all(b["material"] in mats for b in doc["bom_rows"])
    assert not any("재질 목록" in w for w in doc["warnings"]), doc["warnings"]


def test_quote_draft_matches_pack_formula_to_the_won(world):
    m, k, tc, doc = world
    code = m.tenant.code
    lines = _lines(doc)
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, lines)))
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["status"] == "draft" and q["overrides"] == [] and isinstance(q["total"], str)
    pred = Decimal(q["predictions"][0]["value"])
    formula = _load("formulas/quote.py", "eto_quote_q")
    dec = json.loads(json.dumps(_body(doc, lines)), parse_float=Decimal)
    rates = {k_: Decimal(v) for k_, v in m.tasks[f"{code}.quote"].raw["rates"].items()}
    want = formula.quote({**dec["inputs"], **formula.prepare(dec["inputs"], dec["lines"])}, dec["lines"],
                         {"labor_hours": pred}, rates)
    assert Decimal(q["total"]) == want["total"] and {k_: Decimal(v) for k_, v in q["costs"].items()} == want["costs"]
    with connect() as c:
        row = c.execute("SELECT channel FROM mlp_prediction WHERE prediction_id=%s",
                        (q["predictions"][0]["prediction_id"],)).fetchone()
    assert row["channel"] == "quote"


def test_changed_bom_is_an_override(world):
    m, k, tc, doc = world
    code = m.tenant.code
    lines = _lines(doc)
    lines[0]["quantity"] = int(lines[0]["quantity"]) + 1
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, lines)))
    assert r.status_code == 201, r.text
    ov = r.json()["overrides"]
    assert len(ov) == 1 and ov[0]["field"] == "bom"


def test_task_detail_exposes_quote_and_extract_keys(world):
    m, k, tc, doc = world
    code = m.tenant.code
    q = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.quote", headers=h.hdr(k["viewer"])).json()
    assert q["inputs"] and q["recognized"] == {"bom": "bom_rows"} and q["rates"]["vat_rate"] == "0.10"
    assert {f["name"] for f in q["features"]} <= set(q["inputs"])
    d = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.drawing_regions", headers=h.hdr(k["viewer"])).json()
    assert d["document"]["max_entities"] == 20000 and d["labels"] == "none" and len(d["extractors"]) == 2


@pytest.mark.parametrize("field,value", [("quantity", 0), ("quantity", 1.5), ("quantity", 1001), ("labor_rate", 0),
                                         ("labor_rate", 1000001), ("outsource_cost", -1)])
def test_quote_extra_inputs_follow_task_input_limits(world, field, value):
    """D2-A2-03 (웨이브 P 재진입 D2-70): features.yaml 밖 견적 입력도 과제 `input_limits` 범위 — 원천 QuoteInput
    (`KyungDong ML AI/api/main.py:52,57,58` quantity 1~1000 정수 · labor_rate 1~1,000,000 · outsource_cost 0~1e9). 밖이면 422."""
    m, k, tc, doc = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, _lines(doc), **{field: value})))
    assert r.status_code == 422, r.text
    e = r.json()["error"]
    assert e["code"] == "invalid_input" and e["detail"]["field"] == field, e
    assert str(value) not in json.dumps(e["detail"])                       # 입력값을 되풀이하지 않는다


def test_quote_extra_inputs_at_limits_are_accepted(world):
    m, k, tc, doc = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, _lines(doc), quantity=1000, labor_rate=1)))
    assert r.status_code == 201, r.text
