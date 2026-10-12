"""solder 비용식 이관 시험 (M3). 기대값은 원천 식을 손으로 계산한 값이다(원천 코드는 실행하지 않는다).

원천 식: migration/source_inventory.md §8.5 — Σ 조성 % × 단가 / 100 (주석 31 · 은 1220 · 구리 14 · 안티몬 22 · 플럭스 85).
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

PACK = Path(__file__).resolve().parents[1]


def _cost():
    spec = importlib.util.spec_from_file_location("solder_material_cost", PACK / "formulas" / "material_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


def test_cost_hand_calc_and_price_param():
    row = {"sn_pct": 96.0, "ag_pct": 2.5, "cu_pct": 0.6, "sb_pct": 0.5, "flux_pct": 0.4}
    assert _cost()(row, {}) == pytest.approx(96.0 * 31 / 100 + 2.5 * 1220 / 100 + 0.6 * 14 / 100 + 0.5 * 22 / 100 + 0.4 * 85 / 100)
    first = next(iter(row))
    assert _cost()(row, {f"price_{first}": 0}) < _cost()(row, {})


def test_task_objective_uses_formula():
    t = yaml.safe_load((PACK / "tasks" / "recipe_optimize.yaml").read_text(encoding="utf-8"))
    assert t["formulas"] == {"cost_index": "material_cost"} and t["objective"]["minimize"] == "cost_index"
