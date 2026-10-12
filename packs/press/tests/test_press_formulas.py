"""press 비용식 이관 시험 (M3). 기대값은 원천 식을 손으로 계산한 값이다(원천 코드는 실행하지 않는다).

원천 식: cost = 60 + max(0, 24 - t) × 4 + max(0, t - 0.6 L) × 6 (migration/source_inventory.md §1.5).
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

PACK = Path(__file__).resolve().parents[1]


def _cost():
    spec = importlib.util.spec_from_file_location("press_maintenance_cost", PACK / "formulas" / "maintenance_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


@pytest.mark.parametrize("t,life,expected", [
    (0.0, 100.0, 156.0),      # 60 + 24×4
    (10.0, 100.0, 116.0),     # 60 + 14×4
    (24.0, 100.0, 60.0),      # 긴급 구간 끝 · 마모 구간 전
    (30.0, 40.0, 96.0),       # 60 + (30 - 24)×6
    (48.0, 50.0, 168.0),      # 60 + (48 - 30)×6
    (0.5, 0.0, 157.0),        # 60 + 23.5×4 + 0.5×6
])
def test_maintenance_cost_matches_source_formula(t, life, expected):
    assert _cost()({"stop_after_hours": t, "remaining_hours": life}, {}) == pytest.approx(expected, abs=1e-12)


def test_request_params_do_not_change_coefficients():
    """요청 제약값(reserve_hours 등)은 비용 계수가 아니다 — 같은 값이 나와야 한다."""
    row = {"stop_after_hours": 10.0, "remaining_hours": 100.0}
    assert _cost()(row, {"reserve_hours": 12, "max_delay_hours": 48, "max_cost_index": 140}) == _cost()(row, {})


def test_task_points_at_formula_and_decision_var():
    task = yaml.safe_load((PACK / "tasks" / "maintenance_timing.yaml").read_text(encoding="utf-8"))
    assert task["formulas"] == {"maintenance_cost": "maintenance_cost"}
    assert (PACK / "formulas" / "maintenance_cost.py").is_file()
    dv = task["decision_vars"]["stop_after_hours"]
    # 원천 공간: t ∈ [0, max_delay_hours] · 0.5h → max_delay 48 이면 97점 (원천 시험 — migration/source_inventory.md §1.5)
    assert dv["min"] == 0 and dv["step"] == 0.5 and dv["max_param"] == "max_delay_hours"
    assert int((task["params"]["max_delay_hours"]["default"] - dv["min"]) / dv["step"]) + 1 == 97
    p = task["params"]
    assert (p["reserve_hours"]["min"], p["reserve_hours"]["max"]) == (1, 150)
    assert (p["max_delay_hours"]["min"], p["max_delay_hours"]["max"]) == (0, 72)
    assert (p["max_cost_index"]["min"], p["max_cost_index"]["max"]) == (1, 500)
    assert task["objective"] == {"minimize": "maintenance_cost", "tiebreak": [{"maximize": "stop_after_hours"}]}
