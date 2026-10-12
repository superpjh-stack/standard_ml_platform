"""anomaly 추론부 — 이상 점수 · flag · 임계값 · 기여 변수 (predict-contract §2 · task-contract §2).

점수 = 산출물 lock `score` 규칙(`-score_samples` — 클수록 이상). flag = 점수 ≥ lock `threshold`
(학습 구간 모델이 낸 검증 구간 점수의 1-c 분위, D-50 — 임계값은 학습기가 정하고 여기서는 읽기만 한다).
기여 변수 = 변수 하나를 학습 보정값(fill)으로 바꿨을 때 점수가 얼마나 내려가는가(국소 치환). 상위 5, 양수만.
anomaly 의 허용 상태는 ok · review · out_of_range · rejected (watch 없음) — 범위 가장자리는 경고만 남긴다.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..serve.errors import ServeError
from .base import r, range_status, register, warn, worst

TOP = 5


class Anomaly:
    type = "anomaly"

    def values(self, model: Any, frame: pd.DataFrame) -> np.ndarray:
        rule = model.lock.get("score") or "-score_samples"
        m = model.model
        if rule == "-score_samples":
            return -np.asarray(m.score_samples(frame), dtype=float)
        if rule == "score_samples":
            return np.asarray(m.score_samples(frame), dtype=float)
        raise ServeError("산출물의 이상 점수 규칙을 알 수 없습니다", {"rule": "score_rule", "field": None})

    def _threshold(self, model: Any) -> float:
        thr = model.lock.get("threshold")
        if thr is None:   # 임계값 없는 산출물로 flag 를 지어내지 않는다
            raise ServeError("산출물에 이상 임계값이 없습니다", {"rule": "no_threshold", "field": None})
        return float(thr)

    def contributors(self, model: Any, frame: pd.DataFrame, scores: np.ndarray) -> list[list[dict]]:
        lf = model.lock.get("features") or {}
        names = [n for n in frame.columns if (lf.get(n) or {}).get("fill") is not None]
        if not names:
            return [[] for _ in range(len(frame))]
        reps = []
        for i in range(len(frame)):
            block = pd.concat([frame.iloc[[i]]] * len(names), ignore_index=True)
            for n in names:                            # 정수 열에 실수 보정값을 넣을 수 있게
                if not isinstance(lf[n]["fill"], str):
                    block[n] = block[n].astype(float)
            for j, n in enumerate(names):
                block.at[j, n] = lf[n]["fill"]
            reps.append(block)
        alt = self.values(model, pd.concat(reps, ignore_index=True)).reshape(len(frame), len(names))
        out = []
        for i in range(len(frame)):
            c = [(n, float(scores[i] - alt[i, j])) for j, n in enumerate(names)]
            c = sorted((x for x in c if x[1] > 0), key=lambda x: (-x[1], x[0]))[:TOP]
            out.append([{"field": n, "contribution": r(v)} for n, v in c])
        return out

    def score(self, model: Any, frame: pd.DataFrame, task: Any) -> list[dict]:
        thr = self._threshold(model)
        cont = model.lock.get("contamination", task.raw.get("contamination"))
        scores = self.values(model, frame)
        contrib = self.contributors(model, frame, scores)
        return [{"prediction": None, "probability": None,
                 "anomaly": {"score": r(s), "flag": bool(s >= thr), "threshold": r(thr),
                             "contamination": None if cont is None else float(cont), "contributors": c}}
                for s, c in zip(scores, contrib)]

    def rejected(self, model: Any, task: Any) -> dict:
        thr = model.lock.get("threshold")
        cont = model.lock.get("contamination", task.raw.get("contamination"))
        return {"prediction": None, "probability": None,
                "anomaly": {"score": None, "flag": None, "threshold": None if thr is None else r(thr),
                            "contamination": None if cont is None else float(cont), "contributors": []}}

    def status(self, piece: dict, task: Any, oor: list[str], near: list[str]) -> tuple[str, list[dict]]:
        rs, ws = range_status(oor, near)
        if rs == "watch":            # anomaly 에는 watch 상태가 없다 (predict-contract §4)
            rs = None
        st = None
        if piece["anomaly"]["flag"]:
            st = "review"
            ws.append(warn("anomaly_input", None, "학습 분포와 다른 조건 조합입니다"))
        return worst(rs, st), ws


KIND = register(Anomaly())
