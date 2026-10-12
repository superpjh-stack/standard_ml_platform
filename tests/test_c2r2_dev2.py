"""웨이브 C2 2회전 — QA 재검증(r2) 경미 결함 회귀 시험 (D2-111 ~ D2-113).

- DEF-QA2R2-002: JSON 본문 문자열의 NUL(`\\u0000`) → 500 이던 경로(견적 품목 이름 · 메모 · 수정 · 확정 요청, 실측 · 예측 entity_id,
  옛 견적 경로) → 공통 검증에서 422 rule `nul`, 입력값 되풀이 없음, 행 0. QA 재현 `outputs/qa2-r2/q2/probe_nul_r2.py`.
- DEF-QA2R2-003: 실측 API 가 미래 관측 시각(서버 시각 + 5분 초과)을 받았다 → 422 rule `future`.
  응답 `linked_prediction_ids` 가 같은 entity 예측 전부였다 → D2-81 1:1 짝 규칙(대기열 `train.review.live_pairs` 와 같은 SQL).
- DEF-QA2R2-004: 품목 · 입력 숫자 정규화 — 문자열 숫자 앞뒤 공백 · 숫자/문자열 혼재 저장 · 수량 문자열을 품목은 받고 입력은 거부
  → 저장 전 정규형(숫자 = Decimal 10진, 공백 제거), 품목 · 입력 같은 규칙.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
NUL = "a\u0000b"


@pytest.fixture(scope="module")
def kd(tmp_path_factory):
    m = h.make_tenant("kd", tmp_path_factory.mktemp("c2r2kd"))
    code = m.tenant.code
    tdir = m.tenant.path.parent / code
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(h.ROOT / "tenants" / "kd" / "compat.py", tdir / "compat.py")          # 옛 경로 플러그인(시험 회사 폴더로)
    if (h.ROOT / "tenants" / "kd" / "samples").is_dir():
        shutil.copytree(h.ROOT / "tenants" / "kd" / "samples", tdir / "samples")
    ref, _ = h.real_production(m, f"{code}.labor_hours")
    k = h.keys(m)
    tc = h.client(m)
    mats = m.tenant.config["categories"]["main_material"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("eto_sample_dxf_c2r2", h.ROOT / "packs" / "eto" / "synth" / "sample_dxf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": ("sample.dxf", mod.sample_bytes(mats), "application/dxf")})
    assert r.status_code == 201, r.text
    lock = h.lock_of(ref)
    feats = list(h.task_features(m, f"{code}.labor_hours"))
    return {"m": m, "k": k, "tc": tc, "doc": r.json(), "code": code, "pred_inputs": h.mid_inputs(lock, feats)}


def _jpost(w, url, body, key="operator"):
    return w["tc"].post(url, headers={**h.hdr(w["k"][key]), "Content-Type": "application/json"},
                        content=json.dumps(body, ensure_ascii=False).encode("utf-8"))


def _lines(doc, price="6500"):
    return [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
             "price_kg": price} for b in doc["bom_rows"]]


def _inputs(doc, **kw):
    out = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
           "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
    out.update(kw)
    return out


def _qbody(w, lines=None, **kw):
    doc = w["doc"]
    return {"doc_id": doc["doc_id"], "inputs": _inputs(doc, **kw.pop("inputs", {})),
            "lines": _lines(doc) if lines is None else lines, "reviewed": True, "review_note": "검토 완료 견적", **kw}


def _q(w):
    return f"/api/v1/tenants/{w['code']}/tasks/{w['code']}.quote"


def _rows(w, table):
    return h.count(f"SELECT count(*) AS n FROM {table} WHERE tenant_id = %s", (w["code"],))


def _no_echo(r):
    assert "\\u0000" not in r.text and "\x00" not in r.text and "a\\u0000b" not in r.text, r.text


# ── DEF-QA2R2-002 NUL → 422 nul ─────────────────────────────────────────────────────────────────
def _std_nul(r, field=None):
    assert r.status_code == 422, (r.status_code, r.text[:300])
    e = r.json()["error"]
    assert e["code"] == "invalid_input" and e["detail"]["rule"] == "nul", e
    if field is not None:
        assert e["detail"]["field"] == field, e
    _no_echo(r)


def test_nul_quote_create_paths_422(kd):
    w = kd
    L = _lines(w["doc"])
    before = _rows(w, "mlp_quote")
    _std_nul(_jpost(w, f"{_q(w)}/quotes", _qbody(w, [{**L[0], "name": NUL}] + L[1:])), "lines.0.name")
    _std_nul(_jpost(w, f"{_q(w)}/quotes", {**_qbody(w), "review_note": "검토 " + NUL}), "review_note")
    _std_nul(_jpost(w, f"{_q(w)}/quotes", _qbody(w, inputs={"product_family": NUL})), "inputs.product_family")
    _std_nul(_jpost(w, f"{_q(w)}/quotes", _qbody(w, [{**L[0], NUL: 1}] + L[1:])))       # 키 이름의 NUL — 키는 되풀이하지 않는다
    assert _rows(w, "mlp_quote") == before


def test_nul_revision_and_confirm_422_then_normal_flow(kd):
    w = kd
    base = _jpost(w, f"{_q(w)}/quotes", _qbody(w))
    assert base.status_code == 201, base.text
    qid = base.json()["quote_id"]
    L = _lines(w["doc"])
    before = _rows(w, "mlp_quote")
    _std_nul(_jpost(w, f"{_q(w)}/quotes/{qid}/revisions", _qbody(w, [{**L[0], "name": NUL}] + L[1:])), "lines.0.name")
    _std_nul(_jpost(w, f"{_q(w)}/quotes/{qid}/confirm", {"reviewed": True, "review_note": "확정 요청 " + NUL}), "review_note")
    assert _rows(w, "mlp_quote") == before
    r = _jpost(w, f"{_q(w)}/quotes/{qid}/confirm", {"reviewed": True, "review_note": "확정 요청 정상"})
    assert r.status_code == 202, r.text                                     # 부분 상태 없음


def test_nul_predict_and_actuals_entity_id_422(kd):
    w = kd
    U = f"/api/v1/tenants/{w['code']}/tasks/{w['code']}.labor_hours"
    p0, a0 = _rows(w, "mlp_prediction"), _rows(w, "mlp_actual")
    _std_nul(_jpost(w, f"{U}/predict", {"inputs": w["pred_inputs"], "entity_id": NUL}), "entity_id")   # 입력 완전
    _std_nul(_jpost(w, f"{U}/actuals", {"entity_id": NUL, "value": 1.0,
                                        "observed_at": datetime.now(timezone.utc).isoformat()}), "entity_id")
    r = _jpost(w, f"{U}/predict:batch", {"items": [{"inputs": w["pred_inputs"], "entity_id": NUL}]})
    assert r.status_code == 200 and r.json()["items"][0]["error"]["detail"]["errors"][0] == {"field": "items.0.entity_id",
                                                                                           "rule": "nul"}, r.text
    _no_echo(r)
    assert (_rows(w, "mlp_prediction"), _rows(w, "mlp_actual")) == (p0, a0)


def test_nul_old_quote_route_422(kd):
    w = kd
    doc = w["doc"]
    old = {"drawing_id": doc["doc_id"], "product": "반응기", "material": doc["bom_rows"][0]["material"],
           "bom": [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
                    "price_kg": 6500} for b in doc["bom_rows"]],
           "quantity": 1, "cut_m": 24.5, "weld_m": 18.25, "thickness_mm": 6.0, "complexity": 3.0, "labor_rate": 45000,
           "outsource_cost": 0, "reviewed": True, "review_note": "옛 경로 검토"}
    before = _rows(w, "mlp_quote")
    for body in ({**old, "bom": [{**old["bom"][0], "name": NUL}] + old["bom"][1:]}, {**old, "review_note": "옛 검토 " + NUL}):
        r = _jpost(w, "/api/quotes", body)
        assert r.status_code == 422, (r.status_code, r.text[:300])
        _no_echo(r)
        assert "nul" in r.text
    assert _rows(w, "mlp_quote") == before


def test_find_nul_paths():
    from mlcore.serve.validate import find_nul
    assert find_nul({"a": [1, {"name": "x"}]}) is None
    assert find_nul({"lines": [{"name": "ok"}, {"name": NUL}]}) == (True, "lines.1.name")
    assert find_nul({"Bad Key!": NUL}) == (True, "*")                        # 이름 꼴이 아닌 키는 되풀이하지 않는다
    assert find_nul({NUL: 1}) == (True, "*")
    assert find_nul(NUL) == (True, None)


# ── DEF-QA2R2-003 실측: 미래 거부 · 1:1 링크 ───────────────────────────────────────────────────────
def _predict(w, entity):
    r = _jpost(w, f"/api/v1/tenants/{w['code']}/tasks/{w['code']}.labor_hours/predict",
               {"inputs": w["pred_inputs"], "entity_id": entity})
    assert r.status_code == 200, r.text
    return r.json()["prediction_id"]


def _actual(w, entity, at: datetime, value=10.0):
    return _jpost(w, f"/api/v1/tenants/{w['code']}/tasks/{w['code']}.labor_hours/actuals",
                  {"entity_id": entity, "value": value, "observed_at": at.isoformat()})


@pytest.mark.parametrize("ahead", [timedelta(days=30), timedelta(minutes=6)])
def test_future_actual_rejected(kd, ahead):
    w = kd
    before = _rows(w, "mlp_actual")
    r = _actual(w, "E-FUT-" + str(int(ahead.total_seconds())), datetime.now(timezone.utc) + ahead)
    assert r.status_code == 422, r.text
    e = r.json()["error"]
    assert e["code"] == "invalid_input" and e["detail"] == {"field": "observed_at", "rule": "future"}, e
    assert _rows(w, "mlp_actual") == before


def test_actual_within_clock_tolerance_accepted(kd):
    r = _actual(kd, "E-TOL", datetime.now(timezone.utc) + timedelta(minutes=4))
    assert r.status_code == 200, r.text


def test_linked_predictions_follow_one_to_one_rule(kd):
    """D2-81: 예측마다 그 뒤 가장 이른 실측 1건, 같은 실측을 가리키는 예측이 여럿이면 그 실측 직전 마지막 예측 하나."""
    w = kd
    ent = "E-LINK-" + h.secrets_hex(3)
    a_before = _actual(w, ent, datetime.now(timezone.utc) - timedelta(hours=1))           # 예측 전 관측 — 짝 없음
    assert a_before.status_code == 200 and a_before.json()["linked_prediction_ids"] == [], a_before.text
    p1, p2 = _predict(w, ent), _predict(w, ent)
    r1 = _actual(w, ent, datetime.now(timezone.utc))
    assert r1.status_code == 200 and r1.json()["linked_prediction_ids"] == [p2], r1.text
    r2 = _actual(w, ent, datetime.now(timezone.utc))                                     # p1 · p2 는 이미 앞 실측과 짝
    assert r2.status_code == 200 and r2.json()["linked_prediction_ids"] == [], r2.text
    p3 = _predict(w, ent)
    r3 = _actual(w, ent, datetime.now(timezone.utc))
    assert r3.status_code == 200 and r3.json()["linked_prediction_ids"] == [p3], r3.text
    assert p1 not in r1.json()["linked_prediction_ids"]
    with connect() as c:                                                    # 대기열 짝(live_pairs)과 같은 규칙
        from mlcore.train.review import live_pairs
        pairs = [p for p in live_pairs(c, w["code"], f"{w['code']}.labor_hours") if p["entity_id"] == ent]
    assert sorted(p["prediction_id"] for p in pairs) == sorted([p2, p3])


# ── DEF-QA2R2-004 품목 · 입력 정규형 ───────────────────────────────────────────────────────────────
def _stored(w, quote_id):
    with connect() as c:
        row = c.execute("SELECT lines, inputs FROM mlp_quote WHERE tenant_id=%s AND quote_id=%s",
                        (w["code"], quote_id)).fetchone()
        types = c.execute("SELECT jsonb_typeof(x->'price_kg') AS p, jsonb_typeof(x->'quantity') AS q, "
                          "jsonb_typeof(x->'mass_kg') AS m FROM mlp_quote, jsonb_array_elements(lines) x "
                          "WHERE tenant_id=%s AND quote_id=%s", (w["code"], quote_id)).fetchall()
        itypes = c.execute("SELECT key, jsonb_typeof(value) AS t FROM mlp_quote, jsonb_each(inputs) "
                           "WHERE tenant_id=%s AND quote_id=%s", (w["code"], quote_id)).fetchall()
    return row, types, {r["key"]: r["t"] for r in itypes}


def test_line_numbers_normalized_before_save(kd):
    """`" 6500 "` · 7000 · `"5"` 가 섞여 와도 저장 · 응답은 한 모양(숫자 Decimal 10진) — 공백 · 문자열 숫자가 남지 않는다."""
    w = kd
    L = _lines(w["doc"])
    L[0] = {**L[0], "price_kg": " 6500 ", "quantity": f" {L[0]['quantity']} ", "mass_kg": f"{L[0]['mass_kg']}"}
    L[1] = {**L[1], "price_kg": 1000000}
    r = _jpost(w, f"{_q(w)}/quotes", _qbody(w, L))
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["lines"][0]["price_kg"] == 6500 and q["lines"][1]["price_kg"] == 1000000
    assert all(not isinstance(ln[k_], str) for ln in q["lines"] for k_ in ("price_kg", "quantity", "mass_kg")), q["lines"]
    assert q["overrides"] == []                                  # 문자열 · 공백만 다른 인식값은 수정이 아니다
    _, types, _ = _stored(w, q["quote_id"])
    assert {(t["p"], t["q"], t["m"]) for t in types} == {("number", "number", "number")}, types


@pytest.mark.parametrize("value, status, rule", [("1", 201, None), (" 2 ", 201, None), ("1.5", 422, "integer"),
                                                 ("abc", 422, "number"), ("-1", 422, "number"), ("1e2", 422, "number")])
def test_input_numbers_same_rule_as_lines(kd, value, status, rule):
    """수량 문자열 — 품목은 받고 입력은 거부하던 비대칭(QA r2) → 같은 규칙(10진 문자열은 받아 정규형으로, 그 밖은 같은 오류)."""
    w = kd
    r = _jpost(w, f"{_q(w)}/quotes", _qbody(w, inputs={"quantity": value}))
    assert r.status_code == status, r.text
    if status == 201:
        q = r.json()
        assert q["inputs"]["quantity"] == int(value.strip()) and not isinstance(q["inputs"]["quantity"], str)
        _, _, it = _stored(w, q["quote_id"])
        assert it["quantity"] == "number" and it["labor_rate"] == "number", it
    else:
        e = r.json()["error"]
        assert e["detail"] == {"field": "quantity", "rule": rule}, e
        L = _lines(w["doc"])
        rl = _jpost(w, f"{_q(w)}/quotes", _qbody(w, [{**L[0], "quantity": value}] + L[1:]))
        assert rl.status_code == 422 and rl.json()["error"]["detail"] == {"field": "lines.0.quantity", "rule": rule}, rl.text


def test_feature_inputs_decimal_text_and_spaces(kd):
    """모델 입력 변수도 같은 규칙 — `"24"` · `" 18.5 "` 는 Decimal 로, 범주 `" 반응기 "` 는 공백 제거 뒤 판정 · 저장."""
    w = kd
    r = _jpost(w, f"{_q(w)}/quotes", _qbody(w, inputs={"cut_m": "24", "weld_m": " 18.5 ", "product_family": " 반응기 "}))
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["inputs"]["cut_m"] == 24 and Decimal(str(q["inputs"]["weld_m"])) == Decimal("18.5")
    assert q["inputs"]["product_family"] == "반응기"
    _, _, it = _stored(w, q["quote_id"])
    assert it["cut_m"] == it["weld_m"] == "number"
