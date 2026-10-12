"""학습기 — 선정 · 구간 · 기준선 · 산출물 (spec §5 · §6.2 · contracts/interfaces.md §4).

핵심 누수 시험: 시험 구간의 목표 · 변수 값을 바꿔도 선정 · 검증 지표 · 예측 구간 q · 기준선 · 학습 범위 · 모델이
**하나도 바뀌지 않는다** — 바뀌는 것은 시험 지표뿐이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from mlcore.data import snapshot
from mlcore.registry.artifacts import artifact_sha256
from mlcore.train import split
from mlcore.train.trainer import MetricValue, StandardTrainer, TrainConfig

from tests._dev1 import FEATS, raw_rows, std_frame, task

ROOT = Path(__file__).resolve().parents[1]
METRICS = yaml.safe_load((ROOT / "std" / "metrics.yaml").read_text(encoding="utf-8"))["metrics"]


def run(t, f, tmp_path, seed=None):
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    cfg = TrainConfig.from_task(t, sid, seed=seed)
    return StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path).train(cfg)


def _perturb_test(t, f):
    sp, _ = split.plan(f, t, seed=7)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    g = f.copy()
    g.loc[te, "target"] = g.loc[te, "target"] * 3 + 100 if t.type == "regression" else 1 - g.loc[te, "target"]
    g.loc[te, "x1"] = 1e6                                   # 극단값 — 학습 범위에 들어가면 안 된다
    return g


@pytest.mark.parametrize("ttype", ["regression", "risk"])
def test_test_segment_does_not_influence_anything_but_test_metrics(ttype, tmp_path):
    t = task(ttype)
    f = std_frame(t, raw_rows(1000, 11, ttype))
    a = run(t, f, tmp_path / "a")
    b = run(t, _perturb_test(t, f), tmp_path / "b")
    assert a.status == b.status == "succeeded"
    assert a.champion == b.champion and a.valid_metrics == b.valid_metrics
    assert a.report["valid_baseline"] == b.report["valid_baseline"]
    assert a.report["baseline_value"] == b.report["baseline_value"]
    assert a.report["interval"] == b.report["interval"]
    la = json.loads(open(_abs(a.artifact_dir) + "/features.lock.json").read())
    lb = json.loads(open(_abs(b.artifact_dir) + "/features.lock.json").read())
    assert la == {**lb, "snapshot_id": la["snapshot_id"]}
    assert la["features"]["x1"]["p99"] < 1000
    assert a.test_metrics != b.test_metrics


def _abs(p):
    return p if p.startswith("/") else str(ROOT / p)


def test_regression_baseline_interval_and_metric_names(tmp_path):
    t = task()
    f = std_frame(t, raw_rows(1000, 12))
    r = run(t, f, tmp_path)
    sp, _ = split.plan(f, t, seed=7)
    fit_mean = float(f["target"].iloc[list(sp.fit_idx)].mean())
    assert r.report["baseline"] == "train_mean" and r.report["baseline_value"] == pytest.approx(fit_mean)
    assert set(r.test_metrics) == {"mae", "rmse", "r2", "interval_coverage"} | ({"mape"} if (f["target"] > 0).all() else set())
    assert set(r.test_metrics) <= set(METRICS)
    for v in r.test_metrics.values():
        assert isinstance(v, MetricValue) and v.delta_vs_baseline == pytest.approx(v.value - v.baseline)
    assert r.beats_baseline is True and r.test_metrics["mae"].value < r.test_metrics["mae"].baseline
    iv = r.report["interval"]
    assert iv["fit_on"] == "valid" and iv["n"] == 200 and iv["alpha"] == 0.1 and iv["q"] > 0
    assert 0.75 < r.test_metrics["interval_coverage"].value <= 1.0
    assert set(r.valid_metrics) == {"ridge", "extra_trees"}
    best = min(r.valid_metrics, key=lambda k: r.valid_metrics[k]["mae"])
    assert r.champion == best and "검증 구간 mae" in r.selection_reason


def test_risk_baseline_is_fit_positive_rate(tmp_path):
    t = task("risk")
    f = std_frame(t, raw_rows(1000, 13, "risk"))
    r = run(t, f, tmp_path)
    sp, _ = split.plan(f, t, seed=7)
    assert r.report["baseline"] == "train_positive_rate"
    assert r.report["baseline_value"] == pytest.approx(float(f["target"].iloc[list(sp.fit_idx)].mean()))
    assert {"brier", "roc_auc", "pr_auc", "logloss", "ece", "grade_precision", "grade_recall"} <= set(r.test_metrics)
    assert r.test_metrics["roc_auc"].baseline == pytest.approx(0.5)
    assert "calibration_curve" in r.report["test"]


def test_below_baseline_is_reported_not_hidden(tmp_path):
    t = task()
    raw = raw_rows(1000, 14)
    raw["y"] = np.random.default_rng(0).normal(0, 1, len(raw))   # 변수와 무관한 목표
    r = run(t, std_frame(t, raw), tmp_path)
    assert r.status == "succeeded"
    if not r.beats_baseline:
        assert any(w["code"] == "below_baseline" for w in r.warnings)
    assert all(v.baseline is not None for v in r.test_metrics.values())


def test_no_target_fails_visibly(tmp_path):
    t = task()
    f = std_frame(t, raw_rows(500, 1).drop(columns=["y"]))
    r = run(t, f, tmp_path)
    assert r.status == "failed" and r.champion is None and "목표 없음" in r.selection_reason


def test_warnings_few_rows_and_missing(tmp_path):
    t = task(candidates=["ridge", "lightgbm"])
    raw = raw_rows(150, 2)
    raw.loc[: 60, "x2"] = np.nan
    r = run(t, std_frame(t, raw), tmp_path)
    codes = {w["code"] for w in r.warnings}
    assert {"few_rows", "high_missing", "candidate_unavailable"} <= codes
    assert r.report["split"]["policy"] == "time_cv5"


def test_artifacts_and_hash(tmp_path):
    t = task()
    r = run(t, std_frame(t, raw_rows(800, 3)), tmp_path)
    d = Path(_abs(r.artifact_dir))
    assert d.parts[-3:] == ("tt", "tt.target_value", r.run_id)
    assert {p.name for p in d.iterdir()} == {"model.joblib", "features.lock.json", "env.lock", "report.json"}
    assert r.artifact_sha256 == artifact_sha256(d)
    lock = json.loads((d / "features.lock.json").read_text())
    assert lock["order"] == ["x1", "x2", "c1"] and lock["features"]["c1"]["values"] == ["A", "B", "C"]
    assert lock["interval"]["method"] == "split_conformal" and lock["task_type"] == "regression"
    rep = json.loads((d / "report.json").read_text())
    assert rep["champion"] == r.champion and rep["test_metrics"]["mae"]["baseline"] is not None
    import joblib
    model = joblib.load(d / "model.joblib")
    X = std_frame(t, raw_rows(5, 99))[lock["order"]]
    assert np.isfinite(model.predict(X)).all()
    # 같은 스냅숏 · 같은 설정 → 같은 run_id (멱등 키)
    r2 = run(t, std_frame(t, raw_rows(800, 3)), tmp_path / "again")
    assert r2.run_id == r.run_id


def test_anomaly_threshold_from_fit_only(tmp_path):
    t = task("anomaly")
    r = run(t, std_frame(t, raw_rows(800, 4, "anomaly")), tmp_path)
    assert r.status == "succeeded" and set(r.test_metrics) == {"flag_rate"}
    assert r.test_metrics["flag_rate"].baseline == pytest.approx(0.1)
    lock = json.loads(open(_abs(r.artifact_dir) + "/features.lock.json").read())
    assert lock["threshold"] is not None and lock["score"] == "-score_samples"


def test_calls_counter_increments(tmp_path):
    from mlcore.train import trainer
    before = trainer.calls
    t = task()
    run(t, std_frame(t, raw_rows(600, 5)), tmp_path)
    assert trainer.calls == before + 1
