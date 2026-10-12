"""G2-Q01 — 견적 (코어 흐름, 웨이브 P 개발2). goal2 §2 · §2.1 · §3.3 · predict-contract §8.3 · api-contract §6 · D2-19.

- Decimal · ROUND_HALF_UP 만: 정적 검사(gates/check_decimal.py) + 응답 금액은 원 단위 정수 **문자열**, JSON 실수 입력은 float 를 거치지 않는다.
- 사람 수정 → overrides(인식값과 다른 칸) · revision 마다 누적(지우지 않는다 — 소실은 치명).
- 확정: reviewed true + review_note ≥ 5자(공백 제외) 없으면 422 missing_required · 확정 요청 → 승인(kind=quote) → approver 이상 decide.
- 확정 · 대기 중 수정 409 quote_locked · 확정 금액은 모델이 바뀌어도 불변(스냅숏).
- CSV: UTF-8 BOM · 수식 주입 방지 · 금액 문자열 그대로.
**원천 견적식(kd · ot) 원 단위 대조는 팩 견적식(개발3 A2)이 생긴 뒤 이 파일에 더한다.** 여기 견적식은 시험용(tests/_phase2.py).
"""

from __future__ import annotations

import csv
import io
import sys
from decimal import ROUND_HALF_UP, Decimal

import jsonschema
import pytest

import _dev2 as h
import _phase2 as p2
from mlcore.db.conn import connect
from mlcore.registry.models import Registry

pytestmark = [pytest.mark.gate("G2-Q01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
QUOTE_SCHEMA = p2.schema("quote-schema")
ONE = Decimal(1)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = p2.make_world(tmp_path_factory.mktemp("quote"))
    ref, res = h.to_production(m, p2.tid(m, "target_value"))
    k = h.keys(m)
    tc = h.client(m)
    doc = p2.upload(tc, m, k["operator"], p2.sample_dxf()).json()
    return m, k, ref, res, doc


def base(m):
    return f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'estimate')}/quotes"


def _err(r, status, code, *, field=None, rule=None):
    assert r.status_code == status, (r.status_code, r.text)
    e = r.json()["error"]
    assert e["code"] == code, e
    if field:
        assert e["detail"].get("field") == field, e
    if rule:
        assert e["detail"].get("rule") == rule, e
    return e


LINES_JSON = '[{"name": "브래킷", "material": "SS400", "quantity": 2, "mass_kg": 1.5}, ' \
             '{"name": "볼트", "material": "SUS304", "quantity": 4, "mass_kg": 0.25}]'


def body_text(x1="80", x2="12.345678901234567890123", quantity=3, doc_id=None, extra=""):
    doc = f'"doc_id": "{doc_id}", ' if doc_id else ""
    return ('{' + doc + f'"inputs": {{"x1": {x1}, "x2": {x2}, "c1": "A", "quantity": {quantity}}}, '
            f'"lines": {LINES_JSON}{extra}' + '}')


def post_text(tc, url, key, text):
    return tc.post(url, headers={**h.hdr(key), "Content-Type": "application/json"}, content=text.encode("utf-8"))


def expected(q) -> dict:
    """시험용 견적식과 같은 계산을 시험이 따로 한다(Decimal) — 응답의 예측값(소수 4자리)으로."""
    hours = Decimal(q["predictions"][0]["value"])
    qty = Decimal(q["inputs"]["quantity"])
    rates = {k: Decimal(v) for k, v in q["rates"].items()}
    material = sum(((Decimal(str(m)) * Decimal(n) * rates["price_kg"] * qty).quantize(ONE, rounding=ROUND_HALF_UP)
                    for m, n in (("1.5", 2), ("0.25", 4))), Decimal(0))
    labor = (hours * rates["unit_rate"] * qty).quantize(ONE, rounding=ROUND_HALF_UP)
    markup = ((material + labor) * rates["markup"]).quantize(ONE, rounding=ROUND_HALF_UP)
    sub = material + labor + markup
    vat = (sub * rates["vat"]).quantize(ONE, rounding=ROUND_HALF_UP)
    return {"material": str(material), "labor": str(labor), "markup": str(markup), "subtotal": str(sub),
            "vat": str(vat), "total": str(sub + vat)}


# ── 정적 ───────────────────────────────────────────────────────────────────────────────
def test_core_quote_path_has_no_float():
    sys.path.insert(0, str(h.ROOT / "gates"))
    import check_decimal
    core = [p for p in check_decimal.targets() if "src/mlcore" in str(p)]
    assert core, "코어 견적 경로 파일이 없다"
    assert {str(p): check_decimal.scan(p) for p in core} == {str(p): [] for p in core}
    assert check_decimal.scan(h.ROOT / "tests" / "_phase2.py") != []          # 검사기가 float 를 실제로 잡는다(대조)


# ── 초안 ───────────────────────────────────────────────────────────────────────────────
def test_draft_amounts_are_decimal_strings_and_match_formula(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    r = post_text(tc, base(m), k["operator"], body_text(doc_id=doc["doc_id"]))
    assert r.status_code == 201, r.text
    q = r.json()
    jsonschema.validate(q, QUOTE_SCHEMA)
    assert q["status"] == "draft" and q["revision"] == 1 and q["supersedes"] is None and q["currency"] == "KRW"
    want = expected(q)
    assert {k2: q["costs"][k2] for k2 in want if k2 != "total"} == {k2: v for k2, v in want.items() if k2 != "total"}
    assert q["total"] == want["total"] and isinstance(q["total"], str)
    assert all(isinstance(v, str) for v in q["costs"].values()) and all(isinstance(x["amount"], str) for x in q["lines"])
    assert '"total":"' in r.text and '"x2":12.345678901234567890123' in r.text   # 금액 문자열 · 입력 실수는 float 를 거치지 않음
    assert q["rates"] == {"unit_rate": "45000", "price_kg": "1200", "markup": "0.15", "vat": "0.10"}
    assert q["model_versions"] == [{"task": p2.tid(m, "target_value"), "version": ref.version, "synthetic": True}]
    assert q["synthetic"] is True and q["notice"]
    pid = q["predictions"][0]["prediction_id"]
    with connect() as c:                                                     # 작업시간 예측은 표준 predict 1행(근거)
        row = c.execute("SELECT task_id, channel FROM mlp_prediction WHERE prediction_id = %s", (pid,)).fetchone()
        db = c.execute("SELECT total, costs, status FROM mlp_quote WHERE quote_id = %s", (q["quote_id"],)).fetchone()
    assert row == {"task_id": p2.tid(m, "target_value"), "channel": "api"}
    assert db["total"] == Decimal(want["total"]) and db["costs"] == q["costs"] and db["status"] == "draft"


def test_overrides_recorded_and_accumulated(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    q1 = post_text(tc, base(m), k["operator"], body_text(x1="80", doc_id=doc["doc_id"])).json()
    assert q1["overrides"] == []                                             # 인식 폭 80 = 확정 80
    q2 = post_text(tc, f"{base(m)}/{q1['quote_id']}/revisions", k["operator"], body_text(x1="81")).json()
    assert q2["revision"] == 2 and q2["supersedes"] == q1["quote_id"] and q2["doc_id"] == doc["doc_id"]
    assert q2["overrides"] == [{"field": "x1", "recognized": 80.0, "confirmed": 81}]
    q3 = post_text(tc, f"{base(m)}/{q2['quote_id']}/revisions", k["operator"], body_text(x1="80.0005")).json()
    assert q3["overrides"] == q2["overrides"]                                # 허용차 0.001 안 — 새 항목 없음, 이력은 남는다
    q4 = post_text(tc, f"{base(m)}/{q3['quote_id']}/revisions", k["operator"], body_text(x1="79")).json()
    assert q4["overrides"] == [*q2["overrides"], {"field": "x1", "recognized": 80.0, "confirmed": 79}]
    got = tc.get(f"{base(m)}/{q1['quote_id']}", headers=h.hdr(k["operator"])).json()
    assert got["quote_id"] == q4["quote_id"] and got["revision"] == 4       # 어느 ID 로 불러도 최신 revision
    lst = tc.get(f"{base(m)}?search={q4['quote_id']}", headers=h.hdr(k["operator"])).json()
    assert [x["quote_id"] for x in lst["items"]] == [q4["quote_id"]] and lst["total"] == 1


def test_input_validation(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    _err(post_text(tc, base(m), k["operator"], body_text(extra=', "bogus": 1')), 422, "invalid_input", rule="extra_forbidden")
    _err(post_text(tc, base(m), k["operator"], body_text(x1="NaN")), 422, "invalid_input", rule="json_invalid")
    _err(post_text(tc, base(m), k["operator"], body_text(x1="1000")), 422, "out_of_bounds")
    _err(post_text(tc, base(m), k["operator"], body_text(quantity='"three"')), 422, "invalid_input", field="quantity")
    _err(post_text(tc, base(m), k["operator"], '{"inputs": {"x1": 50, "c1": "A", "x2": 50}}'), 422, "missing_required",
         field="quantity")
    _err(post_text(tc, base(m), k["operator"], body_text(doc_id="doc_00000000000000000000000000")), 404, "not_found")
    _err(post_text(tc, base(m), k["viewer"], body_text()), 403, "forbidden")
    _err(post_text(tc, base(m), k["operator"], body_text(extra=', "reviewed": true, "review_note": "짧음"')), 422,
         "missing_required", field="review_note")


def test_model_not_ready_makes_no_draft(tmp_path):
    m = p2.make_world(tmp_path)
    k = h.keys(m)
    tc = h.client(m)
    _err(post_text(tc, base(m), k["operator"], body_text()), 503, "model_not_ready")
    assert h.count("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id = %s", (m.tenant.code,)) == 0


# ── 확정 ───────────────────────────────────────────────────────────────────────────────
def _draft(tc, m, k):
    return post_text(tc, base(m), k["operator"], body_text()).json()


def test_confirm_requires_review_and_note(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    q = _draft(tc, m, k)
    url = f"{base(m)}/{q['quote_id']}/confirm"
    _err(tc.post(url, headers=h.hdr(k["operator"]), json={"review_note": "충분히 긴 메모"}), 422, "missing_required", field="reviewed")
    _err(tc.post(url, headers=h.hdr(k["operator"]), json={"reviewed": False, "review_note": "충분히 긴 메모"}), 422,
         "missing_required", field="reviewed")
    _err(tc.post(url, headers=h.hdr(k["operator"]), json={"reviewed": True, "review_note": "  짧다  "}), 422,
         "missing_required", field="review_note")
    _err(tc.post(url, headers=h.hdr(k["operator"]), json={"reviewed": True}), 422, "missing_required", field="review_note")
    assert tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()["status"] == "draft"


def test_confirm_flow_lock_and_snapshot(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    q = _draft(tc, m, k)
    r = tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                json={"reviewed": True, "review_note": "도면 · BOM 확인함"})
    assert r.status_code == 202 and r.json()["state"] == "pending", r.text
    aid = r.json()["approval_id"]
    pend = tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()
    assert pend["status"] == "pending_confirm" and pend["approval_id"] == aid and pend["reviewed"] is True
    assert pend["total"] == q["total"] and pend["reviewed_by"].startswith("test-operator")
    _err(post_text(tc, f"{base(m)}/{q['quote_id']}/revisions", k["operator"], body_text()), 409, "quote_locked")
    _err(tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                 json={"reviewed": True, "review_note": "다시 요청"}), 409, "quote_locked")
    _err(tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["operator"]),
                 json={"decision": "approve", "reason": "x"}), 403, "forbidden")     # 확정 결정은 approver 이상(D2-04)
    _err(tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver_other"]),
                 json={"decision": "approve", "reason": "x"}), 403, "forbidden")     # 남의 과제 approver
    d = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "확인"})
    assert d.status_code == 200 and d.json()["state"] == "approved", d.text
    conf = tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()
    jsonschema.validate(conf, QUOTE_SCHEMA)
    assert conf["status"] == "confirmed" and conf["confirmed_by"].startswith("test-approver") and conf["confirmed_at"]
    assert conf["revision"] == q["revision"] + 2 and conf["total"] == q["total"]
    _err(post_text(tc, f"{base(m)}/{q['quote_id']}/revisions", k["operator"], body_text()), 409, "quote_locked")
    _err(tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                 json={"reviewed": True, "review_note": "다시 확정"}), 409, "quote_locked")
    _err(tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "x"}),
         409, "already_decided")
    # 모델이 바뀌어도 확정 금액은 그대로 — 새 production 으로 같은 입력의 새 초안은 다른 금액
    h.to_production(m, p2.tid(m, "target_value"), seed=7)
    assert Registry().get(m.tenant.code, p2.tid(m, "target_value")).version != ref.version
    again = tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()
    assert again == conf
    fresh = _draft(tc, m, k)
    assert fresh["model_versions"][0]["version"] != conf["model_versions"][0]["version"]
    with pytest.raises(Exception):                                            # 추가만 — DB 가 수정을 거부한다
        with connect() as c:
            c.execute("UPDATE mlp_quote SET total = 1 WHERE quote_id = %s", (again["quote_id"],))


def test_reject_and_expiry_return_to_draft(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    q = _draft(tc, m, k)
    aid = tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                  json={"reviewed": True, "review_note": "검토 완료함"}).json()["approval_id"]
    d = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "reject", "reason": "단가 확인"})
    assert d.json()["state"] == "rejected"
    back = tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()
    assert back["status"] == "draft" and back["reviewed"] is False and back["approval_id"] is None
    r2 = post_text(tc, f"{base(m)}/{q['quote_id']}/revisions", k["operator"], body_text(quantity=5))
    assert r2.status_code == 201                                                # 반려 뒤에는 다시 고칠 수 있다
    aid2 = tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                   json={"reviewed": True, "review_note": "다시 검토함"}).json()["approval_id"]
    with connect() as c:
        c.execute("UPDATE mlp_approval SET expires_at = now() - interval '1 second', requested_at = now() - interval '2 second' "
                  "WHERE approval_id = %s", (aid2,))
    from mlcore import approval
    assert approval.expire_due(approval_id=aid2) == [aid2]
    assert tc.get(f"{base(m)}/{q['quote_id']}", headers=h.hdr(k["operator"])).json()["status"] == "draft"


def test_quote_approval_listed_for_screen5(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    q = _draft(tc, m, k)
    aid = tc.post(f"{base(m)}/{q['quote_id']}/confirm", headers=h.hdr(k["operator"]),
                  json={"reviewed": True, "review_note": "검토 완료함"}).json()["approval_id"]
    items = tc.get(f"/api/v1/tenants/{m.tenant.code}/approvals?state=pending", headers=h.hdr(k["approver"])).json()["items"]
    mine = [a for a in items if a["approval_id"] == aid]
    assert mine and mine[0]["kind"] == "quote" and mine[0]["action"] == "confirm" and mine[0]["evidence"]["total"] == q["total"]


# ── CSV ───────────────────────────────────────────────────────────────────────────────
def test_csv_bom_and_formula_injection(world):
    m, k, ref, res, doc = world
    tc = h.client(m)
    evil = '[{"name": "=HYPERLINK(\\"a\\")", "material": "+SUM(A1)", "quantity": 2, "mass_kg": 1.5}, ' \
           '{"name": "@cmd", "material": "-1", "quantity": 4, "mass_kg": 0.25}]'
    text = body_text().replace(LINES_JSON, evil)
    q = post_text(tc, base(m), k["operator"], text + "").json()
    r = tc.get(f"{base(m)}/{q['quote_id']}.csv", headers=h.hdr(k["operator"]))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith("﻿".encode("utf-8"))
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    cells = [c for row in rows for c in row]
    assert not any(c[:1] in ("=", "+", "-", "@", "\t", "\r") for c in cells), [c for c in cells if c[:1] in "=+-@"]
    assert "'=HYPERLINK(\"a\")" in cells and "'+SUM(A1)" in cells and "'@cmd" in cells and "'-1" in cells
    summary = dict(row for row in rows if len(row) == 2)
    assert summary["total"] == q["total"] and summary["costs.vat"] == q["costs"]["vat"]       # 금액 문자열 그대로
    _err(tc.get(f"{base(m)}/qte_00000000000000000000000000.csv", headers=h.hdr(k["operator"])), 404, "not_found")
    _err(tc.get(f"{base(m)}/{q['quote_id']}.csv", headers=h.hdr(k["viewer"])), 403, "forbidden")
