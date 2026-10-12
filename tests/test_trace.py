"""G-M07 — 예측 추적: 예측 → 모델 버전 → 학습 실행 → 스냅숏(해시 · 기간 · 행 수) → 소스 참조 · 실측 연결 · 추가만 (개발2)."""

from __future__ import annotations

import psycopg
import pytest

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.gate("G-M07"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]


@pytest.fixture
def world(tmp_path):
    m = h.make_tenant("sw", tmp_path)
    task = f"{m.tenant.code}.delta_e"
    ref, res = h.to_production(m, task, snapshot_source={"kind": "synthetic", "seed": 42, "generator": "packs/textile/synth"})
    return m, task, ref, res, h.keys(m), h.client(m)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _predict(tc, m, task, k, res, entity="LOT-0001"):
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": h.sample_inputs(res), "entity_id": entity})
    assert r.status_code == 200, r.text
    return r.json()


def test_trace_walks_model_run_snapshot_sources_and_actuals(world):
    m, task, ref, res, k, tc = world
    out = _predict(tc, m, task, k, res)
    pid = out["prediction_id"]
    a = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers=h.hdr(k["operator"]),
                json={"entity_id": "LOT-0001", "value": 1.37, "observed_at": _now()})          # 예측 뒤 관측(D2-81 · D2-112)
    assert a.status_code == 200, a.text
    assert a.json()["linked_prediction_ids"] == [pid] and isinstance(a.json()["actual_id"], int)

    t = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k["admin"]))
    assert t.status_code == 200, t.text
    body = t.json()
    assert set(body) == {"prediction", "model", "run", "snapshot", "sources", "actuals"}
    assert body["prediction"]["prediction_id"] == pid and body["prediction"]["outputs"] == out
    assert body["model"] == {"version": ref.version, "stage": "production", "algo": ref.algo,
                             "artifact_sha256": ref.artifact_sha256}
    assert body["run"]["run_id"] == res.run_id and body["run"]["config_hash"] and body["run"]["code_version"] == "test"
    with connect() as c:
        snap = c.execute("SELECT * FROM mlp_snapshot WHERE snapshot_id = %s", (ref.snapshot_id,)).fetchone()
    s = body["snapshot"]
    assert (s["snapshot_id"], s["sha256"], s["rows"], s["synthetic"]) == (snap["snapshot_id"], snap["sha256"], snap["rows"], True)
    assert s["ts_from"].startswith("2026-01-01T00:00:00") and s["ts_from"].endswith("+09:00") and s["ts_to"]
    assert body["sources"] == [{"kind": "synthetic", "ref": {"kind": "synthetic", "seed": 42, "generator": "packs/textile/synth"}}]
    assert [x["value"] for x in body["actuals"]] == [1.37]


def test_actual_links_by_entity_only(world):
    m, task, ref, res, k, tc = world
    p1 = _predict(tc, m, task, k, res, "LOT-A")["prediction_id"]
    p2 = _predict(tc, m, task, k, res, "LOT-A")["prediction_id"]
    _predict(tc, m, task, k, res, "LOT-B")
    obs = _now()
    a = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers=h.hdr(k["operator"]),
                json={"entity_id": "LOT-A", "value": 2, "observed_at": obs})
    # 같은 entity 예측 전부가 아니라 D2-81 1:1 짝 — 이 실측 직전 마지막 예측 하나 (C2 2회전 D2-112 · DEF-QA2R2-003)
    assert a.json()["linked_prediction_ids"] == [p2] and p1 not in a.json()["linked_prediction_ids"]
    again = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers=h.hdr(k["operator"]),
                    json={"entity_id": "LOT-A", "value": 2, "observed_at": obs})
    assert again.json()["actual_id"] == a.json()["actual_id"]          # 같은 실측 재등록은 새 행이 아니다


@pytest.mark.parametrize("body", [
    {"entity_id": "X", "value": "1.0", "observed_at": "2026-10-12T11:00:00+09:00"},
    {"entity_id": "X", "value": 1.0, "observed_at": "2026-10-12T11:00:00"},           # 시간대 없음
    {"entity_id": "", "value": 1.0, "observed_at": "2026-10-12T11:00:00+09:00"},
    {"entity_id": "X", "value": 1.0, "observed_at": "2026-10-12T11:00:00+09:00", "extra": 1},
])
def test_actual_input_errors(world, body):
    m, task, ref, res, k, tc = world
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


def test_actual_nan_rejected(world):
    m, task, ref, res, k, tc = world
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers={**h.hdr(k["operator"]),
                "Content-Type": "application/json"},
                content='{"entity_id": "X", "value": NaN, "observed_at": "2026-10-12T11:00:00+09:00"}')
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


def test_prediction_row_is_append_only(world):
    m, task, ref, res, k, tc = world
    pid = _predict(tc, m, task, k, res)["prediction_id"]
    for sql in ("UPDATE mlp_prediction SET status = 'ok' WHERE prediction_id = %s",
                "DELETE FROM mlp_prediction WHERE prediction_id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as c:
            c.execute(sql, (pid,))
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE prediction_id = %s", (pid,)) == 1


def test_trace_scope_and_role(world, tmp_path):
    m, task, ref, res, k, tc = world
    pid = _predict(tc, m, task, k, res)["prediction_id"]
    for role in ("viewer", "operator", "approver"):
        r = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k[role]))
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    other = h.make_tenant("sw", tmp_path / "o")
    r = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(h.keys(other)["admin"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = tc.get("/api/v1/predictions/prd_NOPE/trace", headers=h.hdr(k["admin"]))
    assert r.status_code == 404
    assert tc.get(f"/api/v1/predictions/{pid}/trace").status_code == 401
