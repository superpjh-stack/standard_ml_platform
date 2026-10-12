"""B03 predict · predict:batch · B04 optimize · B05 actuals · B15 trace (contracts/api-contract.md). 소유 개발2."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import auth
from ...serve import actuals as actuals_mod
from ...serve import trace as trace_mod
from pydantic import ValidationError

from ...serve.contract import ActualBody, BatchBody, OptimizeBody, PredictBody, safe_errors
from ...serve.errors import InvalidInput
from ...serve.predict import BatchItemError, PredictRequest, Predictor
from ...tasks.optimize import OptimizeRequest, Optimizer
from ._common import actor, catalog, principal, task_id

router = APIRouter(prefix="/api/v1")


@router.post("/tenants/{t}/tasks/{task}/predict")
def predict(t: str, task: str, body: PredictBody, request: Request):
    p = auth.require(principal(request), "predict")
    if body.model_version is not None and not auth.at_least(p, "approver"):
        raise auth.Forbidden("모델 버전 지정은 approver 이상입니다")
    cat = catalog(request)
    req = PredictRequest(inputs=body.inputs, entity_id=body.entity_id, explain=body.explain,
                         model_version=body.model_version)
    return Predictor(cat).predict(t, task_id(t, task), req, caller=actor(p), channel="api")


@router.post("/tenants/{t}/tasks/{task}/predict:batch")
def predict_batch(t: str, task: str, body: BatchBody, request: Request):
    p = auth.require(principal(request), "predict")
    reqs: list = []
    for i, raw in enumerate(body.items):          # 건마다 검증 — 한 건의 형식 오류는 그 자리만 (DEF-QA2-003)
        try:
            it = PredictBody.model_validate(raw)
        except ValidationError as e:
            reqs.append(BatchItemError(i, InvalidInput("입력 값이 올바르지 않습니다",
                                                       {"errors": safe_errors(e.errors(), prefix=f"items.{i}")})))
            continue
        reqs.append(PredictRequest(inputs=it.inputs, entity_id=it.entity_id, explain=it.explain,
                                   model_version=it.model_version))
    if any(isinstance(r, PredictRequest) and r.model_version is not None for r in reqs) and not auth.at_least(p, "approver"):
        raise auth.Forbidden("모델 버전 지정은 approver 이상입니다")
    return Predictor(catalog(request)).predict_batch(t, task_id(t, task), reqs, caller=actor(p))


@router.post("/tenants/{t}/tasks/{task}/optimize")
def optimize(t: str, task: str, body: OptimizeBody, request: Request):
    p = auth.require(principal(request), "optimize")
    req = OptimizeRequest(fixed=body.fixed, current=body.current, params=body.params, entity_id=body.entity_id)
    return Optimizer(catalog(request)).optimize(t, task_id(t, task), req, caller=actor(p))


@router.post("/tenants/{t}/tasks/{task}/actuals")
def actuals(t: str, task: str, body: ActualBody, request: Request):
    p = auth.require(principal(request), "predict")
    spec = catalog(request).get(t, task_id(t, task))
    return actuals_mod.add_actual(tenant_id=t, task_id=spec.task.id, entity_id=body.entity_id, value=body.value,
                                  observed_at=body.observed_at, source="api", created_by=actor(p))


@router.get("/predictions/{prediction_id}/trace")
def trace(prediction_id: str, request: Request):
    p = auth.require(principal(request), "trace")
    return trace_mod.trace(prediction_id, tenant_id=p.tenant_id)
