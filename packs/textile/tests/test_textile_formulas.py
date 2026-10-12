"""textile 비용식 이관 시험 (M3). 기대값은 원천 식을 손으로 계산한 값이다(원천 코드는 실행하지 않는다).

원천 식: cost = ink × 2.0 + 360 / line_speed + max(0, temp - 140) × 0.25 + dwell × 0.15 (source_inventory.md §2.5).
원천은 소수 2자리로 반올림한다 — 반올림은 호환 라우터 몫이고 팩 식은 반올림하지 않는다.
"""
import importlib.util
import itertools
from pathlib import Path

import pytest
import yaml

PACK = Path(__file__).resolve().parents[1]


def _cost():
    spec = importlib.util.spec_from_file_location("textile_process_cost", PACK / "formulas" / "process_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


@pytest.mark.parametrize("ink,speed,temp,dwell,expected", [
    (18, 14, 175, 50, 36 + 360 / 14 + 35 * 0.25 + 7.5),     # 기본 조건 → 77.964…(원천 표시 77.96)
    (10, 24, 140, 20, 20 + 15 + 0 + 3),                     # 가열 기준 이하 → 열 항 0
    (30, 6, 210, 80, 60 + 60 + 17.5 + 12),
    (22, 12, 130, 35, 44 + 30 + 0 + 5.25),
])
def test_process_cost_matches_source_formula(ink, speed, temp, dwell, expected):
    row = {"ink_usage": ink, "line_speed": speed, "set_temp": temp, "dwell_time": dwell, "set_pressure": 4}
    assert _cost()(row, {}) == pytest.approx(expected, abs=1e-12)


def test_source_display_rounding():
    row = {"ink_usage": 18, "line_speed": 14, "set_temp": 175, "dwell_time": 50}
    assert round(_cost()(row, {}), 2) == 77.96


def test_task_space_is_source_grid_before_training_range():
    """원천 전수 격자 8 × 5 × 7 × 6 × 5 = 8,400 (원천 시험 — migration/source_inventory.md §2.5). 표준은 학습 범위와 교차해 줄어든다(D-31)."""
    feats = yaml.safe_load((PACK / "features.yaml").read_text(encoding="utf-8"))
    task = yaml.safe_load((PACK / "tasks" / "print_setpoint.yaml").read_text(encoding="utf-8"))
    sizes = [int(round((feats[c]["max"] - feats[c]["min"]) / feats[c]["step"])) + 1 for c in task["controls"]]
    assert sizes == [8, 5, 7, 6, 5] and len(list(itertools.product(*[range(n) for n in sizes]))) == 8400
    assert task["uses"] == ["textile.delta_e", "textile.defect_risk"]
    assert task["formulas"] == {"process_cost": "process_cost"}
    assert task["objective"] == {"minimize": "process_cost", "tiebreak": [{"minimize": "delta_e"}]}
    p = task["params"]
    assert (p["max_delta_e"]["min"], p["max_delta_e"]["max"], p["max_delta_e"]["default"]) == (0.5, 8, 2.5)
    assert (p["max_risk"]["min"], p["max_risk"]["max"], p["max_risk"]["default"]) == (0.01, 0.9, 0.2)
    assert (p["min_line_speed"]["min"], p["min_line_speed"]["max"], p["min_line_speed"]["default"]) == (6, 24, 12)
