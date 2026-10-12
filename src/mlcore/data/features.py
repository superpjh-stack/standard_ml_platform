"""변수 정의 — features.yaml 한 항목 (contracts/feature-contract.md · interfaces.md §1).

계약은 `mlcore/types.py` 에 두라고 하지만 그 파일이 없고 소유가 정해지지 않았다(decisions D-47).
코어는 변수 이름을 모른다 — 팩 YAML 에서 읽은 dict 를 그대로 바꿀 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence


@dataclass(frozen=True)
class FeatureDef:
    name: str
    label: str
    dtype: Literal["float", "int", "category", "bool"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    values: tuple[str, ...] | None = None
    default: Any = None
    required: bool = True
    impute: Literal["median", "most_frequent", "none"] = "median"
    controllable: bool = False
    step: float | None = None
    std_name: str | None = None

    @property
    def numeric(self) -> bool:
        return self.dtype in ("float", "int", "bool")


def feature_defs(pack_features: dict[str, dict], names: Sequence[str], categories: dict | None = None,
                 std_name: dict | None = None) -> list[FeatureDef]:
    """팩 변수 사전에서 과제 변수 순서대로 FeatureDef 를 만든다. values_from: tenant 는 회사 categories 로 채운다."""
    out = []
    categories = categories or {}
    std_name = std_name or {}
    for n in names:
        f = pack_features.get(n)
        if f is None:
            raise KeyError(f"변수 {n!r} 가 변수 사전에 없다")
        values = f.get("values")
        if values is None and f.get("values_from") == "tenant":
            values = categories.get(n)
        dtype = f["dtype"]
        out.append(FeatureDef(
            name=n, label=f.get("label", n), dtype=dtype, unit=f.get("unit"),
            min=f.get("min"), max=f.get("max"),
            values=tuple(str(v) for v in values) if values is not None else None,
            default=f.get("default"), required=bool(f.get("required", True)),
            impute=f.get("impute") or ("most_frequent" if dtype == "category" else "median"),
            controllable=bool(f.get("controllable", False)), step=f.get("step"), std_name=std_name.get(n)))
    return out


class FeatureCoercer:
    """모델 파이프라인 첫 단계 — 입력 DataFrame 을 변수 정의대로 맞춘다(수치 = float, 범주 = str · 결측 = NaN).

    학습 · 추론이 같은 형 변환을 쓰게 model.joblib 안에 들어간다. sklearn 변환기 규약(fit/transform)만 따른다.
    """

    def __init__(self, numeric: Sequence[str] = (), categorical: Sequence[str] = ()):
        self.numeric = list(numeric)
        self.categorical = list(categorical)

    def get_params(self, deep: bool = True) -> dict:
        return {"numeric": self.numeric, "categorical": self.categorical}

    def set_params(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        import numpy as np
        import pandas as pd

        df = pd.DataFrame(X).copy()
        out = pd.DataFrame(index=df.index)
        for c in self.numeric:
            out[c] = pd.to_numeric(df[c], errors="coerce").astype(float) if c in df.columns else np.nan
        for c in self.categorical:
            if c in df.columns:
                s = df[c].astype(object)
                out[c] = s.where(s.notna(), np.nan).map(lambda v: v if isinstance(v, float) else str(v)).astype(object)
            else:
                out[c] = np.nan
        return out

    def fit_transform(self, X, y=None):
        return self.transform(X)
