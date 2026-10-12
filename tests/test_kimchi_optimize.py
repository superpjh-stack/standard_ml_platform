"""팩 kimchi `recipe_optimize` — 배합 · 숙성 무작위 탐색(수락 3,500 · 양념 = 100 − 나머지 · 위반 /3 · /5 가중 · 위반 순위). 개발1 (웨이브 A2).

원천 `../PyoungChang ML AI/api/ml_service.py:90-106` 은 **읽기만** 했다. 기대값은 최적화 코드를 쓰지 않고 다시 계산한다
(배합 등식 · 원재료비 지수 Σ pct × 단가 · 위반량 max(0, 목표 − 예측)/3 + max(0, 비용 − 상한)/5).
회사 등록부 `tenants/pc.yaml` 은 개발3 소유 — `pc.recipe_optimize` 를 켜기 전이므로 시험은 그 파일을 복사한 임시 회사에서 과제를 켠다.
"""

from __future__ import annotations

import importlib.util
import re
import secrets

import pytest

import _dev2 as h
from mlcore.registry import packs, tenants

pytestmark = [pytest.mark.gate("G-M13"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

COMPOSITION = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]
PRICE = {"cabbage_pct": 0.55, "radish_pct": 0.32, "seasoning_pct": 1.55, "salt_pct": 0.12}     # 원천 COST :32


def test_pack_has_recipe_optimize_with_source_shape():
    p = packs.load_pack("kimchi")
    t = p.tasks["recipe_optimize"]
    assert t["type"] == "optimize" and t["uses"] == ["kimchi.sensory_score"]
    assert t["search"] == {"strategy": "random", "max_points": 3500}
    assert t["derived"] == {"seasoning_pct": "100 - cabbage_pct - radish_pct - salt_pct"}
    assert {c["name"]: c.get("scale") for c in t["constraints"]} == {"target_score": 3, "max_material_cost": 5}
    assert sorted(t["fixed"]) == ["cabbage_origin", "prod_line"]
    rules = p.tasks["sensory_score"].get("input_rules") or []
    assert rules and rules[0]["between"] == [98, 102]                       # 원천 main.py:20


def test_material_cost_formula_hand_calc():
    spec = importlib.util.spec_from_file_location("kimchi_cost", packs.PACKS_DIR / "kimchi" / "formulas" / "material_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    row = {"cabbage_pct": 71.0, "radish_pct": 8.0, "seasoning_pct": 19.1, "salt_pct": 1.9, "brining_hours": 12}
    assert mod.cost(row, {}) == pytest.approx(sum(row[k] * PRICE[k] for k in COMPOSITION))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from mlcore.db.conn import connect
    from mlcore.serve.catalog import TaskCatalog
    tmp = tmp_path_factory.mktemp("kimchi-opt")
    code = "t" + secrets.token_hex(3)
    text = (packs.PACKS_DIR.parent / "tenants" / "pc.yaml").read_text(encoding="utf-8")
    text = re.sub(r"^code: pc\b", f"code: {code}", text, flags=re.M)
    text = re.sub(r"(?<![A-Za-z0-9_])pc\.(?=[a-z])", f"{code}.", text)
    line = re.search(r"^  enable: \[([^\]]*)\]", text, re.M)
    if f"{code}.recipe_optimize" not in line.group(1):
        text = text[:line.end(1)] + f", {code}.recipe_optimize" + text[line.end(1):]
    base = tmp / f"tenants-{code}"
    base.mkdir()
    (base / f"{code}.yaml").write_text(text, encoding="utf-8")
    m = tenants.load_and_merge(code, tenants_base=base)
    assert f"{code}.recipe_optimize" in m.tasks
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)", (code, "김치 시험", "kimchi", "demo"))
        for task_id, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                      "VALUES (%s,%s,%s,%s,%s,%s)", (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    ref, res = h.real_production(m, f"{code}.sensory_score")
    cats = m.tenant.config["categories"]
    return m, TaskCatalog(m), ref, {"cabbage_origin": cats["cabbage_origin"][0], "prod_line": cats["prod_line"][1]}


def _run(world, params):
    from mlcore.tasks.optimize import Optimizer, OptimizeRequest
    m, cat, ref, fixed = world
    code = m.tenant.code
    return Optimizer(cat).optimize(code, f"{code}.recipe_optimize", OptimizeRequest(fixed=fixed, params=params), caller="t")


def test_accepts_3500_balanced_recipes_in_range(world):
    m, cat, ref, fixed = world
    out = _run(world, {"target_score": 80, "max_material_cost": 85})          # 원천 시험 요청(tests/test_api.py:18)
    rec = out["recommendation"]
    assert rec["strategy"] == "random" and rec["n_candidates"] == 3500 and rec["in_train_range_rate"] == 1.0
    lock = h.lock_of(ref)["features"]["seasoning_pct"]
    for c in rec["candidates"]:
        x = c["conditions"]
        assert sum(x[k] for k in COMPOSITION) == pytest.approx(100.0)
        assert max(8, lock["p1"]) - 1e-9 <= x["seasoning_pct"] <= min(35, lock["p99"]) + 1e-9
        assert c["objective_value"] == pytest.approx(sum(x[k] * PRICE[k] for k in COMPOSITION), rel=1e-9)


def test_infeasible_ranks_by_weighted_violation(world):
    out = _run(world, {"target_score": 95, "max_material_cost": 45})          # 원천 경계 최댓값 · 최솟값 — 충족 불가
    rec = out["recommendation"]
    assert not rec["feasible"] and out["status"] == "review"
    vs = []
    for c in rec["candidates"]:
        pred = c["predictions"]["sensory_score"]
        x = c["conditions"]
        cost = sum(x[k] * PRICE[k] for k in COMPOSITION)
        hand = max(0.0, 95 - pred) / 3 + max(0.0, cost - 45) / 5               # 원천 :98
        assert c["violation"] == pytest.approx(hand, abs=1e-5)
        vs.append(hand)
    assert vs == sorted(vs)
