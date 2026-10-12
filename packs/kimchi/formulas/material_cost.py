"""배합 원재료비 지수 — 순수 함수 (spec §8.1). 원천 식: migration/source_inventory.md §9.5 (`ml_service.py:32,97`).

material_cost = Σ 배합 % × 단가 (배추 · 무 · 양념 · 소금). 상대 지수이며 원화가 아니다.
단가는 params `price_<변수>` 로 받고, 없으면 원천 데모 가정값을 쓴다(원천 주석: "실제 구매단가로 교체해야 합니다").
row 에는 조절 변수 · derived(양념 = 100 − 나머지) 값이 함께 들어온다.
"""

DEFAULTS = {"cabbage_pct": 0.55, "radish_pct": 0.32, "seasoning_pct": 1.55, "salt_pct": 0.12}


def cost(row: dict, params: dict) -> float:
    p = params or {}
    return sum(float(row[k]) * float(p.get(f"price_{k}", v)) for k, v in DEFAULTS.items())
