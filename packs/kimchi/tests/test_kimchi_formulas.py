"""kimchi 비용식 이관 시험 (M3). 기대값은 원천 식을 손으로 계산한 값이다(원천 코드는 실행하지 않는다).

원천 식: migration/source_inventory.md §9.5 — Σ 배합 % × 단가 (배추 .55 · 무 .32 · 양념 1.55 · 소금 .12).
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

PACK = Path(__file__).resolve().parents[1]


def _cost():
    spec = importlib.util.spec_from_file_location("kimchi_material_cost", PACK / "formulas" / "material_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


def test_cost_hand_calc_and_price_param():
    row = {"cabbage_pct": 71.0, "radish_pct": 7.0, "seasoning_pct": 20.0, "salt_pct": 2.0}
    assert _cost()(row, {}) == pytest.approx(71.0 * .55 + 7.0 * .32 + 20.0 * 1.55 + 2.0 * .12)
    first = next(iter(row))
    assert _cost()(row, {f"price_{first}": 0}) < _cost()(row, {})


def test_task_objective_uses_formula():
    t = yaml.safe_load((PACK / "tasks" / "recipe_optimize.yaml").read_text(encoding="utf-8"))
    assert t["formulas"] == {"material_cost_index": "material_cost"} and t["objective"]["minimize"] == "material_cost_index"
