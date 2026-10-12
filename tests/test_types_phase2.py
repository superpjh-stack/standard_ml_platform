"""G2-T01 — 유형 3 계약 (review_queue · extract · quote). goal2 §2 · §2.1 · predict-contract §8 · api-contract §6 · D2-20.

각 유형의 입력 · 출력(스키마) · 상태 전이 · 오류가 계약대로인지, 2차 유형 경로에 501 이 없는지 본다.
세부 흐름은 tests/test_extract.py(G2-E01) · tests/test_quote.py(G2-Q01) — 여기는 유형 계약의 공통 면과 B09 대기열.
"""

from __future__ import annotations

import re

import jsonschema
import pytest
import yaml

import _dev2 as h
import _phase2 as p2

pytestmark = [pytest.mark.gate("G2-T01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
TYPES = ("review_queue", "extract", "quote")
ERROR_CODES = yaml.safe_load((h.ROOT / "std" / "statuses.yaml").read_text(encoding="utf-8"))["error_codes"]
ITEM_SCHEMA = p2.schema("review-item-schema")


def test_std_and_contract_know_the_three_types():
    types = yaml.safe_load((h.ROOT / "std" / "task_types.yaml").read_text(encoding="utf-8"))["types"]
    assert all(types[t]["phase"] == 1 for t in TYPES)
    for name in ("review-item-schema", "document-schema", "quote-schema"):
        jsonschema.Draft202012Validator.check_schema(p2.schema(name))
    for code, status in {"invalid_document": 422, "document_too_large": 413, "quote_locked": 409,
                         "already_decided": 409, "missing_required": 422}.items():
        assert ERROR_CODES[code] == status


def test_api_routes_of_section6_exist():
    from mlcore.api.main import app
    paths = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    text = (h.ROOT / "contracts" / "api-contract.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| B(?:09|10|11) [a-z]+ \| (?:P|1) \| (GET|POST|PATCH) \| `([^`]+)` \|", text, re.M)
    assert len(rows) >= 11
    missing = [r for r in rows if r not in paths]
    assert not missing, missing


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = p2.make_world(tmp_path_factory.mktemp("types2"))
    ref, res = h.to_production(m, p2.tid(m, "target_value"))
    other = p2.make_world(tmp_path_factory.mktemp("types2-other"))
    return m, h.keys(m), h.keys(other), ref, res


def _err(r, status, code, rule=None):
    assert r.status_code == status, (r.status_code, r.text)
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "detail"}
    assert body["error"]["code"] == code and ERROR_CODES[code] == status
    if rule:
        assert body["error"]["detail"].get("rule") == rule, body
    return body["error"]


@pytest.mark.parametrize("short", ["value_review", "drawing", "estimate"])
def test_phase2_task_has_no_predict_or_optimize(world, short):
    m, k, ko, ref, res = world
    tc = h.client(m)
    base = f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, short)}"
    _err(tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": {}}), 404, "not_found", "type_route")
    _err(tc.post(f"{base}/predict:batch", headers=h.hdr(k["operator"]), json={"items": [{"inputs": {}}]}), 404, "not_found",
         "type_route")
    _err(tc.post(f"{base}/optimize", headers=h.hdr(k["operator"]), json={"fixed": {}}), 404, "not_found", "type_route")


@pytest.mark.parametrize("method,path,short", [
    ("GET", "/review", "estimate"), ("PATCH", "/review/rvw_00000000000000000000000000", "drawing"),
    ("GET", "/documents", "value_review"), ("GET", "/documents/doc_00000000000000000000000000", "estimate"),
    ("GET", "/quotes", "drawing"), ("GET", "/quotes/qte_00000000000000000000000000", "value_review"),
    ("GET", "/quotes/qte_00000000000000000000000000.csv", "target_value"),
])
def test_resource_route_on_wrong_type_is_404_type_route(world, method, path, short):
    m, k, ko, ref, res = world
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, short)}{path}"
    r = h.client(m).request(method, url, headers=h.hdr(k["admin"]), json={"state": "false_alarm", "note": "x"}
                            if method == "PATCH" else None)
    _err(r, 404, "not_found", "type_route")


# ── B09 대기열 ────────────────────────────────────────────────────────────────────────
def test_review_list_and_decide_contract(world):
    m, k, ko, ref, res = world
    tc = h.client(m)
    pid = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'target_value')}/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": h.safe_inputs(res), "entity_id": "LOT-1"}).json()["prediction_id"]
    a = p2.review_item(m)
    b = p2.review_item(m, origin="live_residual", prediction_id=pid)
    base = f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'value_review')}/review"
    lst = tc.get(f"{base}?state=open&limit=1", headers=h.hdr(k["operator"])).json()       # operator 조회
    assert set(lst) == {"items", "next_cursor", "total", "can_decide"} and lst["can_decide"] is False and lst["total"] >= 2 and len(lst["items"]) == 1
    assert lst["next_cursor"]
    nxt = tc.get(f"{base}?state=open&limit=1&cursor={lst['next_cursor']}", headers=h.hdr(k["operator"])).json()
    assert {lst["items"][0]["item_id"], nxt["items"][0]["item_id"]} == {a, b}
    for it in lst["items"] + nxt["items"]:
        jsonschema.validate(it, ITEM_SCHEMA)
    _err(tc.get(base, headers=h.hdr(k["viewer"])), 403, "forbidden")                    # viewer ✕ (goal2 §6)
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["operator"]), json={"state": "false_alarm", "note": "노이즈"}), 403, "forbidden")
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["approver_other"]), json={"state": "false_alarm", "note": "노이즈"}), 403,
         "forbidden")                                                                    # 자기 과제만
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["approver"]), json={"state": "open", "note": "x"}), 422, "invalid_input")
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["approver"]), json={"state": "false_alarm", "note": " "}), 422, "invalid_input")
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["approver"]), json={"state": "false_alarm", "note": "x", "x": 1}), 422,
         "invalid_input")
    r = tc.patch(f"{base}/{a}", headers=h.hdr(k["approver"]), json={"state": "confirmed_issue", "note": "재측정 필요"})
    assert r.status_code == 200, r.text
    it = r.json()
    jsonschema.validate(it, ITEM_SCHEMA)
    assert it["state"] == "confirmed_issue" and it["note"] == "재측정 필요" and it["decided_by"].startswith("test-approver")
    _err(tc.patch(f"{base}/{a}", headers=h.hdr(k["admin"]), json={"state": "false_alarm", "note": "다시"}), 409,
         "already_decided")                                                              # 닫힌 항목 재검토
    _err(tc.patch(f"{base}/rvw_00000000000000000000000000", headers=h.hdr(k["approver"]),
                  json={"state": "false_alarm", "note": "x"}), 404, "not_found")
    closed = tc.get(f"{base}?state=confirmed_issue", headers=h.hdr(k["approver"])).json()["items"]
    assert [x["item_id"] for x in closed] == [a]
    _err(tc.get(base, headers=h.hdr(ko["admin"])), 404, "not_found")                    # 다른 회사 키


def test_review_concurrent_decide_one_wins(world):
    m, k, ko, ref, res = world
    from concurrent.futures import ThreadPoolExecutor

    from mlcore.serve import review
    a = p2.review_item(m)

    def go(state):
        try:
            review.close_item(m.tenant.code, p2.tid(m, "value_review"), a, state=state, note="동시", actor="x", role="approver")
            return "ok"
        except review.AlreadyDecided:
            return "409"
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(go, ["confirmed_issue", "false_alarm"] * 2))
    assert sorted(got) == ["409", "409", "409", "ok"]


def test_review_origin_cannot_be_training_split(world):
    m, k, ko, ref, res = world
    with pytest.raises(Exception):
        p2.review_item(m, origin="train_split")                                         # DB CHECK — 학습 구간 잔차 금지
