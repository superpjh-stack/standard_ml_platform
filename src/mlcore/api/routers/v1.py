"""/api/v1 라우터 (contracts/api-contract.md). Phase 0: B01 health + 2차 묶음(B09 · B10 · B11) 501.

나머지 1차 묶음(B02~B08 · B12~B15)은 웨이브 A0/A 에서 담당 개발자가 붙인다(goal §3.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...db.conn import DbUnavailable, q, q1
from ..errors import not_implemented

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health(request: Request):
    """프로세스 · DB · 과제별 model_ready. production 이 없으면 model_ready=false — 기본값으로 꾸미지 않는다."""
    registry = getattr(request.app.state, "registry", None)
    db_ok = True
    production: dict[str, str] = {}
    try:
        q1("SELECT 1 AS ok")
        if registry is not None:
            rows = q("SELECT task_id, version FROM mlp_model_version WHERE tenant_id = %s AND stage = 'production'",
                     (registry.tenant.code,))
            production = {r["task_id"]: r["version"] for r in rows}
    except DbUnavailable:
        db_ok = False
    tasks = []
    if registry is not None:
        for task_id in registry.tasks:
            item = {"task": task_id, "model_ready": task_id in production, "version": production.get(task_id)}
            if task_id in production:
                err = _artifact_error(registry.tenant.code, task_id)
                if err is not None:        # 산출물이 등록부와 다르면 predict 가 503 — health 도 준비 안 됨으로 (QA2 관찰)
                    item.update(model_ready=False, error=err)
            tasks.append(item)
        for task_id, reason in registry.disabled.items():
            tasks.append({"task": task_id, "model_ready": False, "version": None, "disabled": reason})
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "version": request.app.version,
        "tenant": registry.tenant.code if registry is not None else None,
        "tasks": tasks,
    }


def _artifact_error(tenant_id: str, task_id: str) -> str | None:
    """production 산출물 적재 대조(해시 · env.lock) — predict 와 같은 함수 · 같은 캐시. 통과면 None, 아니면 오류 코드."""
    from ...registry.artifacts import load_artifacts
    from ...registry.models import Registry
    from ...serve.errors import ServeError
    try:
        load_artifacts(Registry().get(tenant_id, task_id))
    except ServeError as e:
        return e.code
    return None


# ── 2차 유형 경로 — 경로는 두되 501 (goal §2.3) ─────────────────────────────
@router.get("/tenants/{t}/tasks/{task}/review")
@router.patch("/tenants/{t}/tasks/{task}/review/{item_id}")
def review_queue(t: str, task: str, item_id: str | None = None):
    raise not_implemented("검토 대기열(review_queue)")


@router.post("/tenants/{t}/tasks/{task}/documents")
@router.get("/tenants/{t}/tasks/{task}/documents/{doc_id}")
def documents(t: str, task: str, doc_id: str | None = None):
    raise not_implemented("문서 · 도면 추출(extract)")


@router.post("/tenants/{t}/tasks/{task}/quotes")
@router.get("/tenants/{t}/tasks/{task}/quotes")
@router.get("/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv")
def quotes(t: str, task: str, quote_id: str | None = None):
    raise not_implemented("견적(quote)")
