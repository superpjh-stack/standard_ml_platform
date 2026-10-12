"""웨이브 A 학습 — 분할 정책 4 누수 · anomaly 임계값(D-50) · last_value 기준선 · risk 보정 · 무작위 탐색 · outlier iqr.

공통 누수 판정: 시험 구간의 목표 · 변수를 바꿔도 선정 · 검증 지표 · 기준선 · 구간 · 보정 · 임계값 · 탐색 결과 ·
학습 범위가 **하나도 바뀌지 않는다**(바뀌는 것은 시험 지표뿐). 모든 학습의 ledger = [final_eval, report].
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from mlcore.data import jobs, snapshot
from mlcore.data.calibration import CalibratedModel
from mlcore.train import split, trainer
from mlcore.train.trainer import StandardTrainer, TrainConfig, search_trials

from tests._dev1 import FEATS, raw_rows, std_frame, task

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.gate("G-M05")


def run(t, f, tmp_path, seed=None):
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    return StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path).train(TrainConfig.from_task(t, sid, seed=seed))


def _abs(p: str) -> Path:
    return Path(p) if p.startswith("/") else ROOT / p


def _lock(r) -> dict:
    return json.loads((_abs(r.artifact_dir) / "features.lock.json").read_text(encoding="utf-8"))


def _test_idx(f, t, seed=7):
    sp, _ = split.plan(f, t, seed=seed)
    return sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))


def _perturb_test(t, f, seed=7):
    """시험 구간의 목표 · 변수 값을 바꾼다. 층화 분할은 **목표값으로 층을 나누는 것 자체가 정의**라서(어느 행이
    시험인지가 라벨에 달렸다) 라벨을 뒤집으면 다른 분할이 된다 — 그래서 층화는 변수만 바꾼다."""
    te = _test_idx(f, t, seed)
    g = f.copy()
    if "target" in g.columns and split.choose_policy(t, len(f)) != "stratified_60_20_20":
        g.loc[te, "target"] = g.loc[te, "target"] * 3 + 100 if t.type == "regression" else 1 - g.loc[te, "target"]
    g.loc[te, "x1"] = 1e6
    return g


INVARIANT_KEYS = ("champion", "valid_metrics", "valid_baseline", "baseline", "baseline_value", "interval", "threshold",
                  "calibration", "search", "chosen_params")


def _assert_only_test_changes(a, b):
    assert a.status == b.status == "succeeded", (a.report.get("error"), b.report.get("error"))
    for k in INVARIANT_KEYS:
        assert a.report.get(k) == b.report.get(k), k
    oa, ob = a.report.get("outliers"), b.report.get("outliers")
    assert oa == ob
    la, lb = _lock(a), _lock(b)
    assert la == {**lb, "snapshot_id": la["snapshot_id"]}
    for r in (a, b):
        assert [e["purpose"] for e in r.ledger] == ["final_eval", "report"] and all(e["ok"] for e in r.ledger)


# ── 분할 정책 4 — 각각 누수 시험 ──────────────────────────────────────────────
POLICY_CASES = [
    ("time_60_20_20", dict(ttype="regression"), 1000),
    ("time_cv5", dict(ttype="regression"), 300),
    ("random_60_20_20", dict(ttype="regression", time_key=None, split="random_60_20_20"), 1000),
    ("stratified_60_20_20", dict(ttype="risk", time_key=None, split="stratified_60_20_20"), 1000),
]


@pytest.mark.parametrize("policy,kw,n", POLICY_CASES, ids=[c[0] for c in POLICY_CASES])
def test_each_split_policy_partitions_and_test_segment_never_leaks(policy, kw, n, tmp_path):
    kw = dict(kw)
    ttype = kw.pop("ttype")
    t = task(ttype, **kw)
    f = std_frame(t, raw_rows(n, 21, ttype))
    sp, test = split.plan(f, t, seed=7)
    assert sp.policy == policy
    tr, va, te = set(sp.train_idx), set(sp.valid_idx), set(_test_idx(f, t))
    assert not tr & va and not va & te and not tr & te and tr | va | te == set(range(n)) and len(test) == len(te)
    if policy.startswith("time"):
        assert f["ts"].iloc[sorted(tr | va)].max() < f["ts"].iloc[sorted(te)].min()
    else:
        assert abs(len(tr) / n - 0.6) < 0.01 and abs(len(te) / n - 0.2) < 0.01
    if policy == "stratified_60_20_20":
        rate = f["target"].mean()
        for part in (tr, va, te):
            assert abs(f["target"].iloc[sorted(part)].mean() - rate) < 0.02
    a = run(t, f, tmp_path / "a")
    b = run(t, _perturb_test(t, f), tmp_path / "b")
    _assert_only_test_changes(a, b)
    assert a.report["split"]["policy"] == policy
    assert a.test_metrics != b.test_metrics


@pytest.mark.parametrize("policy", ["random_60_20_20", "stratified_60_20_20"])
@pytest.mark.parametrize("groups", [10, 120])
def test_non_time_policies_respect_group_key(policy, groups):
    ttype = "risk" if policy.startswith("strat") else "regression"
    t = task(ttype, time_key=None, split=policy, group_key="lot")
    f = std_frame(t, raw_rows(1000, 4, ttype, groups=groups).sample(frac=1, random_state=1))
    sp, _ = split.plan(f, t, seed=3)
    g = f["group"]
    parts = [set(g.iloc[list(sp.train_idx)]), set(g.iloc[list(sp.valid_idx)]), set(g.iloc[_test_idx(f, t, 3)])]
    assert not parts[0] & parts[1] and not parts[1] & parts[2] and not parts[0] & parts[2]
    assert all(parts) and sp.boundaries["group_key"] == "lot"
    sp2, _ = split.plan(f, t, seed=3)
    assert sp2.train_idx == sp.train_idx                                     # 시드 고정
    if groups == 120:
        assert abs(len(sp.train_idx) / 1000 - 0.6) < 0.05


def test_time_cv5_group_boundary_and_expanding_folds():
    t = task(group_key="lot")
    f = std_frame(t, raw_rows(400, 5, groups=40))
    sp, test = split.plan(f, t, seed=1)
    assert sp.policy == "time_cv5" and len(sp.folds) == 5
    te_groups = set(f["group"].iloc[_test_idx(f, t, 1)])
    assert not te_groups & set(f["group"].iloc[list(sp.fit_idx)])
    prev = 0
    for tr, va in sp.folds:
        assert len(tr) > prev and not set(f["group"].iloc[list(tr)]) & set(f["group"].iloc[list(va)])
        prev = len(tr)


# ── anomaly 임계값 (D-50) ─────────────────────────────────────────────────────
def test_anomaly_threshold_is_valid_quantile_of_train_model_and_ignores_test(tmp_path):
    from mlcore.train.candidates import build

    t = task("anomaly")
    f = std_frame(t, raw_rows(800, 4, "anomaly"))
    r = run(t, f, tmp_path / "a")
    sp, _ = split.plan(f, t, seed=7)
    m = build("isolation_forest", "anomaly", FEATS, t.raw["candidate_params"] if "candidate_params" in t.raw else None, 7)
    m.fit(f[[x.name for x in FEATS]].iloc[list(sp.train_idx)])
    scores = -m.score_samples(f[[x.name for x in FEATS]].iloc[list(sp.valid_idx)])
    assert r.report["threshold"] == pytest.approx(float(np.quantile(scores, 1 - 0.1)))
    assert _lock(r)["threshold"] == r.report["threshold"]
    assert "검증 구간 점수" in r.selection_reason and "D-50" in r.report["threshold_rule"]
    b = run(t, _perturb_test(t, f), tmp_path / "b")
    _assert_only_test_changes(r, b)


def test_anomaly_band_is_read_from_std_metrics(tmp_path, monkeypatch):
    t = task("anomaly")
    f = std_frame(t, raw_rows(800, 4, "anomaly"))
    base = run(t, f, tmp_path / "a")
    real = trainer.std

    def fake(name):
        d = real(name)
        if name == "metrics":
            d = json.loads(json.dumps(d))
            d["metrics"]["flag_rate"]["beats_band"] = [5.0, 6.0]           # 아무도 못 들어가는 밴드
        return d

    monkeypatch.setattr(trainer, "std", fake)
    assert trainer.beats_band() == (5.0, 6.0)
    r = run(t, f, tmp_path / "b")
    assert base.beats_baseline is True and r.beats_baseline is False
    assert "[5, 6]" in r.report["beats_baseline_rule"] and any(w["code"] == "below_baseline" for w in r.warnings)


@pytest.fixture(scope="module")
def ood(tmp_path_factory):
    base = tmp_path_factory.mktemp("ood")
    out = {}
    for tenant, tid in [("ks", "ks.sensor_ood"), ("sw", "sw.print_ood")]:
        m, t, frame, ref, syn = jobs.read_frame(tenant, tid)
        s = snapshot.freeze(frame, tenant_id=tenant, task=t, source_ref=ref, synthetic=syn, base_dir=base / "s")
        out[tid] = StandardTrainer(artifact_root=base / "a", snapshot_dir=base / "s").train(
            TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta))
    return out


@pytest.mark.parametrize("tid,flag", [("ks.sensor_ood", 0.139), ("sw.print_ood", 0.146)])
def test_pack_anomaly_tasks_beat_baseline_under_new_rule(ood, tid, flag):
    """실측(시드 42 · c 0.08): ks 0.139 · sw 0.146 — 밴드 0.04~0.16 안. 이전 규칙(재적합 표본 내 분위)은 sw 0.167 미달."""
    r = ood[tid]
    fr = r.test_metrics["flag_rate"]
    assert fr.value == pytest.approx(flag, abs=0.001) and fr.baseline == pytest.approx(0.08)
    assert r.beats_baseline is True and not any(w["code"] == "below_baseline" for w in r.warnings)


# ── last_value 기준선 (시계열 회귀) ─────────────────────────────────────────────
def test_last_value_baseline_chosen_on_valid_for_autocorrelated_series(tmp_path):
    t = task()
    raw = raw_rows(1000, 31)
    raw["y"] = np.cumsum(np.random.default_rng(1).normal(0, 1, len(raw))) + 0.02 * raw["x1"]   # 무작위 걸음
    f = std_frame(t, raw)
    r = run(t, f, tmp_path / "a")
    assert r.report["baseline"] == "last_value"
    cmp_ = r.report["baselines_compared"]
    assert cmp_["chosen_on"] == "valid" and cmp_["valid"]["last_value"]["mae"] < cmp_["valid"]["train_mean"]["mae"]
    te = _test_idx(f, t)
    order = f.sort_values(["ts", "entity_id"]).index
    lag = f.loc[order, "target"].shift(1).reindex(f.index)
    manual = float(np.mean(np.abs(f["target"].iloc[te].to_numpy() - lag.iloc[te].to_numpy())))
    assert r.test_metrics["mae"].baseline == pytest.approx(manual)
    assert "last_value" in r.report["beats_baseline_rule"]
    # 독립 행(자기상관 없음)이면 학습 평균이 이긴다 — 더 강한 쪽을 검증 구간에서 고른다
    iid = run(t, std_frame(t, raw_rows(1000, 32)), tmp_path / "b")
    assert iid.report["baseline"] == "train_mean" and iid.report["baselines_compared"]["valid"]["last_value"]
    # 시계열이 아니면 last_value 비교 자체가 없다
    nt = task(time_key=None, split="random_60_20_20")
    assert run(nt, std_frame(nt, raw_rows(1000, 32)), tmp_path / "c").report["baselines_compared"] is None


# ── risk 확률 보정 (검증 구간) ─────────────────────────────────────────────────
@pytest.mark.parametrize("method", ["sigmoid", "isotonic"])
def test_risk_calibration_fit_on_valid_only(method, tmp_path):
    t = task("risk", calibration={"method": method})
    f = std_frame(t, raw_rows(1200, 41, "risk"))
    a = run(t, f, tmp_path / "a")
    cal = a.report["calibration"]
    sp, _ = split.plan(f, t, seed=7)
    assert cal["method"] == method and cal["fit_on"] == "valid" and cal["n"] == len(sp.valid_idx)
    assert not any(w["code"].startswith("calibration") for w in a.warnings)
    model = joblib.load(_abs(a.artifact_dir) / "model.joblib")
    assert isinstance(model, CalibratedModel) and model.method == method
    X = f[[x.name for x in FEATS]].head(50)
    p = model.predict_proba(X)
    assert p.shape == (50, 2) and np.allclose(p.sum(axis=1), 1) and ((p >= 0) & (p <= 1)).all()
    assert not np.allclose(p[:, 1], model.model.predict_proba(X)[:, 1])     # 보정이 실제로 씌워졌다
    assert _lock(a)["calibration"] == cal
    b = run(t, _perturb_test(t, f), tmp_path / "b")
    _assert_only_test_changes(a, b)
    pb = joblib.load(_abs(b.artifact_dir) / "model.joblib")
    grid = np.linspace(0.01, 0.99, 25)
    from mlcore.data.calibration import apply_calibrator
    assert np.allclose(apply_calibrator(method, model.calibrator, grid), apply_calibrator(method, pb.calibrator, grid))


def test_calibration_none_keeps_plain_model(tmp_path):
    t = task("risk")
    r = run(t, std_frame(t, raw_rows(800, 42, "risk")), tmp_path)
    assert r.report["calibration"] is None and not isinstance(joblib.load(_abs(r.artifact_dir) / "model.joblib"), CalibratedModel)


# ── 무작위 탐색 (후보당 ≤ 20, 시드 고정) ────────────────────────────────────────
def test_search_trials_budget_and_determinism():
    big = {"a": list(range(10)), "b": list(range(10))}
    tr = search_trials(big, 20, seed=5)
    assert len(tr) == 20 and tr[0] == {} and len({json.dumps(x, sort_keys=True) for x in tr}) == 20
    assert tr == search_trials(big, 20, seed=5) and tr != search_trials(big, 20, seed=6)
    small = {"a": [1, 2, 3]}
    assert search_trials(small, 20, seed=5) == [{}, {"a": 1}, {"a": 2}, {"a": 3}]


def test_random_search_selects_on_valid_and_is_reproducible(tmp_path):
    space = {"ridge": {"alpha": [0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]},
             "extra_trees": {"min_samples_leaf": [1, 2, 5, 10, 20, 50], "n_estimators": [20, 50]}}
    t = task(candidate_search=space)
    f = std_frame(t, raw_rows(1000, 51))
    a = run(t, f, tmp_path / "a")
    s = a.report["search"]
    assert set(s) == {"ridge", "extra_trees"} and s["ridge"]["trials"] == 9 and s["extra_trees"]["trials"] == 13
    assert all(v["trials"] <= 20 and v["seed"] == 7 for v in s.values())
    assert a.report["chosen_params"][a.champion] == s[a.champion]["best_params"]
    again = run(t, f, tmp_path / "again")
    assert again.report["search"] == s and again.test_predictions == a.test_predictions
    b = run(t, _perturb_test(t, f), tmp_path / "b")
    _assert_only_test_changes(a, b)


def test_search_skipped_for_unsupervised(tmp_path):
    t = task("anomaly", candidate_search={"isolation_forest": {"n_estimators": [50, 100]}})
    r = run(t, std_frame(t, raw_rows(600, 52, "anomaly")), tmp_path)
    assert r.status == "succeeded" and r.report["search"] is None and any(w["code"] == "search_skipped" for w in r.warnings)


# ── outlier: iqr (학습 구간에서만) ─────────────────────────────────────────────
def test_outlier_iqr_removes_only_from_training_rows(tmp_path):
    t = task(outlier="iqr")
    raw = raw_rows(1000, 61)
    f = std_frame(t, raw)
    sp, _ = split.plan(f, t, seed=7)
    bad = list(sp.train_idx)[:15]
    f.loc[bad, "target"] = f["target"].iloc[bad] + 500                     # 학습 구간 이상치 15
    a = run(t, f, tmp_path / "a")
    o = a.report["outliers"]
    assert o["method"] == "iqr" and o["k"] == 1.5 and "target" in o["columns"] and o["folds"][0] >= 15
    assert a.report["outliers_removed"] == sum(o["folds"]) + o["refit"] and o["refit"] >= 15
    off = run(task(), f, tmp_path / "off")
    assert off.report["outliers"] is None and off.report["outliers_removed"] == 0
    assert a.test_metrics["mae"].value < off.test_metrics["mae"].value      # 이상치를 빼면 낫다
    assert a.report["test"]["rows"] == off.report["test"]["rows"] == len(_test_idx(f, t))   # 시험 행은 그대로
    b = run(t, _perturb_test(t, f), tmp_path / "b")                         # 시험 구간 극단값은 경계 · 제거에 안 들어간다
    _assert_only_test_changes(a, b)


def test_outlier_unknown_method_fails_visibly(tmp_path):
    t = task(outlier="zscore")
    r = run(t, std_frame(t, raw_rows(600, 62)), tmp_path)
    assert r.status == "failed" and "iqr" in r.selection_reason
