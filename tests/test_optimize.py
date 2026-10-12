"""G-M13 — 최적화 (goal §2.2 · spec §8.1 · contracts/interfaces.md §8 · predict-contract §3). 소유 개발2.

`ks.maintenance_timing`(결정 변수 1차원 격자) · `sw.print_setpoint`(조절 변수 5차원 격자)를 **개발1 실제 학습기**로 만든
production 의존 모델 위에서 시험한다(시험마다 새 회사 코드 — tests/_dev2.py).

- 탐색점은 전부 학습 범위(p1~p99) ∩ min/max 안 · step 격자 위 (학습 범위 밖 점 0)
- 제약 충족 후보만 needs_approval, 불가능하면 least_violation + review (불가능 제약에서 충족 후보 0)
- 추천은 mlp_recommendation(needs_approval) + 승인 요청(kind=recommendation) — production 은 그대로
- 10,000점 ≤ 10초
기대값은 원천 저장소 규칙(정비: 0.5h 격자 · 비용 최소 · 동률이면 늦은 시점 / 인쇄: 비용 최소 · 동률이면 ΔE)과
의존 모델을 **직접** 불러 다시 계산한 값으로 본다(최적화 코드를 쓰지 않는다).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import math
import time

import jsonschema
import numpy as np
import pandas as pd
import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.registry.artifacts import load_artifacts
from mlcore.registry.models import ModelNotReady, Registry
from mlcore.serve.catalog import TaskCatalog
from mlcore.serve.errors import InvalidInput, MissingRequired, NotFound, OutOfBounds
from mlcore.tasks.optimize import Optimizer, OptimizeRequest

pytestmark = [pytest.mark.gate("G-M13"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

SCHEMA = jsonschema.Draft202012Validator(h.response_schema())


def _world(source: str, tmp):
    m = h.make_tenant(source, tmp)
    cat = TaskCatalog(m)
    opt_id = next(t for t, td in m.tasks.items() if td.type == "optimize")
    td = m.tasks[opt_id]
    uses = {}
    for pack_id in td.raw["uses"]:
        tid = next(t for t, d in m.tasks.items() if d.pack_id == pack_id)
        ref, _ = h.real_production(m, tid)
        uses[tid] = ref
    return m, cat, opt_id, uses


@pytest.fixture(scope="module")
def ks(tmp_path_factory):
    return _world("ks", tmp_path_factory.mktemp("opt-ks"))


@pytest.fixture(scope="module")
def sw(tmp_path_factory):
    return _world("sw", tmp_path_factory.mktemp("opt-sw"))


def _fixed(world) -> dict:
    m, cat, opt_id, uses = world
    names = m.tasks[opt_id].raw["fixed"]
    ref = next(iter(uses.values()))
    return h.mid_inputs(h.lock_of(ref), names)


def _direct(world, conditions: pd.DataFrame, fixed: dict) -> dict[str, np.ndarray]:
    """의존 production 모델을 직접 불러 예측(회귀 clip 포함) — 최적화 코드와 독립."""
    m, cat, opt_id, uses = world
    out = {}
    for tid, ref in uses.items():
        ld = load_artifacts(ref)
        order = ld.lock["order"]
        frame = pd.DataFrame({c: (conditions[c].to_numpy() if c in conditions else [fixed[c]] * len(conditions)) for c in order})
        if m.tasks[tid].type == "regression":
            v = np.asarray(ld.model.predict(frame), float)
            lo = (m.tasks[tid].raw.get("clip") or {}).get("min")
            out[tid.split(".", 1)[1]] = np.maximum(v, lo) if lo is not None else v
        else:
            cls = list(ld.model.classes_)
            out[tid.split(".", 1)[1]] = np.asarray(ld.model.predict_proba(frame), float)[:, cls.index(1)]
    return out


def _formula(m, module: str):
    path = m.pack.path / "formulas" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"_t_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


# ── ks — 1차원 (결정 변수 stop_after_hours, 0.5h 격자) ───────────────────────────────────────────
def test_ks_one_dimensional_grid_matches_source_rule(ks):
    m, cat, opt_id, uses = ks
    td = m.tasks[opt_id]
    fixed = _fixed(ks)
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed), caller="t")
    assert not list(SCHEMA.iter_errors(out))
    rec = out["recommendation"]
    assert out["type"] == "optimize" and out["model"] is None and out["prediction_id"] is None
    assert [u["task"] for u in out["uses"]] == list(uses) and out["uses"][0]["version"] == "v1"   # uses 의 production 버전
    (dv, spec_dv), = td.raw["decision_vars"].items()
    params = {k: float(v["default"]) for k, v in td.raw["params"].items()}
    hi = params[spec_dv["max_param"]]
    expected_points = int(round((hi - spec_dv["min"]) / spec_dv["step"])) + 1
    assert rec["strategy"] == "grid" and rec["n_candidates"] == expected_points == 97    # 원천 candidate_count 97 (48h)
    assert rec["in_train_range_rate"] == 1.0
    # 독립 재계산: 의존 모델 예측 → 비용식 → 제약 → (비용 ↑, 대기 ↓) 정렬
    life = _direct(ks, pd.DataFrame(index=[0]), fixed)[next(iter(uses)).split(".", 1)[1]][0]
    cost = _formula(m, td.raw["formulas"][td.raw["objective"]["minimize"]])
    rows = []
    for t in np.arange(spec_dv["min"], hi + 1e-9, spec_dv["step"]):
        c = cost({dv: t, next(iter(uses)).split(".", 1)[1]: life}, params)
        viol = max(0, params["reserve_hours"] - (life - t)) / max(params["reserve_hours"], 1e-9) + \
            max(0, c - params["max_cost_index"]) / max(params["max_cost_index"], 1e-9)
        rows.append((viol, c, -t))
    feas = sorted(r for r in rows if r[0] <= 1e-10)
    assert rec["feasible"] and rec["n_feasible"] == len(feas) and out["status"] == "needs_approval"
    got = [(c["violation"], c["objective_value"], -c["conditions"][dv]) for c in rec["candidates"]]
    assert len(got) == min(5, len(feas))
    assert np.allclose(got, feas[:len(got)], atol=1e-6)
    assert rec["best"] == rec["candidates"][0]
    for c in rec["candidates"]:
        assert spec_dv["min"] <= c["conditions"][dv] <= hi
        assert all(x["satisfied"] for x in c["constraints"]) and c["violation"] == 0


def test_ks_impossible_constraints_give_least_violation_review(ks):
    m, cat, opt_id, uses = ks
    td = m.tasks[opt_id]
    fixed = _fixed(ks)
    params = {"reserve_hours": 150, "max_cost_index": 1}                     # 원천 test_feasible_and_infeasible_schedules
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed, params=params), caller="t")
    assert not list(SCHEMA.iter_errors(out))
    rec = out["recommendation"]
    assert rec["feasible"] is False and rec["n_feasible"] == 0 and out["status"] == "review"
    assert rec["on_infeasible"] == "least_violation"
    assert {"infeasible", "constraint_unmet"} <= {w["code"] for w in out["warnings"]}
    assert all(c["violation"] > 0 and not all(x["satisfied"] for x in c["constraints"]) for c in rec["candidates"])
    ranked = [(c["violation"], c["objective_value"], -c["conditions"]["stop_after_hours"]) for c in rec["candidates"]]
    assert ranked == sorted(ranked)
    life = _direct(ks, pd.DataFrame(index=[0]), fixed)[next(iter(uses)).split(".", 1)[1]][0]
    allp = {k: float(v["default"]) for k, v in td.raw["params"].items()} | params
    cost = _formula(m, "maintenance_cost")
    brute = min((max(0, 150 - (life - t)) / 150 + max(0, cost({"stop_after_hours": t, "remaining_hours": life}, allp) - 1) / 1,
                 cost({"stop_after_hours": t, "remaining_hours": life}, allp), -t)
                for t in np.arange(0, allp["max_delay_hours"] + 1e-9, 0.5))
    assert np.allclose(ranked[0], brute, atol=1e-6)


# ── sw — 5차원 (조절 변수 5, 학습 범위 ∩ min/max · step) ─────────────────────────────────────────
def test_sw_five_dimensional_space_is_inside_training_range(sw):
    m, cat, opt_id, uses = sw
    td = m.tasks[opt_id]
    spec = cat.get(m.tenant.code, opt_id)
    defs = {f.name: f for f in spec.defs}
    locks = [h.lock_of(r) for r in uses.values()]
    sp = Optimizer(cat).space(spec.task, locks, {k: v["default"] for k, v in td.raw["params"].items()}, defs)
    assert list(sp.axes) == td.raw["controls"] and len(sp.axes) == 5
    assert sp.size == math.prod(len(v) for v in sp.axes.values()) and sp.strategy == "grid" and len(sp.points) == sp.size
    out_of_range = 0
    for name, vals in sp.axes.items():
        f = defs[name]
        lo = max([f.min] + [lk["features"][name]["p1"] for lk in locks])
        hi = min([f.max] + [lk["features"][name]["p99"] for lk in locks])
        for v in vals:
            k = (v - f.min) / f.step
            assert abs(k - round(k)) < 1e-9                                  # step 격자 위
            out_of_range += not (lo - 1e-9 <= v <= hi + 1e-9)
        # 학습 범위 안의 격자점은 하나도 빠뜨리지 않는다
        lattice = [f.min + i * f.step for i in range(int(round((f.max - f.min) / f.step)) + 1)]
        assert vals == [x for x in lattice if lo - 1e-9 <= x <= hi + 1e-9]
    assert out_of_range == 0
    for name in sp.axes:                                                       # 실제 점 프레임도 같은 범위
        assert set(sp.points[name]) <= set(sp.axes[name])


def test_sw_recommendation_matches_brute_force(sw):
    m, cat, opt_id, uses = sw
    td = m.tasks[opt_id]
    fixed = _fixed(sw)
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed), caller="t")
    assert not list(SCHEMA.iter_errors(out))
    rec = out["recommendation"]
    assert rec["in_train_range_rate"] == 1.0 and rec["strategy"] == "grid"
    spec = cat.get(m.tenant.code, opt_id)
    sp = Optimizer(cat).space(spec.task, [h.lock_of(r) for r in uses.values()],
                              {k: v["default"] for k, v in td.raw["params"].items()}, {f.name: f for f in spec.defs})
    assert rec["n_candidates"] == sp.size
    pts = sp.points.reset_index(drop=True)
    pred = _direct(sw, pts, fixed)
    params = {k: float(v["default"]) for k, v in td.raw["params"].items()}
    cost = _formula(m, "process_cost")
    costs = np.array([cost(r, params) for r in pts.to_dict("records")])
    feas = (pred["delta_e"] <= params["max_delta_e"]) & (pred["defect_risk"] <= params["max_risk"]) & \
        (pts["line_speed"].to_numpy() >= params["min_line_speed"])
    assert rec["n_feasible"] == int(feas.sum()) and rec["feasible"] == bool(feas.any())
    order = np.lexsort([pred["delta_e"][feas], costs[feas]])                  # 비용 ↑, 동률이면 ΔE ↑
    best = pts[feas].reset_index(drop=True).iloc[order[0]].to_dict()
    assert rec["best"]["conditions"] == {k: (int(v) if float(v).is_integer() else v) for k, v in best.items()}
    assert rec["best"]["objective_value"] == pytest.approx(costs[feas][order[0]], abs=1e-5)
    got = [c["objective_value"] for c in rec["candidates"]]
    assert got == sorted(got) and len(got) == min(5, int(feas.sum()))
    for c in rec["candidates"]:
        assert c["violation"] == 0 and all(x["satisfied"] for x in c["constraints"])
        assert set(c["predictions"]) == {"delta_e", "defect_risk", "process_cost"}
        assert c["intervals"]["defect_risk"] is None and len(c["intervals"]["delta_e"]) == 2


def test_sw_impossible_constraints_have_no_ok(sw):
    m, cat, opt_id, uses = sw
    params = {"max_delta_e": 0.5, "max_risk": 0.01, "min_line_speed": 24}       # 학습 범위 안에서는 만족 불가(line_speed 24 는 범위 밖)
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw), params=params), caller="t")
    assert not list(SCHEMA.iter_errors(out))
    rec = out["recommendation"]
    assert rec["n_feasible"] == 0 and rec["feasible"] is False
    assert out["status"] == "review" and rec["on_infeasible"] == "least_violation"
    assert not any(c["violation"] == 0 for c in rec["candidates"])
    viol = [c["violation"] for c in rec["candidates"]]
    assert viol == sorted(viol)


def test_current_condition_and_improvement(sw):
    m, cat, opt_id, uses = sw
    td = m.tasks[opt_id]
    spec = cat.get(m.tenant.code, opt_id)
    defs = {f.name: f for f in spec.defs}
    current = {c: defs[c].default for c in td.raw["controls"]}
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw), current=current), caller="t")
    rec = out["recommendation"]
    assert rec["current"]["conditions"] == current
    assert rec["improvement"] == {"process_cost": pytest.approx(rec["current"]["objective_value"] - rec["best"]["objective_value"], abs=1e-5)}
    with pytest.raises(MissingRequired):
        Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw), current={td.raw["controls"][0]: 150}), caller="t")


# ── 기록 · 승인 — needs_approval, production 은 그대로 ────────────────────────────────────────────
def test_recommendation_recorded_needs_approval_and_decided_by_human(sw):
    from mlcore import approval
    m, cat, opt_id, uses = sw
    before = {t: Registry().get(m.tenant.code, t).version for t in uses}
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw)), caller="t#1")
    rid = out["recommendation"]["rec_id"]
    with connect() as c:
        row = c.execute("SELECT * FROM mlp_recommendation WHERE rec_id = %s", (rid,)).fetchone()
        apr = c.execute("SELECT * FROM mlp_approval WHERE kind = 'recommendation' AND ref_id = %s", (rid,)).fetchone()
    assert row["status"] == "needs_approval" and row["tenant_id"] == m.tenant.code and row["task_id"] == opt_id
    assert row["uses_versions"] == {u["task"]: u["version"] for u in out["uses"]}
    assert row["candidates"]["candidates"] == out["recommendation"]["candidates"] and row["applied_at"] is None
    assert apr["state"] == "pending" and apr["action"] == "apply" and apr["approver_role"] == m.tasks[opt_id].raw["approver_role"]
    assert apr["evidence"]["best"] == out["recommendation"]["best"]
    res = approval.decide(apr["approval_id"], actor="a", actor_role="approver", approve=True, reason="시험 인쇄 확인")
    assert res == {"approval_id": apr["approval_id"], "state": "approved", "production_version": None}
    with connect() as c:
        assert c.execute("SELECT status FROM mlp_recommendation WHERE rec_id = %s", (rid,)).fetchone()["status"] == "approved"
    with pytest.raises(approval.AlreadyDecided):
        approval.decide(apr["approval_id"], actor="a", actor_role="approver", approve=False, reason=None)
    assert {t: Registry().get(m.tenant.code, t).version for t in uses} == before   # 운영 모델은 바뀌지 않는다


def test_missing_production_dependency_is_503(tmp_path):
    m = h.make_tenant("sw", tmp_path)
    cat = TaskCatalog(m)
    opt_id = next(t for t, td in m.tasks.items() if td.type == "optimize")
    fixed = {"absorb_rate": 80.0, "fabric_strength": 340.0, "print_type": "나염", "color_tone": "진한 색상"}
    with pytest.raises(ModelNotReady) as e:
        Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed), caller="t")
    assert e.value.status == 503


def test_request_validation(sw):
    m, cat, opt_id, uses = sw
    fixed = _fixed(sw)
    opt = Optimizer(cat)
    with pytest.raises(InvalidInput):
        opt.optimize(m.tenant.code, opt_id, OptimizeRequest(fixed={**fixed, "nope": 1}), caller="t")
    with pytest.raises(InvalidInput):
        opt.optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed, params={"nope": 1}), caller="t")
    with pytest.raises(OutOfBounds):
        opt.optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=fixed, params={"max_risk": 5}), caller="t")
    cat_name = next(n for n, v in fixed.items() if isinstance(v, str))
    with pytest.raises(MissingRequired):
        opt.optimize(m.tenant.code, opt_id, OptimizeRequest(fixed={k: v for k, v in fixed.items() if k != cat_name}), caller="t")
    with pytest.raises(NotFound):                                              # optimize 가 아닌 과제
        opt.optimize(m.tenant.code, next(iter(uses)), OptimizeRequest(fixed=fixed), caller="t")


# ── 10,000 점 ≤ 10 초 · random 결정성 ─────────────────────────────────────────────────────────────
def test_ten_thousand_points_within_ten_seconds_and_random_is_deterministic(sw):
    m, cat, opt_id, uses = sw
    spec = cat.get(m.tenant.code, opt_id)
    # 같은 과제를 간격만 촘촘히 — 공간이 max_points(10,000)를 넘어 random 10,000 점이 된다
    fine = tuple(dataclasses.replace(f, step=1.0) if f.controllable else f for f in spec.defs)
    big = dataclasses.replace(spec, defs=fine)

    class Cat:
        merged = cat.merged

        def get(self, t, task):
            return big if task == opt_id else cat.get(t, task)

        def ids(self):
            return cat.ids()

    t0 = time.perf_counter()
    out = Optimizer(Cat()).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw)), caller="t")
    elapsed = time.perf_counter() - t0
    rec = out["recommendation"]
    assert rec["strategy"] == "random" and rec["n_candidates"] == 10_000 and rec["in_train_range_rate"] == 1.0
    assert elapsed <= 10.0, f"10,000 점 {elapsed:.2f}s"
    again = Optimizer(Cat()).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(sw)), caller="t")
    assert again["recommendation"]["best"] == rec["best"]                    # 시드 고정 — 같은 점 · 같은 답


# ── API — 역할 · 오류 계약 ────────────────────────────────────────────────────────────────────────
def test_optimize_api_roles_and_errors(sw):
    m, cat, opt_id, uses = sw
    k = h.keys(m)
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{opt_id}/optimize"
    body = {"fixed": _fixed(sw)}
    assert tc.post(url, json=body).status_code == 401
    assert tc.post(url, headers=h.hdr(k["viewer"]), json=body).status_code == 403
    r = tc.post(url, headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 200 and not list(SCHEMA.iter_errors(r.json()))
    r = tc.post(url, headers=h.hdr(k["operator"]), json={**body, "params": {"max_risk": 5}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_bounds"
    r = tc.post(url, headers=h.hdr(k["operator"]), json={**body, "extra": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{next(iter(uses))}/optimize", headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
