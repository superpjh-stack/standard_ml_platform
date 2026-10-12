"""_template 팩 합성 생성기 — 단순 선형 자리표시 (contracts/pack-contract.md §4).

원천 이관 대상이 없는 빈 팩이다. 새 업종 팩은 이 파일을 원천 demo_data() 이관으로 바꾼다.
열: entity_id · ts · x1 · x2(결측 2%) · c1 · target_value(회귀) · target_risk(이진).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 600
DEFAULT_SEED = 42
TARGETS = ("target_value", "target_risk")
_C1 = ["A", "B", "C"]
_C1_SHIFT = {"A": 0.0, "B": 5.0, "C": -5.0}


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = pd.DataFrame({"x1": rng.uniform(0, 100, rows), "x2": rng.uniform(0, 100, rows)})
    data["c1"] = rng.choice(_C1, rows)
    data["target_value"] = 10 + 0.4 * data.x1 - 0.2 * data.x2 + data.c1.map(_C1_SHIFT) + rng.normal(0, 3, rows)
    p = 1 / (1 + np.exp(-(data["target_value"] - 25) / 4))
    data["target_risk"] = rng.binomial(1, p)
    data["entity_id"] = [f"DEMO-{i + 1:04d}" for i in range(rows)]
    data["ts"] = pd.date_range("2026-01-01 00:00", periods=rows, freq="h", tz="Asia/Seoul")
    data.loc[rng.choice(rows, max(1, rows // 50), replace=False), "x2"] = np.nan
    for k in ("x1", "x2", "target_value"):
        data[k] = data[k].round(3)
    return data
