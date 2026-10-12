"""배합 원재료 비용지수 — 순수 함수 (spec §8.1). 원천 식: migration/source_inventory.md §8.5 (`ml_service.py:28,134`).

cost_index = Σ 조성 % × 단가 / 100 (주석 · 은 · 구리 · 안티몬 · 플럭스). 상대 지수이며 원화가 아니다.
단가는 params `price_<변수>` 로 받고, 없으면 원천 데모 가정값을 쓴다. 검증되지 않은 가정이다.
row 에는 조절 변수 · derived(주석 = 100 − 나머지) 값이 함께 들어온다.
"""

DEFAULTS = {"sn_pct": 31.0, "ag_pct": 1220.0, "cu_pct": 14.0, "sb_pct": 22.0, "flux_pct": 85.0}


def cost(row: dict, params: dict) -> float:
    p = params or {}
    return sum(float(row[k]) * float(p.get(f"price_{k}", v)) / 100 for k, v in DEFAULTS.items())
