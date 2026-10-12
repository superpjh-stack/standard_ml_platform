"""textile 팩 합성 생성기 — 독립 합성 인쇄 LOT 스냅숏 (contracts/pack-contract.md §4).

원천 `api/ml_service.py:22-57` (`true_delta_e` · `demo_data()`) 이관 (migration/source_inventory.md §2.2).
같은 시드에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서 · 반올림은 그대로다.

이름 대응(원천 → 팩):  lot_id → entity_id · recorded_at → ts. 변수 · 목표 이름은 원천과 같다.
원천의 설비 코드 열(방식 → 설비 대응, 난수 소비 없음)은 회사 값이라 만들지 않는다(회사 등록부 compat).
엔티티 접두어는 팩 중립 `DEMO-`.

이 모듈을 쓰는 과제: delta_e(목표 delta_e) · defect_risk(목표 defect) · print_ood(목표 없음).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 720
DEFAULT_SEED = 42

# 합성 메커니즘의 균등 분포 구간 — 원천 config.py:9-20 (조절 5 + 원단 2), dict 순서 그대로(난수 호출 순서).
_UNIFORM: tuple[tuple[str, float, float], ...] = (
    ("set_temp", 140, 210),
    ("set_pressure", 2, 6),
    ("line_speed", 6, 24),
    ("ink_usage", 10, 30),
    ("dwell_time", 20, 80),
    ("absorb_rate", 60, 98),
    ("fabric_strength", 220, 480),
)
_PRINT_TYPES = ["나염", "승화", "DTF"]                    # 원천 config.py:5 (업종 범주 — features.yaml values)
_PRINT_P = [.45, .35, .2]                                 # 원천 ml_service.py:42
_COLOR_TONES = ["연한 색상", "중간 색상", "진한 색상"]      # 원천 config.py:8
# 합성 메커니즘의 방식별 최적값 — 원천 ml_service.py:23-25 (작업표준이 아니다)
_OPT_TEMP = {"나염": 160, "승화": 195, "DTF": 165}
_OPT_PRESSURE = {"나염": 3.5, "승화": 4.5, "DTF": 4.0}
_OPT_INK = {"연한 색상": 14, "중간 색상": 19, "진한 색상": 25}
_MISSING = ("absorb_rate", "fabric_strength", "ink_usage")   # 원천 :52-53 — 각 8행, 이 순서
_MISSING_PER_COL = 8
_T0 = "2026-08-01 08:00"                                     # 원천 :51 — 1시간 간격, +09:00
TARGETS = ("delta_e", "defect")


def true_delta_e(d: pd.DataFrame) -> pd.Series:
    """원천 :29-36 그대로 — 잡음 없는 합성 ΔE."""
    temp = ((d.set_temp - d.print_type.map(_OPT_TEMP)) / 24) ** 2 * .75
    pressure = ((d.set_pressure - d.print_type.map(_OPT_PRESSURE)) / 1.6) ** 2 * .35
    cure = (np.maximum(0, d.line_speed - 12) * .07 + np.maximum(0, 45 - d.dwell_time) * .025
            + np.maximum(0, d.line_speed - 12) * np.maximum(0, 45 - d.dwell_time) * .006)
    ink = abs(d.ink_usage - d.color_tone.map(_OPT_INK)) * .08
    bleed = np.where(d.print_type == "나염", np.maximum(0, d.absorb_rate - 85) * .07, 0) + np.maximum(0, 72 - d.absorb_rate) * .045
    fabric = np.maximum(0, 300 - d.fabric_strength) * .005
    return .8 + temp + pressure + cure + ink + bleed + fabric


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts · 변수 9 · 목표 2 (delta_e · defect).

    `categories` 는 시그니처 통일용(이 팩 범주는 features.yaml values 고정이라 쓰지 않는다)."""
    rng = np.random.default_rng(seed)
    data = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, lo, hi in _UNIFORM})
    data["print_type"] = rng.choice(_PRINT_TYPES, rows, p=_PRINT_P)
    data["color_tone"] = rng.choice(_COLOR_TONES, rows)
    data["delta_e"] = np.clip(true_delta_e(data) + rng.normal(0, .35, rows), .2, 12)
    p = 1 / (1 + np.exp(np.clip(-(data["delta_e"] - 3.8) / .45, -30, 30)))
    data["defect"] = rng.binomial(1, p)
    data["entity_id"] = [f"DEMO-{i + 1:04d}" for i in range(rows)]
    data["ts"] = pd.date_range(_T0, periods=rows, freq="h", tz="Asia/Seoul")
    for k in _MISSING:
        data.loc[rng.choice(rows, _MISSING_PER_COL, replace=False), k] = np.nan
    for k, _, _ in _UNIFORM:
        data[k] = data[k].round(2)
    data["delta_e"] = data["delta_e"].round(3)
    return data
