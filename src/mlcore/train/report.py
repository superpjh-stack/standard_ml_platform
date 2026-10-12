"""학습 보고서의 시험 구간 부분 (spec §5.4) — final_eval 뒤 `report` 목적으로만 시험 구간을 다시 본다.

순열 중요도(시험 구간, D-29) · 범주별 잔차 표 · (risk) 보정 곡선. 여기서 나온 값은 선정 · 구간 · 임계값에 쓰지 않는다.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from ..data.features import FeatureDef
from .guard import GuardedTest

SCORING = {"regression": "neg_mean_absolute_error", "risk": "neg_brier_score"}


def test_report(frame: pd.DataFrame, test: GuardedTest, *, model, task_type: str, features: Sequence[FeatureDef],
                y_of: Callable[[pd.DataFrame], np.ndarray], predict: Callable[[pd.DataFrame], np.ndarray],
                seed: int) -> dict:
    df = test.take(frame, "report")
    names = [f.name for f in features]
    X = df[names]
    out: dict = {"rows": len(df)}
    if task_type in SCORING and len(df) >= 5:
        y = y_of(df)
        pi = permutation_importance(model, X, y, scoring=SCORING[task_type], n_repeats=5, random_state=seed, n_jobs=1)
        out["permutation_importance"] = sorted(
            ({"feature": n, "mean": float(m), "std": float(s)} for n, m, s in zip(names, pi.importances_mean, pi.importances_std)),
            key=lambda r: -r["mean"])
        pred = predict(X)
        err = pred - y
        out["residuals"] = {"mean": float(np.mean(err)), "std": float(np.std(err)),
                            "quantiles": {str(q): float(np.quantile(err, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}
        by = {}
        for f in features:
            if f.numeric:
                continue
            g = pd.DataFrame({"k": X[f.name].astype(str), "e": np.abs(err)}).groupby("k")["e"]
            by[f.name] = {k: {"n": int(n), "mae": float(m)} for k, n, m in zip(g.size().index, g.size().values, g.mean().values)}
        out["error_by_category"] = by
        if task_type == "risk":
            bins = np.linspace(0, 1, 11)
            idx = np.clip(np.digitize(pred, bins[1:-1], right=True), 0, 9)
            out["calibration_curve"] = [{"bin": int(b), "n": int((idx == b).sum()),
                                         "mean_pred": float(pred[idx == b].mean()), "observed": float(y[idx == b].mean())}
                                        for b in range(10) if (idx == b).any()]
    return out
