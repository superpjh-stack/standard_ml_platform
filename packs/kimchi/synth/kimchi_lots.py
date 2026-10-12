"""kimchi 팩 합성 생성기 — 배합 · 절임 · 숙성 LOT (contracts/pack-contract.md §4 · §6).

원천 `api/ml_service.py:36-55 _demo_data()` 이관 (migration/source_inventory.md §9.2).
같은 시드 · 같은 길이의 범주 목록에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서는 그대로다.

이름 대응(원천 → 팩): lot_id → entity_id · produced_at → ts · line → prod_line (나머지 같음)
엔티티 접두어는 팩 중립 `DEMO-` (원천 접두어는 회사 등록부 compat.entity_prefix).
범주 값(산지 3 · 라인 2)은 회사 값이라 `categories` 인자로만 받는다. 원천 합성식의 범주 효과는
"산지 목록 첫 값 +0.8 · 라인 목록 둘째 값 +0.25" 로 목록 위치에 묶여 있다(회사 목록 순서 = 원천 목록 순서).
배합 4 의 합은 100 이고, 양념이 생성 범위 밖이면 그 행만 같은 난수열로 다시 뽑는다(원천 :39-43 루프 그대로).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 420
DEFAULT_SEED = 42
TARGETS = ("sensory_score",)

# 합성 메커니즘의 균등 분포 구간 — 원천 LIMITS(:27-31). 입력 검증 범위(features.yaml)와 별개다. 바꾸면 행 일치가 깨진다.
_LIMITS = {
    "cabbage_pct": (66.0, 76.0), "radish_pct": (5.0, 11.0), "seasoning_pct": (15.0, 23.0), "salt_pct": (1.2, 2.6),
    "brine_salinity_pct": (9.0, 13.0), "brining_hours": (8.0, 16.0), "fermentation_temp_c": (2.0, 8.0),
    "fermentation_hours": (18.0, 72.0), "storage_temp_c": (-1.0, 4.0),
}
NEUTRAL_CATEGORIES: dict[str, list[str]] = {"cabbage_origin": ["O1", "O2", "O3"], "prod_line": ["L1", "L2"]}
_P = {"cabbage_origin": [.68, .20, .12], "prod_line": [.58, .42]}   # 원천 :46 choice 확률
_MISSING = ("brine_salinity_pct", "fermentation_temp_c", "storage_temp_c")   # 원천 :54 — 각 5행, 이 순서
_T0 = "2025-01-02"                                                         # 원천 :50 — 12시간 간격


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts · 변수 11 · 목표 sensory_score."""
    cats = {**NEUTRAL_CATEGORIES, **{k: list(v) for k, v in (categories or {}).items() if k in NEUTRAL_CATEGORIES}}
    for k, p in _P.items():
        if len(cats[k]) != len(p):
            raise ValueError(f"categories.{k} 는 {len(p)}개여야 한다(원천 난수 소비와 같게)")
    L = _LIMITS
    rng = np.random.default_rng(seed)
    cabbage = rng.uniform(*L["cabbage_pct"], rows)
    radish = rng.uniform(*L["radish_pct"], rows)
    salt = rng.uniform(*L["salt_pct"], rows)
    seasoning = 100 - cabbage - radish - salt
    valid = (seasoning >= L["seasoning_pct"][0]) & (seasoning <= L["seasoning_pct"][1])
    while not valid.all():
        n = int((~valid).sum())
        cabbage[~valid] = rng.uniform(*L["cabbage_pct"], n)
        radish[~valid] = rng.uniform(*L["radish_pct"], n)
        salt[~valid] = rng.uniform(*L["salt_pct"], n)
        seasoning = 100 - cabbage - radish - salt
        valid = (seasoning >= L["seasoning_pct"][0]) & (seasoning <= L["seasoning_pct"][1])
    salinity = rng.uniform(*L["brine_salinity_pct"], rows)
    brining = rng.uniform(*L["brining_hours"], rows)
    ferment_temp = rng.uniform(*L["fermentation_temp_c"], rows)
    ferment_hours = rng.uniform(*L["fermentation_hours"], rows)
    storage_temp = rng.uniform(*L["storage_temp_c"], rows)
    origin = rng.choice(cats["cabbage_origin"], rows, p=_P["cabbage_origin"])
    line = rng.choice(cats["prod_line"], rows, p=_P["prod_line"])
    score = (86 - abs(salinity - 11.1) * 2 - abs(brining - 12) * .65 - abs(ferment_temp - 4.8) * 1.15
             - abs(ferment_hours - 42) * .13 - abs(storage_temp - 1) * .8 - abs(seasoning - 19.5) * .45
             + (origin == cats["cabbage_origin"][0]) * .8 + (line == cats["prod_line"][1]) * .25
             + rng.normal(0, 1.8, rows))
    frame = pd.DataFrame({
        "entity_id": [f"DEMO-{i + 1:04d}" for i in range(rows)],
        "ts": pd.date_range(_T0, periods=rows, freq="12h", tz="Asia/Seoul"),
        "cabbage_pct": cabbage, "radish_pct": radish, "seasoning_pct": seasoning, "salt_pct": salt,
        "brine_salinity_pct": salinity, "brining_hours": brining, "fermentation_temp_c": ferment_temp,
        "fermentation_hours": ferment_hours, "storage_temp_c": storage_temp,
        "cabbage_origin": origin, "prod_line": line, "sensory_score": score})
    for col in _MISSING:
        frame.loc[rng.choice(rows, 5, replace=False), col] = np.nan
    return frame
