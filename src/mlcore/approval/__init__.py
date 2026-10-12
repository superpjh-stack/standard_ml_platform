"""승인 — `production` 을 쓰는 유일한 코드 경로 (spec §6.1 · contracts/interfaces.md §6 · G-M09). 소유 개발2.

decide() 한 트랜잭션:
  1. UPDATE mlp_approval … WHERE approval_id AND state='pending' AND 만료 전 RETURNING — 0행이면 AlreadyDecided(409)
  2. (승인 · model) 과제의 모델 행을 FOR UPDATE 로 잠근다 → 대상 단계 재확인
  3. 기존 production → archived, 대상 → production (promoted_at · promoted_by · approval_id)
  4. mlp_audit INSERT (같은 연결 — 실패하면 전부 롤백)
동시에 같은 승인을 두 번 결정하면 행 잠금 뒤 두 번째 UPDATE 가 0행이 되어 409 다.
감시(monitor)는 Registry.request_promotion 까지만 부른다.
"""

from __future__ import annotations

from .. import audit
from ..db.conn import connect
from ..serve.errors import NotFound, ServeError

__all__ = ["decide", "AlreadyDecided", "get"]

DECIDERS = ("approver", "admin")


class AlreadyDecided(ServeError):
    status, code, default_message = 409, "already_decided", "이미 결정되었거나 만료된 승인입니다"


class Forbidden(ServeError):
    status, code, default_message = 403, "forbidden", "권한이 없습니다"


def get(approval_id: str) -> dict:
    with connect() as c:
        row = c.execute("SELECT * FROM mlp_approval WHERE approval_id = %s", (approval_id,)).fetchone()
    if not row:
        raise NotFound("승인을 찾을 수 없습니다")
    return row


def decide(approval_id: str, *, actor: str, actor_role: str, approve: bool, reason: str | None,
           request_id: str | None = None) -> dict:
    """→ {approval_id, state, production_version}. 회사 범위 · own_task 는 호출자(API)가 먼저 본다."""
    if actor_role not in DECIDERS:
        raise Forbidden("승인 · 반려는 approver 또는 admin 만 할 수 있습니다")
    state = "approved" if approve else "rejected"
    with connect() as c:
        appr = c.execute(
            "UPDATE mlp_approval SET state = %s, decided_by = %s, decided_at = now(), "
            "evidence = evidence || jsonb_build_object('decision_reason', %s::text) "
            "WHERE approval_id = %s AND state = 'pending' AND (expires_at IS NULL OR expires_at > now()) "
            "RETURNING approval_id, tenant_id, task_id, kind, ref_id, action",
            (state, actor, reason, approval_id)).fetchone()
        if not appr:
            raise AlreadyDecided(detail={"approval_id": approval_id})
        tenant_id, task_id, version = appr["tenant_id"], appr["task_id"], appr["ref_id"]
        if appr["kind"] != "model":
            raise ServeError("모델 승인만 지원합니다 (A0)")   # recommendation · quote 결정은 웨이브 A — 트랜잭션 롤백
        previous = None
        if approve:
            rows = c.execute("SELECT version, stage FROM mlp_model_version WHERE tenant_id = %s AND task_id = %s "
                             "ORDER BY version FOR UPDATE", (tenant_id, task_id)).fetchall()
            stages = {r["version"]: r["stage"] for r in rows}
            expected = "staging" if appr["action"] == "promote" else "archived"
            if stages.get(version) != expected:
                raise AlreadyDecided("대상 모델의 단계가 바뀌어 승인할 수 없습니다",
                                     {"approval_id": approval_id, "rule": f"target_not_{expected}"})
            previous = next((v for v, s in stages.items() if s == "production"), None)
            if previous:
                c.execute("UPDATE mlp_model_version SET stage = 'archived' "
                          "WHERE tenant_id = %s AND task_id = %s AND version = %s",
                          (tenant_id, task_id, previous))
            c.execute("UPDATE mlp_model_version SET promoted_at = now(), promoted_by = %s, approval_id = %s, stage = 'production' "
                      "WHERE tenant_id = %s AND task_id = %s AND version = %s",
                      (actor, approval_id, tenant_id, task_id, version))
        prod = c.execute("SELECT version FROM mlp_model_version WHERE tenant_id = %s AND task_id = %s "
                         "AND stage = %s", (tenant_id, task_id, "production")).fetchone()
        audit.write(tenant_id=tenant_id, actor=actor, role=actor_role, action=f"approval.{state}",
                    target=f"{task_id}@{version}",
                    detail={"approval_id": approval_id, "action": appr["action"], "previous_production": previous,
                            "production_version": prod["version"] if prod else None, "reason": reason},
                    request_id=request_id, conn=c)
    return {"approval_id": approval_id, "state": state, "production_version": prod["version"] if prod else None}

