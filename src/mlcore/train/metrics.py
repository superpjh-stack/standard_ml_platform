"""지표 사전 (spec §2.4 · std/metrics.yaml). 이름은 YAML 의 키와 같다. 모든 지표는 기준선과 함께 낸다."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sklearn.metrics import (average_precision_score, brier_score_loss, log_loss, mean_absolute_error,
                             mean_squared_error, precision_score, r2_score, recall_score, roc_auc_score)

from ..registry.packs import std


@lru_cache(maxsize=1)
def dictionary() -> dict:
    return std("metrics")["metrics"]


@lru_cache(maxsize=1)
def task_types() -> dict:
    return std("task_types")["types"]


def selection_metric(task_type: str) -> str | None:
    return task_types()[task_type]["selection_metric"]


def direction(name: str) -> str:
    return dictionary()[name]["direction"]


def better(name: str, a: float, b: float) -> bool:
    """a 가 b 보다 엄격히 나은가 (metrics.yaml direction)."""
    d = direction(name)
    if d == "lower":
        return a < b
    if d == "higher":
        return a > b
    raise ValueError(f"{name}: 방향 {d} 는 우열 비교가 없다")


def regression(y, pred, lo=None, hi=None) -> dict[str, float]:
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    out = {"mae": float(mean_absolute_error(y, pred)), "rmse": float(np.sqrt(mean_squared_error(y, pred))),
           "r2": float(r2_score(y, pred)) if len(y) > 1 else float("nan")}
    if len(y) and np.all(y > 0):
        out["mape"] = float(np.mean(np.abs((y - pred) / y)))
    if lo is not None and hi is not None:
        out["interval_coverage"] = float(np.mean((y >= np.asarray(lo)) & (y <= np.asarray(hi))))
    return out


def ece(y, p, bins: int = 10) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def risk(y, p, threshold: float) -> dict[str, float]:
    y, p = np.asarray(y, int), np.clip(np.asarray(p, float), 1e-15, 1 - 1e-15)
    both = len(set(y.tolist())) == 2
    flag = (p >= threshold).astype(int)
    return {"brier": float(brier_score_loss(y, p)),
            "roc_auc": float(roc_auc_score(y, p)) if both else float("nan"),
            "pr_auc": float(average_precision_score(y, p)) if both else float("nan"),
            "logloss": float(log_loss(y, p, labels=[0, 1])),
            "ece": ece(y, p),
            "grade_precision": float(precision_score(y, flag, zero_division=0)),
            "grade_recall": float(recall_score(y, flag, zero_division=0))}


def anomaly(flags) -> dict[str, float]:
    f = np.asarray(flags, float)
    return {"flag_rate": float(f.mean()) if len(f) else float("nan")}


def with_baseline(model: dict[str, float], base: dict[str, float]) -> dict[str, dict]:
    out = {}
    for k, v in model.items():
        if v is None or np.isnan(v):
            continue                      # 정의되지 않는 지표(예: 한 클래스뿐인 AUC)는 숫자를 지어내지 않고 뺀다
        b = base.get(k)
        ok = b is not None and not (isinstance(b, float) and np.isnan(b)) and not np.isnan(v)
        out[k] = {"value": v, "baseline": b if ok else None, "delta_vs_baseline": (v - b) if ok else None}
    return out
