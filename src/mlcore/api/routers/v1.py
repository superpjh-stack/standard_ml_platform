"""/api/v1 라우터 (contracts/api-contract.md) — B01 health. 2차 묶음(B09 · B10 · B11)은 routers/phase2.py.

나머지 1차 묶음(B02~B08 · B12~B15)은 웨이브 A0/A 에서 담당 개발자가 붙인다(goal §3.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...db.conn import DbUnavailable, q, q1

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
                err = _artifact_error(registry.tenant.code, task_id, request)
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


def _artifact_error(tenant_id: str, task_id: str, request: Request | None = None) -> str | None:
    """production 을 predict 와 같은 판정으로 본다 — 예측 시점 방어(require_servable: live 회사의 합성 모델 → 503,
    DEF-QAR2-001) + 산출물 적재 대조(해시 · env.lock, 같은 함수 · 같은 캐시). 통과면 None, 아니면 오류 코드."""
    from ...registry.artifacts import load_artifacts
    from ...registry.models import Registry
    from ...serve.errors import ServeError
    try:
        ref = Registry().get(tenant_id, task_id)
        if request is not None:
            from ._common import catalog
            catalog(request).require_servable(tenant_id, task_id, ref)
        load_artifacts(ref)
    except ServeError as e:
        return e.code
    return None

# 2차 유형 경로(B09 · B10 · B11)는 routers/phase2.py (웨이브 P — 501 0, goal2 G2-T01)
