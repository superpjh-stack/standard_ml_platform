"""B07 models · B13 approvals (contracts/api-contract.md). 소유 개발2.

promote · rollback 은 **승인 요청만** 만든다(202). production 은 POST /approvals/{id}/decide → approval.decide() 만 바꾼다.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ... import approval, auth
from ...db.conn import q
from ...registry.models import Registry
from ...serve.contract import DecideBody, ReasonBody
from ...serve.errors import NotFound
from ._common import actor, catalog, principal, task_id

router = APIRouter(prefix="/api/v1")
KST = timezone(timedelta(hours=9))


def _iso(ts):
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


@router.get("/tenants/{t}/tasks/{task}/models")
def list_models(t: str, task: str, request: Request):
    auth.require(principal(request), "train", write=False)
    spec = catalog(request).get(t, task_id(t, task))
    items = [{"version": m.version, "stage": m.stage, "algo": m.algo, "metrics": m.metrics,
              "beats_baseline": m.beats_baseline, "synthetic": m.synthetic, "snapshot_id": m.snapshot_id,
              "created_at": _iso(m.created_at), "promoted_at": _iso(m.promoted_at), "promoted_by": m.promoted_by}
             for m in Registry().list(t, spec.task.id)]
    return {"items": items, "next_cursor": None, "total": len(items)}


@router.post("/tenants/{t}/tasks/{task}/models/{v}/stage")
def stage(t: str, task: str, v: str, request: Request):
    p = auth.require(principal(request), "train")
    spec = catalog(request).get(t, task_id(t, task))
    ref = Registry().stage(t, spec.task.id, v, actor=actor(p), role=p.role, request_id=request.state.request_id)
    return {"version": ref.version, "stage": ref.stage}


def _request(t: str, task: str, v: str, request: Request, action: str, reason: str | None):
    p = auth.require(principal(request), "approve")
    spec = catalog(request).get(t, task_id(t, task))
    auth.require_own_task(p, "approve", spec.task.raw["approver_role"])
    aid = Registry().request_promotion(t, spec.task.id, v, actor=actor(p), action=action, reason=reason,
                                       role=p.role, request_id=request.state.request_id)
    return JSONResponse({"approval_id": aid, "state": "pending"}, status_code=202)


@router.post("/tenants/{t}/tasks/{task}/models/{v}/promote")
def promote(t: str, task: str, v: str, request: Request, body: ReasonBody | None = None):
    return _request(t, task, v, request, "promote", body.reason if body else None)


@router.post("/tenants/{t}/tasks/{task}/models/{v}/rollback")
def rollback(t: str, task: str, v: str, request: Request, body: ReasonBody | None = None):
    return _request(t, task, v, request, "rollback", body.reason if body else None)


@router.get("/tenants/{t}/approvals")
def list_approvals(t: str, request: Request, state: str | None = Query(default=None, pattern="^(pending|approved|rejected|expired)$"),
                   limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None, max_length=64)):
    auth.require(principal(request), "approve", write=False)
    sql = ("SELECT approval_id, task_id, kind, ref_id, action, approver_role, state, requested_by, requested_at, "
           "expires_at, decided_by, decided_at, reason, evidence FROM mlp_approval WHERE tenant_id = %s")
    params: list = [t]
    if state:
        sql += " AND state = %s"
        params.append(state)
    if cursor:
        sql += " AND approval_id < %s"
        params.append(cursor)
    sql += " ORDER BY approval_id DESC LIMIT %s"
    params.append(limit + 1)
    rows = q(sql, params)
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{**r, "requested_at": _iso(r["requested_at"]), "expires_at": _iso(r["expires_at"]),
              "decided_at": _iso(r["decided_at"])} for r in rows]
    return {"items": items, "next_cursor": rows[-1]["approval_id"] if more and rows else None}


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, body: DecideBody, request: Request):
    p = auth.require(principal(request), "approve")            # 역할 밖(operator · viewer)은 승인 유무와 상관없이 403
    row = approval.get(approval_id)                            # 없으면 404
    if row["tenant_id"] != p.tenant_id:                       # 다른 회사 → 없는 것과 같다
        raise NotFound("승인을 찾을 수 없습니다")
    auth.require_own_task(p, "approve", row["approver_role"])
    return approval.decide(approval_id, actor=actor(p), actor_role=p.role, approve=body.decision == "approve",
                           reason=body.reason, request_id=request.state.request_id)
