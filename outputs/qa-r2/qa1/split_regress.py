"""QA-R2 회귀 — split_time_group_conflict 가 정상 과제를 거부하지 않는가 · 같은 시각 묶음 · 4 정책."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.data import snapshot
from mlcore.train import split
from tests._dev1 import raw_rows, std_frame, task

def chk(label, t, raw):
    f = snapshot.canonical(std_frame(t, raw))
    try:
        sp, _ = split.plan(f, t, seed=7)
    except split.SplitRefused as e:
        print(f"{label:46s} REFUSED {e}"); return
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    ts = f["ts"] if "ts" in f.columns else None
    msg = f"크기 {len(sp.train_idx)}/{len(sp.valid_idx)}/{len(te)}"
    if ts is not None and t.raw.get("time_key"):
        tr, va, tt = ts.iloc[list(sp.train_idx)], ts.iloc[list(sp.valid_idx)], ts.iloc[te]
        order_ok = (tr.max() < va.min() if len(va) else True) and ((va.max() if len(va) else tr.max()) < tt.min())
        tie = len(set(tr) & set(va)) + len(set(va) & set(tt))
        msg += f" · 시간순 {'OK' if order_ok else 'BROKEN'} · 같은시각 교차 {tie}"
    if "group" in f.columns and f["group"].notna().any():
        g = f["group"]; a, b, c = (set(g.iloc[list(i)]) for i in (sp.train_idx, sp.valid_idx, te))
        msg += f" · 그룹교차 {len(a&b)+len(b&c)+len(a&c)}"
    msg += f" · cut_moved={sp.boundaries.get('cut_moved')}"
    print(f"{label:46s} OK      {msg}")

for n in (1000, 400, 120):
    chk(f"group 없음 n={n}", task(), raw_rows(n, 3))
r = raw_rows(1000, 4); r["ts"] = pd.date_range("2026-01-01", periods=250, freq="h", tz="Asia/Seoul").repeat(4)
chk("group 없음 · 같은 시각 4행", task(), r)
r = raw_rows(1002, 4); r["ts"] = pd.date_range("2026-01-01", periods=334, freq="h", tz="Asia/Seoul").repeat(3)
chk("group 없음 · 같은 시각 3행 (DEF-QA1-008)", task(), r)
r = raw_rows(1000, 5); r["lot"] = [f"G{(i*40)//1000:03d}" for i in range(1000)]
chk("group 블록 40", task(group_key="lot"), r)
r = raw_rows(1000, 5); lots = [(i*40)//1000 for i in range(1000)]
for i in range(1, 1000):
    if lots[i] != lots[i-1]: lots[i-1], lots[i] = lots[i], lots[i-1]   # 경계마다 1행 교차
r["lot"] = [f"G{x:03d}" for x in lots]
chk("group 블록 40 · 모든 경계 1행 교차", task(group_key="lot"), r)
r = raw_rows(1000, 5); lots = [(i*40)//1000 for i in range(1000)]
for k, i in enumerate(range(1, 1000)):
    if lots[i] != lots[i-1] and lots[i] % 4: lots[i-1], lots[i] = lots[i], lots[i-1]
r["lot"] = [f"G{x:03d}" for x in lots]
chk("group 블록 40 · 경계 3/4 교차(1/4 깨끗)", task(group_key="lot"), r)
r = raw_rows(1000, 6); r["lot"] = [f"M{i%2}-{(i//2*2*20)//1000:03d}" for i in range(1000)]
chk("설비 2대 병렬 · LOT 동시 진행(정렬 경계)", task(group_key="lot"), r)
r = raw_rows(1000, 6); r["lot"] = [f"M{i%2}-{((i//2 + (i%2)*12)*2*20)//1000:03d}" for i in range(1000)]
chk("설비 2대 병렬 · LOT 엇갈림", task(group_key="lot"), r)
r = raw_rows(400, 7); r["lot"] = [f"G{(i*20)//400:03d}" for i in range(400)]
chk("time_cv5 블록 20 n=400", task(group_key="lot", split="time_cv5"), r)
r = raw_rows(1000, 8, "risk"); r["lot"] = [f"G{i%25:02d}" for i in range(1000)]
chk("stratified 섞인 그룹(시간 무관)", task("risk", group_key="lot", time_key=None, split="stratified_60_20_20"), r)
r = raw_rows(1000, 8); r["lot"] = [f"G{i%25:02d}" for i in range(1000)]
chk("random 섞인 그룹", task(group_key="lot", time_key=None, split="random_60_20_20"), r)
