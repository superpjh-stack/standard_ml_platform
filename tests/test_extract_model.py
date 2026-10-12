"""extract 의 모델 기반 추출기 학습 — 객체 분류(다중 클래스) (task-contract §6.2 · std D2-15 · goal2 G2-E01 학습 측).

절차: `stratified_60_20_20`(클래스 비율 유지) → 학습 구간 후보 → **검증 macro-F1** 선정 → 학습+검증 재적합 → 시험 1회.
기준선 `majority_class` = 학습 구간 최빈 클래스 상수 예측. 보고: macro-F1 · 클래스별 F1 · 혼동행렬(+ 기준선).
라벨이 없는 과제(`labels: none`)는 지표를 만들지 않는다(null + labels: none).
합성 설명자는 시험 안에서만 만든다(팩 · 회사 이름 없음) — 기대값은 sklearn 으로 이 시험이 독립 계산한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import confusion_matrix, f1_score

from mlcore.data import snapshot
from mlcore.data.features import FeatureDef
from mlcore.data.frame import standardize
from mlcore.data.sources import ReadSpec
from mlcore.data.taskview import learn_view
from mlcore.registry.packs import def_hash
from mlcore.registry.tenants import TaskDef
from mlcore.train import metrics, split
from mlcore.train.trainer import NotTrainable, StandardTrainer, TrainConfig

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ["c_a", "c_b", "c_c", "c_d"]
DESC = [FeatureDef(f"d{i}", f"설명자 {i}", "float", min=-1e6, max=1e6) for i in range(6)]


def extract_task(*, labels="synthetic", model=True, candidates=("logreg", "rf_clf", "et_clf"), seed=42) -> TaskDef:
    raw = {"id": "tmpl.objects", "type": "extract", "title": "t", "entity": "drawing", "approver_role": "quality",
           "document": {"formats": ["dxf"], "max_bytes": 5242880, "max_entities": 2000},
           "extractors": [{"name": "geom", "kind": "rule", "module": "extractors/geom.py", "version": "1.0.0"}],
           "labels": labels, "outputs": ["objects"], "seed": seed}
    if model:
        raw["extractors"].append({"name": "objclf", "kind": "model", "module": "extractors/objclf.py", "version": "1.0.0"})
        raw["model"] = {"features": [f.name for f in DESC], "classes": list(CLASSES), "split": "stratified_60_20_20",
                        "candidates": list(candidates), "candidate_params": {"logreg": {"max_iter": 2000}},
                        "selection": "macro_f1"}
    return TaskDef("tt.objects", raw["id"], "extract", raw, def_hash(raw))


def descriptors(counts=(400, 400, 400, 400), seed=0, noise=1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for k, (c, n) in enumerate(zip(CLASSES, counts)):
        center = np.array([k * 2.0, (k % 2) * 3.0, k ** 1.5, -k, 0.5 * k, 1.0])
        x = center + rng.normal(0, noise, (n, 6))
        parts.append(pd.DataFrame(x, columns=[f.name for f in DESC]).assign(label=c))
    df = pd.concat(parts, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    df.insert(0, "entity_id", [f"OBJ-{i:05d}" for i in range(len(df))])
    return df


def frame_of(t, raw):
    v = learn_view(t)
    return snapshot.canonical(standardize(raw, ReadSpec(tenant_id="tt", task=v, features=DESC), kind="synthetic",
                                          source_ref="test"))


def train(t, f, tmp_path, seed=None):
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    return StandardTrainer(features=DESC, frame=f, artifact_root=tmp_path).train(TrainConfig.from_task(t, sid, seed=seed))


@pytest.fixture(scope="module")
def balanced(tmp_path_factory):
    t = extract_task()
    f = frame_of(t, descriptors())
    r = train(t, f, tmp_path_factory.mktemp("ex"))
    assert r.status == "succeeded", r.report
    return t, f, r


def test_view_moves_model_block_to_learning_keys():
    t = extract_task()
    v = learn_view(t)
    assert v.type == "extract" and v.id == t.id and v.def_hash == t.def_hash
    assert v.raw["features"] == [f.name for f in DESC] and v.raw["candidates"] == ["logreg", "rf_clf", "et_clf"]
    assert v.raw["target"] == {"name": "label"} and v.raw["split"] == "stratified_60_20_20" and not v.raw.get("time_key")
    cfg = TrainConfig.from_task(t, "snp_x")
    assert cfg.candidates == ("logreg", "rf_clf", "et_clf") and cfg.candidate_params["logreg"] == {"max_iter": 2000}


def test_stratified_split_keeps_class_shares(balanced):
    t, f, r = balanced
    b = r.report["split"]
    assert b["policy"] == "stratified_60_20_20" and b["boundaries"]["sizes"] == {"train": 960, "valid": 320, "test": 320}
    sp, _ = split.plan(f, learn_view(t), seed=42)
    for idx, n in ((sp.train_idx, 240), (sp.valid_idx, 80)):
        assert f["target"].iloc[list(idx)].value_counts().to_dict() == {c: n for c in CLASSES}


def test_selection_is_valid_macro_f1(balanced):
    t, f, r = balanced
    assert r.report["selection_metric"] == "macro_f1"
    vm = r.valid_metrics
    assert set(vm) == {"logreg", "rf_clf", "et_clf"}
    best = max(vm, key=lambda k: (vm[k]["macro_f1"], -list(vm).index(k)))
    assert r.champion == best and "macro_f1" in r.selection_reason


def test_test_metrics_with_majority_baseline_and_detail(balanced):
    t, f, r = balanced
    tm = r.test_metrics
    assert set(tm) >= {"macro_f1", "accuracy"}
    assert tm["macro_f1"].baseline is not None and tm["macro_f1"].delta_vs_baseline == pytest.approx(
        tm["macro_f1"].value - tm["macro_f1"].baseline)
    assert r.report["baseline"] == "majority_class" and r.report["baseline_value"] == "c_a"   # 동률 → classes 순서 앞
    # 균형 4 클래스에서 한 클래스만 내는 기준선 macro-F1 = 0.4 / 4 = 0.1 (손 계산)
    assert tm["macro_f1"].baseline == pytest.approx(0.1)
    d = r.report["extract_metrics"]
    assert d["labels"] == "synthetic" and set(d["class_f1"]) == set(CLASSES)
    cm = np.asarray(d["confusion_matrix"]["matrix"])
    assert d["confusion_matrix"]["labels"] == CLASSES and cm.shape == (4, 4) and int(cm.sum()) == 320
    assert np.trace(cm) / cm.sum() == pytest.approx(tm["accuracy"].value)
    assert set(d["baseline"]["class_f1"]) == set(CLASSES)
    assert r.beats_baseline is True


def test_metrics_match_independent_sklearn_on_reloaded_model(balanced):
    t, f, r = balanced
    sp, _ = split.plan(f, learn_view(t), seed=42)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    model = joblib.load(ROOT / r.artifact_dir / "model.joblib") if not Path(r.artifact_dir).is_absolute() else \
        joblib.load(Path(r.artifact_dir) / "model.joblib")
    X, y = f[[d.name for d in DESC]].iloc[te], f["target"].iloc[te].astype(str).to_numpy()
    p = np.asarray(model.predict(X)).astype(str)
    assert r.test_metrics["macro_f1"].value == pytest.approx(f1_score(y, p, labels=CLASSES, average="macro"))
    assert r.report["extract_metrics"]["confusion_matrix"]["matrix"] == confusion_matrix(y, p, labels=CLASSES).tolist()
    lock = json.loads((Path(r.artifact_dir) if Path(r.artifact_dir).is_absolute() else ROOT / r.artifact_dir)
                      .joinpath("features.lock.json").read_text())
    assert lock["task_type"] == "extract" and lock["classes"] == CLASSES and lock["baseline"] == "c_a"
    assert lock["order"] == [d.name for d in DESC]


def test_majority_class_baseline_on_imbalanced(tmp_path):
    t = extract_task(candidates=("logreg",))
    f = frame_of(t, descriptors(counts=(200, 700, 400, 300), seed=3))
    r = train(t, f, tmp_path)
    assert r.status == "succeeded" and r.report["baseline_value"] == "c_b"
    sp, _ = split.plan(f, learn_view(t), seed=42)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    y = f["target"].iloc[te].astype(str).to_numpy()
    expect = f1_score(y, np.full(len(y), "c_b"), labels=CLASSES, average="macro", zero_division=0)
    assert r.test_metrics["macro_f1"].baseline == pytest.approx(expect)


def test_test_segment_does_not_move_selection(balanced, tmp_path):
    t, f, r = balanced
    sp, _ = split.plan(f, learn_view(t), seed=42)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    g = f.copy()
    # 층화 분할은 라벨로 정해지므로 라벨은 두고(분할이 같게) 시험 행 설명자만 바꾼다 — 선정 · 기준선 · 학습 범위는 그대로여야 한다
    g.loc[te, [d.name for d in DESC]] = -g.loc[te, [d.name for d in DESC]] * 7 + 1e5
    r2 = train(t, g, tmp_path)
    assert r2.champion == r.champion and r2.valid_metrics == r.valid_metrics
    assert r2.report["baseline_value"] == r.report["baseline_value"]
    assert r2.test_metrics["macro_f1"].value != r.test_metrics["macro_f1"].value
    assert [e["purpose"] for e in r2.ledger] == ["final_eval", "report"]


def test_labels_none_has_no_metrics(tmp_path):
    t = extract_task(labels="none")
    f = frame_of(t, descriptors(seed=1))
    r = train(t, f, tmp_path)
    assert r.status == "failed" and r.test_metrics == {} and r.champion is None
    assert r.report["labels"] == "none" and r.report["metrics"] is None
    assert r.report["error"]["code"] == "labels_none"
    assert [e for e in r.ledger if e["purpose"] == "final_eval"] == []          # 시험 구간을 보지도 않았다


def test_document_metrics_helper_null_without_labels():
    out = metrics.extract_eval(["c_a", "c_b"], None, CLASSES)
    assert out == {"labels": "none", "metrics": None}
    out = metrics.extract_eval(["c_a", "c_b", "c_b"], ["c_a", "c_b", "c_a"], CLASSES, labels="provided")
    assert out["labels"] == "provided" and out["metrics"]["macro_f1"] == pytest.approx(
        f1_score(["c_a", "c_b", "c_a"], ["c_a", "c_b", "c_b"], labels=CLASSES, average="macro", zero_division=0))
    assert "iou" not in out["metrics"]                    # IoU 는 영역 정답이 없으면 만들지 않는다


def test_unknown_class_in_data_fails_visibly(tmp_path):
    t = extract_task(candidates=("logreg",))
    raw = descriptors(seed=2)
    raw.loc[:9, "label"] = "c_zz"
    r = train(t, frame_of(t, raw), tmp_path)
    assert r.status == "failed" and r.report["error"]["code"] == "unknown_class"


def test_rule_only_extract_is_not_trainable():
    t = extract_task(model=False)
    with pytest.raises(NotTrainable):
        StandardTrainer(features=DESC, frame=pd.DataFrame({"entity_id": ["a"]})).train(TrainConfig.from_task(t, "snp_x"))


def test_same_seed_same_result(balanced, tmp_path):
    t, f, r = balanced
    r2 = train(t, f, tmp_path)
    assert r2.artifact_sha256 == r.artifact_sha256 and r2.report["extract_metrics"] == r.report["extract_metrics"]
