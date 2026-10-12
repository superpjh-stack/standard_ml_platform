"""감시 (spec §9 · contracts/interfaces.md §9). 소유 개발3.

- `psi` · `oor_rate` · `missing_rate` — 순수 계산 (`monitor/stats.py`)
- `run_daily` — mlp_monitor_daily + 재학습 접수 (`monitor/daily.py`)
- `request_approvals` — 감시 재학습 후보 → 승인 요청만 (`monitor/retrain.py`)
- 스케줄러 KST 02:00 (`monitor/scheduler.py`) · doctor (`monitor/doctor.py`)
production 을 쓰는 코드는 여기 없다 — `approval.decide()` 하나뿐(G-M09).
"""

from .stats import missing_rate, oor_rate, psi

__all__ = ["psi", "oor_rate", "missing_rate", "run_daily", "request_approvals"]


def __getattr__(name):  # DB · 학습 쪽 모듈은 쓸 때만 읽는다
    if name == "run_daily":
        from .daily import run_daily
        return run_daily
    if name == "request_approvals":
        from .retrain import request_approvals
        return request_approvals
    raise AttributeError(name)
