"""이관 대조 재현 (M5 · G-M12) — 표준 플랫폼 학습기로 과제 8 을 합성 시드 그대로 다시 잰다. 개발3 (1차) · 개발1 (2차 krs · pc).

    OMP_NUM_THREADS=1 uv run python migration/reproduce.py            # 표 출력 (1차 ks · sw)
    OMP_NUM_THREADS=1 uv run python migration/reproduce.py --json out.json
    OMP_NUM_THREADS=1 uv run python migration/reproduce.py --phase2   # 2차 krs · pc → outputs/reproduce-krs-pc.json

2차(아래 `run_phase2`)는 원천 보고 수치가 없으므로(D2-12) **원천 절차 재현값**을 이 도구가 다시 계산해 표준 값과 나란히 둔다 —
원천 코드를 읽어 같은 시드 · 같은 절차(전처리 · 분할 · 후보 · 선정 · 대기열 · 탐색)를 여기 다시 썼다(원천 import · 실행 0).

- 학습 과제 6: 회사 `demo`(synthetic, 시드 42) → 표준 프레임 → 스냅숏(임시 폴더) → `StandardTrainer`(개발1) 시험 1회 지표.
  보고 수치는 **시험 구간만**(표본 내 · 학습 구간 지표는 쓰지 않는다).
- optimize 2: 원천 시험과 같은 요청(기본 입력 · 기본 제약)으로 표준 규칙의 격자를 이 도구가 직접 센다 —
  조절 변수 = `min + k·step` 중 [학습 p1, p99] ∩ [min, max](의존 모델 lock 의 교집합), 결정 변수 = [min, params 상한].
  의존 과제 모델은 위에서 학습한 산출물(model.joblib · features.lock.json). 운영 경로(`tasks/optimize.py`, 개발2)와
  같은 규칙이지만 등록부 · 승인을 거치지 않는 재현 계산이다.
원천 저장소는 읽기만 했고 실행하지 않는다. 원천 보고값은 migration/source_inventory.md §1.4 · §1.5 · §2.4 · §2.5.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.registry import tenants  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig  # noqa: E402

LEARNED = {"ks": ["remaining_hours", "failure_24h", "sensor_ood"], "sw": ["delta_e", "defect_risk", "print_ood"]}
# 원천 시험이 쓴 요청 (KwangSung · SongWol tests/test_api.py — source_inventory §1.5 · §2.5)
OPT_REQUEST = {
    "ks": {"task": "maintenance_timing", "categories": {"machine_code": 0, "product_type": 0},
           "params": {"reserve_hours": 12, "max_delay_hours": 48, "max_cost_index": 140}},
    "sw": {"task": "print_setpoint", "fixed_cat": {"print_type": "나염", "color_tone": "진한 색상"},
           "params": {"max_delta_e": 2.5, "max_risk": 0.2, "min_line_speed": 12}},
}
OPT_INFEASIBLE = {"ks": {"reserve_hours": 150, "max_delay_hours": 48, "max_cost_index": 1},
                  "sw": {"max_delta_e": 0.5, "max_risk": 0.01, "min_line_speed": 24}}


def _artifact(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def train_all(work: Path) -> dict:
    out = {}
    for code, names in LEARNED.items():
        for name in names:
            tid = f"{code}.{name}"
            m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo")
            s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref=ref, synthetic=syn, base_dir=work / "snap")
            cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
            r = StandardTrainer(artifact_root=work / "art", snapshot_dir=work / "snap").train(cfg)
            out[tid] = {"type": t.type, "status": r.status, "champion": r.champion, "beats_baseline": r.beats_baseline,
                        "rows": len(frame), "split": (r.report.get("split") or {}).get("boundaries", {}).get("sizes"),
                        "test": {k: {"value": v.value, "baseline": v.baseline, "delta": v.delta_vs_baseline}
                                 for k, v in r.test_metrics.items()},
                        "valid": (r.valid_metrics or {}).get(r.champion or "", {}),
                        "artifact_dir": str(_artifact(r.artifact_dir)) if r.artifact_dir else None,
                        "snapshot_sha256": s.sha256}
    return out


def _load(art: str):
    import joblib

    d = Path(art)
    return joblib.load(d / "model.joblib"), json.loads((d / "features.lock.json").read_text(encoding="utf-8"))


def _lattice(lo, hi, base, step):
    k0 = math.ceil((lo - base) / step - 1e-9)
    k1 = math.floor((hi - base) / step + 1e-9)
    return [round(base + k * step, 10) for k in range(k0, k1 + 1)]


def _formula(pack_dir: Path, module: str):
    spec = importlib.util.spec_from_file_location(f"repro_{module}", pack_dir / "formulas" / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


def _score(model, lock, frame: pd.DataFrame, ttype: str) -> np.ndarray:
    x = frame[lock["order"]]
    if ttype == "risk":
        return model.predict_proba(x)[:, 1]
    y = model.predict(x)
    clip = (lock.get("clip") or {}).get("min")
    return np.maximum(clip, y) if clip is not None else y


def optimize(code: str, trained: dict, params: dict | None = None) -> dict:
    m = tenants.load_and_merge(code, tenants_base=tenants.TENANTS_DIR)
    req = OPT_REQUEST[code]
    task = m.tasks[f"{code}.{req['task']}"].raw
    feats = m.pack.features
    cats = m.tenant.config.get("categories") or {}
    params = {**{k: v["default"] for k, v in (task.get("params") or {}).items()}, **(params or req["params"])}
    uses = []
    for u in task["uses"]:
        short = u.split(".", 1)[1]
        tid = f"{code}.{short}"
        model, lock = _load(trained[tid]["artifact_dir"])
        uses.append((short, trained[tid]["type"], model, lock))
    # 고정 입력 = 원천 시험 record (기본값 · 범주 첫 값/지정 값)
    base_row = {}
    for f in task.get("fixed") or []:
        d = feats[f]
        if d.get("dtype") == "category":
            base_row[f] = (req.get("fixed_cat") or {}).get(f) or (cats.get(f) or d.get("values"))[0]
        else:
            base_row[f] = d["default"]
    axes = {}
    for c in task.get("controls") or []:
        d = feats[c]
        lo, hi = d["min"], d["max"]
        for _, _, _, lock in uses:
            it = lock["features"].get(c) or {}
            if it.get("p1") is not None:
                lo, hi = max(lo, it["p1"]), min(hi, it["p99"])
        axes[c] = _lattice(lo, hi, d["min"], d["step"])
    for name, d in (task.get("decision_vars") or {}).items():
        hi = params[d["max_param"]] if d.get("max_param") else d["max"]
        axes[name] = _lattice(float(d["min"]), float(hi), float(d["min"]), float(d["step"]))
    names = list(axes)
    pts = pd.DataFrame(list(itertools.product(*[axes[n] for n in names])), columns=names) if names else pd.DataFrame()
    frame = pts.copy()
    for k, v in base_row.items():
        if k not in frame.columns:
            frame[k] = v
    for c in task.get("controls") or []:
        base_row.setdefault(c, feats[c]["default"])
    env = {n: frame[n].to_numpy(dtype=float) for n in names}
    for short, ttype, model, lock in uses:
        env[short] = _score(model, lock, frame, ttype)
    for fname, module in (task.get("formulas") or {}).items():
        cost = _formula(m.pack.path, module)
        rows = frame.assign(**{k: v for k, v in env.items() if k not in frame.columns}).to_dict("records")
        env[fname] = np.array([cost(r, params) for r in rows])
    env.update({k: float(v) for k, v in params.items()})
    viol = np.zeros(len(frame))
    for c in task["constraints"]:
        lhs, op, rhs = _split(c["expr"])
        a, b = _ev(lhs, env, len(frame)), _ev(rhs, env, len(frame))
        over = np.maximum(0, a - b) if op in ("<=", "<") else np.maximum(0, b - a)
        viol = viol + over / np.maximum(np.abs(b), 1e-9)
    feasible = viol <= 1e-10
    obj = task["objective"]
    key = obj.get("minimize") or obj.get("maximize")
    best = None
    if feasible.any():
        order = np.lexsort(tuple(reversed([_sortkey(o, env) for o in [obj] + list(obj.get("tiebreak") or [])])))
        idx = [i for i in order if feasible[i]][0]
        best = {n: float(frame[n].iloc[idx]) for n in names} | {key: float(env[key][idx])}
    return {"task": f"{code}.{req['task']}", "candidate_count": int(len(frame)), "feasible_count": int(feasible.sum()),
            "axes": {n: len(v) for n, v in axes.items()}, "best": best, "params": params}


def _split(expr: str):
    for op in ("<=", ">=", "<", ">"):
        if op in expr:
            lhs, rhs = expr.split(op, 1)
            return lhs.strip(), op, rhs.strip()
    raise ValueError(expr)


def _ev(side: str, env: dict, n: int):
    val = eval(compile(side, "<expr>", "eval"), {"__builtins__": {}}, env)   # noqa: S307 — 과제 YAML 식(이름 · + - *)
    return np.broadcast_to(np.asarray(val, dtype=float), (n,))


def _sortkey(o: dict, env: dict):
    if "minimize" in o:
        return env[o["minimize"]]
    return -env[o["maximize"]]


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="mlp-repro-") as d:
        work = Path(d)
        trained = train_all(work)
        opt = {code: {"default": optimize(code, trained), "infeasible": optimize(code, trained, OPT_INFEASIBLE[code])}
               for code in ("ks", "sw")}
        for t in trained.values():
            t["artifact_dir"] = None
        return {"learned": trained, "optimize": opt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--phase2", action="store_true", help="2차 krs · pc (기본 출력 outputs/reproduce-krs-pc.json)")
    ap.add_argument("--tenants-base", type=Path, default=None, help="회사 등록부 폴더(기본 저장소 tenants/)")
    a = ap.parse_args(argv)
    if a.phase2:
        res = run_phase2(tenants_base=a.tenants_base)
        res["meta"]["tenants_base"] = "tenants/" if a.tenants_base is None else "임시 등록부(저장소 등록부 준비 전)"
        path = a.json or ROOT / "outputs" / "reproduce-krs-pc.json"
        write_json(res, path)
        print(phase2_table(res))
        print(f"→ {path}")
        return 0
    res = run()
    text = json.dumps(res, ensure_ascii=False, indent=1, default=float)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0



# ══ 2차 — krs(팩 solder) · pc(팩 kimchi) ═════════════════════════════════════════════════════════════════
# 원천 근거: migration/source_inventory.md §8(krs `api/ml_service.py`) · §9(pc `api/ml_service.py`), 원천 결함 K1~K7 · P1~P4(§13).
# 원천 시험 요청: krs `tests/test_api.py:17`(target 47 · 공급사 첫 값 · max_cost 없음) · pc `tests/test_api.py:18`(목표 80 · 상한 85 · 산지 첫 값 · 라인 둘째 값).

PHASE2_TASKS = {"krs": ("joint_strength", "recipe_optimize", "residual_review"),
                "pc": ("sensory_score", "recipe_optimize", "residual_review")}
_LAST_BASE = None            # 마지막 run_phase2 의 등록부 폴더(시험이 같은 원천 프레임을 다시 만들 때)


def _merged(code: str, tenants_base=None):
    return tenants.load_and_merge(code, tenants_base=tenants_base) if tenants_base else tenants.load_and_merge(code)


def source_frame(code: str, task_id: str, *, tenants_base=None) -> pd.DataFrame:
    """팩 합성 생성기(원천 생성기 이관 — 행 일치 100%) 출력을 회사 범주 값으로. 원천 열 이름으로는 바꾸지 않는다(같은 값)."""
    m = _merged(code, tenants_base)
    return tenants.synth_call(m, task_id).generate()


def _reg_metrics(y, p) -> dict:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    return {"mae": float(mean_absolute_error(y, p)), "rmse": float(mean_squared_error(y, p) ** .5), "r2": float(r2_score(y, p))}


def _src_pipeline(est, numeric, categorical, scaler):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
    num = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", scaler())])
    cat = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))])
    return Pipeline([("prepare", ColumnTransformer([("numeric", num, numeric), ("category", cat, categorical)])), ("model", est)])


# ── 원천 절차 재현: krs (`ml_service.py:59-122` · `:125-145` · `:169-195`) ───────────────────────────────
KRS_NUM = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct", "temperature_c", "mixing_min"]
KRS_FEATS = KRS_NUM + ["supplier"]
KRS_TARGET = "joint_strength_mpa"
KRS_COST = {"sn_pct": 31.0, "ag_pct": 1220.0, "cu_pct": 14.0, "sb_pct": 22.0, "flux_pct": 85.0}
KRS_REQUEST = {"target_strength": 47.0, "max_cost": None, "supplier_index": 0, "supplier_source": "A"}   # 원천 시험 :17


def krs_source(frame: pd.DataFrame) -> dict:
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import RobustScaler
    from sklearn.svm import SVR
    from sklearn.tree import DecisionTreeRegressor
    df = frame.drop(columns=["ts"], errors="ignore")
    mask = pd.Series(False, index=df.index)
    for col in KRS_NUM:                                         # :63-68 — 분할 전 전체에서 경계(K6)
        q1, q3 = df[col].quantile([.25, .75])
        iqr = q3 - q1
        mask |= ((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).fillna(False)
    cleaned = df.loc[~mask].copy()
    train, test = train_test_split(cleaned, test_size=.2, random_state=42)      # :96
    cands = {"decision_tree": DecisionTreeRegressor(max_depth=8, min_samples_leaf=5, random_state=42),
             "svr": SVR(C=20, epsilon=.15, gamma="scale"),
             "random_forest": RandomForestRegressor(n_estimators=180, max_depth=10, random_state=42, n_jobs=1),
             "gbr": GradientBoostingRegressor(n_estimators=180, max_depth=3, learning_rate=.04, random_state=42),
             "extra_trees": ExtraTreesRegressor(n_estimators=180, max_depth=12, random_state=42, n_jobs=1)}
    fitted, scores = {}, []
    for name, est in cands.items():
        pipe = _src_pipeline(est, KRS_NUM, ["supplier"], RobustScaler).fit(train[KRS_FEATS], train[KRS_TARGET])
        fitted[name] = pipe
        scores.append({"name": name, **_reg_metrics(test[KRS_TARGET], pipe.predict(test[KRS_FEATS]))})
    scores.sort(key=lambda r: r["rmse"])                         # :116 — 시험 RMSE 선정(K1)
    champ = scores[0]["name"]
    model = fitted[champ]
    # 대기열 :171-175 — 정제 데이터 전체(학습 80% 포함)를 채점(K4)
    scored = cleaned.dropna(subset=[KRS_TARGET])
    err = np.abs(scored[KRS_TARGET].to_numpy() - model.predict(scored[KRS_FEATS]))
    queue = {"threshold": 4.0, "scored_rows": int(len(scored)), "scored_rows_scope": "cleaned_all_rows_incl_train",
             "flagged": int((err >= 4).sum()), "queue_shown": int(min(12, len(scored))), "mean_abs_error": float(err.mean())}
    return {"rows": int(len(df)), "rows_after_outlier": int(len(cleaned)), "outlier_rows_removed": int(mask.sum()),
            "outlier_scope": "all_rows_before_split", "split": {"train": int(len(train)), "test": int(len(test))},
            "candidates": scores, "champion": champ, "test": {k: scores[0][k] for k in ("mae", "rmse", "r2")},
            "preprocess": "median + RobustScaler · most_frequent + OneHot"}, model, queue


def krs_source_optimize(model, supplier: str, supplier_source: str, target: float, max_cost) -> dict:
    """원천 recommend() :125-145 — 시드 int(target×100)+ord(원천 공급사 값) · 연속 균등 5,000 · 미충족이면 전체 표본 최저 비용(K2)."""
    rng = np.random.default_rng(int(target * 100) + ord(supplier_source))
    rows = []
    for _ in range(5000):
        ag, cu, sb, flux = rng.uniform(.35, 4.0), rng.uniform(.15, 1.05), rng.uniform(0, 1.7), rng.uniform(.08, .72)
        rows.append({"ag_pct": ag, "cu_pct": cu, "sb_pct": sb, "flux_pct": flux, "sn_pct": 100 - ag - cu - sb - flux,
                     "temperature_c": rng.uniform(232, 260), "mixing_min": rng.uniform(35, 75), "supplier": supplier})
    f = pd.DataFrame(rows)
    f["pred"] = model.predict(f[KRS_FEATS])
    f["cost"] = sum(f[c] * p / 100 for c, p in KRS_COST.items())
    ok = f.pred >= target
    if max_cost is not None:
        ok &= f.cost <= max_cost
    pool = f[ok] if ok.any() else f
    best = pool.sort_values(["cost", "pred"], ascending=[True, False]).iloc[0]
    return {"n_points": 5000, "feasible": bool(ok.any()), "feasible_rate": float(ok.mean()),
            "best": {**{c: float(best[c]) for c in KRS_NUM}, "joint_strength": float(best.pred), "cost_index": float(best.cost)},
            "seed": int(target * 100) + ord(supplier_source), "sampling": "연속 균등(ag · cu · sb · flux 생성 범위, 온도 232~260, 혼합 35~75)",
            "on_infeasible": "전체 표본 최저 비용(위반량 무시 — K2)", "returned": 1}


# ── 원천 절차 재현: pc (`ml_service.py:58-106` · `main.py:42-47`) ────────────────────────────────────────
PC_COMP = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]
PC_NUM = PC_COMP + ["brine_salinity_pct", "brining_hours", "fermentation_temp_c", "fermentation_hours", "storage_temp_c"]
PC_CAT = ["cabbage_origin", "prod_line"]
PC_TARGET = "sensory_score"
PC_LIMITS = {"cabbage_pct": (66.0, 76.0), "radish_pct": (5.0, 11.0), "seasoning_pct": (15.0, 23.0), "salt_pct": (1.2, 2.6),
             "brine_salinity_pct": (9.0, 13.0), "brining_hours": (8.0, 16.0), "fermentation_temp_c": (2.0, 8.0),
             "fermentation_hours": (18.0, 72.0), "storage_temp_c": (-1.0, 4.0)}
PC_COST = {"cabbage_pct": 0.55, "radish_pct": 0.32, "seasoning_pct": 1.55, "salt_pct": 0.12}
PC_REQUEST = {"target_score": 80.0, "max_material_cost": 85.0, "origin_index": 0, "line_index": 1}       # 원천 시험 :18


def pc_source(frame: pd.DataFrame) -> tuple[dict, object, dict]:
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    data = frame.drop(columns=["ts"], errors="ignore")
    feats = PC_NUM + PC_CAT
    train, test = train_test_split(data, test_size=.22, random_state=42)        # :71 무작위(P3)
    cands = {"ridge": Ridge(alpha=1.0), "extra_trees": ExtraTreesRegressor(n_estimators=180, min_samples_leaf=3, random_state=42),
             "gbr": GradientBoostingRegressor(random_state=42, n_estimators=140, max_depth=2)}
    ranked = []
    for name, est in cands.items():
        pipe = _src_pipeline(clone(est), PC_NUM, PC_CAT, StandardScaler).fit(train[feats], train[PC_TARGET])
        ranked.append({"name": name, **_reg_metrics(test[PC_TARGET], pipe.predict(test[feats]))})
    ranked.sort(key=lambda r: r["mae"])                         # :78 — 시험 MAE 선정(P1)
    champ = ranked[0]["name"]
    final = _src_pipeline(clone(cands[champ]), PC_NUM, PC_CAT, StandardScaler).fit(data[feats], data[PC_TARGET])   # 전체 재적합
    pred = final.predict(data[feats])
    resid = np.abs(data[PC_TARGET].to_numpy() - pred)
    thr = float(np.quantile(resid, .9))                         # :79 — 표본 내 0.9 분위(P2)
    queue = {"threshold": thr, "threshold_from": "in_sample_refit_q90", "scored_rows": int(len(data)),
             "scored_rows_scope": "all_rows_refit_model", "above_threshold": int((resid > thr).sum()), "queue_shown": 8}
    return {"rows": int(len(data)), "split": {"train": int(len(train)), "test": int(len(test))}, "candidates": ranked,
            "champion": champ, "test": {k: ranked[0][k] for k in ("mae", "rmse", "r2")},
            "in_sample": _reg_metrics(data[PC_TARGET], pred), "refit": "all_rows"}, final, queue


def pc_source_optimize(model, origin: str, line: str, target: float, max_cost: float) -> dict:
    """원천 optimize() :90-106 — 시드 42 + int(목표×10) + int(상한) · 배합 수락 3,500 · 위반 /3 · /5."""
    seed = 42 + int(target * 10) + int(max_cost)
    rng = np.random.default_rng(seed)
    L = PC_LIMITS
    cands = []
    while len(cands) < 3500:
        cab, rad, salt = rng.uniform(*L["cabbage_pct"]), rng.uniform(*L["radish_pct"]), rng.uniform(*L["salt_pct"])
        sea = 100 - cab - rad - salt
        if L["seasoning_pct"][0] <= sea <= L["seasoning_pct"][1]:
            cands.append({"cabbage_pct": cab, "radish_pct": rad, "seasoning_pct": sea, "salt_pct": salt})
    f = pd.DataFrame(cands)
    for k in ["brine_salinity_pct", "brining_hours", "fermentation_temp_c", "fermentation_hours", "storage_temp_c"]:
        f[k] = rng.uniform(*L[k], len(f))
    f["cabbage_origin"], f["prod_line"] = origin, line
    f["pred"] = model.predict(f[PC_NUM + PC_CAT])
    f["cost"] = sum(f[k] * v for k, v in PC_COST.items())
    f["violation"] = np.maximum(0, target - f.pred) / 3 + np.maximum(0, f.cost - max_cost) / 5
    ok = (f.pred >= target) & (f.cost <= max_cost)
    best = (f[ok].sort_values(["cost", "pred"], ascending=[True, False]) if ok.any() else f.sort_values(["violation", "cost"])).iloc[0]
    return {"n_points": 3500, "feasible": bool(ok.any()), "feasible_rate": float(ok.mean()),
            "best": {**{c: float(best[c]) for c in PC_NUM}, "sensory_score": float(best.pred), "material_cost_index": float(best.cost),
                     "violation": float(best.violation)},
            "seed": seed, "sampling": "연속 균등(원천 LIMITS) · 양념 범위 안 배합만 수락", "on_infeasible": "위반 ↑ 비용 ↑", "returned": 1}


# ── 표준 값 ───────────────────────────────────────────────────────────────────────────────────────────────
def _std_train(code: str, short: str, work: Path, tenants_base=None):
    from mlcore.train.trainer import resolve_features
    tid = f"{code}.{short}"
    m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo", tenants_base=tenants_base)
    s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref=ref, synthetic=syn, base_dir=work / "snap")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
    r = StandardTrainer(features=resolve_features(t, merged=m), artifact_root=work / "art", snapshot_dir=work / "snap").train(cfg)
    if r.status != "succeeded":
        raise RuntimeError(f"{tid}: 표준 학습 실패 {r.report.get('error')}")
    out = (r.report or {}).get("outliers") or {}
    removed = sum(int(x) for x in (out.get("folds") or []))
    std = {"split_policy": r.report["split"]["policy"], "split": r.report["split"]["boundaries"].get("sizes"),
           "champion": r.champion, "selection": r.selection_reason, "beats_baseline": bool(r.beats_baseline),
           "valid": (r.valid_metrics or {}).get(r.champion or "", {}),
           "test": {k: float(v.value) for k, v in r.test_metrics.items() if k in ("mae", "rmse", "r2")},
           "baseline": {k: (None if v.baseline is None else float(v.baseline)) for k, v in r.test_metrics.items() if k in ("mae", "rmse", "r2")},
           "outlier_scope": "train_only" if out else None, "outlier_rows_removed_train": removed if out else None,
           "snapshot_sha256": s.sha256, "rows": int(len(frame)), "preprocess": "표준(median + StandardScaler(scale 후보만) · OneHot)"}
    return m, t, r, std


def _std_queue(m, code: str, r) -> dict:
    from mlcore.train import review
    q = m.tasks[f"{code}.residual_review"].raw
    thr = review.threshold(q["rule"], r.report, quantile_from=q.get("quantile_from", "valid"))
    items = review.from_run(r.report, q["rule"], task_id=f"{code}.residual_review", model_version="repro",
                            origins=q["origins"], quantile_from=q.get("quantile_from", "valid"), max_items=10 ** 6)
    return {"rule": q["rule"], "threshold": float(thr["value"]), "threshold_from": thr["from"], "origin": "test_split",
            "scored_rows": int(len(r.report["queue_residuals"]["test"])), "queue_size": int(len(items)),
            "max_items": int(q["max_items"])}


def _std_optimize(m, code: str, r, fixed: dict, params: dict) -> dict:
    """표준 탐색 공간(코어 Optimizer.space — 수락 표집 · derived · 학습 범위)을 그대로 쓰고, 평가 · 제약 · 순위는 이 도구가 센다
    (등록부 · 승인을 거치지 않는 재현 계산 — 운영 경로 tasks/optimize.py 와 같은 규칙)."""
    import joblib

    from mlcore.data.features import feature_defs
    from mlcore.tasks.optimize import Optimizer
    task = m.tasks[f"{code}.recipe_optimize"]
    raw = task.raw
    d = _artifact(r.artifact_dir)
    model = joblib.load(d / "model.joblib")
    lock = json.loads((d / "features.lock.json").read_text(encoding="utf-8"))
    cats = m.tenant.config.get("categories") or {}
    names = list(dict.fromkeys(list(raw.get("controls") or []) + list(raw.get("fixed") or []) + list(raw.get("derived") or {})))
    defs = {f.name: f for f in feature_defs(m.pack.features, names, cats, m.pack.std_name)}
    pdefs = {k: v.get("default") for k, v in (raw.get("params") or {}).items()}
    prm = {k: v for k, v in {**pdefs, **params}.items() if v is not None}
    sp = Optimizer(None).space(task, [lock], prm, defs, fixed=fixed)
    pts = sp.points.copy()
    for k, v in fixed.items():
        pts[k] = v
    env = {c: pts[c].to_numpy(dtype=float) for c in pts.columns if pts[c].dtype != object}
    short = raw["uses"][0].split(".", 1)[1]
    env[short] = model.predict(pts[lock["order"]])
    for fname, module in (raw.get("formulas") or {}).items():
        cost = _formula(m.pack.path, module)
        env[fname] = np.array([cost(row, prm) for row in pts.assign(**{short: env[short]}).to_dict("records")])
    env.update({k: float(v) for k, v in prm.items()})
    n = len(pts)
    viol = np.zeros(n)
    used, scales = [], {}
    for c in raw["constraints"]:
        lhs, op, rhs = _split(c["expr"])
        if any(tok in pdefs and tok not in prm for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", c["expr"])):
            continue                                            # optional param 이 없으면 그 제약은 평가하지 않는다
        a, b = _ev(lhs, env, n), _ev(rhs, env, n)
        over = np.maximum(0, a - b) if op in ("<=", "<") else np.maximum(0, b - a)
        scale = c.get("scale")
        viol = viol + over / (float(scale) if scale else np.maximum(np.abs(b), 1e-9))
        used.append(c["name"])
        if scale:
            scales[c["name"]] = scale
    feasible = viol <= 1e-10
    obj = raw["objective"]
    keys = [_sortkey(o, env) for o in [obj] + list(obj.get("tiebreak") or [])]
    if feasible.any():
        order = [i for i in np.lexsort(tuple(reversed(keys))) if feasible[i]]
    else:
        order = list(np.lexsort(tuple(reversed(keys)) + (viol,)))
    i = int(order[0])
    oname = obj.get("minimize") or obj.get("maximize")
    best = {c: float(pts[c].iloc[i]) for c in pts.columns if pts[c].dtype != object}
    best |= {short: float(env[short][i]), oname: float(env[oname][i]), "violation": float(viol[i])}
    return {"n_points": int(n), "n_drawn": int(sp.n_drawn), "strategy": sp.strategy, "feasible": bool(feasible.any()),
            "feasible_rate": float(feasible.mean()), "constraints": used, "scales": scales, "best": best,
            "seed": int(raw.get("seed", 42)), "on_infeasible": raw["on_infeasible"], "returned": 5}


def _diff(std: dict, src: dict) -> tuple[dict, dict]:
    d = {k: round(100 * (std[k] - src[k]) / abs(src[k]), 2) for k in ("mae", "rmse", "r2")}
    return d, {k: abs(v) <= 100 * TOLERANCE2 for k, v in d.items()}


TOLERANCE2 = 0.10


def run_phase2(tenants_base=None) -> dict:
    global _LAST_BASE
    _LAST_BASE = tenants_base
    rows = []
    with tempfile.TemporaryDirectory(prefix="mlp-repro2-") as d:
        work = Path(d)
        # krs ─────────────────────────────────────────────────────────────
        m, t, r, std = _std_train("krs", "joint_strength", work, tenants_base)
        cats = m.tenant.config.get("categories") or {}
        sup = cats["supplier"][KRS_REQUEST["supplier_index"]]
        src, smodel, squeue = krs_source(source_frame("krs", "krs.joint_strength", tenants_base=tenants_base))
        diff, within = _diff(std["test"], src["test"])
        rows.append({"task": "krs.joint_strength", "type": "regression", "metric": "mae", "compare": True,
                     "source_procedure": src, "standard": std, "diff_pct": diff, "within_10pct": within,
                     "reason": ("원천 보고 수치 없음 → 원천 절차 재현값과 대조(D2-12). 차이 사유: 원천은 IQR 이상치 경계를 분할 전 전체에서 재고(K6) "
                                "표준은 학습 구간에서만(D2-03) · 원천 무작위 80/20 · 검증 구간 없음 → 표준 random_60_20_20(D2-21) · "
                                "원천은 모델을 시험 구간 RMSE 로 선정(시험 구간 선정 누수 K1 — 원천 시험 지표는 낙관 편향) · 표준 선정은 검증 구간 · "
                                "원천 RobustScaler → 표준 전처리")})
        squeue_std = _std_queue(m, "krs", r)
        rows.append({"task": "krs.residual_review", "type": "review_queue", "metric": "queue_size", "compare": False,
                     "source_procedure": squeue, "standard": squeue_std,
                     "reason": ("대조 제외: 원천은 학습 80% 를 포함한 정제 데이터 전체를 채점(표본 내 잔차 K4) — 표준은 같은 |잔차| ≥ 4 MPa 규칙을 "
                                "시험 구간 잔차 · 운영 잔차에만(G2-R01). 모수 행이 달라 건수 대조는 뜻이 없다")})
        so = krs_source_optimize(smodel, sup, KRS_REQUEST["supplier_source"], KRS_REQUEST["target_strength"], KRS_REQUEST["max_cost"])
        to = _std_optimize(m, "krs", r, {"supplier": sup}, {"target_strength": KRS_REQUEST["target_strength"]})
        rows.append({"task": "krs.recipe_optimize", "type": "optimize", "metric": "feasible_rate", "compare": False,
                     "source_procedure": so, "standard": to,
                     "reason": ("대조 제외(추천 조건은 모델 · 표집이 달라 점 대 점 비교 불가): 원천 요청 의존 시드 · 연속 균등 표집 · 온도 232~260 · "
                                "혼합 35~75 → 표준 고정 시드 · 격자 위 수락 표집(features step) · 범위 = 요청 경계 ∩ 학습 범위 p1~p99 · "
                                "원천 미충족 시 위반량 무시 최저 비용(K2) → 표준 least_violation · 원천 추천 1 → 표준 상위 5")})
        # pc ──────────────────────────────────────────────────────────────
        m, t, r, std = _std_train("pc", "sensory_score", work, tenants_base)
        cats = m.tenant.config.get("categories") or {}
        origin, line = cats["cabbage_origin"][PC_REQUEST["origin_index"]], cats["prod_line"][PC_REQUEST["line_index"]]
        src, smodel, squeue = pc_source(source_frame("pc", "pc.sensory_score", tenants_base=tenants_base))
        diff, within = _diff(std["test"], src["test"])
        rows.append({"task": "pc.sensory_score", "type": "regression", "metric": "mae", "compare": False,
                     "source_procedure": src, "standard": std, "diff_pct": diff, "within_10pct": within,
                     "reason": ("±10% 대조 제외(D2-02): 표준 절차 재측정(time_60_20_20 · 검증 선정 · 시험 1회)이 정본, 원천 값은 병기만. "
                                "원천은 시각 열이 있는데 무작위 78/22(P3) · 시험 MAE 선정(P1) · 전체 재적합 모델의 표본 내 평가(P2). "
                                f"표준 분할 실제 정책 = {std['split_policy']}(행 420 < 500 이면 time_cv5 — std/split_policies.yaml D-05, 마지막 20% 시험)")})
        rows.append({"task": "pc.residual_review", "type": "review_queue", "metric": "queue_size", "compare": False,
                     "source_procedure": squeue, "standard": _std_queue(m, "pc", r),
                     "reason": ("대조 제외(D2-02 · D2-11): 원천 임계값 = 전체 재적합 모델의 표본 내 |잔차| 0.9 분위(P2) · 화면 상위 8 고정(P4) → "
                                "표준 임계값 = 검증 구간 잔차 0.9 분위, 시험 구간 · 운영 잔차에만 적용")})
        so = pc_source_optimize(smodel, origin, line, PC_REQUEST["target_score"], PC_REQUEST["max_material_cost"])
        to = _std_optimize(m, "pc", r, {"cabbage_origin": origin, "prod_line": line},
                           {"target_score": PC_REQUEST["target_score"], "max_material_cost": PC_REQUEST["max_material_cost"]})
        rows.append({"task": "pc.recipe_optimize", "type": "optimize", "metric": "feasible_rate", "compare": False,
                     "source_procedure": so, "standard": to,
                     "reason": ("대조 제외(D2-02 — 의존 모델이 재측정 모델): 원천 요청 의존 시드 · 연속 균등 → 표준 고정 시드 · 격자 위 수락 표집 3,500 · "
                                "위반 가중 /3 · /5 는 제약 scale 로 같게 · 원천 추천 1 → 표준 상위 5")})
    return {"meta": {"tool": "migration/reproduce.py --phase2", "source_executed": False, "tolerance": TOLERANCE2,
                     "decisions": ["D2-02", "D2-03", "D2-11", "D2-12", "D2-21"],
                     "source_requests": {"krs": KRS_REQUEST, "pc": PC_REQUEST}},
            "rows": sorted(rows, key=lambda r: ORDER2.index(r["task"]))}


ORDER2 = [f"{c}.{t}" for c, ts in PHASE2_TASKS.items() for t in ts]


def write_json(res: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def phase2_table(res: dict) -> str:
    out = ["| 과제 | 지표 | 원천 절차 재현 | 표준 | 차이 % | 대조 |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        s, t = r["source_procedure"], r["standard"]
        if r["type"] == "regression":
            sv = " · ".join(f"{k} {s['test'][k]:.4f}" for k in ("mae", "rmse", "r2"))
            tv = " · ".join(f"{k} {t['test'][k]:.4f}" for k in ("mae", "rmse", "r2"))
            dv = " · ".join(f"{k} {v:+.2f}" for k, v in r["diff_pct"].items())
        elif r["type"] == "review_queue":
            sv = f"임계 {s['threshold']:.4f} · 채점 {s['scored_rows']} · 넘음 {s.get('flagged', s.get('above_threshold'))}"
            tv = f"임계 {t['threshold']:.4f} · 채점 {t['scored_rows']} · 대기열 {t['queue_size']}"
            dv = "—"
        else:
            sv = f"충족률 {s['feasible_rate']:.4f} · 점 {s['n_points']}"
            tv = f"충족률 {t['feasible_rate']:.4f} · 점 {t['n_points']}"
            dv = "—"
        out.append(f"| {r['task']} | {r['metric']} | {sv} | {tv} | {dv} | {'±10%' if r['compare'] else '제외'} |")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
