"""재학습 후보 → 승인 대기열 (spec §9 · interfaces §9). 소유 개발3.

감시가 접수한 학습(`mlp_train_run.created_by = 'monitor'`)이 작업자에 의해 candidate 로 등록되면,
기준선을 이긴 후보만 staging 으로 올리고(`Registry.stage`, 행위자 monitor · 감사 기록) **승인 요청만** 만든다
(`Registry.request_promotion`). production 은 사람이 `approval.decide()` 로만 바꾼다 — 여기서는 부르지 않는다.
staging 을 거치는 이유: 승인 요청은 staging 버전만 받는다(registry 전이 규칙) → decisions.md D-W3-02.
"""

from __future__ import annotations

from ..db.conn import connect
from .daily import MONITOR_ACTOR


def pending_candidates(tenant_id: str, task_id: str | None = None) -> list[dict]:
    """감시가 접수해 학습이 끝난 run 의 candidate 버전(아직 승인 요청 없음)."""
    sql = ("SELECT mv.task_id, mv.version, mv.run_id, mv.beats_baseline FROM mlp_model_version mv "
           "JOIN mlp_train_run r ON r.run_id = mv.run_id "
           "WHERE mv.tenant_id=%s AND r.created_by=%s AND mv.stage='candidate'")
    params: list = [tenant_id, MONITOR_ACTOR]
    if task_id:
        sql += " AND mv.task_id=%s"
        params.append(task_id)
    with connect() as c:
        return c.execute(sql + " ORDER BY mv.created_at", params).fetchall()


def request_approvals(tenant_id: str, task_id: str | None = None, *, reason: str | None = None) -> list[dict]:
    """→ [{task_id, version, approval_id | None, skipped?}]. 기준선 미달 후보는 candidate 로 둔다(승인 요청 없음)."""
    from ..registry.models import InvalidTransition, Registry

    reg = Registry()
    out = []
    for row in pending_candidates(tenant_id, task_id):
        item = {"task_id": row["task_id"], "version": row["version"], "run_id": row["run_id"], "approval_id": None}
        if not row["beats_baseline"]:
            item["skipped"] = "기준선 미달 — candidate 로 둔다"
            out.append(item)
            continue
        try:
            reg.stage(tenant_id, row["task_id"], row["version"], actor=MONITOR_ACTOR, role="system")
            item["approval_id"] = reg.request_promotion(
                tenant_id, row["task_id"], row["version"], actor=MONITOR_ACTOR, action="promote",
                reason=reason or "감시: 드리프트 · 성능 기준 초과로 재학습한 후보", role="system")
        except InvalidTransition as e:
            item["skipped"] = f"전이 거부: {getattr(e, 'detail', None) or e}"
        out.append(item)
    return out
