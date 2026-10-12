"""학습 요청 연결부 (개발2 쪽 접착부 — 학습 자체는 개발1).

- `submit()` — API 의 POST …/train 이 부른다. 개발1 `mlcore.data.jobs.submit`(소스 읽기 → 스냅숏 → mlp_train_run queued)을
  **요청 처리 중에만** 지연 import 한다. API 기동 경로는 학습 모듈을 읽지도 부르지도 않는다(G-M06).
- `run_and_register()` — 작업자(워커 · 시험)가 부른다: `mlcore.train.jobs.execute(run_id)` → 성공이면
  `Registry.register()` → candidate. API 요청 경로에서는 부르지 않는다.
"""

from __future__ import annotations

import importlib
import inspect

from ..db.conn import connect
from .errors import NotFound, ServeError

SUBMIT_MODULES = ("mlcore.data.jobs", "mlcore.train.trainer")   # progress-dev1 §1 위치 → interfaces §4 위치


class TrainerUnavailable(ServeError):
    status, code, default_message = 501, "not_implemented", "학습기가 아직 연결되지 않았습니다"


class SourceDisconnected(ServeError):
    status, code, default_message = 503, "source_disconnected", "학습 데이터 소스에 연결할 수 없습니다"


class TrainBusy(ServeError):
    status, code, default_message = 409, "train_busy", "이 회사의 학습이 이미 진행 중입니다"   # D-54 · spec §5.5 (회사당 1)


def _submit_fn():
    for name in SUBMIT_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        if getattr(mod, "submit", None) is not None:
            return mod.submit
    raise TrainerUnavailable(detail={"rule": "trainer_missing"})


def submit(tenant_id: str, task_id: str, *, actor: str, source_role: str, seed: int | None) -> dict:
    """→ {run_id, status, reused}. 같은 스냅숏 · 같은 설정이면 학습기가 기존 run_id 를 돌려준다(멱등).
    reused = 그 run_id 가 전에 있었고 failed 가 아니었다(failed 재접수 = 새 실행, D-64)."""
    fn = _submit_fn()
    with connect() as c:
        before = {r["run_id"]: r["status"] for r in c.execute(
            "SELECT run_id, status FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s", (tenant_id, task_id)).fetchall()}
    params = inspect.signature(fn).parameters
    extra = {k: v for k, v in (("source_role", source_role), ("seed", seed)) if k in params and v is not None}
    try:
        run_id = fn(tenant_id, task_id, actor=actor, **extra)
    except Exception as e:  # 학습기 예외 이름으로만 판별(개발1 모듈을 정적으로 import 하지 않는다)
        name = type(e).__name__
        if name == "SourceDisconnected":
            raise SourceDisconnected(detail={"rule": "source", "kind": getattr(e, "kind", None)}) from e
        if name == "NoTarget":
            raise SourceDisconnected("목표 없음 — 학습할 목표 열이 없습니다", {"rule": "no_target"}) from e
        if name == "TrainBusy":
            raise TrainBusy(detail={"rule": "tenant_concurrency"}) from e
        if isinstance(e, KeyError):                    # 켜지지 않은 과제 (interfaces §4.1)
            raise NotFound("과제를 찾을 수 없습니다") from e
        raise
    with connect() as c:
        row = c.execute("SELECT status FROM mlp_train_run WHERE run_id = %s", (run_id,)).fetchone()
    # failed 실행의 재접수는 새 실행이다(학습기가 queued 로 되돌림 — D-64) → reused 아님(202)
    return {"run_id": run_id, "status": row["status"] if row else "queued",
            "reused": run_id in before and before[run_id] != "failed"}


def run_and_register(run_id: str):
    """작업자 진입점: 학습 실행 → 성공이면 candidate 등록. → (TrainResult, ModelRef | None)."""
    from ..registry.models import Registry

    jobs = importlib.import_module("mlcore.train.jobs")
    with connect() as c:
        row = c.execute("SELECT tenant_id, task_id FROM mlp_train_run WHERE run_id = %s", (run_id,)).fetchone()
    result = jobs.execute(run_id)
    ref = None
    if result.status == "succeeded":
        ref = Registry().register(result, tenant_id=row["tenant_id"], task_id=row["task_id"])
    return result, ref
