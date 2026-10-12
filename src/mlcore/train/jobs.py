"""학습 작업 실행 — mlp_train_run queued → running → succeeded | failed (spec §5.5).

`uv run python -m mlcore.train.jobs <run_id> [--test]` 또는 `--pending`. OMP_NUM_THREADS=1 로 돈다.
등록부 기록(mlp_model_version)은 하지 않는다 — Registry.register(result) 는 개발2 (interfaces §5).
"""

from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from ..db.conn import connect  # noqa: E402
from .artifacts import clean  # noqa: E402
from .trainer import TrainConfig, TrainResult, train  # noqa: E402


class RunNotFound(Exception):
    pass


def execute(run_id: str, *, test: bool = False) -> TrainResult:
    from ..registry.tenants import load_and_merge

    with connect(test) as c:
        row = c.execute("UPDATE mlp_train_run SET status='running', started_at=now() WHERE run_id=%s AND status='queued' "
                        "RETURNING tenant_id, task_id, snapshot_id, seed, code_version, config_hash", (run_id,)).fetchone()
        if row is None:
            exists = c.execute("SELECT status FROM mlp_train_run WHERE run_id=%s", (run_id,)).fetchone()
            raise RunNotFound(f"{run_id}: " + (f"상태 {exists['status']} — queued 아님" if exists else "없음"))
    try:
        m = load_and_merge(row["tenant_id"])
        task = m.tasks[row["task_id"]]
        cfg = TrainConfig.from_task(task, row["snapshot_id"], seed=row["seed"], code_version=row["code_version"],
                                    pack_meta=m.pack.meta)
        if cfg.config_hash() != row["config_hash"]:
            raise ValueError("과제 정의 · 설정이 접수 뒤 바뀌었다(config_hash 불일치) — 다시 접수한다")
        result = train(cfg)
    except Exception as e:
        with connect(test) as c:
            c.execute("UPDATE mlp_train_run SET status='failed', finished_at=now(), error=%s WHERE run_id=%s",
                      (json.dumps({"type": type(e).__name__, "message": str(e)}, ensure_ascii=False), run_id))
        raise
    with connect(test) as c:
        c.execute("UPDATE mlp_train_run SET status=%s, finished_at=now(), report=%s, error=%s, log=%s WHERE run_id=%s",
                  (result.status, json.dumps(clean(result.report), ensure_ascii=False),
                   None if result.status == "succeeded" else json.dumps(clean(result.report.get("error")), ensure_ascii=False),
                   result.selection_reason, run_id))
    return result


def pending(*, test: bool = False) -> list[str]:
    with connect(test) as c:
        return [r["run_id"] for r in c.execute("SELECT run_id FROM mlp_train_run WHERE status='queued' ORDER BY created_at")]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    ids = pending(test=a.test) if a.pending else [a.run_id]
    for rid in ids:
        r = execute(rid, test=a.test)
        print(json.dumps({"run_id": r.run_id, "status": r.status, "champion": r.champion,
                          "beats_baseline": r.beats_baseline, "artifact_dir": r.artifact_dir}, ensure_ascii=False))
