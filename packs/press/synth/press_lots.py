"""press 팩 합성 생성기 — 독립 합성 LOT 스냅숏 (contracts/pack-contract.md §4).

원천 `api/ml_service.py:20-38 demo_data()` 이관 (migration/source_inventory.md §1.2).
같은 시드 · 같은 범주 목록에서 원천과 **행 일치 100%** — 이름만 표준으로 바꾸고 값 · 순서 · 난수 호출 순서는 그대로다.

이름 대응(원천 → 팩):  machine → machine_code · product → product_type · lot_id → entity_id · recorded_at → ts
엔티티 접두어는 팩 중립 `DEMO-` (원천 접두어는 회사 등록부 compat.entity_prefix 가 호환 라우터에서 붙인다).
범주 값은 회사 값이므로 생성기에 두지 않는다 — `categories` 인자(회사 등록부 `categories`)로 받는다.
`rng.choice(list, n)` 은 목록 길이로만 난수를 뽑으므로, 같은 길이 · 같은 순서의 목록이면 같은 행이 나온다.

이 모듈을 쓰는 과제: remaining_hours(목표 remaining_hours) · failure_24h(목표 failure_24h) · sensor_ood(목표 없음).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 720
DEFAULT_SEED = 42

# 합성 메커니즘의 균등 분포 구간 — 원천 config.py:7-13 의 min/max, 원천 dict 순서 그대로(난수 호출 순서).
# 이 값은 입력 검증 범위(features.yaml)와 별개인 "합성 생성 규칙"이다. 바꾸면 행 일치가 깨진다.
_UNIFORM: tuple[tuple[str, float, float], ...] = (
    ("press_force", 180, 320),
    ("vibration", 0.4, 8),
    ("motor_current", 30, 85),
    ("equip_temp", 30, 85),
    ("mold_temp", 25, 70),
    ("cycle_time", 6, 15),
    ("shot_count", 5000, 180000),
)
# 팩 중립 범주 자리표시(회사 등록부가 없을 때). 원천과 같은 길이(4 · 3)라 난수 소비가 같다.
NEUTRAL_CATEGORIES: dict[str, list[str]] = {
    "machine_code": ["M1", "M2", "M3", "M4"],
    "product_type": ["P1", "P2", "P3"],
}
_MISSING = ("vibration", "motor_current", "mold_temp")   # 원천 :36-37 — 각 8행, 이 순서
_MISSING_PER_COL = 8
_T0 = "2026-08-01 00:00"                                 # 원천 :35 — 1시간 간격, +09:00
TARGETS = ("remaining_hours", "failure_24h")


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts · 변수 9 · 목표 2 (remaining_hours · failure_24h)."""
    cats = {**NEUTRAL_CATEGORIES, **{k: list(v) for k, v in (categories or {}).items() if k in NEUTRAL_CATEGORIES}}
    rng = np.random.default_rng(seed)
    data = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, lo, hi in _UNIFORM})
    data["shot_count"] = data.shot_count.round().astype(int)
    data["machine_code"] = rng.choice(cats["machine_code"], rows)
    data["product_type"] = rng.choice(cats["product_type"], rows)
    wear = (data.shot_count / 180000 * 55 + data.vibration ** 1.35 * 3 +
            np.maximum(data.equip_temp - 50, 0) * .65 + abs(data.press_force - 250) * .12 +
            np.maximum(data.motor_current - 60, 0) * .5 + np.maximum(data.mold_temp - 50, 0) * .2)
    data["remaining_hours"] = np.clip(155 - wear + rng.normal(0, 5, rows), 1, 180)
    p = 1 / (1 + np.exp(np.clip((data["remaining_hours"] - 40) / 13, -30, 30)))
    data["failure_24h"] = rng.binomial(1, p)
    data["entity_id"] = [f"DEMO-{i + 1:04d}" for i in range(rows)]
    data["ts"] = pd.date_range(_T0, periods=rows, freq="h", tz="Asia/Seoul")
    for k in _MISSING:
        data.loc[rng.choice(rows, _MISSING_PER_COL, replace=False), k] = np.nan
    return data
