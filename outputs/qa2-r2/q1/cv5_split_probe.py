"""QA2-1 — 평창 재측정 분할 time_cv5: 경계 · 그룹 · 같은 시각 (pc 실제 프레임 + 임시 과제 변형).

판정(모든 폴드 · 시험 경계): (1) 시간순 — 앞 구간 최대 ts ≤ 뒤 구간 최소 ts, 같은 ts 가 양쪽에 없다 (2) group_key 가 양쪽에 없다
(3) 시험 = 시간순 마지막 ≈20% (4) 폴드 검증 구간끼리 겹치지 않고, 폴드 학습 ⊂ 시험 이전.
변형: pc 원본 · 같은 시각 3행 묶음 · 같은 시각 7행 묶음 · group_key(연속 블록) · group_key 섞임(거부 기대) · 420 행 경계(499/500).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.train import split  # noqa: E402
from _dev1 import raw_rows, std_frame, task  # noqa: E402


def check(frame, t):
    try:
        sp, _ = split.plan(frame, t, seed=0)
    except split.SplitRefused as e:
        return {"refused": e.code}
    n = len(frame)
    te = sorted(set(range(n)) - set(sp.fit_idx))
    ts = pd.to_datetime(frame["ts"])
    g = frame["group"].astype(str) if "group" in frame.columns and t.raw.get("group_key") else None
    probs = []

    def pair(a, b, name):
        if not len(a) or not len(b):
            return
        if ts.iloc[list(a)].max() > ts.iloc[list(b)].min():
            probs.append(f"{name}: 시간 역전")
        if set(ts.iloc[list(a)]) & set(ts.iloc[list(b)]):
            probs.append(f"{name}: 같은 시각이 양쪽")
        if g is not None and set(g.iloc[list(a)]) & set(g.iloc[list(b)]):
            probs.append(f"{name}: 그룹이 양쪽")
    for i, (tr, va) in enumerate(sp.folds or ((sp.train_idx, sp.valid_idx),)):
        pair(tr, va, f"fold{i} 학습|검증")
        pair(va, te, f"fold{i} 검증|시험")
        pair(tr, te, f"fold{i} 학습|시험")
    vals = [set(va) for _, va in (sp.folds or ())]
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            if vals[i] & vals[j]:
                probs.append(f"검증 폴드 {i}·{j} 겹침")
    return {"policy": sp.policy, "n": n, "test": len(te), "test_frac": round(len(te) / n, 4),
            "folds": [(len(a), len(b)) for a, b in (sp.folds or ())], "problems": probs}


def main():
    out = {}
    m, t, frame, ref, syn = jobs.read_frame("pc", "pc.sensory_score", source_role="demo")
    frame = snapshot.canonical(frame)
    out["pc_real"] = check(frame, t)
    for n, ties in ((420, 1), (420, 3), (420, 7), (499, 3), (500, 3)):
        tk = task(time_key="ts", split="time_60_20_20")
        r = raw_rows(n, 5)
        r["ts"] = pd.Timestamp("2025-01-01", tz="Asia/Seoul") + pd.to_timedelta((np.arange(n) // ties) * 12, unit="h")
        out[f"ties{ties}_n{n}"] = check(snapshot.canonical(std_frame(tk, r)), tk)
    # group_key 연속 블록(시간순으로 묶인 LOT) — 가능해야 한다
    tk = task(time_key="ts", group_key="lot", split="time_60_20_20")
    r = raw_rows(420, 6, groups=60)
    r = r.sort_values("ts").reset_index(drop=True)
    r["lot"] = [f"L{i // 7:03d}" for i in range(len(r))]
    f = std_frame(tk, r)
    out["group_blocks"] = check(snapshot.canonical(f), tk) if "group" in f.columns else {"note": "group 열 없음", "cols": list(f.columns)}
    # group 섞임 — 거부 기대
    r2 = raw_rows(420, 7, groups=60)
    r2["lot"] = np.random.default_rng(3).permutation(r2["lot"].to_numpy())   # 그룹을 시간상 섞는다
    f2 = std_frame(tk, r2)
    out["group_mixed"] = check(snapshot.canonical(f2), tk) if "group" in f2.columns else {"note": "group 열 없음", "cols": list(f2.columns)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
