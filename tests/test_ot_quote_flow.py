"""ot.quote — 실제 팩 rollform-quote · 회사 ot 로 학습 → 승인 → 도면 업로드(규칙 + 모델 추출기) → 견적 초안 (코어 0줄, G2-C01).

- ot.cad_objects 모델 추출기는 그 과제의 production(표준 학습기 · 합성 설명자 1,600 · 층화)에서만 온다 — 없으면 503 model_not_ready.
- 샘플 도면(원천 sample_bytes 와 같은 도형) → counts outer 1 · hole 6 · slot 2 · other 0 · dimensions 1200 × 160.
- 견적 금액 = 팩 견적식(Decimal · HALF_UP)을 같은 입력 · 같은 예측으로 직접 부른 값과 원 단위 일치 · 예측 채널 'quote'.
- 인식값(홀 · 슬롯 · 길이 · 폭)과 확정 입력이 0.001 넘게 다르면 overrides — 원천 시험 `[{'field':'holes','recognized':6,'confirmed':7}]`.
- 요소 상한은 팩 document.max_entities 2,000(원천 config.py:25) — 넘으면 413 document_too_large(rule entities).
"""
from __future__ import annotations

import importlib.util
import json
from decimal import Decimal

import pytest

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup"), pytest.mark.gate("G2-P01")]
PACK = h.ROOT / "packs" / "rollform-quote"
RATES = (h.ROOT / "tenants" / "ot" / "tasks" / "quote.yaml")


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PACK / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SD = _load("synth/sample_dxf.py", "rq_flow_sample_dxf")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import yaml
    m = h.make_tenant("ot", tmp_path_factory.mktemp("otq"), overrides={"quote": yaml.safe_load(RATES.read_text(encoding="utf-8"))})
    code = m.tenant.code
    k = h.keys(m)
    tc = h.client(m)
    url = f"/api/v1/tenants/{code}/tasks/{code}.cad_objects/documents"
    before = tc.post(url, headers=h.hdr(k["operator"]), files={"file": ("sample.dxf", SD.sample_bytes(), "application/dxf")})
    h.real_production(m, f"{code}.machining_minutes")
    _, objects_run = h.real_production(m, f"{code}.cad_objects")
    r = tc.post(url, headers=h.hdr(k["operator"]), files={"file": ("sample.dxf", SD.sample_bytes(), "application/dxf")})
    assert r.status_code == 201, r.text
    return m, k, tc, r.json(), before, objects_run


def _body(doc, **kw):
    inputs = {"part_length_mm": 1200, "blank_width_mm": 160, "sheet_thickness_mm": 2, "hole_count": 6, "slot_count": 2,
              "bend_count": 2, "steel_grade": "SPCC", "section_profile": "잔넬", "quantity": 100}
    inputs.update(kw)
    return {"doc_id": doc["doc_id"], "inputs": inputs, "reviewed": True, "review_note": "단일 전개도 치수와 홀·슬롯 확인"}


def test_model_extractor_needs_production(world):
    m, k, tc, doc, before, run = world
    assert before.status_code == 503 and before.json()["error"]["code"] == "model_not_ready"


def test_object_model_is_stratified_macro_f1_with_baseline(world):
    m, k, tc, doc, before, run = world
    assert run.report["split"]["boundaries"]["sizes"] == {"train": 960, "valid": 320, "test": 320}
    assert run.report["selection_metric"] == "macro_f1" and run.report["baseline"] == "majority_class"
    tm = run.test_metrics["macro_f1"]
    assert tm.value == pytest.approx(1.0) and tm.baseline == pytest.approx(0.1) and run.beats_baseline
    cm = run.report["extract_metrics"]["confusion_matrix"]
    assert cm["labels"] == ["outer", "hole", "slot", "other"] and sum(map(sum, cm["matrix"])) == 320


def test_sample_drawing_counts_and_dimensions(world):
    m, k, tc, doc, before, run = world
    assert doc["counts"] == {"outer": 1, "hole": 6, "slot": 2, "other": 0}
    assert doc["dimensions"] == {"length": 1200.0, "width": 160.0} and doc["entity_count"] == 9
    assert doc["labels"] == "synthetic" and doc["metrics"] is None                 # 업로드 도면에는 정답이 없다
    assert [e["kind"] for e in doc["extractor"]] == ["rule", "model"] and doc["extractor"][1]["model_version"]
    assert len(doc["objects"]) == 9 and all(o["review_reason"] is None for o in doc["objects"])
    assert 0.8 <= doc["confidence"] <= 1.0


def test_quote_draft_matches_pack_formula_to_the_won(world):
    m, k, tc, doc, *_ = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc)))
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["status"] == "draft" and q["overrides"] == [] and isinstance(q["total"], str)
    pred = Decimal(q["predictions"][0]["value"])
    formula = _load("formulas/quote.py", "rq_flow_quote")
    dec = json.loads(json.dumps(_body(doc)), parse_float=Decimal)
    raw = m.tasks[f"{code}.quote"].raw["rates"]
    rates = {k_: ({c: Decimal(x) for c, x in v.items()} if isinstance(v, dict) else Decimal(v)) for k_, v in raw.items()}
    want = formula.quote(dec["inputs"], [], {"machining_minutes": pred}, rates)
    assert Decimal(q["total"]) == want["total"] and {k_: Decimal(v) for k_, v in q["costs"].items()} == want["costs"]
    assert q["costs"]["material"] == "423222" and q["costs"]["setup"] == "31500"   # 원천 저장 견적과 같은 단계(예측 무관)
    with connect() as c:
        row = c.execute("SELECT channel FROM mlp_prediction WHERE prediction_id=%s",
                        (q["predictions"][0]["prediction_id"],)).fetchone()
    assert row["channel"] == "quote"


def test_changed_recognized_value_is_an_override(world):
    m, k, tc, doc, *_ = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, hole_count=7)))
    assert r.status_code == 201, r.text
    ov = r.json()["overrides"]
    assert len(ov) == 1 and ov[0]["field"] == "hole_count"
    assert Decimal(str(ov[0]["recognized"])) == 6 and Decimal(str(ov[0]["confirmed"])) == 7
    r2 = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                 "Content-Type": "application/json"}, content=json.dumps(_body(doc, part_length_mm=1200.0005)))
    assert r2.status_code == 201 and r2.json()["overrides"] == []                  # 허용차 0.001 안


def test_entity_limit_is_pack_2000(world):
    m, k, tc, *_ = world
    code = m.tenant.code
    ents = []
    for i in range(2001):
        ents += SD._circle(10 + i, 10, 1, "H")
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.cad_objects/documents", headers=h.hdr(k["operator"]),
                files={"file": ("big.dxf", SD.dxf_bytes(ents), "application/dxf")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "document_too_large"
    assert r.json()["error"]["detail"]["rule"] == "entities"


@pytest.mark.parametrize("value", [0, 1.5, 10001, -3])
def test_quote_quantity_follows_task_input_limits(world, value):
    """D2-A2-03 (웨이브 P 재진입 D2-70): 견적 수량은 과제 `input_limits` — 원천 QuoteInput
    (`OneTouch ML AI/api/main.py:43` quantity 1~10,000 정수). 밖이면 422 invalid_input(field quantity)."""
    m, k, tc, doc, *_ = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, quantity=value)))
    assert r.status_code == 422, r.text
    e = r.json()["error"]
    assert e["code"] == "invalid_input" and e["detail"]["field"] == "quantity", e


def test_quote_quantity_upper_limit_accepted(world):
    m, k, tc, doc, *_ = world
    code = m.tenant.code
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"}, content=json.dumps(_body(doc, quantity=10000)))
    assert r.status_code == 201, r.text
