"""G-M04 B(일부) · G-V01 준비 — 표준 예측 응답 18키 · 유형별 null 규칙 · 기록 · 같은 코어로 두 팩 (개발2)."""

from __future__ import annotations

import jsonschema
import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.serve.contract import RESPONSE_KEYS, PredictResponse

pytestmark = [pytest.mark.gate("G-M04"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
SCHEMA = h.response_schema()


def test_pydantic_model_matches_contract_keys():
    assert list(RESPONSE_KEYS) == SCHEMA["required"]
    assert set(PredictResponse.model_json_schema()["required"]) == set(SCHEMA["required"])   # 선택 항목 0


@pytest.mark.parametrize("source,short,ttype", [("ks", "remaining_hours", "regression"), ("sw", "delta_e", "regression"),
                                                 ("ks", "failure_24h", "risk"), ("sw", "defect_risk", "risk")])
def test_same_core_two_packs_standard_response(tmp_path, source, short, ttype):
    m = h.make_tenant(source, tmp_path)
    task = f"{m.tenant.code}.{short}"
    ref, res = h.to_production(m, task)
    k = h.keys(m)
    tc = h.client(m)
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": h.sample_inputs(res), "entity_id": "E-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert list(body) == SCHEMA["required"]                                  # 18키, 순서까지
    assert body["type"] == ttype and body["tenant"] == m.tenant.code and body["task"] == task
    assert body["model"]["version"] == ref.version and body["model"]["snapshot_id"] == ref.snapshot_id
    assert body["model"]["trained_at"].endswith("+09:00")
    assert body["synthetic"] is True and {"code": "synthetic_model", "field": None,
                                           "message": "합성 데이터로 학습한 모델입니다"} in body["warnings"]
    assert body["notice"] == m.pack.meta["notice"]
    assert body["anomaly"] is None and body["recommendation"] is None and body["uses"] is None
    if ttype == "regression":
        assert body["probability"] is None
        p = body["prediction"]
        assert p["unit"] == m.tasks[task].raw["target"]["unit"] and p["grade"] is None
        assert p["interval"][0] <= p["value"] <= p["interval"][1]
        assert p["baseline"] == pytest.approx(res.lock["baseline"], abs=1e-6)
    else:
        assert body["probability"] == body["prediction"]["value"] and 0 <= body["probability"] <= 1
        assert body["prediction"]["unit"] == "probability" and body["prediction"]["grade"] in ("low", "watch", "high")
        assert body["prediction"]["interval"] is None
        if body["probability"] >= m.tasks[task].raw["thresholds"]["review_prob"]:
            assert body["status"] == "review"
    with connect() as c:
        row = c.execute("SELECT * FROM mlp_prediction WHERE prediction_id = %s", (body["prediction_id"],)).fetchone()
    assert row["outputs"] == body and row["version"] == ref.version and row["entity_id"] == "E-1"
    assert row["status"] == body["status"] and row["channel"] == "api" and row["caller"].startswith("test-operator")


def test_risk_high_probability_is_review(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = f"{m.tenant.code}.failure_24h"
    ref, res = h.to_production(m, task)
    k, tc = h.keys(m), h.client(m)
    probs = res.frame.copy()
    from mlcore.registry.artifacts import load_artifacts
    p = load_artifacts(ref).model.predict_proba(probs)[:, 1]
    hi, lo = int(p.argmax()), int(p.argmin())
    for row, want in ((hi, "review"), (lo, None)):
        r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                    json={"inputs": h.sample_inputs(res, row)})
        body = r.json()
        jsonschema.validate(body, SCHEMA)
        if want:
            assert body["prediction"]["grade"] == "high" and body["status"] == "review"
            assert any(w["code"] == "threshold_exceeded" for w in body["warnings"])
        else:
            assert body["prediction"]["grade"] == "low"


def test_explain_top5(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = f"{m.tenant.code}.remaining_hours"
    _, res = h.to_production(m, task)
    k, tc = h.keys(m), h.client(m)
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": h.sample_inputs(res), "explain": True})
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert body["explain"]["method"] == "permutation_local" and 1 <= len(body["explain"]["top"]) <= 5
    feats = set(m.tasks[task].raw["features"])
    assert all(t["field"] in feats for t in body["explain"]["top"])


def test_staging_version_needs_approver(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = f"{m.tenant.code}.remaining_hours"
    _, res = h.to_production(m, task)
    ref2, _ = h.registered(m, task, seed=4)
    from mlcore.registry.models import Registry
    Registry().stage(m.tenant.code, task, ref2.version, actor="a")
    k, tc = h.keys(m), h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict"
    body = {"inputs": h.sample_inputs(res), "model_version": ref2.version}
    assert tc.post(url, headers=h.hdr(k["operator"]), json=body).status_code == 403
    r = tc.post(url, headers=h.hdr(k["approver"]), json=body)
    assert r.status_code == 200 and r.json()["model"]["version"] == ref2.version
    cand, _ = h.registered(m, task, seed=6)                                   # candidate 로는 예측하지 않는다
    r = tc.post(url, headers=h.hdr(k["approver"]), json={**body, "model_version": cand.version})
    assert r.status_code == 404


def test_roles_and_tenant_scope(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = f"{m.tenant.code}.remaining_hours"
    _, res = h.to_production(m, task)
    k, tc = h.keys(m), h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict"
    body = {"inputs": h.sample_inputs(res)}
    assert tc.post(url, json=body).json()["error"]["code"] == "auth_required"
    assert tc.post(url, headers=h.hdr("mlp_wrong"), json=body).status_code == 401
    r = tc.post(url, headers=h.hdr(k["viewer"]), json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    other = h.make_tenant("ks", tmp_path / "o")
    r = tc.post(url, headers=h.hdr(h.keys(other)["admin"]), json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.nope/predict", headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (m.tenant.code,)) == 0
