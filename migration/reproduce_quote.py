"""이관 대조 재현 — 2차 도면 · 견적 2사(ot · kd) (G-M12 6사 · G2-Q01 · D2-12). 개발3.

    OMP_NUM_THREADS=1 uv run python migration/reproduce_quote.py          # 표 출력 + outputs/reproduce-ot-kd.json

krs · pc 는 개발1 의 `migration/reproduce.py --phase2`(→ outputs/reproduce-krs-pc.json). 여기는 ot · kd 만 같은 방법으로 잰다.

- **표준 재측정**: 회사 `demo`(synthetic, 시드 42) → 표준 프레임 → 스냅숏(임시 폴더) → `StandardTrainer`(개발1) 시험 1회 지표.
  보고 수치는 시험 구간만(표본 내 · 학습 구간 지표는 쓰지 않는다).
- **원천 절차 재현**: 원천 코드(`OneTouch ML AI/api/ml_service.py:61-111` · `KyungDong ML AI/api/ml_service.py:44-67`)를 읽어
  같은 시드 · 같은 분할(행 순서 540/180/180 · 층화 960/320/320) · 같은 전처리 · 같은 후보 · 같은 선정 규칙을 여기 다시 썼다
  (원천 import · 실행 0). 입력 행은 팩 합성 생성기(원천 생성기 이관 — 행 일치 100%)를 원천 열 이름으로 바꾼 것.
- **견적 대조**: 원천 저장 견적(`tests/fixtures/ot/source_quotes.json` — 원천 SQLite 읽기 전용 사본)을 팩 견적식(Decimal)으로
  다시 계산하고, 원천 식(float 곱 → `Decimal(str(x))` HALF_UP, `api/quote.py:6-23`)을 읽은 그대로 쓴 참조와 원 단위로 견준다.
원천 저장소는 읽기만 했고 실행하지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.registry import tenants  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features  # noqa: E402

OUT = ROOT / "outputs" / "reproduce-ot-kd.json"
OT_RENAME = {"part_length_mm": "length", "blank_width_mm": "width", "sheet_thickness_mm": "thickness", "hole_count": "holes",
             "slot_count": "slots", "bend_count": "bends", "steel_grade": "material", "section_profile": "profile",
             "machining_minutes": "minutes"}
OT_NUM = ["length", "width", "thickness", "holes", "slots", "bends"]
OT_CAT = ["material", "profile"]
KD_RENAME = {"total_mass_kg": "mass_kg", "main_material": "material", "product_family": "product", "labor_hours": "hours"}
KD_NUM = ["mass_kg", "cut_m", "weld_m", "thickness_mm", "complexity"]
KD_CAT = ["material", "product"]
GEOMETRY = ["is_circle", "is_closed", "aspect_ratio", "area_ratio", "circularity", "is_curved"]
CLASSES = ["outer", "hole", "slot", "other"]


def _r4(x) -> float:
    return round(float(x), 4)


def _reg_metrics(y, p) -> dict:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    return {"mae": _r4(mean_absolute_error(y, p)), "rmse": _r4(np.sqrt(mean_squared_error(y, p))), "r2": _r4(r2_score(y, p))}


# ── 표준 재측정 ────────────────────────────────────────────────────────────────────────────────
def std_train(code: str, short: str, work: Path) -> dict:
    tid = f"{code}.{short}"
    m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo")
    s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref=ref, synthetic=syn, base_dir=work / "snap")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
    r = StandardTrainer(features=resolve_features(t, merged=m), artifact_root=work / "art", snapshot_dir=work / "snap").train(cfg)
    if r.status != "succeeded":
        raise RuntimeError(f"{tid}: 표준 학습 실패 {(r.report or {}).get('error')}")
    out = {"split_policy": r.report["split"]["policy"], "split": r.report["split"]["boundaries"].get("sizes"),
           "champion": r.champion, "selection": r.selection_reason, "beats_baseline": bool(r.beats_baseline),
           "valid": {k: _r4(v) for k, v in ((r.valid_metrics or {}).get(r.champion or "", {}) or {}).items()},
           "test": {k: _r4(v.value) for k, v in r.test_metrics.items()},
           "baseline": {k: (None if v.baseline is None else _r4(v.baseline)) for k, v in r.test_metrics.items()},
           "rows": int(len(frame)), "snapshot_sha256": s.sha256}
    em = (r.report or {}).get("extract_metrics")
    if em:
        out["confusion_matrix"] = em["confusion_matrix"]
        out["class_f1"] = {k: _r4(v) for k, v in em["class_f1"].items()}
        out["labels"] = em["labels"]
        out["baseline_class"] = r.report.get("baseline_value")
    return out


# ── 원천 절차 재현 ─────────────────────────────────────────────────────────────────────────────
def _src_pipeline(est, numeric, categorical):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    pre = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
        ("categorical", OneHotEncoder(handle_unknown="error", sparse_output=False), categorical)])
    return Pipeline([("prepare", pre), ("model", est)])


def _regression_source(jobs_df: pd.DataFrame, target: str, numeric, categorical, gbr_estimators: int):
    """ot · kd 공통 원천 절차: 행 순서 540/180/180 · 검증 MAE(동률 이름순) · 학습+검증 재적합 · 시험 1회."""
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    feats = numeric + categorical
    tr, va, te = jobs_df.iloc[:540], jobs_df.iloc[540:720], jobs_df.iloc[720:]
    ests = {"Ridge": Ridge(alpha=1),
            "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=gbr_estimators, max_depth=3, random_state=42)}
    comp = []
    for name, est in ests.items():
        p = _src_pipeline(clone(est), numeric, categorical).fit(tr[feats], tr[target]).predict(va[feats])
        comp.append({"model": name, **_reg_metrics(va[target], p)})
    comp.sort(key=lambda x: (x["mae"], x["model"]))
    champion = comp[0]["model"]
    fitted = _src_pipeline(clone(ests[champion]), numeric, categorical).fit(jobs_df.iloc[:720][feats], jobs_df.iloc[:720][target])
    return champion, comp, fitted, _reg_metrics(te[target], fitted.predict(te[feats]))


def ot_source(merged) -> dict:
    jobs_df = tenants.synth_call(merged, "ot.machining_minutes").generate().rename(columns=OT_RENAME)
    champion, comp, fitted, test = _regression_source(jobs_df, "minutes", OT_NUM, OT_CAT, 180)
    rec = {"length": 1200.0, "width": 160.0, "thickness": 2.0, "holes": 6, "slots": 2, "bends": 2, "material": "SPCC", "profile": "잔넬"}
    pred = max(.05, float(fitted.predict(pd.DataFrame([rec])[OT_NUM + OT_CAT])[0]))         # 원천 저장 견적의 입력 (quotes 1행)
    obj = ot_source_objects(merged)
    return {"machining_minutes": {"split": [540, 180, 180], "champion": champion, "valid": comp[0], "candidates": comp,
                                  "test": test, "missing_cells": int(jobs_df[OT_NUM + OT_CAT].isna().sum().sum()),
                                  "first_test_id": jobs_df["entity_id"].iloc[720]},
            "cad_objects": obj, "quote_prediction": pred}


def ot_source_objects(merged) -> dict:
    """원천 OT-M2: 층화 test .2 → dev 중 valid .25 (random_state 42) · StandardScaler · 검증 macro-F1 최대(동률 이름순) · dev 재적합."""
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    f = tenants.synth_call(merged, "ot.cad_objects").generate()
    x, y = f[GEOMETRY].to_numpy(), f["label"].to_numpy()
    xdev, xtest, ydev, ytest = train_test_split(x, y, test_size=.2, stratify=y, random_state=42)
    xtr, xva, ytr, yva = train_test_split(xdev, ydev, test_size=.25, stratify=ydev, random_state=42)
    clf = {"Logistic Regression": LogisticRegression(max_iter=2000),
           "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
           "Extra Trees": ExtraTreesClassifier(n_estimators=100, random_state=42)}
    rows = []
    for name, est in clf.items():
        p = Pipeline([("scale", StandardScaler()), ("model", clone(est))]).fit(xtr, ytr).predict(xva)
        rows.append({"model": name, "accuracy": _r4(accuracy_score(yva, p)), "macro_f1": _r4(f1_score(yva, p, average="macro"))})
    rows.sort(key=lambda m: (-m["macro_f1"], m["model"]))
    champ = rows[0]["model"]
    rec = Pipeline([("scale", StandardScaler()), ("model", clone(clf[champ]))]).fit(xdev, ydev)
    pt = rec.predict(xtest)
    return {"rows": int(len(f)), "split": [len(xtr), len(xva), len(xtest)], "champion": champ, "valid": rows[0], "candidates": rows,
            "test": {"accuracy": _r4(accuracy_score(ytest, pt)), "macro_f1": _r4(f1_score(ytest, pt, average="macro"))},
            "confusion_matrix": confusion_matrix(ytest, pt, labels=CLASSES).tolist(), "classes": CLASSES, "_model": rec}


def kd_source(merged) -> dict:
    jobs_df = tenants.synth_call(merged, "kd.labor_hours").generate().rename(columns=KD_RENAME)
    champion, comp, fitted, test = _regression_source(jobs_df, "hours", KD_NUM, KD_CAT, 160)
    return {"labor_hours": {"split": [540, 180, 180], "champion": champion, "valid": comp[0], "candidates": comp, "test": test}}


# ── 견적 대조 ──────────────────────────────────────────────────────────────────────────────────
def _formula(pack: str):
    spec = importlib.util.spec_from_file_location(f"quote_{pack.replace('-', '_')}", ROOT / "packs" / pack / "formulas" / "quote.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _won_src(x) -> int:
    """원천 won() — float → Decimal(str(x)) → HALF_UP (api/quote.py:6-7)."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ot_source_formula(inp: dict, minutes_raw: float, a: dict, *, round_minutes: bool = True) -> dict:
    """원천 calculate() (api/quote.py:10-23) 를 읽은 그대로 — float 곱. round_minutes=False 는 저장 견적이 만들어진 판(가공비가
    반올림 전 분으로 계산됨 — 아래 대조표 사유)을 재현하는 경로."""
    minutes = round(minutes_raw, 4)
    q = inp["quantity"]
    weight = inp["length"] * inp["width"] * inp["thickness"] / 1e9 * a["density"]
    material = _won_src(weight * a["price_kg"] * (1 + a["scrap_rate"]) * q)
    processing = _won_src((minutes if round_minutes else minutes_raw) * a["machine_per_min"] * q)
    setup = _won_src(a["setup_minutes"] * a["machine_per_min"])
    base = material + processing + setup
    markup = _won_src(base * a["markup"])
    subtotal = base + markup
    vat = _won_src(subtotal * a["vat_rate"])
    return {"material": material, "processing": processing, "setup": setup, "markup": markup, "subtotal": subtotal, "vat": vat,
            "total": subtotal + vat, "minutes_per_piece": minutes, "weight_per_piece": round(weight, 4)}


def ot_quote_check(merged, minutes_raw: float) -> dict:
    fx = json.loads((ROOT / "tests" / "fixtures" / "ot" / "source_quotes.json").read_text(encoding="utf-8"))["rows"]
    rename_in = {"length": "part_length_mm", "width": "blank_width_mm", "thickness": "sheet_thickness_mm", "holes": "hole_count",
                 "slots": "slot_count", "bends": "bend_count", "material": "steel_grade", "profile": "section_profile"}
    raw = merged.tasks["ot.quote"].raw["rates"]
    rates = {k: ({c: Decimal(x) for c, x in v.items()} if isinstance(v, dict) else Decimal(v)) for k, v in raw.items()}
    mod = _formula("rollform-quote")
    rows = []
    for row in fx:
        src_in = row["input"]
        dec_in = json.loads(json.dumps({rename_in.get(k, k): v for k, v in src_in.items() if k in rename_in or k == "quantity"}),
                            parse_float=Decimal)
        minutes_dec = Decimal(str(minutes_raw))
        std = mod.quote(dec_in, [], {"machining_minutes": minutes_dec}, rates)
        ref_now = ot_source_formula(src_in, minutes_raw, row["assumptions"])
        ref_stored = ot_source_formula(src_in, minutes_raw, row["assumptions"], round_minutes=False)
        stored = {"material": row["material_cost"], "processing": row["processing_cost"], "setup": row["setup_cost"],
                  "markup": row["markup_cost"], "subtotal": row["subtotal"], "vat": row["vat"], "total": row["total"]}
        std_costs = {k: int(v) for k, v in std["costs"].items()} | {"total": int(std["total"])}
        # 단계별: 저장값의 앞 단계를 입력으로 같은 식(Decimal)을 적용했을 때 그 단계 저장값과 같은가
        stage = {
            "material": std_costs["material"] == stored["material"],
            "setup": std_costs["setup"] == stored["setup"],
            "markup_from_stored_base": int((Decimal(stored["material"] + stored["processing"] + stored["setup"])
                                            * rates["markup"]).quantize(Decimal(1), rounding=ROUND_HALF_UP)) == stored["markup"],
            "vat_from_stored_subtotal": int((Decimal(stored["subtotal"]) * rates["vat_rate"]).quantize(
                Decimal(1), rounding=ROUND_HALF_UP)) == stored["vat"],
            "processing_unrounded_minutes": int((minutes_dec * rates["machine_per_min"] * dec_in["quantity"]).quantize(
                Decimal(1), rounding=ROUND_HALF_UP)) == stored["processing"],
        }
        rows.append({"ref": row["ref"], "stored": stored, "standard_decimal": std_costs,
                     "source_formula_now": {k: ref_now[k] for k in stored}, "source_formula_stored_revision": {k: ref_stored[k] for k in stored},
                     "minutes_raw": minutes_raw, "minutes_per_piece": {"standard": str(std["predicted"]["machining_minutes"]),
                                                                       "stored": row["minutes_per_piece"]},
                     "weight_per_piece": {"standard": str(std["lines"][0]["weight_per_piece"]), "stored": row["weight_per_piece"]},
                     "stage_match": stage,
                     "standard_equals_source_formula_now": std_costs == {k: ref_now[k] for k in stored},
                     "stored_equals_source_stored_revision": stored == {k: ref_stored[k] for k in stored}})
    return {"rows": rows}


def run() -> dict:
    out: dict = {"note": "ot · kd 이관 재현 (migration/reproduce_quote.py) — 시험 구간 1회 지표만, 원천 실행 0"}
    ot, kd = tenants.load_and_merge("ot"), tenants.load_and_merge("kd")
    with tempfile.TemporaryDirectory(prefix="mlp_repro_ot_kd_") as tmp:
        work = Path(tmp)
        out["ot.machining_minutes"] = {"standard": std_train("ot", "machining_minutes", work)}
        out["ot.cad_objects"] = {"standard": std_train("ot", "cad_objects", work)}
        out["kd.labor_hours"] = {"standard": std_train("kd", "labor_hours", work)}
    src = ot_source(ot)
    src["cad_objects"].pop("_model", None)
    out["ot.machining_minutes"]["source_procedure"] = src["machining_minutes"]
    out["ot.cad_objects"]["source_procedure"] = src["cad_objects"]
    out["kd.labor_hours"]["source_procedure"] = kd_source(kd)["labor_hours"]
    out["kd.labor_hours"]["source_reported"] = {"mae": 4.1071, "rmse": 5.0456, "r2": 0.9956}     # KyungDong docs/verification.md:23
    out["ot.quote"] = ot_quote_check(ot, src["quote_prediction"])
    return out


def _table(res: dict) -> str:
    lines = ["| 과제 | 표준 재측정 (시험) | 원천 절차 재현 (시험) |", "|---|---|---|"]
    for t in ("ot.machining_minutes", "ot.cad_objects", "kd.labor_hours"):
        s, p = res[t]["standard"], res[t]["source_procedure"]
        lines.append(f"| {t} | {s['champion']} {s['test']} (기준선 {s['baseline']}) | {p['champion']} {p['test']} |")
    for r in res["ot.quote"]["rows"]:
        lines.append(f"| ot.quote {r['ref']} | 표준 Decimal {r['standard_decimal']['total']} | 원천 식(현행) {r['source_formula_now']['total']} · "
                     f"저장 {r['stored']['total']} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, default=OUT)
    a = ap.parse_args(argv)
    res = run()
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(_table(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
