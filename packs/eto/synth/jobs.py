"""eto 팩 합성 생성기 — 제작 작업(대당 공수) (contracts/pack-contract.md §4 · §6).

원천 `api/ml_service.py:15-29 demo_jobs()` 이관 (migration/source_inventory.md §11.2).
같은 시드 · 같은 길이 · 같은 순서의 범주 목록에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서는 그대로다.

이름 대응(원천 → 팩): job_id → entity_id · mass_kg → total_mass_kg · material → main_material · product → product_family ·
hours → labor_hours. 범주 값(재질 8 · 제품군 6)은 회사 값이라 `categories` 인자로만 받는다. 원천 합성식의 범주 효과는
목록 위치(재질 i × 3 · 제품군 j × 5)에 묶여 있다(회사 목록 순서 = 원천 목록 순서).
원천에는 시각 열이 없다 — 표준은 `ts` 를 비워 둔다(NaT). 행 순서를 시간으로 꾸미지 않는다(D2-21).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 900
DEFAULT_SEED = 42
TARGETS = ("labor_hours",)

# 합성 메커니즘의 균등 분포 구간 — 원천 FEATURE_META 의 min/max, 원천 dict 순서 그대로(난수 호출 순서).
_UNIFORM: tuple[tuple[str, float, float], ...] = (
    ("total_mass_kg", 10, 10000),
    ("cut_m", 0, 500),
    ("weld_m", 0, 300),
    ("thickness_mm", 1, 30),
    ("complexity", 1, 5),
)
NEUTRAL_CATEGORIES: dict[str, list[str]] = {
    "main_material": [f"M{i}" for i in range(1, 9)],
    "product_family": [f"P{i}" for i in range(1, 7)],
}
_MISSING_POOL, _MISSING_N = 540, 12          # 원천 :28 — 앞 540 행에서 cut_m 12 개


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts(NaT) · 변수 7 · 목표 labor_hours."""
    cats = {**NEUTRAL_CATEGORIES, **{k: list(v) for k, v in (categories or {}).items() if k in NEUTRAL_CATEGORIES}}
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, lo, hi in _UNIFORM})
    frame["main_material"] = rng.choice(cats["main_material"], rows)
    frame["product_family"] = rng.choice(cats["product_family"], rows)
    material_offset = frame.main_material.map({m: i * 3 for i, m in enumerate(cats["main_material"])})
    product_offset = frame.product_family.map({p: i * 5 for i, p in enumerate(cats["product_family"])})
    frame["labor_hours"] = (8 + frame.total_mass_kg ** .8 * .05 + frame.cut_m * .09 + frame.weld_m * .8
                            + frame.thickness_mm ** 1.4 * .3 + frame.complexity * 5 + material_offset + product_offset
                            + rng.normal(0, 4, rows)).clip(lower=1)
    frame.insert(0, "entity_id", [f"DEMO-{i + 1:04d}" for i in range(rows)])
    frame.insert(1, "ts", pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, Asia/Seoul]"))
    frame.loc[rng.choice(min(_MISSING_POOL, rows), min(_MISSING_N, rows), replace=False), "cut_m"] = np.nan
    return frame
