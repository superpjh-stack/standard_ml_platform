"""과제 유형 추론부 공통 — TaskKind (contracts/interfaces.md §7). 소유 개발2.

유형별 모듈(regression · risk …)이 `KINDS` 에 자기를 올린다. 코어는 과제 이름 · 변수 이름을 모른다:
목표 단위 · 기준 · 등급 경계는 전부 과제 정의(TaskDef.raw)와 산출물 lock 에서 온다.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd

from ..serve.errors import NotImplementedTaskType

PHASE2 = ("review_queue", "extract", "quote")


class TaskKind(Protocol):
    type: str

    def values(self, model: Any, frame: pd.DataFrame) -> np.ndarray: ...          # 행별 원점수(설명 · 채점 공용)
    def score(self, model: Any, frame: pd.DataFrame, task: Any) -> list[dict]: ...  # 행별 prediction/probability/anomaly 조각
    def rejected(self, model: Any, task: Any) -> dict: ...                         # 예측하지 않은 조각(값 null)
    def status(self, piece: dict, task: Any, oor: list[str], near: list[str]) -> tuple[str, list[dict]]: ...


KINDS: dict[str, TaskKind] = {}


def register(kind: TaskKind) -> TaskKind:
    KINDS[kind.type] = kind
    return kind


def kind_for(task_type: str) -> TaskKind:
    from . import regression, risk  # noqa: F401 — 등록

    if task_type in KINDS:
        return KINDS[task_type]
    raise NotImplementedTaskType(f"과제 유형 {task_type} 의 추론은 아직 없습니다", {"rule": "task_type", "field": None})


def warn(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def range_status(oor: list[str], near: list[str]) -> tuple[str | None, list[dict]]:
    """범위 판정 경고 · 상태 (predict-contract §2.1). 반환 상태는 우선순위 비교용(없으면 None)."""
    ws = [warn("out_of_range", f, "학습 범위(p1~p99) 밖입니다") for f in oor]
    ws += [warn("near_range", f, "학습 범위 가장자리입니다") for f in near]
    return ("out_of_range" if oor else "watch" if near else None), ws


ORDER = ("ok", "watch", "review", "out_of_range", "rejected")


def worst(*states: str | None) -> str:
    """상태 우선순위 rejected > out_of_range > review > watch > ok (predict-contract §2.2)."""
    present = [s for s in states if s]
    return max(present, key=ORDER.index) if present else "ok"


def r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else float(round(float(x), nd))
