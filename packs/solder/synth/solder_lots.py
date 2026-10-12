"""solder 팩 합성 생성기 — 솔더 배합 LOT (contracts/pack-contract.md §4 · §6).

원천 `api/ml_service.py:31-56 make_sample_data()` 이관 (migration/source_inventory.md §8.2).
같은 시드 · 같은 길이의 공급사 목록에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서는 그대로다
(ag · cu · sb · flux uniform → sn = 100 − 합 → 온도 normal clip → 혼합 normal clip → 공급사 choice(p) → 목표 normal
→ 결측 ag · 온도 · 혼합 각 8행 → 온도 이상치 5행 ← choice([145, 352])). 이 순서를 바꾸면 이관 대조가 깨진다.

이름 대응(원천 → 팩): lot_id → entity_id (나머지 같음). 엔티티 접두어는 팩 중립 `DEMO-`(번호는 원천과 같은 20240000 부터),
원천 접두어는 회사 등록부 compat.entity_prefix. 원천에 시각 열이 없다 → `ts` 는 비워 둔다(NaT, D2-21).
공급사 값은 회사 값이라 `categories` 인자로만 받는다. 원천 합성식의 공급사 효과(+1.1 · +0.3 · −0.7)는 목록 위치에 묶인다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 720
DEFAULT_SEED = 20260917
TARGETS = ("joint_strength_mpa",)

NEUTRAL_CATEGORIES: dict[str, list[str]] = {"supplier": ["S1", "S2", "S3"]}
_P = {"supplier": [.45, .35, .2]}                   # 원천 :40 choice 확률
_EFFECT = (1.1, .3, -.7)                            # 원천 :44 공급사 효과(목록 위치)
_MISSING = ("ag_pct", "temperature_c", "mixing_min")   # 원천 :53 — 각 8행, 이 순서
_OUTLIER = (145, 352)                               # 원천 :55 — 온도 이상치 값


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts(NaT) · 변수 8 · 목표 joint_strength_mpa."""
    cats = {**NEUTRAL_CATEGORIES, **{k: list(v) for k, v in (categories or {}).items() if k in NEUTRAL_CATEGORIES}}
    for k, p in _P.items():
        if len(cats[k]) != len(p):
            raise ValueError(f"categories.{k} 는 {len(p)}개여야 한다(원천 난수 소비와 같게)")
    rng = np.random.default_rng(seed)
    ag = rng.uniform(.35, 4.0, rows)
    cu = rng.uniform(.15, 1.05, rows)
    sb = rng.uniform(0, 1.7, rows)
    flux = rng.uniform(.08, .72, rows)
    sn = 100 - ag - cu - sb - flux
    temp = rng.normal(246, 8, rows).clip(226, 268)
    mixing = rng.normal(53, 14, rows).clip(20, 88)
    sup = cats["supplier"]
    supplier = rng.choice(sup, rows, p=_P["supplier"])
    effect = np.where(supplier == sup[0], _EFFECT[0], np.where(supplier == sup[1], _EFFECT[1], _EFFECT[2]))
    strength = (31 + 5.8 * ag + 2.4 * cu + 1.25 * sb - 2.0 * (flux - .28) ** 2
                - .055 * (temp - 246) ** 2 - .009 * (mixing - 54) ** 2 + effect + rng.normal(0, 1.8, rows))
    frame = pd.DataFrame({
        "entity_id": [f"DEMO-{20240000 + i:08d}" for i in range(rows)],
        "ts": pd.Series(pd.NaT, index=range(rows), dtype="datetime64[ns, Asia/Seoul]"),
        "sn_pct": sn, "ag_pct": ag, "cu_pct": cu, "sb_pct": sb, "flux_pct": flux,
        "temperature_c": temp, "mixing_min": mixing, "supplier": supplier, "joint_strength_mpa": strength})
    for col in _MISSING:
        frame.loc[rng.choice(rows, 8, replace=False), col] = np.nan
    frame.loc[rng.choice(rows, 5, replace=False), "temperature_c"] = rng.choice(list(_OUTLIER), 5)
    return frame
