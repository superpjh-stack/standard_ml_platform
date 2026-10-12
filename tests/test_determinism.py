"""G-M06 A — 결정성: 같은 스냅숏 + 시드 + 코드 버전 → 시험 예측 차이 0 (D-19, OMP_NUM_THREADS=1).

켜진 학습 과제 6(ks 3 · sw 3)을 팩 합성 스냅숏으로 2회 학습해 시험 예측 · 챔피언 · 지표 · 산출물 모델 예측을 대조한다.
"""

from __future__ import annotations

import os

import joblib
import numpy as np
import pytest

from mlcore.data import jobs, snapshot
from mlcore.train.trainer import StandardTrainer, TrainConfig
from tests._dev1 import FEATS, raw_rows, std_frame, task

LEARNED = [("ks", "ks.remaining_hours"), ("ks", "ks.failure_24h"), ("ks", "ks.sensor_ood"),
           ("sw", "sw.delta_e"), ("sw", "sw.defect_risk"), ("sw", "sw.print_ood")]


def test_omp_threads_is_one():
    import mlcore.train.jobs  # noqa: F401  학습 작업 모듈이 기본값 1 을 건다
    assert os.environ.get("OMP_NUM_THREADS") == "1", "학습은 OMP_NUM_THREADS=1 로 돈다 (spec §5.5)"


@pytest.mark.parametrize("tenant,tid", LEARNED)
def test_retrain_same_snapshot_same_predictions(tenant, tid, tmp_path):
    m, t, frame, ref, syn = jobs.read_frame(tenant, tid)
    s1 = snapshot.freeze(frame, tenant_id=tenant, task=t, source_ref=ref, synthetic=syn, base_dir=tmp_path / "s")
    # 소스를 다시 읽어 다시 고정해도 같은 스냅숏
    _, _, frame2, _, _ = jobs.read_frame(tenant, tid)
    s2 = snapshot.freeze(frame2, tenant_id=tenant, task=t, source_ref=ref, synthetic=syn, base_dir=tmp_path / "s")
    assert s1.snapshot_id == s2.snapshot_id and s1.sha256 == s2.sha256
    cfg = TrainConfig.from_task(t, s1.snapshot_id, pack_meta=m.pack.meta)
    r1 = StandardTrainer(artifact_root=tmp_path / "a1", snapshot_dir=tmp_path / "s").train(cfg)
    r2 = StandardTrainer(artifact_root=tmp_path / "a2", snapshot_dir=tmp_path / "s").train(cfg)
    assert r1.status == r2.status == "succeeded"
    p1, p2 = np.asarray(r1.test_predictions), np.asarray(r2.test_predictions)
    assert len(p1) == 144 and float(np.max(np.abs(p1 - p2))) == 0.0
    assert r1.report["test_predictions_sha256"] == r2.report["test_predictions_sha256"]
    assert r1.run_id == r2.run_id and r1.champion == r2.champion and r1.valid_metrics == r2.valid_metrics
    assert {k: v.value for k, v in r1.test_metrics.items()} == {k: v.value for k, v in r2.test_metrics.items()}
    # 산출물 모델도 같은 예측
    X = snapshot.load(s1.snapshot_id, base_dir=tmp_path / "s")[t.raw["features"]]
    m1, m2 = joblib.load(tmp_path / "a1" / tenant / tid / r1.run_id / "model.joblib"), \
        joblib.load(tmp_path / "a2" / tenant / tid / r2.run_id / "model.joblib")
    f = "predict" if t.type == "regression" else ("predict_proba" if t.type == "risk" else "score_samples")
    assert np.array_equal(getattr(m1, f)(X), getattr(m2, f)(X))


def test_column_order_of_source_does_not_change_model(tmp_path):
    t = task()
    f = std_frame(t, raw_rows(800, 9))
    g = f[list(f.columns)[::-1]]
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    a = StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path / "a").train(TrainConfig.from_task(t, sid))
    b = StandardTrainer(features=FEATS, frame=g, artifact_root=tmp_path / "b").train(TrainConfig.from_task(t, sid))
    assert a.test_predictions == b.test_predictions


def test_different_seed_changes_config_hash():
    t = task()
    assert TrainConfig.from_task(t, "snp_x", seed=1).config_hash() != TrainConfig.from_task(t, "snp_x", seed=2).config_hash()
    assert TrainConfig.from_task(t, "snp_x", seed=1).config_hash() == TrainConfig.from_task(t, "snp_y", seed=1).config_hash()
