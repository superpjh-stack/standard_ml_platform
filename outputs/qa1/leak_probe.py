"""QA1 누수 사냥 — 시험 구간 값을 흔들어도 선정 · 보정 · 구간 · 임계값 · 기준선 · 학습 범위가 그대로인가.

방법: 같은 프레임을 두 번 학습한다. 두 번째는 시험 구간 행(=전체 − 학습 − 검증, QA 가 바깥에서 계산)의
목표 · 변수 값만 크게 바꾼다. 시험 구간이 선정 · 보정 등에 들어가지 않는다면 시험 지표를 뺀 모든 것이 같아야 한다.
실행: source outputs/qa1/env.sh && uv run python outputs/qa1/leak_probe.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.train import split  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features, with_last_value  # noqa: E402
from tests._dev1 import FEATS, raw_rows, std_frame, task  # noqa: E402

KEYS = ["champion", "valid_metrics", "valid_baseline", "baseline", "baseline_value", "interval", "threshold",
        "calibration", "chosen_params", "search", "outliers", "outliers_removed"]


def _test_rows(frame, t, seed):
    f = frame.copy()
    if t.type == "regression" and t.raw.get("time_key") and "ts" in f.columns:
        f = with_last_value(f)
    sp, _ = split.plan(f, t, seed)
    return sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx)), sp


def _perturb(frame, rows, t, feats, *, labels=True):
    f = frame.copy()
    num = [x.name for x in feats if x.numeric]
    for c in num:
        col = f[c].to_numpy(dtype=float).copy()
        col[rows] = col[rows] * 1.7 + 13.0
        f[c] = col
    if labels and "target" in f.columns:
        y = f["target"].to_numpy(dtype=float).copy()
        if t.type == "risk":
            y[rows] = 1.0 - y[rows]
        else:
            y[rows] = y[rows] * 3.0 + 50.0
        f["target"] = y
    return f


def _train(frame, t, feats, base, seed=None):
    frame = snapshot.canonical(frame)
    sid = "snp_" + snapshot.content_sha256(frame)[:16]
    cfg = TrainConfig.from_task(t, sid, seed=seed)
    r = StandardTrainer(features=feats, frame=frame, artifact_root=base).train(cfg)
    lock = None
    if r.artifact_dir:
        p = Path(r.artifact_dir)
        p = p if p.is_absolute() else ROOT / p
        lock = json.loads((p / "features.lock.json").read_text())
    return r, lock


def compare(name, frame, t, feats, *, labels=True):
    frame = snapshot.canonical(frame)
    seed = int(t.raw.get("seed", 42))
    rows, sp = _test_rows(frame, t, seed)
    with tempfile.TemporaryDirectory() as d:
        r1, l1 = _train(frame, t, feats, Path(d) / "a")
        f2 = _perturb(frame, rows, t, feats, labels=labels)
        rows2, sp2 = _test_rows(snapshot.canonical(f2), t, seed)
        r2, l2 = _train(f2, t, feats, Path(d) / "b")
    if r1.status != "succeeded" or r2.status != "succeeded":
        return name, "ERR", f"status {r1.status}/{r2.status} {r1.selection_reason[:120]}"
    diffs = []
    if rows != rows2:
        diffs.append("split(test rows)")
    for k in KEYS:
        a, b = r1.report.get(k), r2.report.get(k)
        if json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str):
            diffs.append(k)
    bc1 = (r1.report.get("baselines_compared") or {}).get("valid")
    bc2 = (r2.report.get("baselines_compared") or {}).get("valid")
    if json.dumps(bc1, sort_keys=True) != json.dumps(bc2, sort_keys=True):
        diffs.append("baselines_compared.valid")
    for k in ("ranges", "fills", "baseline", "interval", "threshold", "calibration"):
        if json.dumps((l1 or {}).get(k), sort_keys=True) != json.dumps((l2 or {}).get(k), sort_keys=True):
            diffs.append(f"lock.{k}")
    test_changed = json.dumps(r1.report["test_metrics"], sort_keys=True) != json.dumps(r2.report["test_metrics"], sort_keys=True)
    status = "PASS" if not diffs and test_changed else ("WARN" if not diffs else "FAIL")
    meas = (f"policy={sp.policy} test_rows={len(rows)} champion={r1.champion} 바뀐 항목={diffs or '없음'} "
            f"시험지표 변화={'예' if test_changed else '아니오(교란 무효?)'}")
    return name, status, meas


def main():
    out = []
    # 1) 실제 켜진 학습 과제 6 (팩 합성 스냅숏)
    for tenant, tid in [("ks", "ks.remaining_hours"), ("ks", "ks.failure_24h"), ("ks", "ks.sensor_ood"),
                        ("sw", "sw.delta_e"), ("sw", "sw.defect_risk"), ("sw", "sw.print_ood")]:
        m, t, frame, ref, syn = jobs.read_frame(tenant, tid)
        feats = resolve_features(t)
        out.append(compare(tid, frame, t, feats))
    # 2) 선택 기능 · 다른 분할 정책 (팩 중립 임시 과제)
    space = {"ridge": {"alpha": [0.01, 0.1, 1.0, 10.0, 100.0]}, "extra_trees": {"n_estimators": [20, 50], "max_depth": [3, 6, None]}}
    cases = [
        ("tmp.reg time_60_20_20 + iqr + search", task(outlier="iqr", candidate_search=space), raw_rows(1000, 1), True),
        ("tmp.reg time_cv5 (300행) + iqr", task(outlier="iqr"), raw_rows(300, 2), True),
        ("tmp.reg random_60_20_20 + search", task(time_key=None, split="random_60_20_20", candidate_search=space), raw_rows(1000, 3), True),
        ("tmp.risk stratified + isotonic + search", task("risk", time_key=None, split="stratified_60_20_20",
                                                        calibration={"method": "isotonic"},
                                                        candidate_search={"logreg": {"C": [0.01, 0.1, 1, 10]}}),
         raw_rows(1000, 4, "risk"), False),   # 층화: 라벨을 바꾸면 분할이 정의상 바뀐다(D-67) → 변수만
        ("tmp.risk random + sigmoid", task("risk", time_key=None, split="random_60_20_20", calibration={"method": "sigmoid"}),
         raw_rows(1000, 5, "risk"), True),
        ("tmp.risk time_cv5 + sigmoid", task("risk", calibration={"method": "sigmoid"}), raw_rows(400, 6, "risk"), True),
        ("tmp.anomaly time_60_20_20", task("anomaly"), raw_rows(1000, 7, "anomaly"), True),
        ("tmp.anomaly random", task("anomaly", time_key=None, split="random_60_20_20"), raw_rows(1000, 8, "anomaly"), True),
        ("tmp.anomaly time_cv5", task("anomaly"), raw_rows(300, 9, "anomaly"), True),
    ]
    for name, t, raw, labels in cases:
        out.append(compare(name, std_frame(t, raw), t, FEATS, labels=labels))
    for name, st, meas in out:
        print(f"LEAK  {name:42s} {st:5s} {meas}")


if __name__ == "__main__":
    main()
