"""감시 지표 — 순수 계산 (contracts/interfaces.md §9 · spec §9). DB 를 모른다.

PSI 규칙 (tests/fixtures/<t>/psi_hand.json 의 손 계산과 같은 규칙):
- 수치: 경계 = **기대(학습 스냅숏) 분포**의 10분위(numpy 기본 선형 보간, 결측 제외) 중 서로 다른 값.
  구간은 (-inf, q1], (q1, q2], …, (q_last, +inf) — 값이 경계와 같으면 아래 구간.
- 범주: 기대 · 실제 값의 합집합 범주별 빈도.
- 비율 = 개수 / 결측 아닌 행 수. 0 비율은 `EPS`(1e-6) 바닥(다시 정규화하지 않는다).
- PSI = Σ (a − e) · ln(a / e).
결측은 PSI 에 넣지 않고 결측률로 따로 본다.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

EPS = 1e-6


def _clean(s: Iterable) -> pd.Series:
    s = pd.Series(s)
    return s[s.notna()]


def bin_edges(expected: Iterable, bins: int = 10) -> np.ndarray:
    """기대 분포의 안쪽 경계(오름차순, 중복 제거). 길이 ≤ bins - 1."""
    e = _clean(expected).astype(float).to_numpy()
    if len(e) == 0:
        return np.array([], dtype=float)
    qs = np.quantile(e, [k / bins for k in range(1, bins)])
    return np.unique(qs)


def numeric_shares(values: Iterable, edges: np.ndarray) -> np.ndarray:
    """구간별 비율 — 구간 수 = len(edges) + 1. 값 == 경계면 아래 구간(searchsorted left)."""
    v = _clean(values).astype(float).to_numpy()
    n_bins = len(edges) + 1
    if len(v) == 0:
        return np.zeros(n_bins)
    idx = np.searchsorted(edges, v, side="left")
    return np.bincount(idx, minlength=n_bins) / len(v)


def category_shares(expected: Iterable, actual: Iterable) -> tuple[list[str], np.ndarray, np.ndarray]:
    e, a = _clean(expected).astype(str), _clean(actual).astype(str)
    cats = sorted(set(e) | set(a))
    ec, ac = e.value_counts(), a.value_counts()
    es = np.array([ec.get(c, 0) / len(e) if len(e) else 0.0 for c in cats])
    as_ = np.array([ac.get(c, 0) / len(a) if len(a) else 0.0 for c in cats])
    return cats, es, as_


def psi_from_shares(e: np.ndarray, a: np.ndarray) -> float:
    e = np.maximum(np.asarray(e, float), EPS)
    a = np.maximum(np.asarray(a, float), EPS)
    return float(np.sum((a - e) * np.log(a / e)))


def psi(expected: Iterable, actual: Iterable, *, bins: int = 10, categorical: bool = False) -> float:
    """interfaces §9 시그니처. 실제 값이 하나도 없으면 nan(계산 불가 — 0 으로 꾸미지 않는다)."""
    if len(_clean(actual)) == 0 or len(_clean(expected)) == 0:
        return float("nan")
    if categorical:
        _, e, a = category_shares(expected, actual)
        return psi_from_shares(e, a)
    edges = bin_edges(expected, bins)
    return psi_from_shares(numeric_shares(expected, edges), numeric_shares(actual, edges))


def oor_rate(values: Iterable, rng: dict) -> float:
    """학습 범위(수치 p1~p99 · 범주 본 값 목록) 밖 비율. 결측은 분모에서 뺀다. 값이 없으면 nan."""
    v = _clean(values)
    if len(v) == 0:
        return float("nan")
    if "values" in rng:
        allowed = {str(x) for x in rng["values"]}
        return float((~v.astype(str).isin(allowed)).mean())
    x = v.astype(float)
    return float(((x < float(rng["p1"])) | (x > float(rng["p99"]))).mean())


def missing_rate(values: Iterable) -> float:
    s = pd.Series(values)
    return float(s.isna().mean()) if len(s) else float("nan")


def level(value: float | None, warn: float | None, retrain: float | None = None) -> str:
    """ok · warn · retrain — 값이 없으면(nan) ok 가 아니라 호출자가 detail 에 사유를 적는다(여기서는 ok)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "ok"
    if retrain is not None and value >= retrain:
        return "retrain"
    if warn is not None and value >= warn:
        return "warn"
    return "ok"
