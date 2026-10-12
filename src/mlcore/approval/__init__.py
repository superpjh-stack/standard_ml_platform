"""승인 — `production` 을 쓰는 유일한 코드 경로 (spec §6.1 · contracts/interfaces.md §6 · G-M09). 소유 개발2.

decide() 한 트랜잭션:
  1. UPDATE mlp_approval … WHERE approval_id AND state='pending' AND 만료 전 RETURNING — 0행이면 AlreadyDecided(409)
  2. (승인 · model) 과제의 모델 행을 FOR UPDATE 로 잠근다 → 대상 단계 재확인
  3. 기존 production → archived, 대상 → production (promoted_at · promoted_by · approval_id)
  4. mlp_audit INSERT (같은 연결 — 실패하면 전부 롤백)
동시에 같은 승인을 두 번 결정하면 행 잠금 뒤 두 번째 UPDATE 가 0행이 되어 409 다.
감시(monitor)는 Registry.request_promotion 까지만 부른다.

만료(D-130, D-73 후속): 승인 요청은 `expires_at = 요청 시각 + TTL`(모델 168h · 추천 24h — 환경변수
`MLP_APPROVAL_TTL_HOURS_MODEL` · `MLP_APPROVAL_TTL_HOURS_RECOMMENDATION` 로 바꾼다)을 넣는다. 지난 대기 건은
`expire_due()` 가 state='expired'(decided_by='system') + 감사 `approval.expired` 로 닫는다 — 목록 조회 · 재요청 · decide 직전에
부른다(스케줄러 없이 늦은 판정). 닫힌 건은 부분 고유 색인(`state='pending'`)에서 빠지므로 같은 대상 재요청은 새 승인을 만든다.
"""

from __future__ import annotations

import math
import os

from .. import audit
from ..db.conn import connect
from ..serve.errors import NotFound, ServeError

__all__ = ["decide", "AlreadyDecided", "get", "expire_due", "ttl_hours"]

DECIDERS = ("approver", "admin")
TTL_HOURS = {"model": 168, "recommendation": 24, "quote": 168}      # D-130 제안값(사람 확인 전 가설)
TTL_MAX_HOURS = 24 * 366                                              # 환경변수 상한 1년 — 넘으면 기본값(F20-5)


def ttl_hours(kind: str) -> float:
    """승인 종류별 만료 시간(시간). 환경변수 MLP_APPROVAL_TTL_HOURS_<KIND> 가 있으면 그 값(양수만)."""
    raw = os.environ.get(f"MLP_APPROVAL_TTL_HOURS_{kind.upper()}")
    if raw:
        try:
            v = float(raw)
        except ValueError:
            v = None
        if v is not None and math.isfinite(v) and 0 < v <= TTL_MAX_HOURS:   # inf · nan · 과대값은 받지 않는다 (DEF-QAR2-005)
            return v
    return float(TTL_HOURS.get(kind, TTL_HOURS["model"]))


def expire_due(*, tenant_id: str | None = None, approval_id: str | None = None, conn=None) -> list[str]:
    """만료 시각이 지난 대기 승인을 expired 로 닫는다(+ 감사 1행씩, 추천은 dismissed). → 닫은 approval_id 목록."""
    if conn is None:
        with connect() as c:
            return expire_due(tenant_id=tenant_id, approval_id=approval_id, conn=c)
    sql = ("UPDATE mlp_approval SET state = 'expired', decided_by = 'system', decided_at = now() "
           "WHERE state = 'pending' AND expires_at IS NOT NULL AND expires_at <= now()")
    params: list = []
    if tenant_id is not None:
        sql += " AND tenant_id = %s"
        params.append(tenant_id)
    if approval_id is not None:
        sql += " AND approval_id = %s"
        params.append(approval_id)
    rows = conn.execute(sql + " RETURNING approval_id, tenant_id, task_id, kind, ref_id, action, expires_at", params).fetchall()
    for r in rows:
        if r["kind"] == "quote":                       # 확정 대기 견적은 초안으로 되돌린다(다시 고칠 수 있게 — 새 행)
            from ..serve import quotes
            quotes.decide_in_tx(conn, r, approve=False, actor="system")
        if r["kind"] == "recommendation":
            conn.execute("UPDATE mlp_recommendation SET status = 'dismissed' WHERE tenant_id = %s AND rec_id = %s "
                         "AND status = 'needs_approval'", (r["tenant_id"], r["ref_id"]))
        audit.write(tenant_id=r["tenant_id"], actor="system", role="system", action="approval.expired",
                    target=f"{r['task_id']}@{r['ref_id']}",
                    detail={"approval_id": r["approval_id"], "kind": r["kind"], "action": r["action"],
                            "expires_at": r["expires_at"]}, conn=conn)
    return [r["approval_id"] for r in rows]


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
    expire_due(approval_id=approval_id)            # 만료 건은 먼저 닫는다(별도 트랜잭션) — 아래 조건부 UPDATE 는 0행 → 409
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
        if appr["kind"] == "recommendation":
            return _decide_recommendation(c, appr, state=state, actor=actor, actor_role=actor_role, reason=reason,
                                          request_id=request_id)
        if appr["kind"] == "quote":
            return _decide_quote(c, appr, state=state, actor=actor, actor_role=actor_role, reason=reason,
                                 request_id=request_id)
        if appr["kind"] != "model":
            raise ServeError("모르는 승인 종류입니다", {"rule": "kind", "field": None})
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



def _decide_recommendation(c, appr: dict, *, state: str, actor: str, actor_role: str, reason: str | None,
                           request_id: str | None) -> dict:
    """추천 승인 — mlp_recommendation.status 만 바꾼다(needs_approval → approved | rejected). 설비 · MES 에 쓰지 않는다.
    production 모델은 건드리지 않는다. 같은 트랜잭션에서 감사 1행."""
    got = c.execute("UPDATE mlp_recommendation SET status = %s WHERE tenant_id = %s AND rec_id = %s "
                    "AND status = 'needs_approval' RETURNING rec_id",
                    (state, appr["tenant_id"], appr["ref_id"])).fetchone()
    if not got:
        raise AlreadyDecided("추천의 상태가 바뀌어 결정할 수 없습니다",
                             {"approval_id": appr["approval_id"], "rule": "recommendation_not_pending"})
    audit.write(tenant_id=appr["tenant_id"], actor=actor, role=actor_role, action=f"recommendation.{state}",
                target=f"{appr['task_id']}@{appr['ref_id']}",
                detail={"approval_id": appr["approval_id"], "action": appr["action"], "reason": reason},
                request_id=request_id, conn=c)
    return {"approval_id": appr["approval_id"], "state": state, "production_version": None}


def _decide_quote(c, appr: dict, *, state: str, actor: str, actor_role: str, reason: str | None,
                  request_id: str | None) -> dict:
    """견적 확정 — 승인: confirmed 새 행(스냅숏 고정), 반려: draft 새 행. production 모델 · 설비 쓰기 0. 감사 1행 같은 트랜잭션.
    확정 결정은 approver 이상(D2-04 · std/roles.yaml quotes.confirm) — DECIDERS 가 이미 막는다."""
    from ..serve import quotes
    quotes.decide_in_tx(c, appr, approve=state == "approved", actor=actor)
    audit.write(tenant_id=appr["tenant_id"], actor=actor, role=actor_role, action=f"quote.{'confirmed' if state == 'approved' else 'rejected'}",
                target=f"{appr['task_id']}@{appr['ref_id']}",
                detail={"approval_id": appr["approval_id"], "action": appr["action"], "reason": reason},
                request_id=request_id, conn=c)
    return {"approval_id": appr["approval_id"], "state": state, "production_version": None}
