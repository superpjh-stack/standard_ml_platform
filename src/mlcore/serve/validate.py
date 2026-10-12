"""입력 검증 3단 · 결측 보정 · 범위 판정 (spec §7.3 · contracts/interfaces.md §7). 순서 고정:
validate_format(422 invalid_input) → validate_bounds(422 out_of_bounds) → check_rules(422 invalid_input, rule input_rule)
→ check_missing/impute(422 missing_required) → range_check(200 + out_of_range / near_range).
`check_rules` = 과제 `input_rules`(변수 조합 규칙 — 예: 조성 합 100 ± 0.1, task-contract §1). 결측이 있는 규칙은 건너뛴다(보정 전 값).

오류 detail 에는 변수 이름(field)과 규칙 이름(rule)만 둔다 — 입력값을 되풀이하지 않는다.

변수 정의는 계약대로 `Sequence[FeatureDef]`(`mlcore.data.features`, D-47)를 받는다. 병합된 features.yaml dict
(`{이름: 정의}`)도 같은 모양으로 바꿔 받는다(시험 · 호환용) — 판정은 FeatureDef 하나로만 한다.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence, Union

from ..data.features import FeatureDef, feature_defs
from .errors import InvalidInput, MissingRequired, OutOfBounds

Features = Union[Sequence[FeatureDef], Mapping[str, dict]]


def as_defs(features: Features) -> dict[str, FeatureDef]:
    """→ {이름: FeatureDef} (과제 변수 순서)."""
    if isinstance(features, Mapping):
        if all(isinstance(v, FeatureDef) for v in features.values()):
            return dict(features)
        return {f.name: f for f in feature_defs(dict(features), list(features))}
    return {f.name: f for f in features}

SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
NEAR_FRACTION = 0.02   # 학습 범위 가장자리 2% (predict-contract §2.1 near_range)
NUMERIC = ("float", "int")


def _missing(v: Any) -> bool:
    return v is None


def validate_format(inputs: dict, features: Features) -> None:
    features = as_defs(features)
    if not isinstance(inputs, dict):
        raise InvalidInput(detail={"field": "inputs", "rule": "type"})
    for name, v in inputs.items():
        f = features.get(name)
        if f is None:   # 변수 이름 꼴이면 field 로 알려 주고, 아니면 되풀이하지 않는다(값 · 임의 문자열 반사 0)
            shown = name if isinstance(name, str) and SAFE_NAME.match(name) else None
            raise InvalidInput("알 수 없는 입력 변수입니다", {"field": shown, "rule": "unknown_key"})
        if _missing(v):
            continue
        dtype = f.dtype
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


def validate_bounds(inputs: dict, features: Features) -> None:
    features = as_defs(features)
    for name, v in inputs.items():
        if _missing(v):
            continue
        f = features[name]
        if f.dtype in NUMERIC:
            try:
                x = float(v)
            except OverflowError:
                raise OutOfBounds(detail={"field": name, "rule": "max"}) from None
            if f.min is not None and x < float(f.min):
                raise OutOfBounds(detail={"field": name, "rule": "min"})
            if f.max is not None and x > float(f.max):
                raise OutOfBounds(detail={"field": name, "rule": "max"})
        elif f.dtype == "category":
            allowed = f.values
            if allowed is not None and v not in allowed:
                raise OutOfBounds("허용된 범주 값이 아닙니다", {"field": name, "rule": "values"})


def check_rules(inputs: dict, rules: Iterable[Mapping] | None) -> None:
    """과제 `input_rules: [{name, expr, between: [lo, hi]}]` — 식 값이 [lo, hi] 밖이면 422 invalid_input
    (detail field = 규칙 이름, rule = input_rule). 식의 변수 중 하나라도 없거나 null 이면 그 규칙은 건너뛴다."""
    from .expr import ExprError, compile_expr, eval_expr, names_of
    for r in rules or []:
        tree = compile_expr(str(r["expr"]))
        env = {}
        for n in names_of(tree):
            v = inputs.get(n)
            if _missing(v) or isinstance(v, (bool, str)):
                env = None
                break
            env[n] = float(v)
        if env is None:
            continue
        try:
            x = float(eval_expr(tree, env))
        except ExprError:
            continue
        lo, hi = r["between"]
        if not math.isfinite(x) or x < float(lo) or x > float(hi):
            raise InvalidInput("입력 조합이 과제 규칙을 벗어났습니다", {"field": str(r["name"]), "rule": "input_rule"})


def check_missing(inputs: dict, features: Features, max_imputed: int) -> list[str]:
    """보정할 변수 이름(features 순서). 필수 누락 · 보정 불가(impute: none) · 한도 초과는 MissingRequired."""
    todo = []
    for name, f in as_defs(features).items():
        if not _missing(inputs.get(name)):
            continue
        if f.required:
            raise MissingRequired("필수 입력이 없습니다", {"field": name, "rule": "required"})
        if f.impute == "none":
            raise MissingRequired("보정할 수 없는 변수입니다", {"field": name, "rule": "impute_none"})
        todo.append(name)
    if len(todo) > max_imputed:
        raise MissingRequired(f"보정 한도({max_imputed})를 넘었습니다", {"field": None, "rule": "max_imputed",
                                                                  "count": len(todo)})
    return todo


def impute(inputs: dict, features: Features, lock: dict, max_imputed: int) -> tuple[dict, list[str]]:
    """학습 구간 보정값(lock.features[*].fill)으로 채운다. 보정값이 없으면 MissingRequired — 지어내지 않는다."""
    features = as_defs(features)
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


def ml_inputs(values: dict) -> dict:
    """견적 · 문서 입력(JSON 숫자 = Decimal, parse_float=Decimal) → 회귀 모델 입력.
    금액 계산은 Decimal 그대로 두고(serve/quotes.py), **모델 입력 경계에서만** 수치형으로 바꾼다 — 모델은 실수로 예측한다.
    정수값 Decimal 은 int, 그 밖 Decimal 은 float. 문자열 · None · int 는 그대로."""
    from decimal import Decimal
    out = {}
    for k, v in values.items():
        if isinstance(v, Decimal):
            out[k] = int(v) if v == v.to_integral_value() else float(v)
        else:
            out[k] = v
    return out
