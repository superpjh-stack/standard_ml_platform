"""실측 등록 · 예측 연결 (spec §7.4). 실측은 entity_id 로 mlp_prediction 과 이어진다.

- 관측 시각이 서버 시각 + 허용 오차(5분 — 시계 차이) 보다 뒤면 422 `invalid_input` {field observed_at, rule future}
  (DEF-QA2R2-003 · D2-112 · api-contract B03). 미래 실측이 예측 **전에** 들어와 "예측 뒤 관측" 짝이 되는 것을 막는다.
- 응답 `linked_prediction_ids` = D2-81 1:1 짝 규칙(대기열 `train.review.live_pairs` 와 같은 SQL `pairs_cte`)으로 이 실측과
  짝이 된 예측 — 0개 또는 1개. 같은 entity 의 예측 전부가 아니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..db.conn import connect
from .errors import InvalidInput

FUTURE_TOLERANCE = timedelta(minutes=5)


def check_observed_at(observed_at: datetime, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if observed_at > now + FUTURE_TOLERANCE:
        raise InvalidInput("관측 시각이 서버 시각보다 뒤입니다(미래 실측)", {"field": "observed_at", "rule": "future"})


def add_actual(*, tenant_id: str, task_id: str, entity_id: str, value: float, observed_at: datetime,
               source: str = "api", created_by: str | None = None) -> dict:
    """→ {actual_id, linked_prediction_ids}. 같은 (entity_id, observed_at) 재등록은 기존 행을 돌려준다(값은 바꾸지 않는다)."""
    from ..train.review import pairs_cte
    check_observed_at(observed_at)
    with connect() as c:
        row = c.execute(
            "INSERT INTO mlp_actual (tenant_id, task_id, entity_id, value, observed_at, source, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, task_id, entity_id, observed_at) DO NOTHING "
            "RETURNING actual_id", (tenant_id, task_id, entity_id, float(value), observed_at, source, created_by)).fetchone()
        if row is None:
            row = c.execute("SELECT actual_id FROM mlp_actual WHERE tenant_id=%s AND task_id=%s AND entity_id=%s "
                            "AND observed_at=%s", (tenant_id, task_id, entity_id, observed_at)).fetchone()
        linked = c.execute(pairs_cte(one_entity=True) + " SELECT prediction_id FROM r WHERE rn = 1 AND actual_id = %s "
                           "ORDER BY ts, prediction_id", (tenant_id, task_id, entity_id, row["actual_id"])).fetchall()
    return {"actual_id": row["actual_id"], "linked_prediction_ids": [r["prediction_id"] for r in linked]}
