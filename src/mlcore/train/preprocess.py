"""전처리 공장 (spec §5.1).

수치 = SimpleImputer(median) → StandardScaler(트리 모델은 생략), 범주 = SimpleImputer(most_frequent) →
OneHotEncoder(handle_unknown="ignore"). 이상치 제거는 기본 꺼짐(과제 `outlier: iqr` 로 켠다 — A 에서 구현).
"""

from __future__ import annotations

from typing import Sequence

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ..data.features import FeatureCoercer, FeatureDef


def split_kinds(features: Sequence[FeatureDef]) -> tuple[list[str], list[str]]:
    num = [f.name for f in features if f.numeric]
    cat = [f.name for f in features if not f.numeric]
    return num, cat


def build_preprocessor(features: Sequence[FeatureDef], *, scale: bool) -> Pipeline:
    num, cat = split_kinds(features)
    num_steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    parts = []
    if num:
        parts.append(("num", Pipeline(num_steps), num))
    if cat:
        parts.append(("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), cat))
    return Pipeline([
        ("coerce", FeatureCoercer(num, cat)),
        ("columns", ColumnTransformer(parts, remainder="drop", verbose_feature_names_out=False)),
    ])
