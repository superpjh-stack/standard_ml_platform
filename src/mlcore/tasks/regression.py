"""regression 추론부 — 값 · 예측 구간(split conformal q) · 기준선(학습 평균) · 기준 판정."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .base import r, range_status, register, warn, worst


class Regression:
    type = "regression"

    def values(self, model: Any, frame: pd.DataFrame) -> np.ndarray:
        return np.asarray(model.model.predict(frame), dtype=float)

    def _clip(self, v: float, task: Any) -> float:
        clip = task.raw.get("clip") or {}
        if clip.get("min") is not None:
            v = max(v, float(clip["min"]))
        if clip.get("max") is not None:
            v = min(v, float(clip["max"]))
        return v

    def score(self, model: Any, frame: pd.DataFrame, task: Any) -> list[dict]:
        unit = (task.raw.get("target") or {}).get("unit") or ""
        interval = (model.lock.get("interval") or {})
        q = interval.get("q")
        out = []
        for raw in self.values(model, frame):
            v = self._clip(float(raw), task)
            iv = None
            if q is not None:
                lo, hi = self._clip(float(raw) - float(q), task), self._clip(float(raw) + float(q), task)
                iv = [r(lo), r(hi)]
            out.append({"prediction": {"value": r(v), "unit": unit, "interval": iv, "grade": None,
                                       "baseline": r(model.lock.get("baseline"))},
                        "probability": None, "anomaly": None})
        return out

    def rejected(self, model: Any, task: Any) -> dict:
        unit = (task.raw.get("target") or {}).get("unit") or ""
        return {"prediction": {"value": None, "unit": unit, "interval": None, "grade": None,
                               "baseline": r(model.lock.get("baseline"))},
                "probability": None, "anomaly": None}

    def status(self, piece: dict, task: Any, oor: list[str], near: list[str]) -> tuple[str, list[dict]]:
        rs, ws = range_status(oor, near)
        v = piece["prediction"]["value"]
        th = task.raw.get("thresholds") or {}
        st = None
        if v is not None:
            above, below, band = th.get("review_above"), th.get("review_below"), th.get("watch_band")
            if above is not None and v > above:
                st = "review"
                ws.append(warn("threshold_exceeded", None, f"예측값이 검토 기준({above})을 넘습니다"))
            elif below is not None and v < below:
                st = "review"
                ws.append(warn("threshold_exceeded", None, f"예측값이 검토 기준({below}) 아래입니다"))
            elif band is not None and ((above is not None and v >= above - band) or (below is not None and v <= below + band)):
                st = "watch"
                ws.append(warn("watch_band", None, "예측값이 검토 기준에 가깝습니다"))
        return worst(rs, st), ws


KIND = register(Regression())
