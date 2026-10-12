"""이관 재현 krs · pc (G-M12 6사 · D2-12 · D2-02 · D2-03). 개발1 (웨이브 A2).

`migration/reproduce.py --phase2` 가 같은 합성 시드로 (1) 원천 절차 재현값(원천 코드를 **읽어** 다시 쓴 절차 — 원천 실행 0)과
(2) 표준 플랫폼 값(표준 학습기 · 대기열 · 최적화 공간)을 나란히 내고, krs 는 ±10% 대조 · pc 는 대조 제외(재측정 + 원천 표본 내 병기)로
`outputs/reproduce-krs-pc.json` 행을 만든다. 시험은 결과를 원천 식 · 독립 재계산과 맞춘다.
회사 등록부 `tenants/krs.yaml` 이 아직 없으면(개발3 작업 중) 같은 모양의 임시 등록부(팩 solder · 공급사 3값)로 돈다.
"""

from __future__ import annotations

import importlib.util
import json

import numpy as np
import pytest
import yaml

from mlcore.registry import packs

pytestmark = [pytest.mark.gate("G-M12")]

ROOT = packs.PACKS_DIR.parent
TASKS = ["krs.joint_strength", "krs.recipe_optimize", "krs.residual_review",
         "pc.sensory_score", "pc.recipe_optimize", "pc.residual_review"]


def _mod():
    spec = importlib.util.spec_from_file_location("repro_mod", ROOT / "migration" / "reproduce.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tenants_base(tmp):
    """저장소 등록부가 준비됐으면(krs 있음 · pc.recipe_optimize 켜짐) 그대로(None), 아니면 같은 모양의 임시 폴더.
    pc 는 저장소 파일 사본에 recipe_optimize 만 켜고, krs 는 저장소 파일이 있으면 사본 · 없으면 팩 solder 임시 등록부."""
    import re
    pc = (ROOT / "tenants" / "pc.yaml").read_text(encoding="utf-8")
    line = re.search(r"^  enable: \[([^\]]*)\]", pc, re.M)
    krs = ROOT / "tenants" / "krs.yaml"
    if krs.is_file() and "pc.recipe_optimize" in line.group(1):
        return None
    base = tmp / "tenants"
    base.mkdir()
    if "pc.recipe_optimize" not in line.group(1):
        pc = pc[:line.end(1)] + ", pc.recipe_optimize" + pc[line.end(1):]
    (base / "pc.yaml").write_text(pc, encoding="utf-8")
    if krs.is_file():
        (base / "krs.yaml").write_text(krs.read_text(encoding="utf-8"), encoding="utf-8")
        return base
    cfg = {"code": "krs", "name": "솔더 시험 회사", "pack": "solder", "mode": "demo", "hub_company": "krs", "aliases": [],
           "tasks": {"enable": ["krs.joint_strength", "krs.recipe_optimize", "krs.residual_review"]},
           "categories": {"supplier": ["A", "B", "C"]},
           "sources": {"demo": {"kind": "synthetic", "seed": 20260917, "rows": 720}},
           "feature_map": {}, "target_map": {}, "unmapped": {}, "approvers": {"quality_lead": []},
           "notify": {"webhook_env": None}, "compat": {"entity_prefix": "KS-"}, "labels": {}}
    (base / "krs.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return base


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("repro2")
    mod = _mod()
    res = mod.run_phase2(tenants_base=_tenants_base(tmp))
    path = tmp / "reproduce-krs-pc.json"
    mod.write_json(res, path)
    return res, json.loads(path.read_text(encoding="utf-8")), mod


def _row(res, task):
    return next(r for r in res["rows"] if r["task"] == task)


def test_rows_cover_six_tasks_with_both_values_and_reason(out):
    res, disk, _ = out
    assert [r["task"] for r in disk["rows"]] == TASKS
    for r in disk["rows"]:
        assert r["source_procedure"] and r["standard"] and r["reason"], r["task"]
        assert isinstance(r["compare"], bool)
    assert disk["meta"]["source_executed"] is False                    # 원천은 읽기만


def test_krs_joint_strength_source_procedure_selects_on_test_split(out):
    res, _, _ = out
    r = _row(res, "krs.joint_strength")
    src = r["source_procedure"]
    ranked = src["candidates"]
    assert len(ranked) == 5 and src["champion"] == min(ranked, key=lambda c: c["rmse"])["name"]   # 시험 RMSE 선정(K1)
    assert src["split"] == {"train": src["rows_after_outlier"] - src["split"]["test"], "test": src["split"]["test"]}
    assert src["outlier_scope"] == "all_rows_before_split" and src["outlier_rows_removed"] > 0      # K6
    std = r["standard"]
    assert std["split_policy"] == "random_60_20_20" and std["outlier_scope"] == "train_only"         # D2-03
    assert std["champion"] in {"decision_tree", "svr", "random_forest", "gbr", "extra_trees"}
    assert "시험 구간" in r["reason"] and "K1" in r["reason"] and "IQR" in r["reason"]
    assert r["compare"] is True
    for k in ("mae", "rmse", "r2"):
        d = (std["test"][k] - src["test"][k]) / abs(src["test"][k])
        assert r["diff_pct"][k] == pytest.approx(round(100 * d, 2))
        assert r["within_10pct"][k] == (abs(d) <= 0.10)


def test_krs_outlier_count_matches_independent_iqr(out):
    res, _, mod = out
    frame = mod.source_frame("krs", "krs.joint_strength", tenants_base=mod._LAST_BASE)
    num = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct", "temperature_c", "mixing_min"]
    mask = np.zeros(len(frame), dtype=bool)
    for c in num:
        q1, q3 = frame[c].quantile([.25, .75])
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        mask |= ((frame[c] < lo) | (frame[c] > hi)).fillna(False).to_numpy()
    assert _row(res, "krs.joint_strength")["source_procedure"]["outlier_rows_removed"] == int(mask.sum())


def test_krs_queue_source_in_sample_vs_standard_test_split(out):
    res, _, _ = out
    r = _row(res, "krs.residual_review")
    assert r["source_procedure"]["scored_rows_scope"] == "cleaned_all_rows_incl_train"           # K4
    assert r["source_procedure"]["threshold"] == 4.0 and r["standard"]["threshold"] == 4.0
    assert r["standard"]["origin"] == "test_split" and r["standard"]["scored_rows"] == 144
    assert 0 < r["standard"]["queue_size"] <= 144
    assert r["compare"] is False and "K4" in r["reason"]


def test_krs_optimize_both_sample_5000_balanced(out):
    res, _, _ = out
    r = _row(res, "krs.recipe_optimize")
    s, t = r["source_procedure"], r["standard"]
    assert s["n_points"] == 5000 and t["n_points"] == 5000
    for best in (s["best"], t["best"]):
        comp = sum(best[k] for k in ("sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct"))
        assert comp == pytest.approx(100.0, abs=1e-6)
    assert 0 <= t["feasible_rate"] <= 1 and 0 <= s["feasible_rate"] <= 1
    assert "K2" in r["reason"]


def test_pc_excluded_from_10pct_with_remeasure_and_in_sample(out):
    res, _, _ = out
    r = _row(res, "pc.sensory_score")
    assert r["compare"] is False and "D2-02" in r["reason"]
    src, std = r["source_procedure"], r["standard"]
    assert std["split_policy"] == "time_cv5" and std["split_policy"] in r["reason"]      # 행 420 < 500 (D-05) — 시간순 · 마지막 20% 시험
    assert set(src["test"]) == {"mae", "rmse", "r2"} and set(src["in_sample"]) == {"mae", "rmse", "r2"}
    assert src["champion"] == min(src["candidates"], key=lambda c: c["mae"])["name"]             # 시험 MAE 선정(P1)
    assert src["split"] == {"train": 327, "test": 93}                                            # 420 × 0.22 올림
    assert src["in_sample"]["mae"] < src["test"]["mae"]                                          # 표본 내 낙관(P2)


def test_pc_queue_threshold_from_valid_not_in_sample(out):
    res, _, _ = out
    r = _row(res, "pc.residual_review")
    s, t = r["source_procedure"], r["standard"]
    assert s["threshold_from"] == "in_sample_refit_q90" and t["threshold_from"] == "valid"
    assert s["queue_shown"] == 8 and s["above_threshold"] == 42                                    # 420 × 10%
    assert t["queue_size"] >= 0 and t["scored_rows"] == 84


def test_pc_optimize_weighted_violation_3500(out):
    res, _, _ = out
    r = _row(res, "pc.recipe_optimize")
    s, t = r["source_procedure"], r["standard"]
    assert s["n_points"] == 3500 and t["n_points"] == 3500
    assert t["scales"] == {"target_score": 3, "max_material_cost": 5}
    for best in (s["best"], t["best"]):
        assert sum(best[k] for k in ("cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct")) == pytest.approx(100.0, abs=1e-6)
