"""개발1 시험 도우미 — 팩 중립 임시 과제 · 합성 프레임 (팩 이름 · 회사 이름을 쓰지 않는다).

실 회사 과제(ks · sw)는 팩 합성 생성기(개발3)를 `mlcore.data.jobs.read_frame` 으로 읽는다.
여기 임시 생성기는 시험 안에서만 쓰는 단순 선형 합성이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mlcore.data.features import FeatureDef
from mlcore.registry.packs import def_hash
from mlcore.registry.tenants import TaskDef

FEATS = [
    FeatureDef("x1", "변수 1", "float", unit="-", min=0, max=100),
    FeatureDef("x2", "변수 2", "float", unit="-", min=0, max=100, required=False),
    FeatureDef("c1", "범주 1", "category", values=("A", "B", "C")),
]


def task(ttype: str = "regression", *, tid: str = "tt.target_value", time_key: str | None = "ts",
         group_key: str | None = None, split: str = "time_60_20_20", candidates=None, **extra) -> TaskDef:
    raw = {"id": "tmpl." + tid.split(".", 1)[1], "type": ttype, "title": "t", "entity": "lot", "time_key": time_key,
           "group_key": group_key, "features": [f.name for f in FEATS], "split": split,
           "out_of_range": "predict_with_warning", "approver_role": "quality", "seed": 7}
    if ttype == "regression":
        raw.update(target={"name": "y", "unit": "-", "direction": "lower_is_better"},
                   interval={"method": "split_conformal", "alpha": 0.1}, candidates=candidates or ["ridge", "extra_trees"])
    elif ttype == "risk":
        raw.update(target={"name": "y", "positive": 1}, thresholds={"review_prob": 0.5},
                   candidates=candidates or ["logreg", "gbc"])
    else:
        raw.update(contamination=0.1, candidates=candidates or ["isolation_forest"])
    raw.update(extra)
    return TaskDef(tid, raw["id"], ttype, raw, def_hash(raw))


def raw_rows(n: int = 600, seed: int = 0, ttype: str = "regression", groups: int | None = None) -> pd.DataFrame:
    """임시 합성 생성기 — entity_id · ts · x1 · x2 · c1 · y."""
    rng = np.random.default_rng(seed)
    x1 = rng.uniform(0, 100, n)
    x2 = rng.uniform(0, 100, n)
    c1 = rng.choice(["A", "B", "C"], n)
    lin = 0.5 * x1 - 0.2 * x2 + np.where(c1 == "B", 10, 0) + rng.normal(0, 3, n)
    df = pd.DataFrame({"entity_id": [f"E{i:05d}" for i in range(n)],
                       "ts": pd.date_range("2026-01-01", periods=n, freq="h", tz="Asia/Seoul"),
                       "x1": x1, "x2": x2, "c1": c1})
    df.loc[rng.choice(n, n // 20, replace=False), "x2"] = np.nan
    if ttype == "regression":
        df["y"] = lin
    elif ttype == "risk":
        df["y"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-(lin - 20) / 6))).astype(int)
    if groups:
        df["lot"] = [f"G{(i * groups) // n:03d}" for i in range(n)]
    return df


def std_frame(t: TaskDef, raw: pd.DataFrame, tenant: str = "tt") -> pd.DataFrame:
    from mlcore.data.frame import standardize
    from mlcore.data.sources import ReadSpec

    return standardize(raw, ReadSpec(tenant_id=tenant, task=t, features=FEATS), kind="synthetic", source_ref="test")
