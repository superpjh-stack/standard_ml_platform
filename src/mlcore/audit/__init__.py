"""감사 로그 — mlp_audit 는 추가만 한다 (spec §10.2-2). 이후 소유 개발2."""

from __future__ import annotations

import json
import logging

log = logging.getLogger("mlcore.audit")


def write(*, tenant_id: str, actor: str, action: str, role: str | None = None, target: str | None = None,
          detail: dict | None = None, request_id: str | None = None, conn=None) -> None:
    """INSERT 만. conn 을 주면 그 트랜잭션 안에서(승인 decide 와 같은 트랜잭션), 없으면 새 연결."""
    sql = ("INSERT INTO mlp_audit (tenant_id, actor, role, action, target, detail, request_id) "
           "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)")
    params = (tenant_id or "-", actor, role, action, target, json.dumps(detail or {}, ensure_ascii=False, default=str), request_id)
    if conn is not None:
        conn.execute(sql, params)
        return
    from ..db.conn import connect
    with connect() as c:
        c.execute(sql, params)
