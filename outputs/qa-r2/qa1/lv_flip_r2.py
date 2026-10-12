"""QA-R2 — DEF-QA1-001 재검증: lv_flip 원 절차(무작위 60그룹) + 분할이 성립하는 그룹 배치(블록 · 시간순 그룹)에서
시험 목표만 교란했을 때 검증 기준선 비교 · 기준선 종류 · beats 가 그대로인가."""
import sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from mlcore.data import snapshot
from mlcore.train import split
from tests._dev1 import FEATS, raw_rows, std_frame, task
from leak_probe import _train

def run(label, lots, n=1000):
    t = task(group_key="lot", candidates=["ridge"])
    raw = raw_rows(n, 11)
    raw["y"] = np.cumsum(np.random.default_rng(1).normal(0, 1, n)) + raw["y"] * 0.05
    raw["lot"] = lots(n)
    f = snapshot.canonical(std_frame(t, raw))
    try:
        sp, _ = split.plan(f, t, 7)
    except split.SplitRefused as e:
        with tempfile.TemporaryDirectory() as d:
            r, _ = _train(f, t, FEATS, Path(d) / "a")
        print(f"{label}: 분할 거부 code={e.code if hasattr(e,'code') else e} · 학습 status={r.status} · report.error={ (r.report or {}).get('error') }")
        return
    rows = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    val = set(sp.valid_idx)
    order = f.sort_values(["ts", "entity_id"], kind="mergesort").index.to_numpy(); pos = {r: k for k, r in enumerate(order)}
    f2 = f.copy(); y = f2["target"].to_numpy(float).copy(); hit = 0
    for r in rows:   # 원 공격: 시험 행 목표를 시각순 다음(검증) 행 목표로
        k = pos[r]
        if k + 1 < n and order[k + 1] in val:
            y[r] = f["target"].iloc[order[k + 1]] + 1000.0; hit += 1
    # 공격이 0행이면 시험 목표 전부를 크게 바꾼다
    if hit == 0:
        y[rows] = y[rows] * 3 + 500
    f2["target"] = y
    with tempfile.TemporaryDirectory() as d:
        a, _ = _train(f, t, FEATS, Path(d) / "a"); b, _ = _train(f2, t, FEATS, Path(d) / "b")
    ba = a.report["baselines_compared"]["valid"]; bb = b.report["baselines_compared"]["valid"]
    same = ba == bb and a.report["baseline"] == b.report["baseline"] and a.beats_baseline == b.beats_baseline
    print(f"{label}: status {a.status}/{b.status} · 원공격 해당 시험행 {hit} · 검증 기준선 A={ba} B={bb} · 종류 {a.report['baseline']}/{b.report['baseline']} · beats {a.beats_baseline}/{b.beats_baseline} → {'PASS 불변' if same else 'FAIL 변함'}")

run("무작위 60그룹(원 재현)", lambda n: [f"G{x:02d}" for x in np.random.default_rng(0).integers(0, 60, n)])
run("완전 섞임 25그룹", lambda n: [f"G{i % 25:02d}" for i in range(n)])
run("블록 40그룹(시간순 연속)", lambda n: [f"G{(i * 40) // n:03d}" for i in range(n)])
run("블록 10그룹", lambda n: [f"G{(i * 10) // n:03d}" for i in range(n)])
