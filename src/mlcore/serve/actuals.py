"""실측 등록 · 예측 연결 (spec §7.4). 실측은 entity_id 로 mlp_prediction 과 이어진다."""

from __future__ import annotations

from datetime import datetime

from ..db.conn import connect


def add_actual(*, tenant_id: str, task_id: str, entity_id: str, value: float, observed_at: datetime,
               source: str = "api", created_by: str | None = None) -> dict:
    """→ {actual_id, linked_prediction_ids}. 같은 (entity_id, observed_at) 재등록은 기존 행을 돌려준다(값은 바꾸지 않는다)."""
    with connect() as c:
        row = c.execute(
            "INSERT INTO mlp_actual (tenant_id, task_id, entity_id, value, observed_at, source, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, task_id, entity_id, observed_at) DO NOTHING "
            "RETURNING actual_id", (tenant_id, task_id, entity_id, float(value), observed_at, source, created_by)).fetchone()
        if row is None:
            row = c.execute("SELECT actual_id FROM mlp_actual WHERE tenant_id=%s AND task_id=%s AND entity_id=%s "
                            "AND observed_at=%s", (tenant_id, task_id, entity_id, observed_at)).fetchone()
        linked = c.execute("SELECT prediction_id FROM mlp_prediction WHERE tenant_id=%s AND task_id=%s AND entity_id=%s "
                           "ORDER BY ts, prediction_id", (tenant_id, task_id, entity_id)).fetchall()
    return {"actual_id": row["actual_id"], "linked_prediction_ids": [r["prediction_id"] for r in linked]}
