"""QA2-1 — 객체 분류(ot.cad_objects) 층화 분할 · majority_class 기준선 · labels none 이면 지표 0.

1. 표준 학습(StandardTrainer) — 구간별 클래스 수(층화 60/20/20 → 240/80/80 × 4), 시험 1회, 기준선 majority_class
   (재적합 구간 최빈 · 동률이면 classes 앞) → macro-F1 = 1/4 × F1(최빈) = 0.1 을 독립 계산.
2. 같은 과제를 `labels: none` 으로 바꾼 사본(팩이 그렇게 정의한 경우와 같다 — 등록부는 labels none + model 블록을 막지 않는다)
   으로 학습 → 보고서 · 시험 지표에 macro_f1 · accuracy 가 나오는지(G2-E01 · goal2 치명 '라벨 없이 IoU/F1').
3. 시험 교란 불변: 시험 구간 라벨만 바꾼 프레임 → 챔피언 · 검증 지표 · 기준선 클래스 동일.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.data.taskview import learn_view  # noqa: E402
from mlcore.train import split  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features  # noqa: E402


def run(t, frame, feats, m, work, tag):
    s = snapshot.freeze(frame, tenant_id="ot", task=t, source_ref={"qa": tag}, synthetic=True, base_dir=work / f"s{tag}")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
    r = StandardTrainer(features=feats, frame=frame, artifact_root=work / f"a{tag}").train(cfg)
    return r


def main():
    work = Path(tempfile.mkdtemp(prefix="qa21-ext-"))
    out = {}
    m, t, frame, ref, syn = jobs.read_frame("ot", "ot.cad_objects", source_role="demo")
    frame = snapshot.canonical(frame)
    feats = resolve_features(t, merged=m)
    lv = learn_view(t)
    sp, _ = split.plan(frame, lv, seed=lv.raw.get("seed", 42))
    te = sorted(set(range(len(frame))) - set(sp.fit_idx))
    seg = {"train": list(sp.train_idx), "valid": list(sp.valid_idx), "test": te}
    out["class_counts"] = {k: frame["target"].iloc[v].astype(str).value_counts().sort_index().to_dict() for k, v in seg.items()}
    r = run(t, frame, feats, m, work, "base")
    rep = r.report
    out["base"] = {"status": r.status, "champion": r.champion, "labels": rep.get("labels"),
                   "test": {k: (v.value, v.baseline) for k, v in r.test_metrics.items()},
                   "baseline": rep["baseline"], "baseline_value": rep["baseline_value"], "ledger": [e["purpose"] for e in r.ledger]}
    classes = list(lv.raw["classes"])
    fit_y = frame["target"].iloc[list(sp.fit_idx)].astype(str).tolist()
    maj = max(classes, key=lambda c: (fit_y.count(c), -classes.index(c)))
    yt = frame["target"].iloc[te].astype(str).to_numpy()
    f1_maj = 2 * (yt == maj).sum() / ((yt == maj).sum() + len(yt))
    out["independent_majority"] = {"class": maj, "macro_f1": round(f1_maj / len(classes), 6), "accuracy": float((yt == maj).mean())}
    # 2. labels none 사본
    raw = dict(t.raw); raw["labels"] = "none"
    t_none = replace(t, raw=raw)
    r2 = run(t_none, frame, feats, m, work, "none")
    out["labels_none"] = {"status": r2.status, "labels": r2.report.get("labels"),
                          "test_metric_keys": sorted(r2.test_metrics) if r2.test_metrics else None,
                          "macro_f1": (r2.test_metrics or {}).get("macro_f1") and r2.test_metrics["macro_f1"].value,
                          "extract_metrics_keys": sorted((r2.report.get("extract_metrics") or {}).keys())[:8]}
    # 3. 시험 교란
    f3 = frame.copy()
    f3.loc[f3.index[te], "target"] = np.roll(f3["target"].iloc[te].to_numpy(), 1)
    r3 = run(t, f3, feats, m, work, "pert")
    out["test_perturbed_same"] = {"champion": r3.champion == r.champion,
                                  "valid": json.dumps(r3.valid_metrics, sort_keys=True) == json.dumps(r.valid_metrics, sort_keys=True),
                                  "baseline_value": r3.report["baseline_value"] == rep["baseline_value"],
                                  "test_macro_f1_changed": r3.test_metrics["macro_f1"].value != r.test_metrics["macro_f1"].value}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
