"""정비 비용지수 — 순수 함수 (spec §8.1 · M3). 원천 식: migration/source_inventory.md §1.5.

cost = base + max(0, urgent_window - t) × urgent_hour + max(0, t - wear_ratio × L) × wear_hour
t = stop_after_hours(결정 변수), L = remaining_hours(의존 과제 예측). 상대 지수이며 원화가 아니다.
계수는 params 로 받고, 없으면 원천 데모 가정값을 쓴다. 검증되지 않은 가정이다.
"""

DEFAULTS = {"base": 60.0, "urgent_hour": 4.0, "wear_hour": 6.0, "urgent_window": 24.0, "wear_ratio": 0.6}


def cost(row: dict, params: dict) -> float:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if k in DEFAULTS}}
    t = float(row["stop_after_hours"])
    life = float(row["remaining_hours"])
    return (p["base"] + max(0.0, p["urgent_window"] - t) * p["urgent_hour"]
            + max(0.0, t - life * p["wear_ratio"]) * p["wear_hour"])
