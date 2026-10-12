"""학습 작업 실행 — mlp_train_run queued → running → succeeded | failed (spec §5.5 · interfaces §4.1 · D-57).

작업자: `uv run python -m mlcore.train.jobs --pending [--test]` 또는 `… <run_id>`. OMP_NUM_THREADS=1 로 돈다.
`make train`: `… --submit <tenant> <task> [--source-role demo] [--seed 42]` — 접수 뒤 같은 프로세스에서 run_and_register.
작업자는 run 마다 **`mlcore.serve.training.run_and_register(run_id)`** 를 부른다 — execute → succeeded 면
`Registry.register()` → candidate. `execute` 만 부르고 등록을 빠뜨리는 길은 두지 않는다(D-57).
`execute` 자체는 등록하지 않는다(등록은 개발2 접착부 한 곳).
등록부 루트는 `mlcore.data.jobs.tenants_base_for`(인자 → 환경변수 MLP_TENANTS_DIR → 기본 tenants/)로 찾는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

from ..db.conn import connect  # noqa: E402
from .artifacts import clean  # noqa: E402
from .trainer import StandardTrainer, TrainConfig, TrainResult, resolve_features  # noqa: E402


class RunNotFound(Exception):
    pass


def execute(run_id: str, *, test: bool = False, tenants_base: str | Path | None = None) -> TrainResult:
    from ..data.jobs import load_merged

    with connect(test) as c:
        row = c.execute("UPDATE mlp_train_run SET status='running', started_at=now() WHERE run_id=%s AND status='queued' "
                        "RETURNING tenant_id, task_id, snapshot_id, seed, code_version, config_hash", (run_id,)).fetchone()
        if row is None:
            exists = c.execute("SELECT status FROM mlp_train_run WHERE run_id=%s", (run_id,)).fetchone()
            raise RunNotFound(f"{run_id}: " + (f"상태 {exists['status']} — queued 아님" if exists else "없음"))
    try:
        m = load_merged(row["tenant_id"], tenants_base)
        task = m.tasks[row["task_id"]]
        cfg = TrainConfig.from_task(task, row["snapshot_id"], seed=row["seed"], code_version=row["code_version"],
                                    pack_meta=m.pack.meta)
        if cfg.config_hash() != row["config_hash"]:
            raise ValueError("과제 정의 · 설정이 접수 뒤 바뀌었다(config_hash 불일치) — 다시 접수한다")
        result = StandardTrainer(features=resolve_features(task, merged=m)).train(cfg)
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


def work(run_ids: list[str]) -> list[dict]:
    """작업자 본체 — run 마다 serve.training.run_and_register. 한 run 의 실패가 다음 run 을 막지 않는다(실패는 행에 남는다)."""
    from ..serve.training import run_and_register

    out = []
    for rid in run_ids:
        try:
            r, ref = run_and_register(rid)
            out.append({"run_id": r.run_id, "status": r.status, "champion": r.champion,
                        "beats_baseline": r.beats_baseline, "artifact_dir": r.artifact_dir,
                        "version": getattr(ref, "version", None), "stage": getattr(ref, "stage", None)})
        except Exception as e:  # 숨기지 않는다 — 출력 · 종료 코드로 보인다
            out.append({"run_id": rid, "status": "error", "error": f"{type(e).__name__}: {e}"})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mlcore.train.jobs")
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--pending", action="store_true", help="queued 전부(접수 순)")
    ap.add_argument("--submit", nargs=2, metavar=("TENANT", "TASK"), help="make train — 접수 뒤 같은 프로세스에서 실행 · 등록")
    ap.add_argument("--source-role", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--test", action="store_true", help="시험 DB(ml_test_db)")
    a = ap.parse_args(argv)
    if not a.pending and not a.run_id and not a.submit:
        ap.error("run_id · --pending · --submit TENANT TASK 중 하나")
    if a.test:   # run_and_register 는 기본 DSN 을 쓴다 — 시험 DB 를 기본 DSN 으로
        from ..settings import get_settings

        os.environ["MLP_DB_DSN"] = os.environ.get("MLP_TEST_DB_DSN") or get_settings().test_db_dsn
        get_settings.cache_clear()
    if a.submit:
        from ..data.jobs import submit

        tenant, task = a.submit
        ids = [submit(tenant, task if "." in task else f"{tenant}.{task}", actor="make-train",
                      source_role=a.source_role, seed=a.seed)]
    else:
        ids = pending() if a.pending else [a.run_id]
    rows = work(ids)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    return 1 if any(r["status"] in ("error", "failed") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
