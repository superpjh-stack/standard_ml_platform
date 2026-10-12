"""B08 POST …/train — 학습 요청 (contracts/api-contract.md §4). 학습기는 개발1, 여기는 요청 · 응답 모양만."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ... import auth
from ...serve import training
from ...serve.contract import TrainBody
from ._common import actor, catalog, principal, task_id

router = APIRouter(prefix="/api/v1")


@router.post("/tenants/{t}/tasks/{task}/train")
def train(t: str, task: str, request: Request, body: TrainBody | None = None):
    p = auth.require(principal(request), "train")
    spec = catalog(request).get(t, task_id(t, task))
    body = body or TrainBody()
    out = training.submit(t, spec.task.id, actor=actor(p), source_role=body.source_role, seed=body.seed)
    if out["reused"]:
        return {"run_id": out["run_id"], "status": out["status"], "reused": True}
    return JSONResponse({"run_id": out["run_id"], "status": out["status"]}, status_code=202)


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request):
    """B08 GET /runs/{id} — 학습 실행 조회(contracts/api-contract.md §4). 다른 회사 · 없음은 404 로 숨긴다."""
    from ...data.jobs import run_view
    from ...serve.errors import NotFound

    p = auth.require(principal(request), "train", write=False)
    body = run_view(run_id, tenant_id=p.tenant_id)
    if body is None:
        raise NotFound("run")
    return body
