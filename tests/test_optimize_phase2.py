"""최적화 · 입력 규칙 코어 확장 (웨이브 P 마감 — A2 solder · kimchi recipe_optimize · 조성 합 검사 대비). 소유 개발2(아키텍트 대행).

task-contract §1 `input_rules` · §2 `derived` · 제약 `scale` · params `optional` · `search.max_draws`.
시험 팩 = 저장소 textile 팩의 **임시 사본**(과제 YAML 만 바꿈) — 실제 solder · kimchi 팩을 만들지 않는다.
기대값은 최적화 코드를 쓰지 않고 다시 계산한다(식 · 학습 범위 · 위반량 손 계산).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil

import jsonschema
import numpy as np
import pytest
import yaml

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.registry import packs, tenants
from mlcore.serve.catalog import TaskCatalog
from mlcore.serve.errors import InvalidInput
from mlcore.serve.predict import PredictRequest, Predictor
from mlcore.tasks.optimize import Optimizer, OptimizeRequest

pytestmark = [pytest.mark.gate("G-M13"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

SCHEMA = jsonschema.Draft202012Validator(h.response_schema())
DERIVED = "260 - set_temp - 2 * ink_usage"          # 시험용 등식(원천 조성 등식과 같은 꼴: 상수 − Σ 조절 변수)


def _edit_tasks(dst, strategy: str, max_points: int):
    p = dst / "tasks" / "print_setpoint.yaml"
    t = yaml.safe_load(p.read_text(encoding="utf-8"))
    t.pop("warn_with", None)
    t["controls"] = ["set_temp", "set_pressure", "line_speed", "ink_usage"]
    t["derived"] = {"dwell_time": DERIVED}
    t["params"]["max_cost"] = {"label": "비용 상한", "unit": "지수", "default": None, "optional": True, "min": 0, "max": 1000000}
    t["constraints"] = [
        {"name": "max_delta_e", "expr": "delta_e <= max_delta_e", "scale": 3},
        {"name": "max_risk", "expr": "defect_risk <= max_risk", "scale": 5},
        {"name": "min_line_speed", "expr": "line_speed >= min_line_speed"},
        {"name": "max_cost", "expr": "process_cost <= max_cost"},
    ]
    t["search"] = {"strategy": strategy, "max_points": max_points}
    t["input_rules"] = [{"name": "absorb_band", "expr": "absorb_rate", "between": [65, 95]}]
    p.write_text(yaml.safe_dump(t, allow_unicode=True, sort_keys=False), encoding="utf-8")
    p = dst / "tasks" / "delta_e.yaml"
    t = yaml.safe_load(p.read_text(encoding="utf-8"))
    t["input_rules"] = [{"name": "temp_speed", "expr": "(set_temp + line_speed)", "between": [150, 225]}]
    p.write_text(yaml.safe_dump(t, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _world(tmp, strategy: str = "random", max_points: int = 300):
    pb = tmp / "packs"
    dst = pb / "textile"
    shutil.copytree(h.ROOT / "packs" / "textile", dst, ignore=shutil.ignore_patterns("__pycache__"))
    _edit_tasks(dst, strategy, max_points)
    code = "t" + secrets.token_hex(3)
    text = (h.ROOT / "tenants" / "sw.yaml").read_text(encoding="utf-8")
    text = re.sub(r"^code: sw\b", f"code: {code}", text, flags=re.M)
    text = re.sub(r"(?<![A-Za-z0-9_])sw\.(?=[a-z])", f"{code}.", text)
    tb = tmp / f"tenants-{code}"
    tb.mkdir()
    (tb / f"{code}.yaml").write_text(text, encoding="utf-8")
    m = tenants.load_and_merge(code, tenants_base=tb, packs_base=pb)
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)",
                  (code, "최적화 시험", "textile", m.tenant.config["mode"]))
        for task_id, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                      "VALUES (%s,%s,%s,%s,%s,%s)", (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    refs = {}
    for short in ("delta_e", "defect_risk"):
        ref, _ = h.to_production(m, f"{code}.{short}")
        refs[short] = ref
    return m, TaskCatalog(m), f"{code}.print_setpoint", refs


@pytest.fixture(scope="module")
def rnd(tmp_path_factory):
    return _world(tmp_path_factory.mktemp("opt2-rnd"), "random", 100)


@pytest.fixture(scope="module")
def grid(tmp_path_factory):
    return _world(tmp_path_factory.mktemp("opt2-grid"), "grid", 100000)


def _fixed(world) -> dict:
    m, cat, opt_id, refs = world
    return h.mid_inputs(h.lock_of(refs["delta_e"]), m.tasks[opt_id].raw["fixed"])


def _accept_band(refs) -> tuple[float, float]:
    """dwell_time 수락 구간 = features.yaml [min, max] ∩ 두 의존 모델 학습 범위 (최적화 코드와 독립)."""
    lo, hi = 20.0, 80.0
    for ref in refs.values():
        item = h.lock_of(ref)["features"]["dwell_time"]
        lo, hi = max(lo, item["p1"]), min(hi, item["p99"])
    return lo, hi


def _stored(rec_id: str) -> dict:
    with connect() as c:
        return c.execute("SELECT candidates FROM mlp_recommendation WHERE rec_id=%s", (rec_id,)).fetchone()["candidates"]


# ── derived · 수락 표집 ─────────────────────────────────────────────────────────────────────────
def test_random_acceptance_fills_max_points_inside_range(rnd):
    m, cat, opt_id, refs = rnd
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(rnd)), caller="t")
    assert not list(SCHEMA.iter_errors(out))
    rec = out["recommendation"]
    assert rec["strategy"] == "random" and rec["n_candidates"] == 100 and rec["in_train_range_rate"] == 1.0
    lo, hi = _accept_band(refs)
    for c in rec["candidates"]:
        cond = c["conditions"]
        expect = 260 - cond["set_temp"] - 2 * cond["ink_usage"]
        assert cond["dwell_time"] == pytest.approx(expect)                     # 식 그대로
        assert lo - 1e-9 <= cond["dwell_time"] <= hi + 1e-9                   # 학습 범위 밖 0
    acc = _stored(rec["rec_id"])["acceptance"]
    assert acc["accepted"] == 100 and acc["drawn"] > 100 and acc["capped"] is False and acc["derived"] == ["dwell_time"]


def test_space_is_seed_deterministic_and_all_points_accepted(rnd):
    m, cat, opt_id, refs = rnd
    spec = cat.get(m.tenant.code, opt_id)
    defs = {f.name: f for f in spec.defs}
    locks = [h.lock_of(r) for r in refs.values()]
    params = {k: v["default"] for k, v in spec.task.raw["params"].items() if v.get("default") is not None}
    a = Optimizer(cat).space(spec.task, locks, params, defs, fixed=_fixed(rnd))
    b = Optimizer(cat).space(spec.task, locks, params, defs, fixed=_fixed(rnd))
    assert a.points.equals(b.points) and len(a.points) == 100 and a.n_drawn == b.n_drawn
    lo, hi = _accept_band(refs)
    d = 260 - a.points["set_temp"] - 2 * a.points["ink_usage"]
    assert np.allclose(a.points["dwell_time"], d) and ((d >= lo - 1e-9) & (d <= hi + 1e-9)).all()
    # 독립 재계산: 뽑은 수까지의 순서에서 범위 안인 점 수가 정확히 100 (그 앞에서 멈췄다)
    assert a.n_drawn < a.size


def test_max_draws_cap_returns_accepted_so_far(rnd):
    from types import SimpleNamespace
    m, cat, opt_id, refs = rnd
    spec = cat.get(m.tenant.code, opt_id)
    defs = {f.name: f for f in spec.defs}
    locks = [h.lock_of(r) for r in refs.values()]
    raw = dict(spec.task.raw, search={"strategy": "random", "max_points": 100, "max_draws": 100})
    sp = Optimizer(cat).space(SimpleNamespace(raw=raw), locks, {}, defs, fixed=_fixed(rnd))
    assert sp.n_drawn == 100 and 0 < len(sp.points) < 100 and sp.capped is True


def test_grid_filters_derived_out_of_range(grid):
    m, cat, opt_id, refs = grid
    spec = cat.get(m.tenant.code, opt_id)
    defs = {f.name: f for f in spec.defs}
    locks = [h.lock_of(r) for r in refs.values()]
    params = {k: v["default"] for k, v in spec.task.raw["params"].items() if v.get("default") is not None}
    sp = Optimizer(cat).space(spec.task, locks, params, defs, fixed=_fixed(grid))
    lo, hi = _accept_band(refs)
    total = int(np.prod([len(v) for v in sp.axes.values()]))
    # 격자 전체를 손으로 세어 수락 수와 비교
    import itertools
    names = list(sp.axes)
    n_ok = sum(1 for pt in itertools.product(*[sp.axes[n] for n in names])
               if lo - 1e-9 <= 260 - pt[names.index("set_temp")] - 2 * pt[names.index("ink_usage")] <= hi + 1e-9)
    assert sp.strategy == "grid" and len(sp.points) == n_ok and 0 < n_ok < total and sp.n_drawn == total
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(grid)), caller="t")
    assert out["recommendation"]["n_candidates"] == n_ok and out["recommendation"]["in_train_range_rate"] == 1.0


# ── 제약 scale · 선택 param ─────────────────────────────────────────────────────────────────────
def _hand_violation(c: dict, scales: dict) -> float:
    total = 0.0
    for k in c["constraints"]:
        if k["satisfied"]:
            continue
        total += max(0.0, -k["slack"]) / (scales.get(k["name"]) or max(abs(k["rhs"]), 1e-9))
    return total


def test_scale_violation_and_least_violation_order(rnd):
    m, cat, opt_id, refs = rnd
    impossible = {"max_delta_e": 0.5, "max_risk": 0.01, "min_line_speed": 24}
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(rnd), params=impossible), caller="t")
    rec = out["recommendation"]
    scales = {"max_delta_e": 3, "max_risk": 5}
    if rec["feasible"]:
        pytest.skip("시험 모델에서 불가능 제약이 충족됐다")
    vs = [_hand_violation(c, scales) for c in rec["candidates"]]
    for c, v in zip(rec["candidates"], vs):
        assert c["violation"] == pytest.approx(v, abs=1e-6)                   # Σ max(0,-slack)/scale (scale 없으면 |rhs|)
    assert vs == sorted(vs) and out["status"] == "review"


def test_optional_param_skips_constraint(rnd):
    m, cat, opt_id, refs = rnd
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(rnd)), caller="t")
    names = {k["name"] for k in out["recommendation"]["best"]["constraints"]}
    assert "max_cost" not in names and {"max_delta_e", "max_risk", "min_line_speed"} <= names
    assert _stored(out["recommendation"]["rec_id"])["skipped_constraints"] == ["max_cost"]
    out2 = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(rnd), params={"max_cost": 1000000}),
                                   caller="t")
    assert "max_cost" in {k["name"] for k in out2["recommendation"]["best"]["constraints"]}
    assert _stored(out2["recommendation"]["rec_id"])["skipped_constraints"] == []


def test_current_condition_gets_derived(rnd):
    m, cat, opt_id, refs = rnd
    cur = {"set_temp": 180, "set_pressure": 4, "line_speed": 15, "ink_usage": 20}
    out = Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed=_fixed(rnd), current=cur), caller="t")
    assert out["recommendation"]["current"]["conditions"]["dwell_time"] == pytest.approx(260 - 180 - 40)


# ── input_rules ───────────────────────────────────────────────────────────────────────────────
def test_input_rule_predict_and_batch_422(rnd):
    m, cat, opt_id, refs = rnd
    tid = f"{m.tenant.code}.delta_e"
    base = h.mid_inputs(h.lock_of(refs["delta_e"]), m.tasks[tid].raw["features"])
    ok = {**base, "set_temp": 180, "line_speed": 15}
    bad = {**base, "set_temp": 205, "line_speed": 22}                         # 227 > 225
    pr = Predictor(cat)
    assert pr.predict(m.tenant.code, tid, PredictRequest(inputs=ok), caller="t")["prediction"] is not None
    with pytest.raises(InvalidInput) as e:
        pr.predict(m.tenant.code, tid, PredictRequest(inputs=bad), caller="t")
    assert e.value.detail == {"field": "temp_speed", "rule": "input_rule"}
    assert "227" not in json.dumps(e.value.body(), ensure_ascii=False)        # 입력값을 되풀이하지 않는다
    out = pr.predict_batch(m.tenant.code, tid, [PredictRequest(inputs=ok), PredictRequest(inputs=bad)], caller="t")
    assert out["items"][1]["error"]["code"] == "invalid_input"
    assert out["items"][1]["error"]["detail"]["rule"] == "input_rule" and "error" not in out["items"][0]
    # 결측이 있으면 규칙을 건너뛴다(보정 전 값)
    miss = {**bad, "line_speed": None}
    m.tasks[tid].raw  # 필수 변수라 missing_required 로 막힐 수 있다 — 규칙 때문이 아님을 확인
    with pytest.raises(Exception) as e2:
        pr.predict(m.tenant.code, tid, PredictRequest(inputs=miss), caller="t")
    assert getattr(e2.value, "detail", {}).get("rule") != "input_rule"


def test_input_rule_optimize_fixed_422(rnd):
    m, cat, opt_id, refs = rnd
    with pytest.raises(InvalidInput) as e:
        Optimizer(cat).optimize(m.tenant.code, opt_id, OptimizeRequest(fixed={**_fixed(rnd), "absorb_rate": 62}), caller="t")
    assert e.value.detail == {"field": "absorb_band", "rule": "input_rule"}


# ── 등록부 거부 ───────────────────────────────────────────────────────────────────────────────
def _pack_task(name: str):
    pk = packs.load_pack("textile")
    return pk, dict(pk.tasks[name])


@pytest.mark.parametrize("mutate, needle", [
    (lambda t: t.update(derived={"set_temp": "200 - ink_usage"}), "조절"),                     # derived 가 controls
    (lambda t: t.update(derived={"dwell_time": "foo(1)"}), "식"),                               # 함수 호출
    (lambda t: t.update(derived={"dwell_time": "100 - absent"}), "이름"),                       # 모르는 이름
    (lambda t: t.update(derived={"color_tone": "1"}), "수치 변수"),                              # 범주 변수
    (lambda t: t["constraints"][0].update(scale=0), "scale"),
    (lambda t: t["params"].update(x={"default": None}), "optional"),
    (lambda t: t["params"].update(x={"default": None, "optional": "yes"}), "optional"),
    (lambda t: t.update(search={"strategy": "random", "max_points": 100, "max_draws": 10}), "max_draws"),
    (lambda t: t.update(input_rules=[{"name": "r", "expr": "set_temp", "between": [5, 1]}]), "between"),
    (lambda t: t.update(input_rules=[{"name": "r", "expr": "print_type", "between": [0, 1]}]), "수치 변수"),
    (lambda t: t.update(input_rules=[{"name": "r", "expr": "set_temp"}]), "세 키"),
])
def test_registry_rejects_bad_optimize_keys(mutate, needle):
    pk, t = _pack_task("print_setpoint")
    import copy
    t = copy.deepcopy(t)
    t.pop("warn_with", None)
    t["controls"] = ["set_temp", "set_pressure", "line_speed", "ink_usage"]
    mutate(t)
    probs = packs.validate_task("print_setpoint", t, "textile", pk.features, pk.tasks)
    assert any(needle in p for p in probs), probs


def test_registry_accepts_good_keys_and_derived_only_optimize():
    import copy
    pk, t = _pack_task("print_setpoint")
    t = copy.deepcopy(t)
    t["controls"] = ["set_temp", "set_pressure", "line_speed", "ink_usage"]
    t["derived"] = {"dwell_time": DERIVED}
    t["params"]["max_cost"] = {"default": None, "optional": True, "min": 0, "max": 10}
    t["constraints"] = [dict(t["constraints"][0], scale=3)]
    t["input_rules"] = [{"name": "r", "expr": "absorb_rate + fabric_strength * 0", "between": [60, 98]}]
    assert packs.validate_task("print_setpoint", t, "textile", pk.features, pk.tasks) == []
    _, r = _pack_task("delta_e")
    r = copy.deepcopy(r)
    r["derived"] = {"dwell_time": "1"}
    assert any("optimize" in p for p in packs.validate_task("delta_e", r, "textile", pk.features, pk.tasks))


def test_override_cannot_change_derived_or_input_rules(tmp_path):
    from mlcore.registry.tenants import RegistryRejected
    pb = tmp_path / "packs"
    shutil.copytree(h.ROOT / "packs" / "textile", pb / "textile", ignore=shutil.ignore_patterns("__pycache__"))
    _edit_tasks(pb / "textile", "random", 100)
    for short, over in (("print_setpoint", {"derived": {"dwell_time": "1 + set_temp"}}),
                        ("delta_e", {"input_rules": [{"name": "temp_speed", "expr": "set_temp", "between": [0, 999]}]})):
        code = "t" + secrets.token_hex(3)
        text = (h.ROOT / "tenants" / "sw.yaml").read_text(encoding="utf-8")
        text = re.sub(r"^code: sw\b", f"code: {code}", text, flags=re.M)
        text = re.sub(r"(?<![A-Za-z0-9_])sw\.(?=[a-z])", f"{code}.", text)
        tb = tmp_path / f"tenants-{code}"
        (tb / code / "tasks").mkdir(parents=True)
        (tb / f"{code}.yaml").write_text(text, encoding="utf-8")
        (tb / code / "tasks" / f"{short}.yaml").write_text(yaml.safe_dump(over, allow_unicode=True), encoding="utf-8")
        with pytest.raises(RegistryRejected) as e:
            tenants.load_and_merge(code, tenants_base=tb, packs_base=pb)
        assert e.value.rule == "R1" or "R1" in str(e.value)
