"""분할 정책 — 바꿀 수 없는 누수 규칙 (spec §5.3 · std/split_policies.yaml · contracts/interfaces.md §3).

- time_key 가 있으면 시간순(time_60_20_20, 행 < small_rows_threshold 면 time_cv5)을 강제한다. 과제 YAML 의 split 이
  시간순이 아니어도 시간순으로 돌린다(덮어쓰기 불가 규칙).
- group_key 가 있으면 같은 그룹이 경계 양쪽에 있지 않게 자른다.
- 시험 구간 인덱스는 SplitPlan 에 없다. GuardedTest 만 들고 있다.
인덱스는 frame 의 위치(iloc) 이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import numpy as np
import pandas as pd

from ..registry.packs import std
from .guard import AccessLedger, GuardedTest

Policy = Literal["time_60_20_20", "time_cv5", "stratified_60_20_20", "random_60_20_20"]
TIME_POLICIES = ("time_60_20_20", "time_cv5")


@dataclass(frozen=True)
class SplitPlan:
    policy: str
    train_idx: tuple[int, ...]
    valid_idx: tuple[int, ...]
    folds: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...] = ()
    boundaries: dict = field(default_factory=dict)

    @property
    def fit_idx(self) -> tuple[int, ...]:
        """재적합 구간(학습 + 검증). 시험 구간은 들어가지 않는다."""
        return tuple(sorted(set(self.train_idx) | set(self.valid_idx)))


@lru_cache(maxsize=1)
def _policies() -> dict:
    return std("split_policies")


def choose_policy(task, rows: int) -> str:
    raw = task.raw
    rules = _policies()["rules"]
    if raw.get("time_key"):
        if rows < int(rules["small_rows_threshold"]):
            return "time_cv5"
        return "time_60_20_20"
    if raw.get("split") in ("stratified_60_20_20", "random_60_20_20"):
        return raw["split"]
    return "stratified_60_20_20" if task.type == "risk" else "random_60_20_20"


def _time_order(frame: pd.DataFrame) -> np.ndarray:
    keys = [k for k in ("ts", "entity_id") if k in frame.columns]
    return frame.reset_index(drop=True).sort_values(keys, kind="mergesort").index.to_numpy()


def _group_cut(groups: np.ndarray, target: int) -> int:
    """target 에서 가장 가까운, 양쪽 그룹 교집합이 0 인 자르는 위치."""
    n = len(groups)
    first, last = {}, {}
    for i, g in enumerate(groups):
        first.setdefault(g, i)
        last[g] = i
    ok = np.zeros(n + 1, dtype=bool)
    # 위치 c 에서 자를 수 있다 ⇔ [0, c) 의 어떤 그룹도 c 이후에 나오지 않는다
    reach = -1
    ok[0] = True
    for i in range(n):
        reach = max(reach, last[groups[i]])
        ok[i + 1] = reach <= i
    cands = np.flatnonzero(ok)
    return int(cands[np.argmin(np.abs(cands - target))])


def _time_split(frame: pd.DataFrame, task, fr: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    order = _time_order(frame)
    n = len(order)
    a = int(round(n * fr["train"]))
    b = int(round(n * (fr["train"] + fr["valid"])))
    bounds: dict = {"order": "time"}
    if task.raw.get("group_key") and "group" in frame.columns:
        groups = frame["group"].astype(str).to_numpy()[order]
        if len(set(groups)) < n:
            # 같은 그룹이 시간상 섞여 있으면 그룹 블록 순서(첫 등장 시각)로 다시 줄 세운다
            first = {}
            for i, g in enumerate(groups):
                first.setdefault(g, i)
            regroup = np.array(sorted(range(n), key=lambda i: (first[groups[i]], i)))
            if not np.array_equal(regroup, np.arange(n)):
                bounds["regrouped"] = True
            order = order[regroup]
            groups = groups[regroup]
            a = _group_cut(groups, a)
            b = _group_cut(groups, max(b, a))
        bounds["group_key"] = task.raw["group_key"]
    ts = frame["ts"].to_numpy()[order] if "ts" in frame.columns else None
    if ts is not None and n:
        bounds["train_ts"] = [str(ts[0]), str(ts[a - 1])] if a else None
        bounds["valid_ts"] = [str(ts[a]), str(ts[b - 1])] if b > a else None
        bounds["test_ts"] = [str(ts[b]), str(ts[n - 1])] if n > b else None
    bounds["sizes"] = {"train": a, "valid": b - a, "test": n - b}
    return order[:a], order[a:b], order[b:], bounds


def _group_random(frame: pd.DataFrame, fr: dict, rng: np.random.RandomState, *, stratify: bool):
    """group_key 가 있는 비시계열 분할 — 그룹 단위로 섞어 행 수 비율 60/20/20 에 가깝게 자른다(그룹이 경계를 넘지 않는다).
    stratify 면 그룹의 다수 목표값별로 따로 섞어 번갈아 채운다(층화 근사)."""
    g = frame["group"].astype(str).to_numpy()
    sizes = pd.Series(g).value_counts().sort_index()
    names = list(sizes.index)
    if stratify and "target" in frame.columns:
        # 층별로 섞은 뒤 층 안 순위 비율((i + 0.5) / 층 크기)로 합쳐 줄 세운다 — 앞 60% 에 각 층이 비율대로 들어간다
        major = frame.groupby(g)["target"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else -1)
        keyed = []
        for k in sorted(major.unique()):
            members = rng.permutation([nm for nm in names if major[nm] == k])
            keyed += [((i + 0.5) / len(members), str(nm)) for i, nm in enumerate(members)]
        order = [nm for _, nm in sorted(keyed)]
    else:
        order = list(rng.permutation(names))
    n = len(frame)
    a, b = n * fr["train"], n * (fr["train"] + fr["valid"])
    part, acc = {}, 0
    for name in order:
        mid = acc + sizes[name] / 2
        part[name] = 0 if mid <= a else (1 if mid <= b else 2)
        acc += sizes[name]
    lab = np.array([part[x] for x in g])
    return np.flatnonzero(lab == 0), np.flatnonzero(lab == 1), np.flatnonzero(lab == 2)


def plan(frame: pd.DataFrame, task, seed: int, *, ledger: AccessLedger | None = None) -> tuple[SplitPlan, GuardedTest]:
    ledger = ledger if ledger is not None else AccessLedger()
    n = len(frame)
    policy = choose_policy(task, n)
    pol = _policies()["policies"][policy]
    folds: tuple = ()
    if policy == "time_60_20_20":
        tr, va, te, bounds = _time_split(frame, task, pol["fractions"])
    elif policy == "time_cv5":
        tf = float(pol["test_fraction"])
        tr_all, _, te, bounds = _time_split(frame, task, {"train": 1 - tf, "valid": 0.0})
        k = int(pol["folds"])
        m = len(tr_all)
        edges = [int(round(m * (i + 1) / (k + 1))) for i in range(k + 1)]
        if task.raw.get("group_key") and "group" in frame.columns:
            # 폴드 경계도 그룹을 넘지 않게(시험 경계와 같은 규칙) — 끝 경계(m)는 그대로
            gtr = frame["group"].astype(str).to_numpy()[tr_all]
            cut = [_group_cut(gtr, e) for e in edges[:-1]] + [m]
            edges = sorted({c for c in cut if c > 0})
            if len(edges) < k + 1:
                raise ValueError(f"time_cv5: 그룹이 적어 폴드 {k} 개를 만들 수 없다(경계 {len(edges)})")
        folds = tuple((tuple(int(i) for i in tr_all[:edges[i]]), tuple(int(i) for i in tr_all[edges[i]:edges[i + 1]]))
                      for i in range(k))
        # train/valid = 마지막 폴드 (검증 구간 잔차 · 선정은 폴드 전체로)
        tr, va = np.array(folds[-1][0]), np.array(folds[-1][1])
        bounds["folds"] = [{"train": len(f[0]), "valid": len(f[1])} for f in folds]
    else:
        rng = np.random.RandomState(seed)
        fr = pol["fractions"]
        grouped = bool(task.raw.get("group_key")) and "group" in frame.columns
        if grouped:
            tr, va, te = _group_random(frame, fr, rng, stratify=policy == "stratified_60_20_20")
        elif policy == "stratified_60_20_20" and "target" in frame.columns:
            tr, va, te = [], [], []
            for _, idx in sorted(frame.groupby(frame["target"].fillna(-1)).indices.items()):
                idx = rng.permutation(np.asarray(idx))
                a, b = int(round(len(idx) * fr["train"])), int(round(len(idx) * (fr["train"] + fr["valid"])))
                tr += list(idx[:a]); va += list(idx[a:b]); te += list(idx[b:])
            tr, va, te = np.sort(tr), np.sort(va), np.sort(te)
        else:
            idx = rng.permutation(n)
            a, b = int(round(n * fr["train"])), int(round(n * (fr["train"] + fr["valid"])))
            tr, va, te = np.sort(idx[:a]), np.sort(idx[a:b]), np.sort(idx[b:])
        bounds = {"order": pol["order"], "seed": seed, "sizes": {"train": len(tr), "valid": len(va), "test": len(te)}}
        if grouped:
            bounds["group_key"] = task.raw["group_key"]
    sp = SplitPlan(policy, tuple(int(i) for i in tr), tuple(int(i) for i in va), folds, bounds)
    return sp, GuardedTest(te, ledger)
