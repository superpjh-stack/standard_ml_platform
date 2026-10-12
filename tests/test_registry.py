"""G-M06 C — 등록부 상태 전이 · 산출물 해시 · env.lock 대조 · 과제당 production 1 · 기동 학습 0 (개발2)."""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

import _dev2 as h
from mlcore import approval
from mlcore.db.conn import connect
from mlcore.registry import artifacts
from mlcore.registry.models import InvalidTransition, ModelNotReady, Registry

pytestmark = [pytest.mark.gate("G-M06"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
TASK = "remaining_hours"


@pytest.fixture
def ks(tmp_path):
    return h.make_tenant("ks", tmp_path)


def tid(m, short=TASK):
    return f"{m.tenant.code}.{short}"


def test_register_is_candidate_with_hash_and_env_lock(ks):
    ref, res = h.registered(ks, tid(ks))
    assert (ref.stage, ref.version) == ("candidate", "v1")
    assert ref.artifact_sha256 == artifacts.artifact_sha256(res.artifact_dir)
    assert ref.env_lock == artifacts.current_env_lock()
    assert ref.synthetic is True and ref.snapshot_id.startswith("snp_") and ref.run_id == res.run_id
    for f in artifacts.FILES:
        assert (Path(res.artifact_dir) / f).is_file()


def test_register_same_run_is_idempotent_and_versions_increase(ks):
    ref, res = h.registered(ks, tid(ks))
    again = Registry().register(res, tenant_id=ks.tenant.code, task_id=tid(ks))
    assert again.version == ref.version
    ref2, _ = h.registered(ks, tid(ks), seed=1)
    assert ref2.version == "v2"
    assert [m.version for m in Registry().list(ks.tenant.code, tid(ks))] == ["v2", "v1"]


def test_failed_train_is_not_registered(ks):
    res = h.fake_train(ks, tid(ks))
    res.status = "failed"
    with pytest.raises(InvalidTransition):
        Registry().register(res, tenant_id=ks.tenant.code, task_id=tid(ks))


def test_stage_rules(ks):
    reg = Registry()
    lose, _ = h.registered(ks, tid(ks), beats_baseline=False)
    with pytest.raises(InvalidTransition) as e:
        reg.stage(ks.tenant.code, tid(ks), lose.version, actor="a")
    assert e.value.detail["rule"] == "baseline"
    blocked, _ = h.registered(ks, tid(ks), seed=2, warnings=[{"code": "leak", "severity": "block"}])
    with pytest.raises(InvalidTransition) as e:
        reg.stage(ks.tenant.code, tid(ks), blocked.version, actor="a")
    assert e.value.detail["rule"] == "blocking_warning"
    good, _ = h.registered(ks, tid(ks), seed=3)
    assert reg.stage(ks.tenant.code, tid(ks), good.version, actor="a").stage == "staging"
    with pytest.raises(InvalidTransition):
        reg.stage(ks.tenant.code, tid(ks), good.version, actor="a")   # staging → staging 없음


def test_live_tenant_refuses_synthetic_staging(tmp_path):
    live = h.make_tenant("ks", tmp_path, mode="eval")
    ref, _ = h.registered(live, tid(live))
    with connect() as c:
        c.execute("UPDATE mlp_tenant SET mode = 'live' WHERE tenant_id = %s", (live.tenant.code,))
    with pytest.raises(InvalidTransition) as e:
        Registry().stage(live.tenant.code, tid(live), ref.version, actor="a")
    assert e.value.detail["rule"] == "live_synthetic"


def test_request_promotion_never_changes_stage(ks):
    reg = Registry()
    ref, _ = h.registered(ks, tid(ks))
    with pytest.raises(InvalidTransition):   # candidate 는 승격 요청 불가
        reg.request_promotion(ks.tenant.code, tid(ks), ref.version, actor="a", action="promote", reason=None)
    reg.stage(ks.tenant.code, tid(ks), ref.version, actor="a")
    aid = reg.request_promotion(ks.tenant.code, tid(ks), ref.version, actor="a", action="promote", reason=None)
    assert aid.startswith("apr_")
    assert reg.request_promotion(ks.tenant.code, tid(ks), ref.version, actor="a", action="promote", reason=None) == aid
    assert reg.get(ks.tenant.code, tid(ks), ref.version).stage == "staging"
    with pytest.raises(ModelNotReady):
        reg.get(ks.tenant.code, tid(ks))


def test_one_production_per_task(ks):
    reg = Registry()
    v1, _ = h.to_production(ks, tid(ks))
    v2, _ = h.to_production(ks, tid(ks), seed=5)
    assert (v1.version, v2.version) == ("v1", "v2")
    assert reg.get(ks.tenant.code, tid(ks)).version == "v2"
    assert reg.get(ks.tenant.code, tid(ks), "v1").stage == "archived"
    n = h.count("SELECT count(*) AS n FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s AND stage='production'",
                (ks.tenant.code, tid(ks)))
    assert n == 1
    # DB 부분 고유 색인이 두 번째 production 을 거부한다 (코드 밖 쓰기도 막힌다)
    with pytest.raises(psycopg.errors.UniqueViolation), connect() as c:
        c.execute("UPDATE mlp_model_version SET stage = 'production' WHERE tenant_id=%s AND task_id=%s AND version='v1'",
                  (ks.tenant.code, tid(ks)))


def test_artifact_hash_mismatch_refused(ks):
    ref, res = h.to_production(ks, tid(ks))
    artifacts.load_artifacts(ref)                                  # 원래는 적재된다
    p = Path(res.artifact_dir) / "model.joblib"
    p.write_bytes(p.read_bytes() + b"\0")                          # 바꿔치기
    with pytest.raises(artifacts.ArtifactMismatch) as e:
        artifacts.load_artifacts(ref)
    assert e.value.detail["rule"] == "sha256"
    tc = h.client(ks)
    k = h.keys(ks)
    r = tc.post(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": h.sample_inputs(res)})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_artifact_mismatch"


def test_package_version_mismatch_refused(ks, monkeypatch):
    ref, res = h.to_production(ks, tid(ks))
    real = artifacts.current_env_lock()
    fake = json.loads(json.dumps(real))
    fake["packages"]["scikit-learn"] = "0.0.1"
    monkeypatch.setattr(artifacts, "current_env_lock", lambda: fake)
    with pytest.raises(artifacts.ArtifactMismatch) as e:
        artifacts.load_artifacts(ref)
    assert e.value.detail["rule"] == "env_lock" and "scikit-learn" in e.value.detail["field"]
    tc = h.client(ks)
    k = h.keys(ks)
    r = tc.post(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": h.sample_inputs(res)})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_artifact_mismatch"


def test_no_production_is_503_and_startup_does_not_train(ks):
    k = h.keys(ks)
    before = h.count("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s", (ks.tenant.code,))
    tc = h.client(ks)                                              # 기동
    r = tc.post(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": {}})
    # 필수 범주 변수가 없으면 모델과 무관하게 422 — 모델 없음은 입력이 맞을 때만 드러난다
    assert r.status_code == 422
    feats = h.task_features(ks, tid(ks))
    good = h.sample_inputs(h.SimpleNamespace(frame=h.synth_frame(feats, 3, 0)))
    r = tc.post(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": good})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "model_not_ready"
    assert set(r.json()) == {"error"}                             # 대체 · 기본값 응답 없음
    assert h.count("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s", (ks.tenant.code,)) == before
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (ks.tenant.code,)) == 0


def test_rollback_needs_reason_and_restores_archived(ks):
    reg = Registry()
    h.to_production(ks, tid(ks))
    h.to_production(ks, tid(ks), seed=9)
    with pytest.raises(InvalidTransition):
        reg.request_promotion(ks.tenant.code, tid(ks), "v1", actor="a", action="rollback", reason="")
    aid = reg.request_promotion(ks.tenant.code, tid(ks), "v1", actor="a", action="rollback", reason="v2 성능 저하")
    out = approval.decide(aid, actor="b", actor_role="approver", approve=True, reason="확인")
    assert out["production_version"] == "v1"
    assert reg.get(ks.tenant.code, tid(ks), "v2").stage == "archived"


def test_train_route_calls_trainer_and_is_idempotent(ks, monkeypatch):
    """POST …/train — 학습기(개발1)는 가짜 모듈로 대신한다. 같은 요청 재전송은 200 + 기존 run_id."""
    import sys
    import types
    calls = []
    fake = types.ModuleType("mlcore.data.jobs")

    def submit(tenant_id, task_id, *, actor):
        calls.append((tenant_id, task_id, actor))
        if len(calls) == 1:
            fake.run = h.fake_train(ks, task_id).run_id
        return fake.run
    fake.submit = submit
    monkeypatch.setitem(sys.modules, "mlcore.data.jobs", fake)
    k, tc = h.keys(ks), h.client(ks)
    url = f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/train"
    assert tc.post(url, headers=h.hdr(k["approver"]), json={"source_role": "demo"}).status_code == 403
    r1 = tc.post(url, headers=h.hdr(k["admin"]), json={"source_role": "demo", "seed": 42})
    assert r1.status_code == 202 and r1.json()["run_id"] == fake.run
    r2 = tc.post(url, headers=h.hdr(k["admin"]), json={"source_role": "demo", "seed": 42})
    assert r2.status_code == 200 and r2.json() == {"run_id": fake.run, "status": "succeeded", "reused": True}
    assert len(calls) == 2 and calls[0][:2] == (ks.tenant.code, tid(ks))
    assert tc.post(url, headers=h.hdr(k["admin"]), json={"source_role": "nope"}).status_code == 422


def test_train_route_without_trainer_is_explicit(ks, monkeypatch):
    import sys
    for name in ("mlcore.data.jobs", "mlcore.train.trainer"):
        monkeypatch.setitem(sys.modules, name, None)                   # import 하면 ModuleNotFoundError
    k, tc = h.keys(ks), h.client(ks)
    r = tc.post(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/train", headers=h.hdr(k["admin"]), json={})
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"
