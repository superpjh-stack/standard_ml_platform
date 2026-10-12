"""QA1 — group 경계 · 시간순 · last_value 기준선 누수 (4 정책 전부 + time_cv5 폴드 경계).
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/group_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "outputs" / "qa-r2" / "qa1"))

from mlcore.data import snapshot  # noqa: E402
from mlcore.train import split  # noqa: E402
# R2: LAST_VALUE · with_last_value 제거됨(D-85)
from tests._dev1 import FEATS, raw_rows, std_frame, task  # noqa: E402
from leak_probe import compare  # noqa: E402


def sets(frame, sp):
    te = sorted(set(range(len(frame))) - set(sp.train_idx) - set(sp.valid_idx))
    g = frame["group"]
    return [set(g.iloc[list(ix)]) for ix in (sp.train_idx, sp.valid_idx, te)], te


def main():
    out = []
    layouts = {
        "블록(연속 LOT 40)": lambda n: [f"G{(i * 40) // n:03d}" for i in range(n)],
        "완전 섞임(25)": lambda n: [f"G{i % 25:02d}" for i in range(n)],
        "무작위(60)": lambda n: [f"G{x:02d}" for x in np.random.default_rng(0).integers(0, 60, n)],
    }
    pols = [("time_60_20_20", dict(), 1000, "regression"), ("time_cv5", dict(), 400, "regression"),
            ("stratified_60_20_20", dict(time_key=None, split="stratified_60_20_20"), 1000, "risk"),
            ("random_60_20_20", dict(time_key=None, split="random_60_20_20"), 1000, "regression")]
    for lname, gen in layouts.items():
        for pname, kw, n, tt in pols:
            t = task(tt, group_key="lot", **kw)
            raw = raw_rows(n, 11, tt)
            raw["lot"] = gen(n)
            f = snapshot.canonical(std_frame(t, raw))
            try:
                sp, test = split.plan(f, t, seed=7)
            except ValueError as e:
                out.append(("G-M05", f"group {pname} {lname}", "PASS", f"분할 거부(실패를 보임): {e}"))
                continue
            (a, b, c), te = sets(f, sp)
            cross = len(a & b) + len(b & c) + len(a & c)
            fold_cross = 0
            for ftr, fva in sp.folds:
                fold_cross += len(set(f["group"].iloc[list(ftr)]) & set(f["group"].iloc[list(fva)]))
            meas = f"교차 그룹 {cross} · 폴드 교차 {fold_cross} · 크기 {len(sp.train_idx)}/{len(sp.valid_idx)}/{len(te)}"
            if pname.startswith("time"):
                ts = f["ts"]
                fut = int((ts.iloc[list(sp.train_idx)].to_numpy()[:, None] > ts.iloc[te].to_numpy()[None, :]).any(axis=1).sum())
                fut_v = int((ts.iloc[list(sp.valid_idx)].to_numpy()[:, None] > ts.iloc[te].to_numpy()[None, :]).any(axis=1).sum()) if sp.valid_idx else 0
                meas += f" · 시험 최초 시각보다 늦은 학습행 {fut} · 검증행 {fut_v} · regrouped={sp.boundaries.get('regrouped', False)}"
                # last_value 기준선: 검증 행의 직전(시각순) 행이 시험 구간인가
                if tt == "regression":
                    order = f.sort_values(["ts", "entity_id"], kind="mergesort").index.to_numpy()
                    pos = {r: k for k, r in enumerate(order)}
                    tes = set(te)
                    prev_in_test = sum(1 for r in sp.valid_idx if pos[r] > 0 and order[pos[r] - 1] in tes)
                    prev_in_test_tr = sum(1 for r in sp.train_idx if pos[r] > 0 and order[pos[r] - 1] in tes)
                    meas += f" · 직전 행이 시험인 검증행 {prev_in_test} · 학습행 {prev_in_test_tr}"
                st = "FAIL" if cross or fold_cross else ("WARN" if fut or fut_v else "PASS")
            else:
                st = "FAIL" if cross else "PASS"
            out.append(("G-M05", f"group {pname} {lname}", st, meas))
    # 같은 시각 다수 행(설비 여러 대) — 경계에서 같은 ts 가 갈라지는가 (group 없음)
    t = task()
    raw = raw_rows(1000, 12)
    raw["ts"] = pd.date_range("2026-01-01", periods=250, freq="h", tz="Asia/Seoul").repeat(4)
    f = snapshot.canonical(std_frame(t, raw))
    sp, _ = split.plan(f, t, seed=7)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    ts = f["ts"]
    tie_tv = len(set(ts.iloc[list(sp.train_idx)]) & set(ts.iloc[list(sp.valid_idx)]))
    tie_vt = len(set(ts.iloc[list(sp.valid_idx)]) & set(ts.iloc[te]))
    out.append(("G-M05", "같은 시각 행이 경계 양쪽", "WARN" if tie_tv or tie_vt else "PASS",
                f"학습∩검증 시각 {tie_tv} · 검증∩시험 시각 {tie_vt} (4행/시각, 1000행)"))
    # last_value 기준선 누수 — 섞인 그룹 + 시계열 회귀에서 시험 목표를 바꾸면 검증 기준선 비교가 바뀌는가
    t = task(group_key="lot")
    raw = raw_rows(1000, 13)
    raw["lot"] = [f"G{i % 25:02d}" for i in range(1000)]
    out.append(("G-M05", "last_value(섞인 그룹) 시험값 교란",) + compare("grouped", std_frame(t, raw), t, FEATS)[1:])
    for g, name, st, meas in out:
        print(f"{g}  {name:40s} {st:5s} {meas}")


if __name__ == "__main__":
    main()
