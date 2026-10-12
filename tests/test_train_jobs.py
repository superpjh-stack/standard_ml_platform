"""학습 작업 — submit(소스 → 스냅숏 → mlp_snapshot → mlp_train_run queued) · execute(running → succeeded) · 멱등 (spec §5.5).

시험 DB(ml_test_db)만 쓴다. 산출물 · 스냅숏 파일은 var/(gitignore) 에 쌓인다.
"""

from __future__ import annotations

import pytest

from mlcore.data import jobs as djobs
from mlcore.db.conn import DbUnavailable, connect
from mlcore.train import jobs as tjobs

ACTOR = "test-dev1"


def _cleanup(tenant: str, task_id: str):
    with connect(test=True) as c:
        c.execute("DELETE FROM mlp_train_run r WHERE tenant_id=%s AND task_id=%s AND created_by=%s AND NOT EXISTS "
                  "(SELECT 1 FROM mlp_model_version v WHERE v.run_id = r.run_id)", (tenant, task_id, ACTOR))


@pytest.fixture
def db():
    try:
        with connect(test=True) as c:
            c.execute("SELECT 1")
    except DbUnavailable:
        pytest.fail("ml_test_db 연결 불가 — make setup")


@pytest.mark.parametrize("tenant,task_id", [("ks", "ks.remaining_hours"), ("sw", "sw.delta_e")])
def test_submit_execute_idempotent(db, tenant, task_id):
    _cleanup(tenant, task_id)
    rid = djobs.submit(tenant, task_id, actor=ACTOR, test=True)
    assert rid.startswith("run_")
    with connect(test=True) as c:
        run = c.execute("SELECT * FROM mlp_train_run WHERE run_id=%s", (rid,)).fetchone()
        snap = c.execute("SELECT * FROM mlp_snapshot WHERE snapshot_id=%s", (run["snapshot_id"],)).fetchone()
    if run["created_by"] != ACTOR:          # 다른 시험이 같은 스냅숏 · 설정으로 이미 만든 실행 — 멱등이 맞다
        pytest.skip("같은 run 이 다른 시험에서 이미 있다(멱등)")
    assert run["status"] == "queued" and run["seed"] == 42
    assert snap["synthetic"] is True and snap["rows"] == 720 and len(snap["sha256"]) == 64
    assert djobs.submit(tenant, task_id, actor=ACTOR, test=True) == rid          # 멱등
    r = tjobs.execute(rid, test=True)
    assert r.status == "succeeded" and r.run_id == rid and r.synthetic is True
    with connect(test=True) as c:
        done = c.execute("SELECT status, report, started_at, finished_at FROM mlp_train_run WHERE run_id=%s", (rid,)).fetchone()
    assert done["status"] == "succeeded" and done["finished_at"] >= done["started_at"]
    assert done["report"]["champion"] == r.champion and done["report"]["test_metrics"]["mae"]["baseline"] is not None
    with pytest.raises(tjobs.RunNotFound):
        tjobs.execute(rid, test=True)                                            # 두 번 돌지 않는다
    _cleanup(tenant, task_id)


def test_submit_unknown_task(db):
    with pytest.raises(KeyError):
        djobs.submit("ks", "ks.nope", actor=ACTOR, test=True)


def test_submit_eval_csv_role(db):
    """eval 역할(csv fixture)로 받으면 synthetic=False 스냅숏."""
    _cleanup("sw", "sw.delta_e")
    rid = djobs.submit("sw", "sw.delta_e", actor=ACTOR, source_role="eval", test=True)
    with connect(test=True) as c:
        row = c.execute("SELECT s.synthetic, s.source_ref FROM mlp_train_run r JOIN mlp_snapshot s USING (snapshot_id) "
                        "WHERE r.run_id=%s", (rid,)).fetchone()
    assert row["synthetic"] is False and row["source_ref"]["kind"] == "csv"
    _cleanup("sw", "sw.delta_e")
