"""감시 실측 성능 — extract(모델 추출기) 의 선정 지표 macro_f1 (개발1 → 개발3 요청 · D2-45).

예측 기록의 prediction.label 과 실측(클래스 색인) 짝으로 macro-F1 을 손 계산과 맞춘다. 짝이 없으면 '실측 없음'(지어내지 않음),
숫자 회귀 짝과 섞지 않는다. 1차 mae · brier 경로는 그대로.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from mlcore.monitor import daily


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args):
        return SimpleNamespace(fetchall=lambda: self.rows)


def _task(classes):
    return SimpleNamespace(id="t.cad_objects", type="extract", raw={"model": {"classes": classes}})


PROD = {"version": "v1", "metrics": {"macro_f1": {"value": 0.8}}}


def test_macro_f1_from_label_pairs_matches_hand_count():
    classes = ["outer", "hole", "slot", "other"]
    rows = [{"outputs": {"prediction": {"label": p}}, "value": float(classes.index(a))}
            for p, a in [("hole", "hole"), ("hole", "slot"), ("slot", "slot"), ("outer", "outer")]]
    out = daily.live_performance("t", _task(classes), date(2026, 10, 12), 30, PROD, conn=FakeConn(rows))
    # 손 계산: outer F1 1 · hole P .5 R 1 → .6667 · slot P 1 R .5 → .6667 · other 0(지지 0, zero_division 0) → 평균 .5833
    assert out["value"] == pytest.approx((1 + 2 / 3 + 2 / 3 + 0) / 4)
    assert out["detail"]["n"] == 4 and out["detail"]["metric"] == "macro_f1"
    assert out["drop"] == pytest.approx((0.8 - out["value"]) / 0.8)


def test_no_label_pairs_is_no_actuals_not_zero():
    classes = ["a", "b"]
    rows = [{"outputs": {"prediction": {"value": 1.0}}, "value": 1.0},      # 라벨 없는 기록
            {"outputs": {"prediction": {"label": "a"}}, "value": 7.0}]      # 색인 밖 실측
    out = daily.live_performance("t", _task(classes), date(2026, 10, 12), 30, PROD, conn=FakeConn(rows))
    assert out["value"] is None and out["detail"]["note"] == "실측 없음" and out["detail"]["n"] == 0
