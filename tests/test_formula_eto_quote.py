"""팩 eto 견적식 — Decimal · ROUND_HALF_UP 이고 원천 저장 견적과 원 단위 일치 (G2-Q01 일부 · D2-07 · D2-07a).

기대값 = 원천 앱이 저장한 견적 2건 `tests/fixtures/kd/source_quotes.json`(migration/source_expected.py, 원천 SQLite 읽기 전용).
원천 식은 float + Python round(짝수 반올림). 표준은 Decimal · HALF_UP — 두 견적은 .5 경계에서도 같은 값이 나온다
(1.0275 h × 45,000 = 46,237.5 → 짝수 · HALF_UP 모두 46,238 · 가산 1,006,303.5 → 둘 다 1,006,304). 갈리는 경우는 아래 손 계산 사례.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.gate("G2-Q01")]

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "packs" / "eto" / "formulas" / "quote.py"
QUOTES = json.loads((ROOT / "tests" / "fixtures" / "kd" / "source_quotes.json").read_text(encoding="utf-8"))["rows"]
COST_KEYS = {"material": "material_cost", "labor": "labor_cost", "outsource": "outsource_cost", "markup": "markup_cost",
             "subtotal": "subtotal", "vat": "vat"}


def _mod():
    spec = importlib.util.spec_from_file_location("eto_quote_formula", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q = _mod()


def dec(obj):
    """JSON 을 코어처럼 Decimal 로 다시 읽는다(json.loads(parse_float=Decimal) — float 를 거치지 않는다)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def rates_from_snapshot(snap: dict) -> dict:
    return {k: Decimal(str(v)) for k, v in snap.items()}


@pytest.mark.parametrize("row", QUOTES, ids=[r["ref"] for r in QUOTES])
def test_matches_source_quote_to_the_won(row):
    inp = dec(row["input"])
    hours = dec({"h": row["hours_per_unit"]})["h"]
    out = Q.quote(inp, inp["bom"], {"labor_hours": hours}, rates_from_snapshot(row["cost_snapshot"]))
    for ours, theirs in COST_KEYS.items():
        assert out["costs"][ours] == Decimal(row[theirs]), (ours, out["costs"][ours], row[theirs])
    assert out["total"] == Decimal(row["total"])
    assert [ln["amount"] for ln in out["lines"]] == [Decimal(ln["cost"]) for ln in row["lines"]]
    assert [ln["weight_total"] for ln in out["lines"]] == [dec({"w": ln["weight_total"]})["w"] for ln in row["lines"]]
    assert all(isinstance(v, Decimal) and v == v.to_integral_value() for v in [*out["costs"].values(), out["total"]])
    assert out["predicted"]["labor_hours"] == hours                 # 원천 hours_per_unit(소수 4자리) 그대로


def test_prepare_total_mass_matches_source_feature():
    for row in QUOTES:
        inp = dec(row["input"])
        assert Q.prepare(inp, inp["bom"])["total_mass_kg"] == Decimal(str(row["mass_kg"])) == Decimal("650")


def test_sample_8486493_from_docs():
    """원천 docs/verification.md:29 — 샘플 1대 58.146 h · 합계 8,486,493 원."""
    (row,) = [r for r in QUOTES if r["total"] == 8486493]
    assert row["hours_per_unit"] == 58.146


@pytest.mark.parametrize("hours, half_up, half_even", [
    ("1.00005", "1.0001", "1.0000"),     # 공수 4자리 반올림이 .5 경계 — 원천 round(…, 4) 는 짝수 쪽(D2-07a)
    ("2.00015", "2.0002", "2.0002"),
])
def test_hours_rounding_is_half_up(hours, half_up, half_even):
    out = Q.quote({"quantity": 1, "labor_rate": Decimal("1"), "outsource_cost": Decimal("0")}, [],
                  {"labor_hours": Decimal(hours)}, {"scrap_rate": Decimal("0.08"), "markup": Decimal("0"), "vat_rate": Decimal("0"),
                                                    "labor_per_hour": Decimal("1")})
    assert out["predicted"]["labor_hours"] == Decimal(half_up)


def test_half_won_rounds_up_where_source_rounds_even():
    """vat = 25 × 0.10 = 2.5 → HALF_UP 3 (원천 round(2.5) = 2). 이런 행은 대조표에 D2-07a 사유로 남는다."""
    out = Q.quote({"quantity": 1, "labor_rate": Decimal("25"), "outsource_cost": Decimal("0")}, [],
                  {"labor_hours": Decimal("1")}, {"scrap_rate": Decimal("0"), "markup": Decimal("0"), "vat_rate": Decimal("0.10"),
                                                  "labor_per_hour": Decimal("0")})
    assert out["costs"]["vat"] == Decimal("3") and round(25 * 0.10) == 2


def test_labor_rate_defaults_to_rates_and_quantity_multiplies():
    out = Q.quote({"quantity": 2, "outsource_cost": Decimal("100000")},
                  [{"name": "S", "material": "M1", "quantity": 1, "mass_kg": Decimal("10"), "price_kg": Decimal("1000")}],
                  {"labor_hours": Decimal("1.5")},
                  {"scrap_rate": Decimal("0.08"), "markup": Decimal("0.15"), "vat_rate": Decimal("0.1"), "labor_per_hour": Decimal("45000")})
    assert out["costs"]["material"] == Decimal("21600")          # 10 × 1000 × 1.08 × 2
    assert out["costs"]["labor"] == Decimal("135000")            # 1.5 × 45000 × 2
    assert out["costs"]["outsource"] == Decimal("200000")        # 원천 시험 :46 outsource × 대수
    assert out["total"] == out["costs"]["subtotal"] + out["costs"]["vat"]


def test_static_no_float_path():
    """gates/check_decimal.py 와 같은 검사(F1~F7) — 이 파일 단독."""
    import sys
    sys.path.insert(0, str(ROOT / "gates"))
    from check_decimal import scan                                     # noqa: E402
    assert scan(PATH) == []
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)]


def test_rates_in_registry_are_decimal_strings():
    """원천 COST(:16) 계수는 과제 rates 로 옮길 때 문자열 — 팩 과제 quote 가 생기면 그 rates 를 읽는다(D2-31)."""
    for row in QUOTES:
        snap = row["cost_snapshot"]
        assert snap == {"labor_per_hour": 45000.0, "scrap_rate": 0.08, "markup": 0.15, "vat_rate": 0.1}
    tasks = list((ROOT / "packs" / "eto" / "tasks").glob("*.yaml"))
    for t in tasks:
        raw = yaml.safe_load(t.read_text(encoding="utf-8"))
        for v in (raw.get("rates") or {}).values():
            assert isinstance(v, str)
