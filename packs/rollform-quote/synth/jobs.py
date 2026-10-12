"""rollform-quote 팩 합성 생성기 — 롤포밍 가공 작업(개당 가공 분) (contracts/pack-contract.md §4 · §6).

원천 `api/ml_service.py:43-58 demo_jobs()` 이관 (migration/source_inventory.md §10.2).
같은 시드 · 같은 길이 · 같은 순서의 범주 목록에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서는 그대로다.

이름 대응(원천 → 팩): job_id → entity_id · length → part_length_mm · width → blank_width_mm · thickness → sheet_thickness_mm ·
holes → hole_count · slots → slot_count · bends → bend_count · material → steel_grade · profile → section_profile ·
minutes → machining_minutes. 원천 이름(length · width · material …)은 코어 · 계약 단어와 겹쳐 쓰지 않는다(G-M01 · D2-31 ②).
범주 값(재질 3 · 형상 4)은 회사 값이라 `categories` 인자로만 받는다. 원천 합성식의 범주 효과는 목록 위치에 묶여 있다
(재질 계수 1 · 1.06 · 1.4, 형상 가산 .2 · .5 · .8 · .3 — 회사 목록 순서 = 원천 목록 순서).
원천에는 시각 열이 없다 — 표준은 `ts` 를 비워 둔다(NaT). 행 순서를 시간으로 꾸미지 않는다(D2-21).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 900
DEFAULT_SEED = 42
TARGETS = ("machining_minutes",)

# 합성 메커니즘의 균등 분포 구간 — 원천 FEATURE_META 의 min/max, 원천 dict 순서 그대로(난수 호출 순서).
_UNIFORM: tuple[tuple[str, float, float], ...] = (
    ("part_length_mm", 100, 6000),
    ("blank_width_mm", 30, 600),
    ("sheet_thickness_mm", .5, 6),
    ("hole_count", 0, 100),
    ("slot_count", 0, 50),
    ("bend_count", 0, 12),
)
_INTEGER = ("hole_count", "slot_count", "bend_count")
NEUTRAL_CATEGORIES: dict[str, list[str]] = {
    "steel_grade": ["M1", "M2", "M3"],
    "section_profile": ["P1", "P2", "P3", "P4"],
}
_GRADE_FACTOR = (1, 1.06, 1.4)              # 원천 :50 — 재질 목록 위치별 가공 계수
_PROFILE_SHIFT = (.2, .5, .8, .3)           # 원천 :51 — 형상 목록 위치별 가산
_MISSING_POOL, _MISSING_N = 540, 12          # 원천 :57 — 앞 540 행에서 전개 폭 12 개


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts(NaT) · 변수 8 · 목표 machining_minutes."""
    cats = {**NEUTRAL_CATEGORIES, **{k: list(v) for k, v in (categories or {}).items() if k in NEUTRAL_CATEGORIES}}
    for k, n in (("steel_grade", len(_GRADE_FACTOR)), ("section_profile", len(_PROFILE_SHIFT))):
        if len(cats[k]) != n:
            raise ValueError(f"{k} 범주는 {n}개(원천 목록 위치에 합성 효과가 묶여 있다) — 있음 {len(cats[k])}")
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, lo, hi in _UNIFORM})
    for k in _INTEGER:
        frame[k] = frame[k].round().astype(int)
    frame["steel_grade"] = rng.choice(cats["steel_grade"], rows)
    frame["section_profile"] = rng.choice(cats["section_profile"], rows)
    factor = frame.steel_grade.map(dict(zip(cats["steel_grade"], _GRADE_FACTOR)))
    shape = frame.section_profile.map(dict(zip(cats["section_profile"], _PROFILE_SHIFT)))
    # 가정한 가공시간 메커니즘(원천 주석 그대로: 실측 · 공학식 아님)
    frame["machining_minutes"] = ((.3 + frame.part_length_mm / 2200 + frame.blank_width_mm / 1400 + frame.hole_count * .028
                                   + frame.slot_count * .095 + frame.bend_count * .16 + frame.sheet_thickness_mm ** 1.45 * .12
                                   + shape) * factor + rng.normal(0, .16, rows))
    frame.insert(0, "entity_id", [f"DEMO-{i + 1:04d}" for i in range(rows)])
    frame.insert(1, "ts", pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, Asia/Seoul]"))
    frame.loc[rng.choice(min(_MISSING_POOL, rows), min(_MISSING_N, rows), replace=False), "blank_width_mm"] = np.nan
    return frame
