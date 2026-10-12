"""아키텍트 후속(웨이브 A 결정 정리) — D-63 models 항목 run_id · D-64 failed 재접수 = 202(재사용 아님)."""
from __future__ import annotations

import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.serve import training


def test_models_items_carry_run_id(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    ref, res = h.registered(m, f"{m.tenant.code}.remaining_hours")
    keys = h.keys(m)
    c = h.client(m)
    r = c.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.remaining_hours/models", headers=h.hdr(keys["admin"]))
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["run_id"] == res.run_id == ref.run_id


@pytest.mark.parametrize("prior,reused", [("failed", False), ("succeeded", True)])
def test_resubmit_failed_is_new_run(tmp_path, monkeypatch, prior, reused):
    m = h.make_tenant("ks", tmp_path)
    task = f"{m.tenant.code}.remaining_hours"
    res = h.fake_train(m, task)
    with connect() as c:
        c.execute("UPDATE mlp_train_run SET status=%s WHERE run_id=%s", (prior, res.run_id))

    def fake_submit(tenant_id, task_id, *, actor, source_role=None, seed=None):
        with connect() as c:   # 학습기 규칙(D-W1-05): failed → queued 로 되돌린 같은 run_id
            if prior == "failed":
                c.execute("UPDATE mlp_train_run SET status='queued' WHERE run_id=%s", (res.run_id,))
        return res.run_id

    monkeypatch.setattr(training, "_submit_fn", lambda: fake_submit)
    out = training.submit(m.tenant.code, task, actor="t", source_role="demo", seed=None)
    assert out["run_id"] == res.run_id and out["reused"] is reused
    assert out["status"] == ("queued" if prior == "failed" else "succeeded")
