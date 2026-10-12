"""작업자 · 재시도 · 실행 조회 · 등록부 루트 주입 (D-57 · D-49 후속 · 이슈 #4 · api-contract §4 runs/{id}).

- 작업자(`python -m mlcore.train.jobs --pending | <run_id>`)는 run 마다 `serve.training.run_and_register` 를 부른다
  → succeeded 면 candidate 가 생긴다(등록을 빠뜨리는 길 없음).
- 재시도: 결정적 run_id 의 failed 실행을 같은 요청이 다시 오면 queued 로 되돌리고 `mlp_audit train.retry` 1행.
- 등록부 루트: `registry.tenants.load_and_merge` 를 감싸지 않고 환경변수 `MLP_TENANTS_DIR` 로만 임시 회사를 찾는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import _dev2 as h
from mlcore.data import jobs as djobs
from mlcore.db.conn import connect
from mlcore.train import jobs as tjobs

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.gate("G-M06"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
ACTOR = "test-dev1-worker"


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    m = h.make_tenant("ks", tmp_path)
    monkeypatch.setenv("MLP_TENANTS_DIR", str(h.tenants_base(m)))
    return m


def _row(rid):
    with connect() as c:
        return c.execute("SELECT * FROM mlp_train_run WHERE run_id=%s", (rid,)).fetchone()


def test_tenants_base_resolution(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (b / "zz.yaml").write_text("code: zz\n", encoding="utf-8")
    monkeypatch.setenv("MLP_TENANTS_DIR", f"{a}:{b}")
    assert djobs.tenants_base_for("zz") == b                      # 여러 폴더면 그 회사 파일이 있는 첫 폴더
    assert djobs.tenants_base_for("zz", tmp_path) == tmp_path     # 인자가 먼저
    assert djobs.tenants_base_for("ks") is None                   # 없으면 기본 tenants/
    assert djobs.load_merged("ks").tenant.code == "ks"            # 기본 폴더로 간다(여러 폴더 값을 한 경로로 읽지 않는다)
    monkeypatch.delenv("MLP_TENANTS_DIR")
    assert djobs.tenants_base_for("zz") is None


def test_worker_calls_run_and_register_and_registers_candidate(tenant):
    code = tenant.tenant.code
    rid = djobs.submit(code, f"{code}.remaining_hours", actor=ACTOR)
    assert _row(rid)["status"] == "queued"
    assert tjobs.main([rid]) == 0                                  # CLI 와 같은 길(work → run_and_register)
    row = _row(rid)
    assert row["status"] == "succeeded"
    with connect() as c:
        v = c.execute("SELECT version, stage FROM mlp_model_version WHERE run_id=%s", (rid,)).fetchone()
    assert v and v["stage"] == "candidate"
    view = djobs.run_view(rid)
    for k in ("run_id", "status", "task", "snapshot", "champion", "valid_metrics", "test_metrics", "beats_baseline",
              "version", "warnings"):
        assert k in view
    assert view["version"] == v["version"] and view["snapshot"]["rows"] == 720 and len(view["snapshot"]["sha256"]) == 64
    assert view["snapshot"]["ts_from"].endswith("+09:00")
    mae = view["test_metrics"]["mae"]
    assert set(mae) == {"value", "baseline", "delta_vs_baseline"}
    assert view["report"]["selection_reason"] and view["report"]["permutation_importance"]
    assert djobs.run_view(rid, tenant_id="other") is None and djobs.run_view("run_0000000000000000") is None


def test_worker_source_uses_run_and_register_only():
    txt = (ROOT / "src" / "mlcore" / "train" / "jobs.py").read_text(encoding="utf-8")
    main = txt[txt.index("def work("):]
    assert "run_and_register" in main and not re.search(r"\bexecute\(", main)


def test_failed_run_is_requeued_with_audit(tenant):
    code = tenant.tenant.code
    tid = f"{code}.failure_24h"
    rid = djobs.submit(code, tid, actor=ACTOR)
    with connect() as c:                                           # 실패를 흉내 — 작업자가 남기는 모양 그대로
        c.execute("UPDATE mlp_train_run SET status='failed', started_at=now(), finished_at=now(), "
                  "error='{\"type\": \"MemoryError\", \"message\": \"oom\"}'::jsonb WHERE run_id=%s", (rid,))
    assert djobs.submit(code, tid, actor=ACTOR + "-2") == rid       # 같은 run_id
    row = _row(rid)
    assert row["status"] == "queued" and row["error"] is None and row["started_at"] is None
    assert "MemoryError" in row["log"] and row["created_by"] == ACTOR + "-2"
    with connect() as c:
        a = c.execute("SELECT actor, action, target, detail FROM mlp_audit WHERE tenant_id=%s AND action='train.retry'",
                      (code,)).fetchall()
    assert len(a) == 1 and a[0]["target"] == rid and a[0]["detail"]["previous_error"]["type"] == "MemoryError"
    assert djobs.submit(code, tid, actor=ACTOR) == rid and _row(rid)["status"] == "queued"   # queued 는 그대로(감사 없음)
    # 다른 과제가 queued 인 동안 실패 재접수 → 회사당 1개 규칙(TrainBusy)
    with connect() as c:
        c.execute("UPDATE mlp_train_run SET status='failed' WHERE run_id=%s", (rid,))
    other = djobs.submit(code, f"{code}.remaining_hours", actor=ACTOR)
    with pytest.raises(djobs.TrainBusy):
        djobs.submit(code, tid, actor=ACTOR)
    assert _row(rid)["status"] == "failed" and _row(other)["status"] == "queued"
    tjobs.work([other])
    assert djobs.submit(code, tid, actor=ACTOR) == rid and _row(rid)["status"] == "queued"
    r = tjobs.work([rid])
    assert r[0]["status"] == "succeeded" and r[0]["stage"] == "candidate"


def test_worker_reports_errors_without_stopping(tenant):
    out = tjobs.work(["run_doesnotexist0000"])
    assert out[0]["status"] == "error" and "RunNotFound" in out[0]["error"]


def test_make_train_cli_submits_and_registers(tenant, capsys):
    code = tenant.tenant.code
    assert tjobs.main(["--submit", code, "remaining_hours"]) == 0
    out = capsys.readouterr().out
    assert '"stage": "candidate"' in out and '"status": "succeeded"' in out
