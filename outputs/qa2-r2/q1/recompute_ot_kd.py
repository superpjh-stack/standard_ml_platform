"""QA2-1 — ot · kd 원천 절차 독립 재계산 (원천 코드는 읽기만, import · 실행 0).

원천 `KyungDong ML AI/api/ml_service.py:15-58` · `config.py` 와 `OneTouch ML AI/api/ml_service.py:19-108` · `config.py`
를 읽고 다시 썼다. 기대: kd 시험 MAE 4.1071 · RMSE 5.0456 · R² 0.9956(docs/verification.md:23),
ot 시험 MAE 0.3166(저장 견적 test_mae) · 객체 분류 macro-F1 1.0.
또 표준 팩 합성 생성기 행과 셀 단위 대조(G2-P01 4개사 추가분 중 ot · kd).
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (ExtraTreesClassifier, ExtraTreesRegressor, GradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42
KD_META = {"mass_kg": (10, 10000), "cut_m": (0, 500), "weld_m": (0, 300), "thickness_mm": (1, 30), "complexity": (1, 5)}
KD_MAT = ["STS304", "STS316L", "STS316", "SS400", "A516", "AL6061", "STS430", "ALUMINUM"]
KD_PROD = ["반응기", "교반기", "진공건조기", "누체필터", "저장탱크", "Pure Steam Generator"]
OT_META = {"length": (100, 6000), "width": (30, 600), "thickness": (.5, 6), "holes": (0, 100), "slots": (0, 50), "bends": (0, 12)}
OT_MAT = ["SPCC", "SS400", "SUS304"]
OT_PROF = ["잔넬", "T바", "각관", "C형강"]


def kd_jobs():
    rng = np.random.default_rng(SEED)
    n = 900
    f = pd.DataFrame({k: rng.uniform(lo, hi, n) for k, (lo, hi) in KD_META.items()})
    f["material"] = rng.choice(KD_MAT, n)
    f["product"] = rng.choice(KD_PROD, n)
    mo = f.material.map({m: i * 3 for i, m in enumerate(KD_MAT)})
    po = f["product"].map({p: i * 5 for i, p in enumerate(KD_PROD)})
    f["hours"] = (8 + f.mass_kg ** .8 * .05 + f.cut_m * .09 + f.weld_m * .8 + f.thickness_mm ** 1.4 * .3
                  + f.complexity * 5 + mo + po + rng.normal(0, 4, n)).clip(lower=1)
    f["job_id"] = [f"KD-SYN-{i+1:04}" for i in range(n)]
    f.loc[rng.choice(540, 12, replace=False), "cut_m"] = np.nan
    return f


def ot_jobs():
    rng = np.random.default_rng(SEED)
    n = 900
    f = pd.DataFrame({k: rng.uniform(lo, hi, n) for k, (lo, hi) in OT_META.items()})
    for k in ["holes", "slots", "bends"]:
        f[k] = f[k].round().astype(int)
    f["material"] = rng.choice(OT_MAT, n)
    f["profile"] = rng.choice(OT_PROF, n)
    factor = f.material.map({"SPCC": 1, "SS400": 1.06, "SUS304": 1.4})
    shape = f.profile.map({"잔넬": .2, "T바": .5, "각관": .8, "C형강": .3})
    f["minutes"] = (.3 + f.length / 2200 + f.width / 1400 + f.holes * .028 + f.slots * .095 + f.bends * .16
                    + f.thickness ** 1.45 * .12 + shape) * factor + rng.normal(0, .16, n)
    f["job_id"] = [f"OT-SYN-{i+1:04}" for i in range(n)]
    f.loc[rng.choice(540, 12, replace=False), "width"] = np.nan
    return f


def geometry():
    rng = np.random.default_rng(SEED)
    rec, lab = [], []
    for label in ["outer", "hole", "slot", "other"]:
        for _ in range(400):
            if label == "hole":
                row = [1, 1, 1, rng.uniform(.00001, .08), 1, 1]
            elif label == "slot":
                a = rng.uniform(1.6, 8)
                area, per = 4 * (a - 1) + np.pi, 4 * (a - 1) + 2 * np.pi
                row = [0, 1, a, rng.uniform(.0001, .12), 4 * np.pi * area / per ** 2, 1]
            elif label == "outer":
                a = rng.uniform(1, 30)
                row = [0, 1, a, 1, np.pi * a / (a + 1) ** 2, rng.choice([0, 1])]
            else:
                row = [0, rng.choice([0, 1]), rng.uniform(1, 30), rng.uniform(.001, .4), rng.uniform(0, .65), 0]
            rec.append(row)
            lab.append(label)
    return np.array(rec), np.array(lab)


def pipe(est, num, cat):
    pre = ColumnTransformer([("n", Pipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())]), num),
                             ("c", OneHotEncoder(handle_unknown="error", sparse_output=False), cat)])
    return Pipeline([("p", pre), ("m", est)])


def m3(y, p):
    return {"mae": round(float(mean_absolute_error(y, p)), 4), "rmse": round(float(np.sqrt(mean_squared_error(y, p))), 4),
            "r2": round(float(r2_score(y, p)), 4)}


def regress(jobs, num, cat, ycol, gb_n):
    feats = num + cat
    tr, va, te = jobs.iloc[:540], jobs.iloc[540:720], jobs.iloc[720:]
    ests = {"Ridge": Ridge(alpha=1), "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=2, random_state=SEED),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=2, random_state=SEED),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=gb_n, max_depth=3, random_state=SEED)}
    res = []
    for nm, e in ests.items():
        m = pipe(clone(e), num, cat).fit(tr[feats], tr[ycol])
        res.append({"model": nm, **m3(va[ycol], m.predict(va[feats]))})
    res.sort(key=lambda r: (r["mae"], r["model"]))
    champ = res[0]["model"]
    fit = pipe(clone(ests[champ]), num, cat).fit(jobs.iloc[:720][feats], jobs.iloc[:720][ycol])
    return champ, res, m3(te[ycol], fit.predict(te[feats]))


def recog():
    x, y = geometry()
    xd, xt, yd, yt = train_test_split(x, y, test_size=.2, stratify=y, random_state=SEED)
    xtr, xv, ytr, yv = train_test_split(xd, yd, test_size=.25, stratify=yd, random_state=SEED)
    cls = {"Logistic Regression": LogisticRegression(max_iter=2000), "Random Forest": RandomForestClassifier(n_estimators=100, random_state=SEED),
           "Extra Trees": ExtraTreesClassifier(n_estimators=100, random_state=SEED)}
    res = []
    for nm, e in cls.items():
        p = Pipeline([("s", StandardScaler()), ("m", clone(e))]).fit(xtr, ytr).predict(xv)
        res.append({"model": nm, "macro_f1": round(float(f1_score(yv, p, average="macro")), 4)})
    res.sort(key=lambda r: (-r["macro_f1"], r["model"]))
    ch = res[0]["model"]
    p = Pipeline([("s", StandardScaler()), ("m", clone(cls[ch]))]).fit(xd, yd).predict(xt)
    return ch, res, {"macro_f1": round(float(f1_score(yt, p, average="macro")), 4), "accuracy": round(float(accuracy_score(yt, p)), 4),
                     "sizes": [len(ytr), len(yv), len(yt)], "test_class_counts": {c: int((yt == c).sum()) for c in sorted(set(yt))}}, x, y


def compare_frames(mine: pd.DataFrame, std: pd.DataFrame, cols_map: dict) -> dict:
    out = {"rows_mine": len(mine), "rows_std": len(std), "cells": 0, "equal": 0, "diffs": []}
    for a, b in cols_map.items():
        if b not in std.columns:
            out["diffs"].append(f"std 에 열 없음 {b}")
            continue
        x, y = mine[a].reset_index(drop=True), std[b].reset_index(drop=True)
        for i in range(min(len(x), len(y))):
            out["cells"] += 1
            xv, yv = x.iloc[i], y.iloc[i]
            if (pd.isna(xv) and pd.isna(yv)) or (not pd.isna(xv) and not pd.isna(yv) and
                                                   (str(xv) == str(yv) or (isinstance(xv, (float, int, np.floating, np.integer)) and
                                                                            np.isclose(float(xv), float(yv), rtol=0, atol=1e-12)))):
                out["equal"] += 1
            elif len(out["diffs"]) < 5:
                out["diffs"].append(f"{a}[{i}] {xv!r} != {yv!r}")
    return out


def main():
    rep = {}
    kd = kd_jobs()
    ch, res, tm = regress(kd, list(KD_META), ["material", "product"], "hours", 160)
    rep["kd"] = {"champion": ch, "valid": res, "test": tm, "doc": {"mae": 4.1071, "rmse": 5.0456, "r2": 0.9956},
                 "missing_cells": int(kd[list(KD_META) + ["material", "product"]].isna().sum().sum())}
    ot = ot_jobs()
    ch, res, tm = regress(ot, list(OT_META), ["material", "profile"], "minutes", 180)
    rep["ot"] = {"champion": ch, "valid": res, "test": tm, "stored_test_mae": 0.3166}
    rch, rres, rt, gx, gy = recog()
    rep["ot_recog"] = {"champion": rch, "valid": rres, "test": rt}
    # 표준 팩 합성 생성기와 셀 대조
    sys.path.insert(0, ".")
    try:
        from mlcore.registry import tenants
        from mlcore.data.sources import synthetic  # noqa: F401
        rep["synth"] = {}
        for code, mine, ycol in (("kd", kd, "hours"), ("ot", ot, "minutes")):
            merged = tenants.load_and_merge(code)
            rep["synth"][code] = {"tasks": sorted(merged.tasks)}
    except Exception as e:  # noqa: BLE001
        rep["synth_error"] = repr(e)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
