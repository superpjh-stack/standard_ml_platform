"""G-M09 — 승인: production 은 approval.decide() 로만 · 한 트랜잭션(조건부 UPDATE + 감사) · 동시 2건 중 1건만 · 409 (개발2)."""

from __future__ import annotations

import threading

import pytest

import _dev2 as h
from mlcore import approval, audit
from mlcore.db.conn import connect
from mlcore.registry.models import ModelNotReady, Registry

pytestmark = [pytest.mark.gate("G-M09"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]


@pytest.fixture
def ks(tmp_path):
    return h.make_tenant("ks", tmp_path)


def tid(m):
    return f"{m.tenant.code}.remaining_hours"


def staged(m, seed=0):
    ref, res = h.registered(m, tid(m), seed=seed)
    Registry().stage(m.tenant.code, tid(m), ref.version, actor="test-admin")
    return ref.version


def pending(m, seed=0):
    v = staged(m, seed)
    return v, Registry().request_promotion(m.tenant.code, tid(m), v, actor="req", action="promote", reason=None)


def state(aid):
    return approval.get(aid)["state"]


def test_decide_promotes_and_audits_in_one_transaction(ks):
    v, aid = pending(ks)
    out = approval.decide(aid, actor="boss", actor_role="approver", approve=True, reason="지표 확인")
    assert out == {"approval_id": aid, "state": "approved", "production_version": v}
    ref = Registry().get(ks.tenant.code, tid(ks))
    assert (ref.version, ref.promoted_by) == (v, "boss")
    n = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s AND action='approval.approved' "
                "AND detail->>'approval_id' = %s", (ks.tenant.code, aid))
    assert n == 1


def test_audit_failure_rolls_back_everything(ks, monkeypatch):
    v, aid = pending(ks)

    def boom(**kw):
        raise RuntimeError("audit down")
    monkeypatch.setattr(audit, "write", boom)
    with pytest.raises(RuntimeError):
        approval.decide(aid, actor="boss", actor_role="approver", approve=True, reason=None)
    monkeypatch.undo()
    assert state(aid) == "pending"
    with pytest.raises(ModelNotReady):
        Registry().get(ks.tenant.code, tid(ks))
    assert Registry().get(ks.tenant.code, tid(ks), v).stage == "staging"


def test_second_decision_is_409(ks):
    _, aid = pending(ks)
    approval.decide(aid, actor="a", actor_role="approver", approve=True, reason=None)
    with pytest.raises(approval.AlreadyDecided):
        approval.decide(aid, actor="b", actor_role="approver", approve=False, reason=None)
    assert state(aid) == "approved"


def test_reject_keeps_production(ks):
    h.to_production(ks, tid(ks))
    v2, aid = pending(ks, seed=3)
    out = approval.decide(aid, actor="a", actor_role="approver", approve=False, reason="근거 부족")
    assert out["state"] == "rejected" and out["production_version"] == "v1"
    assert Registry().get(ks.tenant.code, tid(ks), v2).stage == "staging"


def test_expired_approval_is_409(ks):
    _, aid = pending(ks)
    with connect() as c:
        c.execute("UPDATE mlp_approval SET expires_at = now() - interval '1 minute' WHERE approval_id = %s", (aid,))
    with pytest.raises(approval.AlreadyDecided):
        approval.decide(aid, actor="a", actor_role="approver", approve=True, reason=None)
    with pytest.raises(ModelNotReady):
        Registry().get(ks.tenant.code, tid(ks))


def test_non_approver_role_refused(ks):
    _, aid = pending(ks)
    with pytest.raises(approval.Forbidden):
        approval.decide(aid, actor="op", actor_role="operator", approve=True, reason=None)
    assert state(aid) == "pending"


def _race(fn_a, fn_b):
    barrier = threading.Barrier(2)
    results: list = [None, None]

    def run(i, fn):
        barrier.wait()
        try:
            results[i] = ("ok", fn())
        except Exception as e:  # noqa: BLE001
            results[i] = ("err", e)
    ts = [threading.Thread(target=run, args=(0, fn_a)), threading.Thread(target=run, args=(1, fn_b))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    return results


@pytest.mark.parametrize("rep", range(3))
def test_concurrent_same_approval_only_one_wins(ks, rep):
    v, aid = pending(ks, seed=rep)
    res = _race(lambda: approval.decide(aid, actor="tab1", actor_role="approver", approve=True, reason=None),
                lambda: approval.decide(aid, actor="tab2", actor_role="approver", approve=True, reason=None))
    oks = [r for r in res if r[0] == "ok"]
    errs = [r for r in res if r[0] == "err"]
    assert len(oks) == 1 and len(errs) == 1 and isinstance(errs[0][1], approval.AlreadyDecided), res
    assert Registry().get(ks.tenant.code, tid(ks)).version == v
    n = h.count("SELECT count(*) AS n FROM mlp_audit WHERE detail->>'approval_id' = %s AND action IN ('approval.approved', 'approval.rejected')", (aid,))
    assert n == 1


def test_concurrent_different_approvals_keep_one_production(ks):
    v1, a1 = pending(ks, seed=10)
    v2, a2 = pending(ks, seed=11)
    res = _race(lambda: approval.decide(a1, actor="x", actor_role="approver", approve=True, reason=None),
                lambda: approval.decide(a2, actor="y", actor_role="approver", approve=True, reason=None))
    assert all(r[0] == "ok" for r in res), res               # 서로 다른 승인은 차례로 둘 다 처리된다
    n = h.count("SELECT count(*) AS n FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s AND stage='production'",
                (ks.tenant.code, tid(ks)))
    assert n == 1


# ── API ─────────────────────────────────────────────────────────────────────
def test_api_promote_creates_pending_only_then_decide(ks):
    k = h.keys(ks)
    tc = h.client(ks)
    v = staged(ks)
    base = f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/models/{v}"
    assert tc.post(base + "/promote", headers=h.hdr(k["operator"])).status_code == 403
    assert tc.post(base + "/promote", headers=h.hdr(k["approver_other"])).status_code == 403
    r = tc.post(base + "/promote", headers=h.hdr(k["approver"]), json={"reason": "검증 지표 개선"})
    assert r.status_code == 202 and r.json()["state"] == "pending"
    aid = r.json()["approval_id"]
    with pytest.raises(ModelNotReady):                          # 승인 요청만으로는 production 이 바뀌지 않는다
        Registry().get(ks.tenant.code, tid(ks))
    lst = tc.get(f"/api/v1/tenants/{ks.tenant.code}/approvals?state=pending", headers=h.hdr(k["operator"]))
    assert lst.status_code == 200 and [i["approval_id"] for i in lst.json()["items"]] == [aid]
    assert "next_cursor" in lst.json()
    d = f"/api/v1/approvals/{aid}/decide"
    assert tc.post(d, headers=h.hdr(k["operator"]), json={"decision": "approve", "reason": "x"}).status_code == 403
    assert tc.post(d, headers=h.hdr(k["approver_other"]), json={"decision": "approve", "reason": "x"}).status_code == 403
    r = tc.post(d, headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "확인"})
    assert r.status_code == 200 and r.json() == {"approval_id": aid, "state": "approved", "production_version": v}
    r = tc.post(d, headers=h.hdr(k["admin"]), json={"decision": "reject", "reason": "늦음"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"
    models = tc.get(f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/models", headers=h.hdr(k["approver"]))
    assert models.status_code == 200 and models.json()["items"][0]["stage"] == "production"


def test_api_other_tenant_is_404(ks, tmp_path):
    other = h.make_tenant("ks", tmp_path / "o")
    ko = h.keys(other)
    _, aid = pending(ks)
    tc = h.client(ks)
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(ko["admin"]), json={"decision": "approve", "reason": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = tc.get(f"/api/v1/tenants/{ks.tenant.code}/approvals", headers=h.hdr(ko["admin"]))
    assert r.status_code == 404
    assert state(aid) == "pending"


def test_api_stage_admin_only(ks):
    k = h.keys(ks)
    tc = h.client(ks)
    ref, _ = h.registered(ks, tid(ks))
    url = f"/api/v1/tenants/{ks.tenant.code}/tasks/{tid(ks)}/models/{ref.version}/stage"
    assert tc.post(url, headers=h.hdr(k["approver"])).status_code == 403
    r = tc.post(url, headers=h.hdr(k["admin"]))
    assert r.status_code == 200 and r.json()["stage"] == "staging"


def test_promotion_evidence_has_shadow_diff(tmp_path):
    """승인 카드의 그림자 예측 차이 — 최근 운영 입력으로 대상 · production 을 같이 채점(시험 구간 미사용)."""
    m = h.make_tenant("ks", tmp_path)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, res = h.to_production(m, task)
    from mlcore.serve.catalog import TaskCatalog
    from mlcore.serve.predict import PredictRequest, Predictor
    for i in range(3):
        Predictor(TaskCatalog(m)).predict(m.tenant.code, task, PredictRequest(inputs=h.sample_inputs(res, i)), caller="t")
    ref2, _ = h.registered(m, task, seed=3)
    reg = Registry()
    reg.stage(m.tenant.code, task, ref2.version, actor="a")
    aid = reg.request_promotion(m.tenant.code, task, ref2.version, actor="b", action="promote", reason=None)
    ev = approval.get(aid)["evidence"]
    assert ev["production"]["version"] == ref.version and ev["target"]["version"] == ref2.version
    assert ev["shadow"]["n"] == 3 and ev["shadow"]["basis"] == "recent_operating_inputs"
    assert ev["shadow"]["max_abs_diff"] >= ev["shadow"]["mean_abs_diff"] >= 0
