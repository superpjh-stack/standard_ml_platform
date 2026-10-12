"""QA1 G-M12 — 원천 ks · sw `api/ml_service.py` · `config.py` 를 **읽고 QA 가 다시 쓴** 재계산(원천 저장소는 실행하지 않는다).

원천 근거: KwangSung ML AI/api/ml_service.py:20-38(demo_data) · :74-108(state) · config.py:2-19
           SongWol ML AI/api/ml_service.py:29-57(true_delta_e · demo_data) · :93-126(state) · config.py:2-28
1) 원천 demo_data() 를 QA 사본으로 만들어 팩 합성 생성기(jobs.read_frame demo)와 셀 단위 대조.
2) 원천 state() 절차(시간순 432/144/144 · 검증 선정 · 학습+검증 재적합 · 시험 1회)를 QA 사본으로 돌려 지표 재계산.
3) docs/migration-report.md 표준 재현값 · 원천 문서값과 대조.
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/migration_recompute.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingClassifier, GradientBoostingRegressor,
                              IsolationForest, RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, brier_score_loss, mean_absolute_error, mean_squared_error,
                             r2_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SEED = 42

# ── ks 원천 사본 ─────────────────────────────────────────
KS_META = {"press_force": (180, 320), "vibration": (0.4, 8), "motor_current": (30, 85), "equip_temp": (30, 85),
           "mold_temp": (25, 70), "cycle_time": (6, 15), "shot_count": (5000, 180000)}
KS_MACHINES = ["PRS-01", "PRS-02", "PRS-03", "PRS-04"]
KS_PRODUCTS = ["FRONT SHELL", "CENTER PLATE", "DIAPHRAGM PLATE"]


def ks_demo(rows=720):
    rng = np.random.default_rng(SEED)
    d = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, (lo, hi) in KS_META.items()})
    d["shot_count"] = d.shot_count.round().astype(int)
    d["machine"] = rng.choice(KS_MACHINES, rows)
    d["product"] = rng.choice(KS_PRODUCTS, rows)
    wear = (d.shot_count / 180000 * 55 + d.vibration ** 1.35 * 3 + np.maximum(d.equip_temp - 50, 0) * .65
            + abs(d.press_force - 250) * .12 + np.maximum(d.motor_current - 60, 0) * .5 + np.maximum(d.mold_temp - 50, 0) * .2)
    d["remaining_hours"] = np.clip(155 - wear + rng.normal(0, 5, rows), 1, 180)
    p = 1 / (1 + np.exp(np.clip((d["remaining_hours"] - 40) / 13, -30, 30)))
    d["failure_24h"] = rng.binomial(1, p)
    d["recorded_at"] = pd.date_range("2026-08-01", periods=rows, freq="h")
    for k in ["vibration", "motor_current", "mold_temp"]:
        d.loc[rng.choice(rows, 8, replace=False), k] = np.nan
    return d


# ── sw 원천 사본 ─────────────────────────────────────────
SW_CTRL = {"set_temp": (140, 210), "set_pressure": (2, 6), "line_speed": (6, 24), "ink_usage": (10, 30), "dwell_time": (20, 80)}
SW_FAB = {"absorb_rate": (60, 98), "fabric_strength": (220, 480)}
SW_META = {**SW_CTRL, **SW_FAB}
OPT_T = {"나염": 160, "승화": 195, "DTF": 165}
OPT_P = {"나염": 3.5, "승화": 4.5, "DTF": 4.0}
OPT_I = {"연한 색상": 14, "중간 색상": 19, "진한 색상": 25}


def sw_true(d):
    temp = ((d.set_temp - d.print_type.map(OPT_T)) / 24) ** 2 * .75
    pres = ((d.set_pressure - d.print_type.map(OPT_P)) / 1.6) ** 2 * .35
    cure = (np.maximum(0, d.line_speed - 12) * .07 + np.maximum(0, 45 - d.dwell_time) * .025
            + np.maximum(0, d.line_speed - 12) * np.maximum(0, 45 - d.dwell_time) * .006)
    ink = abs(d.ink_usage - d.color_tone.map(OPT_I)) * .08
    bleed = np.where(d.print_type == "나염", np.maximum(0, d.absorb_rate - 85) * .07, 0) + np.maximum(0, 72 - d.absorb_rate) * .045
    fabric = np.maximum(0, 300 - d.fabric_strength) * .005
    return .8 + temp + pres + cure + ink + bleed + fabric


def sw_demo(rows=720):
    rng = np.random.default_rng(SEED)
    d = pd.DataFrame({k: rng.uniform(lo, hi, rows) for k, (lo, hi) in SW_META.items()})
    d["print_type"] = rng.choice(["나염", "승화", "DTF"], rows, p=[.45, .35, .2])
    d["color_tone"] = rng.choice(["연한 색상", "중간 색상", "진한 색상"], rows)
    d["delta_e"] = np.clip(sw_true(d) + rng.normal(0, .35, rows), .2, 12)
    p = 1 / (1 + np.exp(np.clip(-(d["delta_e"] - 3.8) / .45, -30, 30)))
    d["defect"] = rng.binomial(1, p)
    d["recorded_at"] = pd.date_range("2026-08-01 08:00", periods=rows, freq="h")
    for k in ["absorb_rate", "fabric_strength", "ink_usage"]:
        d.loc[rng.choice(rows, 8, replace=False), k] = np.nan
    for k in SW_META:
        d[k] = d[k].round(2)
    d["delta_e"] = d["delta_e"].round(3)
    return d


def pipe(est, num, cat):
    prep = ColumnTransformer([("n", Pipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())]), num),
                              ("c", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat)])
    return Pipeline([("p", prep), ("e", est)])


def reg_m(y, p):
    return {"mae": float(mean_absolute_error(y, p)), "rmse": float(np.sqrt(mean_squared_error(y, p))), "r2": float(r2_score(y, p))}


def cls_m(y, p):
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)), "brier": float(brier_score_loss(y, p))}


def source_state(d, num, cat, target, label, regs, clss, *, round_pred=None, round_prob=None):
    feats = num + cat
    tr, va, te = d.iloc[:432], d.iloc[432:576], d.iloc[576:]
    rv = {n: reg_m(va[target], pipe(e, num, cat).fit(tr[feats], tr[target]).predict(va[feats])) for n, e in regs.items()}
    cv = {n: cls_m(va[label], pipe(e, num, cat).fit(tr[feats], tr[label]).predict_proba(va[feats])[:, 1]) for n, e in clss.items()}
    # 원천: 지표를 소수 3 · 4자리로 반올림한 뒤 (값, 이름) 정렬
    champ = sorted(rv, key=lambda n: (round(rv[n]["mae"], 3), n))[0]
    rchamp = sorted(cv, key=lambda n: (round(cv[n]["brier"], 4), n))[0]
    dev = d.iloc[:576]
    m = pipe(clone(regs[champ]), num, cat).fit(dev[feats], dev[target])
    rm = pipe(clone(clss[rchamp]), num, cat).fit(dev[feats], dev[label])
    an = pipe(IsolationForest(n_estimators=100, contamination=.08, random_state=SEED), num, cat).fit(dev[feats])
    pred = m.predict(te[feats])
    prob = rm.predict_proba(te[feats])[:, 1]
    if round_pred is not None:
        pred = pred.round(round_pred)
    if round_prob is not None:
        prob_r = prob.round(round_prob)
    else:
        prob_r = prob
    flag = float((an.predict(te[feats]) == -1).mean())
    return {"champion": champ, "valid": rv[champ], "risk_champion": rchamp, "test": reg_m(te[target], pred),
            "risk_test": cls_m(te[label], prob_r), "risk_test_unrounded": cls_m(te[label], prob), "flag_rate": flag}


def main():
    from mlcore.data import jobs

    out = []
    # 1) 행 일치
    for tenant, tid, src, cmap in [
        ("ks", "ks.remaining_hours", ks_demo(), {"machine": "machine_code", "product": "product_type"}),
        ("sw", "sw.delta_e", sw_demo(), {}),
    ]:
        _, t, frame, _, _ = jobs.read_frame(tenant, tid)
        f = frame.sort_values("ts").reset_index(drop=True)
        s = src.rename(columns=cmap).reset_index(drop=True)
        cols = [c for c in s.columns if c in f.columns and c not in ("recorded_at",)]
        tgt = (t.raw.get("target") or {}).get("name")
        mism, cells = 0, 0
        for c in cols + ([tgt] if tgt else []):
            a = s[c]
            b = f["target"] if c == tgt else f[c]
            if pd.api.types.is_numeric_dtype(a):
                eq = (np.isclose(a.astype(float), b.astype(float), rtol=0, atol=1e-12) | (a.isna() & b.isna()))
            else:
                eq = a.astype(str) == b.astype(str)
            mism += int((~eq).sum())
            cells += len(a)
        tsok = bool((pd.to_datetime(s["recorded_at"]).dt.tz_localize("Asia/Seoul").values == f["ts"].values).all())
        out.append(("G-M12", f"행 일치 {tenant} demo_data ↔ 팩 synth", "PASS" if mism == 0 and len(s) == len(f) and tsok else "FAIL",
                    f"행 {len(s)}/{len(f)} · 비교 열 {len(cols) + 1} · 셀 {cells} · 불일치 {mism} · 시각 일치 {tsok}"))
    # 2) 원천 절차 재계산
    ks = source_state(ks_demo(), list(KS_META), ["machine", "product"], "remaining_hours", "failure_24h",
                      {"Ridge": Ridge(alpha=3), "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=3, random_state=SEED),
                       "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=3, random_state=SEED),
                       "Gradient Boosting": GradientBoostingRegressor(n_estimators=120, max_depth=2, random_state=SEED)},
                      {"Logistic Regression": LogisticRegression(max_iter=500),
                       "Random Forest": RandomForestClassifier(n_estimators=100, min_samples_leaf=5, random_state=SEED),
                       "Gradient Boosting": GradientBoostingClassifier(n_estimators=80, max_depth=2, random_state=SEED)})
    sw = source_state(sw_demo(), list(SW_META), ["print_type", "color_tone"], "delta_e", "defect",
                      {"Ridge": Ridge(alpha=3), "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=3, random_state=SEED),
                       "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=3, random_state=SEED),
                       "Gradient Boosting": GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=.05, random_state=SEED)},
                      {"Logistic Regression": LogisticRegression(max_iter=1000),
                       "Random Forest": RandomForestClassifier(n_estimators=100, min_samples_leaf=5, random_state=SEED),
                       "Gradient Boosting": GradientBoostingClassifier(n_estimators=80, max_depth=2, random_state=SEED)},
                      round_pred=3, round_prob=4)
    # 3) 대조: (QA 재계산 원천값, migration-report 표준 재현값, 원천 문서값)
    report = {
        "ks.remaining_hours": [("mae", ks["test"]["mae"], 5.5683, 5.568), ("rmse", ks["test"]["rmse"], 6.9793, 6.979), ("r2", ks["test"]["r2"], 0.9199, 0.9199)],
        "ks.failure_24h": [("roc_auc", ks["risk_test"]["roc_auc"], 0.6444, 0.6444), ("pr_auc", ks["risk_test"]["pr_auc"], 0.1426, 0.1426), ("brier", ks["risk_test"]["brier"], 0.0576, 0.0576)],
        "sw.delta_e": [("mae", sw["test"]["mae"], 0.5569, 0.557), ("rmse", sw["test"]["rmse"], 0.7088, 0.709), ("r2", sw["test"]["r2"], 0.7222, 0.722)],
        "sw.defect_risk": [("roc_auc", sw["risk_test"]["roc_auc"], 0.8686, 0.868), ("pr_auc", sw["risk_test"]["pr_auc"], 0.7823, 0.781), ("brier", sw["risk_test"]["brier"], 0.1261, 0.127)],
    }
    for task, rows in report.items():
        for m, qa, std_rep, doc in rows:
            d_std = (std_rep - qa) / qa * 100
            d_doc = (doc - qa) / qa * 100
            st = "PASS" if abs(d_std) <= 10 else "FAIL"
            out.append(("G-M12", f"{task} {m}", st,
                        f"QA 원천 재계산 {qa:.4f} · 보고서 표준 {std_rep} (Δ {d_std:+.2f}%) · 원천 문서 {doc} (Δ {d_doc:+.2f}%)"))
    out.append(("G-M12", "ks 챔피언", "PASS" if (ks["champion"], ks["risk_champion"]) == ("Gradient Boosting", "Random Forest") else "FAIL",
                f"QA 재계산 회귀 {ks['champion']} · 위험 {ks['risk_champion']} (보고서 gbr · rf_clf) · 검증 MAE {ks['valid']['mae']:.4f}"))
    out.append(("G-M12", "sw 챔피언", "PASS" if (sw["champion"], sw["risk_champion"]) == ("Extra Trees", "Gradient Boosting") else "FAIL",
                f"QA 재계산 회귀 {sw['champion']} · 위험 {sw['risk_champion']} (보고서 extra_trees · gbc) · 검증 MAE {sw['valid']['mae']:.4f}"))
    u = sw["risk_test_unrounded"]
    out.append(("G-M12", "sw.defect_risk 반올림 전 확률", "INFO",
                f"원천은 시험 확률을 4자리 반올림 후 채점(ml_service.py:117) — 반올림 전 AUC {u['roc_auc']:.4f} · AP {u['pr_auc']:.4f} · Brier {u['brier']:.4f}"))
    out.append(("G-M12", "이상 탐지 원천 규칙 flag_rate", "INFO",
                f"원천 규칙(재적합 표본 내 contamination) 시험 flag ks {ks['flag_rate']:.4f} · sw {sw['flag_rate']:.4f} (보고서 §4 D-50: 0.160 · 0.167)"))
    for g, n, s, m in out:
        print(f"{g}  {n:36s} {s:5s} {m}")


if __name__ == "__main__":
    main()
