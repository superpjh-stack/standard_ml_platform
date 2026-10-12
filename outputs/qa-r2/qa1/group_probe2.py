"""QA1 — (1) 무작위 그룹 배치에서 last_value 기준선이 시험 목표를 보는가 (2) 같은 시각 3행 묶음이 경계에서 갈라지는가.
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/group_probe2.py"""
import sys, json, tempfile
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "outputs" / "qa-r2" / "qa1"))
from mlcore.data import snapshot
from mlcore.train import split
from tests._dev1 import FEATS, raw_rows, std_frame, task
from leak_probe import compare, _test_rows, _perturb, _train

for n, kw in [(1000, {}), (400, {})]:
    t = task(group_key="lot")
    raw = raw_rows(n, 11)
    raw["lot"] = [f"G{x:02d}" for x in np.random.default_rng(0).integers(0, 60, n)]
    f = snapshot.canonical(std_frame(t, raw))
    name, st, meas = compare(f"lv-random60-{n}", f, t, FEATS)
    print("LV", n, st, meas)
    # 상세: 검증 기준선 비교 값 차이
    try:
        rows, sp = _test_rows(f, t, 7)
    except split.SplitRefused as e:
        print("   R2: 분할 거부", getattr(e, "code", "")); continue
    with tempfile.TemporaryDirectory() as d:
        r1, _ = _train(f, t, FEATS, Path(d) / "a")
        r2, _ = _train(_perturb(f, rows, t, FEATS), t, FEATS, Path(d) / "b")
    print("   valid baselines A:", json.dumps(r1.report.get("baselines_compared", {}) and r1.report["baselines_compared"]["valid"], default=str)[:300])
    print("   valid baselines B:", json.dumps(r2.report.get("baselines_compared", {}) and r2.report["baselines_compared"]["valid"], default=str)[:300])
    print("   baseline kind A/B:", r1.report["baseline"], r2.report["baseline"], "beats A/B:", r1.beats_baseline, r2.beats_baseline)

# 같은 시각 3행
t = task()
raw = raw_rows(1002, 12)
raw["ts"] = pd.date_range("2026-01-01", periods=334, freq="h", tz="Asia/Seoul").repeat(3)
f = snapshot.canonical(std_frame(t, raw))
sp, test = split.plan(f, t, seed=7)
te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
ts = f["ts"]
print("TIE sizes", len(sp.train_idx), len(sp.valid_idx), len(te),
      "train∩valid ts", len(set(ts.iloc[list(sp.train_idx)]) & set(ts.iloc[list(sp.valid_idx)])),
      "valid∩test ts", len(set(ts.iloc[list(sp.valid_idx)]) & set(ts.iloc[te])))
