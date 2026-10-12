"""QA2-1 — krs · pc 원천 절차 독립 재계산 + 4 팩 합성 생성기 행 일치 (원천 코드는 읽기만, import · 실행 0).

원천 `Koreal Solder ML AI/api/ml_service.py:31-122 · 168-200` · `PyoungChang ML AI/api/ml_service.py:36-70` 을 읽고 다시 썼다.
ot · kd 생성기는 `recompute_ot_kd.py` 의 다시 쓴 함수를 쓴다. 표준 쪽은 팩 `synth/*.py generate(categories=회사 범주)`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler, StandardScaler
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import recompute_ot_kd as okd  # noqa: E402

# ── krs ─────────────────────────────────────────
K_FEAT = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct", "temperature_c", "mixing_min", "supplier"]
K_NUM = K_FEAT[:-1]
K_T = "joint_strength_mpa"


def krs_data(rows=720):
    rng = np.random.default_rng(20260917)
    ag = rng.uniform(.35, 4.0, rows); cu = rng.uniform(.15, 1.05, rows); sb = rng.uniform(0, 1.7, rows)
    flux = rng.uniform(.08, .72, rows); sn = 100 - ag - cu - sb - flux
    temp = rng.normal(246, 8, rows).clip(226, 268); mixing = rng.normal(53, 14, rows).clip(20, 88)
    sup = rng.choice(["A", "B", "C"], rows, p=[.45, .35, .2])
    st = (31 + 5.8 * ag + 2.4 * cu + 1.25 * sb - 2.0 * (flux - .28) ** 2 - .055 * (temp - 246) ** 2 - .009 * (mixing - 54) ** 2
          + np.where(sup == "A", 1.1, np.where(sup == "B", .3, -.7)) + rng.normal(0, 1.8, rows))
    df = pd.DataFrame({"lot_id": [f"KS-{20240000 + i:08d}" for i in range(rows)], "sn_pct": sn, "ag_pct": ag, "cu_pct": cu,
                       "sb_pct": sb, "flux_pct": flux, "temperature_c": temp, "mixing_min": mixing, "supplier": sup, K_T: st})
    for c in ["ag_pct", "temperature_c", "mixing_min"]:
        df.loc[rng.choice(rows, 8, replace=False), c] = np.nan
    df.loc[rng.choice(rows, 5, replace=False), "temperature_c"] = rng.choice([145, 352], 5)
    return df


def krs_clean(df):
    mask = pd.Series(False, index=df.index)
    for c in K_NUM:
        q1, q3 = df[c].quantile([.25, .75]); iqr = q3 - q1
        mask |= ((df[c] < q1 - 1.5 * iqr) | (df[c] > q3 + 1.5 * iqr)).fillna(False)
    return df.loc[~mask].copy(), int(mask.sum())


def krs_pipe(m):
    num = Pipeline([("i", SimpleImputer(strategy="median")), ("s", RobustScaler())])
    cat = Pipeline([("i", SimpleImputer(strategy="most_frequent")), ("o", OneHotEncoder(handle_unknown="ignore", sparse_output=False))])
    return Pipeline([("p", ColumnTransformer([("n", num, K_NUM), ("c", cat, ["supplier"])])), ("m", m)])


def krs():
    data = krs_data(); cl, removed = krs_clean(data)
    tr, te = train_test_split(cl, test_size=.2, random_state=42)
    cands = {"Decision Tree": DecisionTreeRegressor(max_depth=8, min_samples_leaf=5, random_state=42),
             "SVR": SVR(C=20, epsilon=.15, gamma="scale"),
             "Random Forest": RandomForestRegressor(n_estimators=180, max_depth=10, random_state=42, n_jobs=1),
             "Gradient Boosting": GradientBoostingRegressor(n_estimators=180, max_depth=3, learning_rate=.04, random_state=42),
             "Extra Trees": ExtraTreesRegressor(n_estimators=180, max_depth=12, random_state=42, n_jobs=1)}
    scores, fitted = [], {}
    for nm, e in cands.items():
        p = krs_pipe(e).fit(tr[K_FEAT], tr[K_T]); fitted[nm] = p; pr = p.predict(te[K_FEAT])
        scores.append({"name": nm, "mae": float(mean_absolute_error(te[K_T], pr)), "rmse": float(mean_squared_error(te[K_T], pr) ** .5),
                       "r2": float(r2_score(te[K_T], pr))})
    scores.sort(key=lambda r: round(r["rmse"], 3))
    ch = scores[0]["name"]
    sc = cl.dropna(subset=[K_T]).copy()
    sc["ae"] = (sc[K_T] - fitted[ch].predict(sc[K_FEAT])).abs()
    return data, {"rows": len(data), "cleaned": len(cl), "removed": removed, "champion": ch,
                  "test": {k: round(v, 4) for k, v in scores[0].items() if k != "name"}, "all": scores,
                  "residual_queue_in_sample": {"scored": len(sc), "ge4": int((sc.ae >= 4).sum()), "shown": min(12, int((sc.ae >= 0).sum()))},
                  "iqr_rows_removed_from_test_side": int(len(te))}


# ── pc ─────────────────────────────────────────
P_COMP = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]
P_NUM = P_COMP + ["brine_salinity_pct", "brining_hours", "fermentation_temp_c", "fermentation_hours", "storage_temp_c"]
P_CAT = ["cabbage_origin", "line"]
P_FEAT = P_NUM + P_CAT
P_LIM = {"cabbage_pct": (66.0, 76.0), "radish_pct": (5.0, 11.0), "seasoning_pct": (15.0, 23.0), "salt_pct": (1.2, 2.6),
         "brine_salinity_pct": (9.0, 13.0), "brining_hours": (8.0, 16.0), "fermentation_temp_c": (2.0, 8.0),
         "fermentation_hours": (18.0, 72.0), "storage_temp_c": (-1.0, 4.0)}


def pc_data(rows=420):
    rng = np.random.default_rng(42); L = P_LIM
    cab = rng.uniform(*L["cabbage_pct"], rows); rad = rng.uniform(*L["radish_pct"], rows); salt = rng.uniform(*L["salt_pct"], rows)
    sea = 100 - cab - rad - salt
    ok = (sea >= L["seasoning_pct"][0]) & (sea <= L["seasoning_pct"][1])
    while not ok.all():
        n = int((~ok).sum()); cab[~ok] = rng.uniform(*L["cabbage_pct"], n); rad[~ok] = rng.uniform(*L["radish_pct"], n)
        salt[~ok] = rng.uniform(*L["salt_pct"], n); sea = 100 - cab - rad - salt
        ok = (sea >= L["seasoning_pct"][0]) & (sea <= L["seasoning_pct"][1])
    sal = rng.uniform(*L["brine_salinity_pct"], rows); bri = rng.uniform(*L["brining_hours"], rows)
    ft = rng.uniform(*L["fermentation_temp_c"], rows); fh = rng.uniform(*L["fermentation_hours"], rows); stt = rng.uniform(*L["storage_temp_c"], rows)
    org = rng.choice(["평창", "강릉", "기타계약"], rows, p=[.68, .20, .12]); line = rng.choice(["K1", "K2"], rows, p=[.58, .42])
    score = (86 - abs(sal - 11.1) * 2 - abs(bri - 12) * .65 - abs(ft - 4.8) * 1.15 - abs(fh - 42) * .13 - abs(stt - 1) * .8
             - abs(sea - 19.5) * .45 + (org == "평창") * .8 + (line == "K2") * .25 + rng.normal(0, 1.8, rows))
    f = pd.DataFrame({"lot_id": [f"PC-K-{i+1:04d}" for i in range(rows)], "produced_at": pd.date_range("2025-01-02", periods=rows, freq="12h"),
                      "cabbage_pct": cab, "radish_pct": rad, "seasoning_pct": sea, "salt_pct": salt, "brine_salinity_pct": sal,
                      "brining_hours": bri, "fermentation_temp_c": ft, "fermentation_hours": fh, "storage_temp_c": stt,
                      "cabbage_origin": org, "line": line, "sensory_score": score})
    for c in ["brine_salinity_pct", "fermentation_temp_c", "storage_temp_c"]:
        f.loc[rng.choice(rows, 5, replace=False), c] = np.nan
    return f


def pc_pipe(m):
    num = Pipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())])
    cat = Pipeline([("i", SimpleImputer(strategy="most_frequent")), ("e", OneHotEncoder(handle_unknown="ignore"))])
    return Pipeline([("p", ColumnTransformer([("n", num, P_NUM), ("c", cat, P_CAT)])), ("m", m)])


def pc():
    d = pc_data(); T = "sensory_score"
    tr, te = train_test_split(d, test_size=.22, random_state=42)
    cands = {"릿지 회귀": Ridge(alpha=1.0), "엑스트라 트리": ExtraTreesRegressor(n_estimators=180, min_samples_leaf=3, random_state=42),
             "그래디언트 부스팅": GradientBoostingRegressor(random_state=42, n_estimators=140, max_depth=2)}
    rk = []
    for nm, e in cands.items():
        pr = pc_pipe(e).fit(tr[P_FEAT], tr[T]).predict(te[P_FEAT])
        rk.append({"model": nm, "mae": float(mean_absolute_error(te[T], pr)), "r2": float(r2_score(te[T], pr)),
                   "rmse": float(sqrt(mean_squared_error(te[T], pr)))})
    rk.sort(key=lambda r: round(r["mae"], 3)); ch = rk[0]["model"]
    final = pc_pipe(cands[ch]).fit(d[P_FEAT], d[T]); pin = final.predict(d[P_FEAT]); res = np.abs(d[T] - pin)
    thr = float(np.quantile(res, .9))
    return d, {"champion": ch, "test": {k: round(rk[0][k], 4) for k in ("mae", "r2", "rmse")}, "all": rk,
               "in_sample": {"mae": round(float(mean_absolute_error(d[T], pin)), 4), "r2": round(float(r2_score(d[T], pin)), 4)},
               "residual_threshold_in_sample_q90": round(thr, 4), "over": int((res > thr).sum()), "ge": int((res >= thr).sum())}


# ── 행 일치 ─────────────────────────────────────
def gen(pack, mod, tenant):
    s = importlib.util.spec_from_file_location(f"qa21_{pack}_{mod}", ROOT / "packs" / pack / "synth" / f"{mod}.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    cats = (yaml.safe_load((ROOT / "tenants" / f"{tenant}.yaml").read_text(encoding="utf-8")) or {}).get("categories") or {}
    try:
        return m.generate(categories=cats)
    except TypeError:
        return m.generate()


def cmp(mine, std, cmap):
    cells = eq = 0; diffs = []
    if len(mine) != len(std):
        diffs.append(f"행 수 {len(mine)} != {len(std)}")
    for a, b in cmap.items():
        x, y = mine[a].reset_index(drop=True), std[b].reset_index(drop=True)
        for i in range(min(len(x), len(y))):
            cells += 1; xv, yv = x.iloc[i], y.iloc[i]
            same = (pd.isna(xv) and pd.isna(yv)) if (pd.isna(xv) or pd.isna(yv)) else (
                float(xv) == float(yv) if isinstance(xv, (int, float, np.integer, np.floating)) and not isinstance(xv, bool) else str(xv) == str(yv))
            eq += bool(same)
            if not same and len(diffs) < 5:
                diffs.append(f"{a}[{i}] {xv!r} != {yv!r}")
    return {"rows": [len(mine), len(std)], "cells": cells, "equal": eq, "pct": round(100 * eq / max(cells, 1), 4), "diffs": diffs}


def main():
    out = {}
    kdata, out["krs"] = krs()
    pdata, out["pc"] = pc()
    rows = {}
    s = gen("solder", "solder_lots", "krs")
    km = kdata.assign(supplier=kdata.supplier.map({"A": "공급사A", "B": "공급사B", "C": "공급사C"}))
    rows["krs"] = cmp(km, s, {**{c: c for c in K_NUM}, "supplier": "supplier", K_T: K_T})
    s = gen("kimchi", "kimchi_lots", "pc")
    rows["pc"] = cmp(pdata, s, {**{c: c for c in P_NUM}, "cabbage_origin": "cabbage_origin", "line": "prod_line", "sensory_score": "sensory_score"})
    ts_same = all(pd.Timestamp(a) == pd.Timestamp(b).tz_localize(None) for a, b in zip(pdata.produced_at, s.ts))
    rows["pc"]["ts_wallclock_equal"] = bool(ts_same)
    s = gen("rollform-quote", "jobs", "ot"); o = okd.ot_jobs()
    rows["ot_jobs"] = cmp(o, s, {"length": "part_length_mm", "width": "blank_width_mm", "thickness": "sheet_thickness_mm", "holes": "hole_count",
                                 "slots": "slot_count", "bends": "bend_count", "material": "steel_grade", "profile": "section_profile", "minutes": "machining_minutes"})
    s = gen("rollform-quote", "cad_objects", "ot"); gx, gy = okd.geometry()
    g = pd.DataFrame(gx, columns=["circle", "closed", "aspect", "relative_area", "circularity", "curved"]); g["label"] = gy
    rows["ot_objects"] = cmp(g, s, {"circle": "is_circle", "closed": "is_closed", "aspect": "aspect_ratio", "relative_area": "area_ratio",
                                    "circularity": "circularity", "curved": "is_curved", "label": "label"})
    s = gen("eto", "jobs", "kd"); k = okd.kd_jobs()
    rows["kd_jobs"] = cmp(k, s, {"mass_kg": "total_mass_kg", "cut_m": "cut_m", "weld_m": "weld_m", "thickness_mm": "thickness_mm",
                                 "complexity": "complexity", "material": "main_material", "product": "product_family", "hours": "labor_hours"})
    out["rows"] = rows
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
