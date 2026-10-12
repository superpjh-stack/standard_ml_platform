"""risk 확률 보정 래퍼 (spec §5.2 · task-contract §2 `calibration: {method: none | sigmoid | isotonic}`).

보정기(시그모이드 · 등위)는 **학습 구간 모델이 낸 검증 구간 확률**로만 맞춘다(시험 구간 미사용 — 누수 없음).
맞춘 보정기를 학습+검증 재적합 모델의 확률에 그대로 씌운다 — 회귀 구간 q · anomaly 임계값과 같은 방식.

이 모듈이 `mlcore.data` 에 있는 까닭: 보정된 모델은 model.joblib 로 저장되고 추론 프로세스(API)가 읽는다.
API 는 `mlcore.train` 을 import 하지 않아야 하므로(G-M06 B), 직렬화된 모델이 참조하는 클래스는 `FeatureCoercer`
(`data/features.py`)처럼 data 쪽에 둔다. 학습 코드는 없다(보정기 fit 은 학습기가 부른다).
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

METHODS = ("sigmoid", "isotonic")
_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


def fit_calibrator(method: str, p_valid, y_valid):
    """검증 구간 (확률, 0/1 목표) → 보정기. sigmoid = 로짓 위 Platt, isotonic = 단조 회귀(구간 밖은 끝값)."""
    p, y = np.asarray(p_valid, float), np.asarray(y_valid, int)
    if method not in METHODS:
        raise ValueError(f"보정 방법 {method!r} — {METHODS} 중 하나")
    if len(set(y.tolist())) < 2:
        raise ValueError("검증 구간 목표가 한 클래스뿐이라 보정할 수 없다")
    if method == "sigmoid":
        return LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p).reshape(-1, 1), y)
    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)


def apply_calibrator(method: str, calibrator, p) -> np.ndarray:
    p = np.asarray(p, float)
    if method == "sigmoid":
        return calibrator.predict_proba(_logit(p).reshape(-1, 1))[:, 1]
    return np.clip(calibrator.predict(p), 0.0, 1.0)


class CalibratedModel(ClassifierMixin, BaseEstimator):
    """재적합 분류기 + 검증 구간 보정기. predict_proba 의 양성 열(클래스 1)만 보정한다(이진 과제)."""

    def __init__(self, model=None, method: str = "sigmoid", calibrator=None):
        self.model = model
        self.method = method
        self.calibrator = calibrator

    @property
    def classes_(self):
        return self.model.classes_

    def __sklearn_is_fitted__(self) -> bool:
        return self.model is not None and self.calibrator is not None

    def fit(self, X, y=None):  # 보정기는 검증 구간으로 이미 맞췄다 — 다시 맞추지 않는다
        return self

    def predict_proba(self, X) -> np.ndarray:
        raw = np.asarray(self.model.predict_proba(X), float)
        cls = list(self.model.classes_)
        pos = cls.index(1)
        p = apply_calibrator(self.method, self.calibrator, raw[:, pos])
        out = np.empty_like(raw)
        out[:, pos] = p
        out[:, 1 - pos] = 1 - p
        return out

    def predict(self, X) -> np.ndarray:
        cls = np.asarray(self.model.classes_)
        return cls[(self.predict_proba(X)[:, list(cls).index(1)] >= 0.5).astype(int)] if len(cls) == 2 else self.model.predict(X)
