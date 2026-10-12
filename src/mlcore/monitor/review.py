"""대기열 일정 작업 — 감시 일일 작업 뒤 live_residual 항목 생성 (task-contract §6.1 `schedule` · G2-R01 · D2-11). 소유 개발3.

과제마다(유형 review_queue · origins 에 live_residual · schedule daily_after_monitor):
  1. uses 과제의 production 버전을 찾는다(없으면 만들지 않고 '운영 모델 없음').
  2. 그 버전 예측 중 **실측이 붙은 것**만 짝을 짓는다(`train.review.live_pairs` — prediction_id 필수).
  3. 임계값: `abs_residual_ge` 는 그 값, `top_quantile` 은 production run 보고서의 **검증 구간 잔차** 분위
     (`train.review.threshold` — 증거가 맞지 않으면 InSampleEvaluation, 항목 0). 운영 묶음 자체로 분위를 재지 않는다.
  4. 이미 항목이 있는 prediction_id 는 건너뛴다(같은 예측은 한 번만). 정렬 |잔차| ↓ · `max_items` 상한.
  5. `mlp_review_item` 에 INSERT 만 한다(state open). 검토 결과(PATCH)는 API(개발2)가, 재학습은 사람이 정한다.
production 을 바꾸지 않는다 — 이 모듈에 승인 · 모델 상태 쓰기는 없다(G-M09).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..db.conn import connect
from ..registry import tenants
from ..settings import ROOT

ORIGIN = "live_residual"
SCHEDULE = "daily_after_monitor"
ITEM_PREFIX = "rvw"


def queue_tasks(merged: tenants.Merged) -> list[tenants.TaskDef]:
    out = []
    for td in merged.tasks.values():
        if td.type != "review_queue":
            continue
        if ORIGIN in (td.raw.get("origins") or []) and (td.raw.get("schedule") or SCHEDULE) == SCHEDULE:
            out.append(td)
    return out


def production_of(tenant_id: str, task_id: str, *, conn) -> dict | None:
    return conn.execute("SELECT version, run_id, artifact_path FROM mlp_model_version "
                        "WHERE tenant_id=%s AND task_id=%s AND stage='production'", (tenant_id, task_id)).fetchone()


def run_report(tenant_id: str, task_id: str, version: str) -> dict | None:
    """production run 보고서 — mlp_train_run.report, 없으면 산출물 report.json(같은 run 이 쓴 것)."""
    with connect() as c:
        row = c.execute("SELECT r.report, mv.artifact_path FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                        "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s", (tenant_id, task_id, version)).fetchone()
    if row is None:
        return None
    if row["report"]:
        return row["report"]
    p = Path(row["artifact_path"] or "")
    p = (p if p.is_absolute() else ROOT / p) / "report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _existing(conn, tenant_id: str, task_id: str) -> set[str]:
    rows = conn.execute("SELECT prediction_id FROM mlp_review_item WHERE tenant_id=%s AND task_id=%s AND prediction_id IS NOT NULL",
                        (tenant_id, task_id)).fetchall()
    return {r["prediction_id"] for r in rows}


def _insert(conn, tenant_id: str, item: dict) -> bool:
    from ..serve.ids import new_id

    row = conn.execute(
        "INSERT INTO mlp_review_item (item_id, tenant_id, task_id, entity_id, prediction_id, predicted, actual, residual, reason, "
        "origin, state, version, rule, threshold) "
        "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s,%s,%s "
        "WHERE NOT EXISTS (SELECT 1 FROM mlp_review_item WHERE tenant_id=%s AND task_id=%s AND prediction_id=%s) "
        "RETURNING item_id",
        (new_id(ITEM_PREFIX), tenant_id, item["task"], item["entity_id"], item["prediction_id"], item["predicted"],
         item["actual"], item["residual"], item["reason"], item["origin"], item["model_version"], item["rule"],
         item["threshold"], tenant_id, item["task"], item["prediction_id"])).fetchone()
    return row is not None


def review_task(merged: tenants.Merged, task: tenants.TaskDef, day: date) -> dict:
    """한 대기열 과제 → 요약 {task_id, uses, version, rule, threshold, threshold_from, pairs, created, skipped?, error?}."""
    from ..train import review as tr

    tenant_id = merged.tenant.code
    raw = task.raw
    uses = f"{tenant_id}.{str((raw.get('uses') or [''])[0]).split('.', 1)[-1]}"
    rule = dict(raw.get("rule") or {})
    summary: dict[str, Any] = {"tenant_id": tenant_id, "task_id": task.id, "day": day, "origin": ORIGIN, "uses": uses,
                               "rule": next(iter(rule), None), "version": None, "threshold": None, "threshold_from": None,
                               "pairs": 0, "created": 0}
    with connect() as c:
        prod = production_of(tenant_id, uses, conn=c)
    if prod is None:
        return {**summary, "skipped": "운영 모델 없음 (model_not_ready) — 항목을 만들지 않는다"}
    summary["version"] = prod["version"]
    try:
        report = run_report(tenant_id, uses, prod["version"]) if summary["rule"] == "top_quantile" else None
        thr = tr.threshold(rule, report, quantile_from=raw.get("quantile_from", tr.QUANTILE_FROM))
        summary.update(threshold=thr["value"], threshold_from=thr["from"])
        with connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mlp_review:{tenant_id}:{task.id}",))
            seen = _existing(c, tenant_id, task.id)
            pairs = [p for p in tr.live_pairs(c, tenant_id, uses, version=prod["version"]) if p["prediction_id"] not in seen]
            summary["pairs"] = len(pairs)
            made = tr.from_live(pairs, rule, task_id=task.id, origins=raw.get("origins") or [], run_report=report,
                                quantile_from=raw.get("quantile_from", tr.QUANTILE_FROM),
                                max_items=int(raw.get("max_items") or tr.DEFAULT_MAX_ITEMS), reason=raw.get("reason"))
            summary["created"] = sum(_insert(c, tenant_id, it) for it in made)
    except Exception as e:  # noqa: BLE001 — 숨기지 않는다: 요약에 사유를 남기고 다음 과제로(항목은 지어내지 않는다)
        summary["error"] = {"type": type(e).__name__, "message": str(e)[:300]}
    return summary


def run_review(tenant_id: str, day: date, *, merged: tenants.Merged | None = None) -> list[dict]:
    merged = merged or tenants.load_and_merge(tenant_id)
    return [review_task(merged, td, day) for td in queue_tasks(merged)]
