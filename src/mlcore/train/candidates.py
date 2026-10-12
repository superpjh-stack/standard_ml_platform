"""후보 모델 이름 사전 (spec §5.2 · std/candidates.yaml). 구현 경로 · 기본값은 YAML 에서만 온다."""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Sequence

from sklearn.pipeline import Pipeline

from ..data.features import FeatureDef
from ..registry.packs import std
from .preprocess import build_preprocessor


class CandidateUnavailable(Exception):
    """후보가 사전에 없거나, 유형이 맞지 않거나, 선택 의존성이 꺼져 있다."""


@lru_cache(maxsize=1)
def catalog() -> dict:
    return std("candidates")["candidates"]


def estimator(name: str, task_type: str, params: dict | None, seed: int):
    c = catalog().get(name)
    if c is None:
        raise CandidateUnavailable(f"후보 {name!r} 가 std/candidates.yaml 에 없다")
    if task_type not in c["types"]:
        raise CandidateUnavailable(f"후보 {name!r} 는 {task_type} 용이 아니다")
    if c.get("enabled_by_default") is False:
        raise CandidateUnavailable(f"후보 {name!r} 는 선택 의존성({c.get('optional_dependency')}) — 기본 꺼짐 (D-02)")
    mod, _, cls = c["impl"].rpartition(".")
    try:
        klass = getattr(importlib.import_module(mod), cls)
    except ImportError as e:
        raise CandidateUnavailable(f"후보 {name!r} 구현을 불러올 수 없다: {e.name}") from e
    est = klass()
    kw = {**(c.get("defaults") or {}), **(params or {})}
    valid = est.get_params()
    unknown = sorted(set(kw) - set(valid))
    if unknown:
        raise CandidateUnavailable(f"후보 {name!r} 에 없는 하이퍼파라미터 {unknown}")
    if "random_state" in valid:
        kw.setdefault("random_state", seed)
    if "n_jobs" in valid:
        kw["n_jobs"] = 1                      # 결정성 · 768MB (spec §5.5)
    return est.set_params(**kw)


def build(name: str, task_type: str, features: Sequence[FeatureDef], params: dict | None, seed: int) -> Pipeline:
    c = catalog().get(name) or {}
    est = estimator(name, task_type, params, seed)
    return Pipeline([("prep", build_preprocessor(features, scale=bool(c.get("scale", False)))), ("model", est)])
