"""시험 구간 1회 평가 — `GuardedTest.take(…, "final_eval")` 를 부르는 유일한 곳 (G-M05 정적 검사).

재적합 구간과 시험 구간이 겹치면 InSampleEvaluation(표본 내 평가 금지).
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd

from .guard import GuardedTest, assert_not_in_sample


def final_evaluation(frame: pd.DataFrame, test: GuardedTest, fit_idx: Sequence[int],
                     score: Callable[[pd.DataFrame], Any]) -> Any:
    assert_not_in_sample(fit_idx, test)
    test_frame = test.take(frame, "final_eval")
    return score(test_frame)
