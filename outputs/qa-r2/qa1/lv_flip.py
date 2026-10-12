"""QA1 — DEF-QA1-001 재현: 시험 구간 목표만 바꿔 last_value/train_mean 기준선 선택(→ beats_baseline)을 뒤집을 수 있는가.
시험 행 r 의 목표를 '시각순 다음 행(검증 구간)의 목표' 로 바꾼다 → 그 검증 행의 last_value 가 완벽해진다.
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/lv_flip.py"""
import sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "outputs" / "qa-r2" / "qa1"))
from mlcore.data import snapshot
from tests._dev1 import FEATS, raw_rows, std_frame, task
from leak_probe import _test_rows, _train

t = task(group_key="lot", candidates=["ridge"])
n = 1000
raw = raw_rows(n, 11)
# 목표에 강한 시간 자기상관 + 그룹 무작위 배치
raw["y"] = np.cumsum(np.random.default_rng(1).normal(0, 1, n)) + raw["y"] * 0.05
raw["lot"] = [f"G{x:02d}" for x in np.random.default_rng(0).integers(0, 60, n)]
f = snapshot.canonical(std_frame(t, raw))
rows, sp = _test_rows(f, t, 7)
order = f.sort_values(["ts", "entity_id"], kind="mergesort").index.to_numpy()
pos = {r: k for k, r in enumerate(order)}
tes = set(rows); val = set(sp.valid_idx)
f2 = f.copy(); y = f2["target"].to_numpy(float).copy()
hit = 0
for r in rows:
    k = pos[r]
    if k + 1 < n and order[k + 1] in val:
        y[r] = f["target"].iloc[order[k + 1]] + 1000.0; hit += 1
f2["target"] = y
with tempfile.TemporaryDirectory() as d:
    a, _ = _train(f, t, FEATS, Path(d) / "a")
    b, _ = _train(f2, t, FEATS, Path(d) / "b")
for nm, r in (("원본", a), ("시험목표만 교란", b)):
    bc = r.report["baselines_compared"]["valid"]
    print(f"{nm}: 바뀐 시험행 {hit if r is b else 0} · 검증 MAE train_mean {bc['train_mean']['mae']:.4f} last_value {bc['last_value']['mae']:.4f}"
          f" → 기준선 {r.report['baseline']} · 시험 MAE {r.report['test_metrics']['mae']['value']:.4f} 기준선 {r.report['test_metrics']['mae']['baseline']:.4f} · beats {r.beats_baseline}")
