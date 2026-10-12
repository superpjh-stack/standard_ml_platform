"""검토 대기열 조회 · 판정 — B09 `/review*` (api-contract §6 · predict-contract §8.1 · task-contract §6.1). 소유 개발2.

항목을 **만드는 것**은 학습(test_split — 개발1 guard 경유) · 감시 일일 작업(live_residual — 개발3)이다. 여기는 읽고 닫는다.
상태 전이 `open → confirmed_issue | false_alarm` 한 번만 — 닫힌 항목 재검토 409 already_decided(조건부 UPDATE 0행).
"""

from __future__ import annotations

import re
from datetime import timedelta, timezone

from .. import audit
from ..db.conn import connect
from .errors import InvalidInput, NotFound, ServeError

KST = timezone(timedelta(hours=9))
ITEM_ID = re.compile(r"^rvw_[0-9A-Z]{26}$")
STATES = ("open", "confirmed_issue", "false_alarm")
CLOSE = ("confirmed_issue", "false_alarm")
NOTE_MAX = 500


class AlreadyDecided(ServeError):
    status, code, default_message = 409, "already_decided", "이미 검토가 끝난 항목입니다"


def _iso(ts):
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


def view(r: dict) -> dict:
    return {"item_id": r["item_id"], "task": r["task_id"], "entity_id": r["entity_id"],
            "prediction_id": r["prediction_id"], "model_version": r["version"], "predicted": r["predicted"],
            "actual": r["actual"], "residual": r["residual"], "rule": r["rule"], "threshold": r["threshold"],
            "reason": r["reason"], "origin": r["origin"], "state": r["state"], "decided_by": r["decided_by"],
            "decided_at": _iso(r["decided_at"]), "note": r["note"], "created_at": _iso(r["created_at"])}


COLS = ("item_id, task_id, entity_id, prediction_id, version, predicted, actual, residual, rule, threshold, reason, "
        "origin, state, decided_by, decided_at, note, created_at")


def list_items(tenant_id: str, task_id: str, *, state: str | None, limit: int, cursor: str | None) -> dict:
    where = "FROM mlp_review_item WHERE tenant_id = %s AND task_id = %s"
    params: list = [tenant_id, task_id]
    if state:
        where += " AND state = %s"
        params.append(state)
    count_params = list(params)
    page = where
    if cursor:
        page += " AND item_id < %s"
        params.append(cursor)
    with connect() as c:
        rows = c.execute(f"SELECT {COLS} {page} ORDER BY item_id DESC LIMIT %s", [*params, limit + 1]).fetchall()
        total = c.execute(f"SELECT count(*) AS n {where}", count_params).fetchone()["n"]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [view(r) for r in rows], "next_cursor": rows[-1]["item_id"] if more and rows else None,
            "total": total}


def close_item(tenant_id: str, task_id: str, item_id: str, *, state: str, note: str, actor: str, role: str | None,
           request_id: str | None = None) -> dict:
    if state not in CLOSE:
        raise InvalidInput("state 는 confirmed_issue · false_alarm 입니다", {"field": "state", "rule": "enum"})
    if not isinstance(note, str) or not note.strip() or len(note) > NOTE_MAX:
        raise InvalidInput(f"note 는 1~{NOTE_MAX}자입니다", {"field": "note", "rule": "length"})
    if not ITEM_ID.match(item_id or ""):
        raise NotFound("검토 항목을 찾을 수 없습니다")
    with connect() as c:
        row = c.execute(f"UPDATE mlp_review_item SET state = %s, note = %s, decided_by = %s, decided_at = now(), "
                        f"updated_at = now() WHERE tenant_id = %s AND task_id = %s AND item_id = %s AND state = 'open' "
                        f"RETURNING {COLS}", (state, note, actor, tenant_id, task_id, item_id)).fetchone()
        if row is None:
            exists = c.execute("SELECT state FROM mlp_review_item WHERE tenant_id = %s AND task_id = %s AND item_id = %s",
                               (tenant_id, task_id, item_id)).fetchone()
            if exists is None:
                raise NotFound("검토 항목을 찾을 수 없습니다")
            raise AlreadyDecided(detail={"rule": exists["state"], "field": None})
        audit.write(tenant_id=tenant_id, actor=actor, role=role, action=f"review.{state}", target=f"{task_id}@{item_id}",
                    detail={"residual": row["residual"], "origin": row["origin"]}, request_id=request_id, conn=c)
    return view(row)
