"""감시 스케줄러 — 매일 KST 02:00 (spec §9 · D-06). API 프로세스 밖에서 돈다(G-M06 · G-M14).

    uv run python -m mlcore.monitor.scheduler --tenant <code>               # 상주 (APScheduler, KST 02:00)
    uv run python -m mlcore.monitor.scheduler --tenant <code> --once [--day YYYY-MM-DD]   # 한 번(기본 어제)

한 번의 실행 = (1) 감시가 전에 접수한 재학습 중 작업자가 candidate 로 등록한 것 → 승인 요청,
(2) 어제 하루치 `run_daily` → 기준 초과면 재학습 접수. 학습 실행은 작업자(`python -m mlcore.train.jobs --pending`).
production 은 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from .daily import KST, run_daily
from .retrain import request_approvals

CRON = {"hour": 2, "minute": 0}


def run_once(tenant_id: str, day: date | None = None, *, retrain_source: str | None = None) -> dict:
    day = day or (datetime.now(KST).date() - timedelta(days=1))
    approvals = request_approvals(tenant_id)
    rows = run_daily(tenant_id, day, retrain_source=retrain_source)
    summary = [r for r in rows if r["metric"] == "_summary"]
    return {"tenant": tenant_id, "day": day.isoformat(), "approvals": approvals,
            "tasks": summary, "rows": sum(1 for r in rows if r["metric"] != "_summary")}


def build(tenant_id: str, *, retrain_source: str | None = None):
    """APScheduler 상주 스케줄러(시작하지 않은 상태). 시험은 이것으로 트리거 모양만 본다."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BlockingScheduler(timezone=KST)
    sched.add_job(run_once, CronTrigger(timezone=KST, **CRON), args=[tenant_id], kwargs={"retrain_source": retrain_source},
                  id=f"monitor-{tenant_id}", max_instances=1, coalesce=True, misfire_grace_time=3600)
    return sched


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="감시 스케줄러 (KST 02:00)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--day", type=date.fromisoformat, default=None)
    ap.add_argument("--retrain-source", default=None, help="재학습 소스 역할(기본 = 회사 mode)")
    a = ap.parse_args(argv)
    if a.once:
        print(json.dumps(run_once(a.tenant, a.day, retrain_source=a.retrain_source), ensure_ascii=False, default=str))
        return 0
    build(a.tenant, retrain_source=a.retrain_source).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
