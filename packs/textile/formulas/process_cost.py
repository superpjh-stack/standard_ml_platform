"""인쇄 공정 비용지수 — 순수 함수 (spec §8.1 · M3). 원천 식: migration/source_inventory.md §2.5.

cost = ink_usage × ink + time / line_speed + max(0, set_temp - heat_base) × heat + dwell_time × dwell
상대 지수이며 원화가 아니다. 원천은 소수 2자리로 반올림한다(호환 라우터가 재현).
"""

DEFAULTS = {"ink": 2.0, "time": 360.0, "heat": 0.25, "heat_base": 140.0, "dwell": 0.15}


def cost(row: dict, params: dict) -> float:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if k in DEFAULTS}}
    return (float(row["ink_usage"]) * p["ink"] + p["time"] / float(row["line_speed"])
            + max(0.0, float(row["set_temp"]) - p["heat_base"]) * p["heat"] + float(row["dwell_time"]) * p["dwell"])
