"""팩 solder — 합성 생성기 행 일치 · 접합강도 회귀(IQR 학습 구간만) · 잔차 대기열(|잔차| ≥ 4) · 배합 최적화. 개발1 (웨이브 A2).

원천 `../Koreal Solder ML AI/api/ml_service.py` 는 **읽기만** 했다(import · 실행 0). 원천 `make_sample_data()`(:31-56)를
이 파일 안에 읽은 그대로 다시 써서(원천 이름 · 원천 공급사 값) 팩 생성기와 값 · 순서 100% 대조한다.
회사 등록부 `tenants/krs.yaml` 은 개발3 소유라 시험은 임시 회사(팩 solder · 공급사 3값)를 만들어 쓴다.
기대값은 최적화 · 학습 코드를 쓰지 않고 다시 계산한다(조성 등식 · 비용식 · |잔차| 손 계산).
"""

from __future__ import annotations

import importlib.util
import secrets

import numpy as np
import pandas as pd
import pytest
import yaml

from mlcore.registry import packs, tenants

pytestmark = [pytest.mark.gate("G2-P01")]

ROOT = packs.PACKS_DIR.parent
SRC_SUPPLIERS = ["A", "B", "C"]            # 원천 :40 공급사 값(시험 안에서만 — 팩은 중립 값)
NUMERIC = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct", "temperature_c", "mixing_min"]
COMPOSITION = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct"]
PRICE = {"sn_pct": 31.0, "ag_pct": 1220.0, "cu_pct": 14.0, "sb_pct": 22.0, "flux_pct": 85.0}   # 원천 COST :28


def reference_krs(rows: int = 720) -> pd.DataFrame:
    """원천 make_sample_data()(api/ml_service.py:31-56)를 읽은 그대로 다시 쓴 참조."""
    rng = np.random.default_rng(20260917)
    ag = rng.uniform(.35, 4.0, rows)
    cu = rng.uniform(.15, 1.05, rows)
    sb = rng.uniform(0, 1.7, rows)
    flux = rng.uniform(.08, .72, rows)
    sn = 100 - ag - cu - sb - flux
    temp = rng.normal(246, 8, rows).clip(226, 268)
    mixing = rng.normal(53, 14, rows).clip(20, 88)
    supplier = rng.choice(["A", "B", "C"], rows, p=[.45, .35, .2])
    strength = (31 + 5.8 * ag + 2.4 * cu + 1.25 * sb - 2.0 * (flux - .28) ** 2
                - .055 * (temp - 246) ** 2 - .009 * (mixing - 54) ** 2
                + np.where(supplier == "A", 1.1, np.where(supplier == "B", .3, -.7)) + rng.normal(0, 1.8, rows))
    df = pd.DataFrame({"lot_id": [f"KS-{20240000 + i:08d}" for i in range(rows)], "sn_pct": sn, "ag_pct": ag,
                       "cu_pct": cu, "sb_pct": sb, "flux_pct": flux, "temperature_c": temp, "mixing_min": mixing,
                       "supplier": supplier, "joint_strength_mpa": strength})
    for col in ["ag_pct", "temperature_c", "mixing_min"]:
        df.loc[rng.choice(rows, 8, replace=False), col] = np.nan
    df.loc[rng.choice(rows, 5, replace=False), "temperature_c"] = rng.choice([145, 352], 5)
    return df


def _gen():
    return packs.load_synth(packs.load_pack("solder"), "joint_strength")


@pytest.fixture(scope="module")
def ours() -> pd.DataFrame:
    return _gen()(720, 20260917, categories={"supplier": SRC_SUPPLIERS})


# ── 팩 · 생성기 ────────────────────────────────────────────────────────────────

def test_pack_loads_three_tasks_and_synth_spec():
    p = packs.load_pack("solder")
    assert sorted(p.tasks) == ["joint_strength", "recipe_optimize", "residual_review"]
    assert p.tasks["joint_strength"]["type"] == "regression"
    assert p.tasks["recipe_optimize"]["type"] == "optimize"
    assert p.tasks["residual_review"]["type"] == "review_queue"
    assert p.meta["synth"]["seed"] == 20260917 and p.meta["synth"]["rows"] == 720
    b = yaml.safe_load((p.path / "baselines.yaml").read_text(encoding="utf-8"))
    assert set(b) == set(p.tasks) and all(v.get("value") is not None for v in b.values())


def test_rows_match_source_generator_100pct(ours):
    ref = reference_krs().rename(columns={"lot_id": "entity_id"})
    ref["entity_id"] = ref.entity_id.str.replace("KS-", "DEMO-", regex=False)     # 회사 접두어 = compat.entity_prefix
    assert len(ours) == len(ref) == 720
    cols = [c for c in ours.columns if c != "ts"]
    assert set(cols) == set(ref.columns)
    pd.testing.assert_frame_equal(ours[cols].reset_index(drop=True), ref[cols].reset_index(drop=True))
    assert ours.ts.isna().all()                                            # 시각을 지어내지 않는다(D2-21)


def test_missing_and_outliers_as_source(ours):
    ref = reference_krs()
    # 결측 24 칸(ag · temp · mixing 각 8) 위에 이상치 5 가 덮일 수 있다 — 원천과 같은 수
    assert int(ours[NUMERIC].isna().sum().sum()) == int(ref[NUMERIC].isna().sum().sum()) <= 24
    assert int(ours.temperature_c.isin([145.0, 352.0]).sum()) == 5
    comp = ours[COMPOSITION].dropna().sum(axis=1)
    assert np.allclose(comp, 100.0)


def test_neutral_categories_and_length_guard():
    g = _gen()
    n = g(50, 1)
    assert set(n.supplier) <= {"S1", "S2", "S3"}
    a = g(50, 1, categories={"supplier": ["x", "y", "z"]})
    assert list(a.supplier.map({"x": "S1", "y": "S2", "z": "S3"})) == list(n.supplier)
    assert np.allclose(a.joint_strength_mpa, n.joint_strength_mpa)          # 효과는 목록 위치에 묶인다
    with pytest.raises(ValueError):
        g(10, 1, categories={"supplier": ["x", "y"]})


def test_material_cost_formula_hand_calc():
    spec = importlib.util.spec_from_file_location("solder_cost", ROOT / "packs" / "solder" / "formulas" / "material_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    row = {"sn_pct": 95.5, "ag_pct": 3.0, "cu_pct": 0.5, "sb_pct": 0.7, "flux_pct": 0.3, "temperature_c": 250}
    want = sum(row[k] * PRICE[k] / 100 for k in COMPOSITION)
    assert mod.cost(row, {}) == pytest.approx(want)
    assert mod.cost(row, {"price_ag_pct": 0}) == pytest.approx(want - 3.0 * 1220 / 100)


# ── 임시 회사 (팩 solder) ─────────────────────────────────────────────────────

def make_world(tmp, *, db: bool):
    code = "t" + secrets.token_hex(3)
    base = tmp / f"tenants-{code}"
    base.mkdir(parents=True)
    cfg = {"code": code, "name": "솔더 시험", "pack": "solder", "mode": "demo", "hub_company": code, "aliases": [],
           "tasks": {"enable": [f"{code}.joint_strength", f"{code}.recipe_optimize", f"{code}.residual_review"]},
           "categories": {"supplier": ["SA", "SB", "SC"]},
           "sources": {"demo": {"kind": "synthetic", "seed": 20260917, "rows": 720}},
           "feature_map": {}, "target_map": {}, "unmapped": {}, "approvers": {"quality_lead": []},
           "notify": {"webhook_env": None}, "compat": {}, "labels": {}}
    (base / f"{code}.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    m = tenants.load_and_merge(code, tenants_base=base)
    if db:
        from mlcore.db.conn import connect
        with connect() as c:
            c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)", (code, "솔더 시험", "solder", "demo"))
            for task_id, td in m.tasks.items():
                c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                          "VALUES (%s,%s,%s,%s,%s,%s)", (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    return m, base


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    """표준 학습기로 joint_strength 1회 학습(DB 없이 — 스냅숏 · 산출물은 임시 폴더)."""
    from mlcore.data import jobs, snapshot
    from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features
    tmp = tmp_path_factory.mktemp("solder-train")
    m, base = make_world(tmp, db=False)
    tid = f"{m.tenant.code}.joint_strength"
    mm, t, frame, ref, syn = jobs.read_frame(m.tenant.code, tid, source_role="demo", tenants_base=base)
    s = snapshot.freeze(frame, tenant_id=m.tenant.code, task=t, source_ref=ref, synthetic=syn, base_dir=tmp / "snap")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=mm.pack.meta)
    r = StandardTrainer(features=resolve_features(t, merged=mm), artifact_root=tmp / "art", snapshot_dir=tmp / "snap").train(cfg)
    return {"m": m, "frame": frame, "result": r}


def test_joint_strength_trains_five_candidates_beats_baseline(trained):
    r = trained["result"]
    assert r.status == "succeeded", r.report.get("error")
    assert set(r.valid_metrics) == {"decision_tree", "svr", "random_forest", "gbr", "extra_trees"}
    assert r.beats_baseline and r.test_metrics["mae"].value < r.test_metrics["mae"].baseline
    assert r.report["split"]["policy"] == "random_60_20_20"


def test_iqr_outliers_removed_only_from_training_rows(trained):
    r, frame = trained["result"], trained["frame"]
    rep = r.report
    out = rep.get("outliers") or {}
    assert out.get("method") == "iqr" and out.get("k") == 1.5
    sizes = rep["split"]["boundaries"]["sizes"]
    # 검증 · 시험 행은 그대로(720 의 20% · 20%) — 이상치 행이 있어도 빼지 않는다
    assert sizes["valid"] == 144 and sizes["test"] == 144
    removed = out.get("folds") or []
    assert removed and all(int(x) >= 0 for x in removed)
    # 시험 구간 잔차 행 수 = 시험 행 수(이상치 포함 채점)
    q = rep["queue_residuals"]
    assert len(q["test"]) == 144
    hot = set(frame.loc[frame.temperature_c.isin([145.0, 352.0]), "entity_id"])
    assert hot, "합성 이상치 5행"


def test_residual_review_abs_4_on_test_split_only(trained):
    from mlcore.train import review
    m, r = trained["m"], trained["result"]
    qtask = m.tasks[f"{m.tenant.code}.residual_review"].raw
    assert qtask["rule"] == {"abs_residual_ge": 4.0} and "test_split" in qtask["origins"]
    items = review.from_run(r.report, qtask["rule"], task_id=f"{m.tenant.code}.residual_review", model_version="v-test",
                            origins=qtask["origins"], max_items=qtask["max_items"])
    test_rows = r.report["queue_residuals"]["test"]
    want = sorted((row for row in test_rows if abs(row["actual"] - row["predicted"]) >= 4.0),
                  key=lambda row: -abs(row["actual"] - row["predicted"]))
    assert len(items) == min(len(want), qtask["max_items"]) and items
    assert [i["entity_id"] for i in items] == [w["entity_id"] for w in want][: len(items)]
    assert all(i["origin"] == "test_split" and abs(i["residual"]) >= 4.0 for i in items)


# ── 배합 최적화 (DB · production 모델) ─────────────────────────────────────────

def _db_ok() -> bool:
    import _dev2 as h
    return h.db_ok()


@pytest.fixture(scope="module")
def opt_world(tmp_path_factory):
    import _dev2 as h
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    from mlcore.serve.catalog import TaskCatalog
    m, base = make_world(tmp_path_factory.mktemp("solder-opt"), db=True)
    ref, res = h.real_production(m, f"{m.tenant.code}.joint_strength")
    return m, TaskCatalog(m), ref


def test_recipe_optimize_composition_sums_100_and_cost_hand_calc(opt_world):
    import _dev2 as h
    from mlcore.tasks.optimize import Optimizer, OptimizeRequest
    m, cat, ref = opt_world
    code = m.tenant.code
    out = Optimizer(cat).optimize(code, f"{code}.recipe_optimize",
                                  OptimizeRequest(fixed={"supplier": "SA"}, params={"target_strength": 48}), caller="t")
    rec = out["recommendation"]
    assert rec["strategy"] == "random" and rec["n_candidates"] == 5000 and rec["in_train_range_rate"] == 1.0
    lock = h.lock_of(ref)
    sn = lock["features"]["sn_pct"]
    for c in rec["candidates"]:
        x = c["conditions"]
        assert sum(x[k] for k in COMPOSITION) == pytest.approx(100.0)          # 조성 등식
        assert sn["p1"] - 1e-9 <= x["sn_pct"] <= sn["p99"] + 1e-9            # 수락 범위
        assert c["objective_value"] == pytest.approx(sum(x[k] * PRICE[k] / 100 for k in COMPOSITION), rel=1e-9)
    names = {k["name"] for k in rec["candidates"][0]["constraints"]}
    assert names == {"target_strength"}                                     # max_cost 없음 → 평가 안 함(optional)
    if rec["feasible"]:
        costs = [c["objective_value"] for c in rec["candidates"]]
        assert costs == sorted(costs)
        assert all(c["predictions"]["joint_strength"] >= 48 - 1e-9 for c in rec["candidates"])


def test_recipe_optimize_max_cost_constraint_and_infeasible_ranking(opt_world):
    from mlcore.tasks.optimize import Optimizer, OptimizeRequest
    m, cat, ref = opt_world
    code = m.tenant.code
    out = Optimizer(cat).optimize(code, f"{code}.recipe_optimize",
                                  OptimizeRequest(fixed={"supplier": "SC"}, params={"target_strength": 70, "max_cost": 30}),
                                  caller="t")
    rec = out["recommendation"]
    assert {k["name"] for k in rec["candidates"][0]["constraints"]} == {"target_strength", "max_cost"}
    if not rec["feasible"]:
        vs = [c["violation"] for c in rec["candidates"]]
        assert vs == sorted(vs) and out["status"] == "review"


def test_composition_input_rule_rejects_unbalanced(opt_world):
    import _dev2 as h
    from mlcore.serve.errors import InvalidInput
    from mlcore.serve.predict import PredictRequest, Predictor
    m, cat, ref = opt_world
    code = m.tenant.code
    good = h.mid_inputs(h.lock_of(ref), NUMERIC + ["supplier"])
    good.update({"sn_pct": 96.0, "ag_pct": 2.5, "cu_pct": 0.6, "sb_pct": 0.6, "flux_pct": 0.3})
    Predictor(cat).predict(code, f"{code}.joint_strength", PredictRequest(inputs=good), caller="t")
    bad = dict(good, sn_pct=97.0)                                           # 합 101
    with pytest.raises(InvalidInput) as e:
        Predictor(cat).predict(code, f"{code}.joint_strength", PredictRequest(inputs=bad), caller="t")
    assert (e.value.detail or {}).get("rule") == "input_rule"
