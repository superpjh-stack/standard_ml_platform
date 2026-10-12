"""예측 기록 — mlp_prediction 은 추가만 (spec §7.4 · §10.2-2). 이 모듈의 INSERT 가 유일한 쓰기 경로다."""

from __future__ import annotations

import json

from ..db.conn import connect


def record(*, prediction_id: str, tenant_id: str, task_id: str, version: str, entity_id: str | None,
           inputs: dict, outputs: dict, status: str, caller: str, channel: str, synthetic: bool, conn=None) -> None:
    sql = ("INSERT INTO mlp_prediction (prediction_id, tenant_id, task_id, version, entity_id, inputs, outputs, status, "
           "caller, channel, synthetic) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)")
    params = (prediction_id, tenant_id, task_id, version, entity_id, json.dumps(inputs, ensure_ascii=False),
              json.dumps(outputs, ensure_ascii=False), status, caller, channel, synthetic)
    if conn is not None:
        conn.execute(sql, params)
        return
    with connect() as c:
        c.execute(sql, params)
