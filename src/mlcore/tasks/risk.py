"""risk 추론부 — 양성 확률 · 등급(low/watch/high) · 기준선(학습 양성률)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .base import r, range_status, register, warn, worst


class Risk:
    type = "risk"

    def values(self, model: Any, frame: pd.DataFrame) -> np.ndarray:
        m = model.model
        proba = np.asarray(m.predict_proba(frame), dtype=float)
        classes = list(getattr(m, "classes_", [0, 1]))
        positive = model.lock.get("positive", 1)
        idx = classes.index(positive) if positive in classes else proba.shape[1] - 1
        return proba[:, idx]

    @staticmethod
    def grade(p: float, task: Any) -> str:
        th = task.raw.get("thresholds") or {}
        if p >= float(th["review_prob"]):
            return "high"
        if th.get("watch_prob") is not None and p >= float(th["watch_prob"]):
            return "watch"
        return "low"

    def score(self, model: Any, frame: pd.DataFrame, task: Any) -> list[dict]:
        out = []
        for p in self.values(model, frame):
            p = min(1.0, max(0.0, float(p)))
            out.append({"prediction": {"value": r(p), "unit": "probability", "interval": None,
                                       "grade": self.grade(p, task), "baseline": r(model.lock.get("baseline"))},
                        "probability": r(p), "anomaly": None})
        return out

    def rejected(self, model: Any, task: Any) -> dict:
        return {"prediction": {"value": None, "unit": "probability", "interval": None, "grade": None,
                               "baseline": r(model.lock.get("baseline"))},
                "probability": None, "anomaly": None}

    def status(self, piece: dict, task: Any, oor: list[str], near: list[str]) -> tuple[str, list[dict]]:
        rs, ws = range_status(oor, near)
        g = piece["prediction"]["grade"]
        th = task.raw.get("thresholds") or {}
        st = None
        if g == "high":
            st = "review"
            ws.append(warn("threshold_exceeded", None, f"위험 확률이 검토 기준({th.get('review_prob')})을 넘습니다"))
        elif g == "watch":
            st = "watch"
            ws.append(warn("watch_band", None, f"위험 확률이 주의 기준({th.get('watch_prob')}) 이상입니다"))
        return worst(rs, st), ws


KIND = register(Risk())
