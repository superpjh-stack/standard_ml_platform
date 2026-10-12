"""B03 predict · B05 actuals · B15 trace (contracts/api-contract.md). 소유 개발2."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import auth
from ...serve import actuals as actuals_mod
from ...serve import trace as trace_mod
from ...serve.contract import ActualBody, PredictBody
from ...serve.predict import PredictRequest, Predictor
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
