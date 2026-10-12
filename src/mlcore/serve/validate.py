"""입력 검증 3단 · 결측 보정 · 범위 판정 (spec §7.3 · contracts/interfaces.md §7). 순서 고정:
validate_format(422 invalid_input) → validate_bounds(422 out_of_bounds) → check_missing/impute(422 missing_required)
→ range_check(200 + out_of_range / near_range).

오류 detail 에는 변수 이름(field)과 규칙 이름(rule)만 둔다 — 입력값을 되풀이하지 않는다.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .errors import InvalidInput, MissingRequired, OutOfBounds

NEAR_FRACTION = 0.02   # 학습 범위 가장자리 2% (predict-contract §2.1 near_range)
NUMERIC = ("float", "int")


def _missing(v: Any) -> bool:
    return v is None


def validate_format(inputs: dict, features: Mapping[str, dict]) -> None:
    if not isinstance(inputs, dict):
        raise InvalidInput(detail={"field": "inputs", "rule": "type"})
    for name, v in inputs.items():
        f = features.get(name)
        if f is None:
            raise InvalidInput("알 수 없는 입력 변수입니다", {"field": str(name)[:64], "rule": "unknown_key"})
        if _missing(v):
            continue
        dtype = f.get("dtype")
        if dtype in NUMERIC:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise InvalidInput("숫자여야 합니다", {"field": name, "rule": "type"})
            if isinstance(v, float) and not math.isfinite(v):
                raise InvalidInput("NaN · Infinity 는 허용하지 않습니다", {"field": name, "rule": "finite"})
            if dtype == "int" and isinstance(v, float) and not v.is_integer():
                raise InvalidInput("정수여야 합니다", {"field": name, "rule": "integer"})
        elif dtype == "category":
            if not isinstance(v, str):
                raise InvalidInput("범주 값(문자열)이어야 합니다", {"field": name, "rule": "type"})
        elif dtype == "bool":
            if not isinstance(v, bool):
                raise InvalidInput("참/거짓이어야 합니다", {"field": name, "rule": "type"})


def validate_bounds(inputs: dict, features: Mapping[str, dict]) -> None:
    for name, v in inputs.items():
        if _missing(v):
            continue
        f = features[name]
        if f.get("dtype") in NUMERIC:
            try:
                x = float(v)
            except OverflowError:
                raise OutOfBounds(detail={"field": name, "rule": "max"}) from None
            if f.get("min") is not None and x < float(f["min"]):
                raise OutOfBounds(detail={"field": name, "rule": "min"})
            if f.get("max") is not None and x > float(f["max"]):
                raise OutOfBounds(detail={"field": name, "rule": "max"})
        elif f.get("dtype") == "category":
            allowed = f.get("values")
            if allowed is not None and v not in allowed:
                raise OutOfBounds("허용된 범주 값이 아닙니다", {"field": name, "rule": "values"})


def check_missing(inputs: dict, features: Mapping[str, dict], max_imputed: int) -> list[str]:
    """보정할 변수 이름(features 순서). 필수 누락 · 보정 불가(impute: none) · 한도 초과는 MissingRequired."""
    todo = []
    for name, f in features.items():
        if not _missing(inputs.get(name)):
            continue
        if f.get("required", True):
            raise MissingRequired("필수 입력이 없습니다", {"field": name, "rule": "required"})
        if f.get("impute", "median") == "none":
            raise MissingRequired("보정할 수 없는 변수입니다", {"field": name, "rule": "impute_none"})
        todo.append(name)
    if len(todo) > max_imputed:
        raise MissingRequired(f"보정 한도({max_imputed})를 넘었습니다", {"field": None, "rule": "max_imputed",
                                                                  "count": len(todo)})
    return todo


def impute(inputs: dict, features: Mapping[str, dict], lock: dict, max_imputed: int) -> tuple[dict, list[str]]:
    """학습 구간 보정값(lock.features[*].fill)으로 채운다. 보정값이 없으면 MissingRequired — 지어내지 않는다."""
    todo = check_missing(inputs, features, max_imputed)
    out = {name: inputs.get(name) for name in features}
    lf = lock.get("features") or {}
    for name in todo:
        fill = (lf.get(name) or {}).get("fill")
        if fill is None:
            raise MissingRequired("학습 보정값이 없는 변수입니다", {"field": name, "rule": "no_fill"})
        out[name] = fill
    return out, todo


def range_check(inputs: dict, lock: dict, skip: Iterable[str] = ()) -> tuple[list[str], list[str]]:
    """(학습 범위 밖 변수, 가장자리 2% 안 변수). 수치는 [p1, p99], 범주는 학습에 나온 값."""
    skip = set(skip)
    oor, near = [], []
    for name, item in (lock.get("features") or {}).items():
        if name in skip or name not in inputs or _missing(inputs[name]):
            continue
        v = inputs[name]
        if item.get("dtype") == "category":
            vals = item.get("values")
            if vals and v not in vals:
                oor.append(name)
            continue
        lo, hi = item.get("p1"), item.get("p99")
        if lo is None or hi is None:
            continue
        x = float(v)
        if x < lo or x > hi:
            oor.append(name)
        else:
            edge = (hi - lo) * NEAR_FRACTION
            if edge > 0 and (x - lo < edge or hi - x < edge):
                near.append(name)
    return oor, near
