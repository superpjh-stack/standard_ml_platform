"""합성 생성기 행 일치 시험 (G-M12 · pack-contract §4 · goal §3.1 M2).

원천 코드는 import · 실행하지 않는다(CLAUDE.md "원천은 읽기만"). 원천 demo_data() 를 읽어 같은 난수 호출 순서를
packs/<pack>/synth/ 로 옮겼고, 여기서는 그 결과를 **원천 문서 · 원천 시험에 적힌 값** 과 대조한다.
지표 대조는 원천 학습 절차(ml_service.py 의 pipeline · state)를 이 파일 안에서 읽은 그대로 다시 써서 잰다 —
같은 sklearn 1.6.1 · numpy 1.26.4(D-21)에서 시험 지표가 원천 보고값과 소수 자리까지 같으면, 입력 행이 같다는 강한 증거다.

근거 표기(원천 = 이 저장소 밖, 읽기 전용):
  KS = ../KwangSung ML AI ,  SW = ../SongWol ML AI
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingClassifier, GradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, brier_score_loss, mean_absolute_error, mean_squared_error,
                             r2_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from mlcore.registry import packs, tenants
from mlcore.settings import ROOT

PRESS_NUM = ["press_force", "vibration", "motor_current", "equip_temp", "mold_temp", "cycle_time", "shot_count"]
PRESS_CAT = ["machine_code", "product_type"]
TEXTILE_NUM = ["set_temp", "set_pressure", "line_speed", "ink_usage", "dwell_time", "absorb_rate", "fabric_strength"]
TEXTILE_CAT = ["print_type", "color_tone"]


def _frame(code: str, task: str) -> pd.DataFrame:
    m = tenants.load_and_merge(code)
    return tenants.synth_call(m, task).generate()


@pytest.fixture(scope="module")
def ks_frame() -> pd.DataFrame:
    return _frame("ks", "ks.remaining_hours")


@pytest.fixture(scope="module")
def sw_frame() -> pd.DataFrame:
    return _frame("sw", "sw.delta_e")


# ── 1. 데이터 통계 — 원천 시험 · 문서에 적힌 값 ─────────────────────────────────────────────

@pytest.mark.parametrize("code,task,num", [("ks", "ks.remaining_hours", PRESS_NUM), ("sw", "sw.delta_e", TEXTILE_NUM)])
def test_rows_missing_duplicates_impossible(code, task, num):
    # KS tests/test_api.py:25,27 · SW tests/test_api.py:31,33 — rows == 720 · missing_cells == 24 · duplicate_lots == impossible_cells == 0
    # KS docs/verification.md:9 · SW docs/verification.md:9 — "720건·결측 24셀·중복 0·범위 이탈 0"
    # missing_cells 는 FEATURES(수치+범주) 기준 (KS ml_service.py:160 · SW :206), impossible 은 FEATURE_META min/max (KS :161 · SW :208)
    d = _frame(code, task)
    m = tenants.load_and_merge(code)
    feats = m.pack.features
    assert len(d) == 720
    assert int(d[list(m.tasks[task].raw["features"])].isna().sum().sum()) == 24
    assert int(d["entity_id"].duplicated().sum()) == 0
    assert sum(int(((d[k] < feats[k]["min"]) | (d[k] > feats[k]["max"])).sum()) for k in num) == 0


def test_ks_missing_injection_columns(ks_frame):
    # KS ml_service.py:36-37 — vibration · motor_current · mold_temp 각 8 행, 다른 열은 결측 0
    na = ks_frame.isna().sum()
    assert {k: int(v) for k, v in na.items() if v} == {"vibration": 8, "motor_current": 8, "mold_temp": 8}
    assert ks_frame["shot_count"].dtype.kind == "i"                       # KS ml_service.py:23 정수
    assert ks_frame["remaining_hours"].between(1, 180).all()              # KS :30 clip(1, 180)


def test_sw_missing_rounding_and_defect_rate(sw_frame):
    # SW ml_service.py:52-56 — absorb_rate · fabric_strength · ink_usage 각 8, 수치 소수 2 · ΔE 소수 3
    na = sw_frame.isna().sum()
    assert {k: int(v) for k, v in na.items() if v} == {"absorb_rate": 8, "fabric_strength": 8, "ink_usage": 8}
    for k in TEXTILE_NUM:
        s = sw_frame[k].dropna()
        assert np.allclose(s, s.round(2))
    assert np.allclose(sw_frame["delta_e"], sw_frame["delta_e"].round(3))
    # SW docs/verification.md:24 — "합성 불량률 31.5%" (overview defect_rate = round(mean, 4), SW ml_service.py:209)
    assert round(float(sw_frame["defect"].mean()) * 100, 1) == 31.5


def test_sw_filter_count(sw_frame):
    # SW docs/verification.md:18 — 데이터 화면 "DTF/연한 색상 필터 41건"
    assert int(((sw_frame.print_type == "DTF") & (sw_frame.color_tone == "연한 색상")).sum()) == 41


def test_time_order_and_entity_ids(ks_frame, sw_frame):
    # KS ml_service.py:34-35 (2026-08-01T00:00+09:00, 1h) · SW :50-51 (2026-08-01T08:00+09:00, 1h)
    for d, start in ((ks_frame, "2026-08-01 00:00"), (sw_frame, "2026-08-01 08:00")):
        assert str(d["ts"].dt.tz) == "Asia/Seoul"
        assert d["ts"].iloc[0] == pd.Timestamp(start, tz="Asia/Seoul")
        assert (d["ts"].diff().dropna() == pd.Timedelta(hours=1)).all()
        assert d["entity_id"].iloc[0] == "DEMO-0001" and d["entity_id"].iloc[-1] == "DEMO-0720"


# ── 2. 기대 지표 — 원천 학습 절차를 읽은 그대로 다시 써서 시험 지표 대조 ─────────────────────

def _pipeline(est, num, cat):   # KS ml_service.py:41-46 · SW :60-65 (트리에도 스케일러 — 원천 결함 S3 그대로)
    prepare = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), num),
        ("category", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
    ])
    return Pipeline([("prepare", prepare), ("estimator", est)])


def _source_procedure(d, num, cat, target, risk, regressors, classifiers, round_preds):
    """KS ml_service.py:73-100 · SW :92-119 — 432/144/144 시간순, 검증 MAE · Brier 선정, 576 재적합, 시험 1회."""
    feats = num + cat
    train, valid, test = d.iloc[:432], d.iloc[432:576], d.iloc[576:]
    metrics, risk_metrics = [], []
    for name, est in regressors.items():
        p = _pipeline(est, num, cat).fit(train[feats], train[target]).predict(valid[feats])
        metrics.append({"model": name, "mae": round(float(mean_absolute_error(valid[target], p)), 3),
                        "r2": round(float(r2_score(valid[target], p)), 4)})
    for name, est in classifiers.items():
        p = _pipeline(est, num, cat).fit(train[feats], train[risk]).predict_proba(valid[feats])[:, 1]
        risk_metrics.append({"model": name, "brier": round(float(brier_score_loss(valid[risk], p)), 4)})
    metrics.sort(key=lambda r: (r["mae"], r["model"]))
    risk_metrics.sort(key=lambda r: (r["brier"], r["model"]))
    champ, rchamp = metrics[0]["model"], risk_metrics[0]["model"]
    dev = d.iloc[:576]
    pred = _pipeline(clone(regressors[champ]), num, cat).fit(dev[feats], dev[target]).predict(test[feats])
    prob = _pipeline(clone(classifiers[rchamp]), num, cat).fit(dev[feats], dev[risk]).predict_proba(test[feats])[:, 1]
    if round_preds:                                   # SW ml_service.py:116-117 — 예측 소수 3 · 확률 소수 4 후 지표
        pred, prob = pred.round(3), prob.round(4)
    y, r = test[target], test[risk]
    return {
        "champion": champ, "risk_champion": rchamp, "valid": metrics[0],
        "mae": round(float(mean_absolute_error(y, pred)), 3), "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 3),
        "r2": round(float(r2_score(y, pred)), 4), "roc_auc": round(float(roc_auc_score(r, prob)), 4),
        "pr_auc": round(float(average_precision_score(r, prob)), 4), "brier": round(float(brier_score_loss(r, prob)), 4),
    }


def test_ks_reported_metrics_reproduced(ks_frame):
    # KS ml_service.py:77-82 후보 · 하이퍼파라미터, random_state = SEED 42 (config.py:2)
    regs = {"Ridge": Ridge(alpha=3),
            "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=3, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=3, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=120, max_depth=2, random_state=42)}
    clfs = {"Logistic Regression": LogisticRegression(max_iter=500),
            "Random Forest": RandomForestClassifier(n_estimators=100, min_samples_leaf=5, random_state=42),
            "Gradient Boosting": GradientBoostingClassifier(n_estimators=80, max_depth=2, random_state=42)}
    got = _source_procedure(ks_frame, PRESS_NUM, PRESS_CAT, "remaining_hours", "failure_24h", regs, clfs, round_preds=False)
    # KS docs/verification.md:30-34 (= migration/source_inventory.md §1.4) — 원천 보고 자리수까지 정확히 일치
    assert got["champion"] == "Gradient Boosting" and got["risk_champion"] == "Random Forest"
    assert got["valid"]["mae"] == 5.213 and got["valid"]["r2"] == 0.9143            # verification.md:31
    assert (got["mae"], got["rmse"], got["r2"]) == (5.568, 6.979, 0.9199)           # verification.md:32
    assert (got["roc_auc"], got["pr_auc"], got["brier"]) == (0.6444, 0.1426, 0.0576)  # verification.md:34


def test_sw_reported_metrics_reproduced(sw_frame):
    # SW ml_service.py:96-101 후보 · 하이퍼파라미터 (GBR 200/3/0.05 · LogReg 1000)
    regs = {"Ridge": Ridge(alpha=3),
            "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=3, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=3, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=.05, random_state=42)}
    clfs = {"Logistic Regression": LogisticRegression(max_iter=1000),
            "Random Forest": RandomForestClassifier(n_estimators=100, min_samples_leaf=5, random_state=42),
            "Gradient Boosting": GradientBoostingClassifier(n_estimators=80, max_depth=2, random_state=42)}
    got = _source_procedure(sw_frame, TEXTILE_NUM, TEXTILE_CAT, "delta_e", "defect", regs, clfs, round_preds=True)
    # SW docs/verification.md:23 — ΔE: 챔피언 Extra Trees · 검증 MAE 0.520 / R² 0.752 · 시험 MAE 0.557 / RMSE 0.709 / R² 0.722 (문서 소수 3자리)
    assert got["champion"] == "Extra Trees" and got["risk_champion"] == "Gradient Boosting"
    assert got["valid"]["mae"] == 0.520 and round(got["valid"]["r2"], 3) == 0.752
    assert (got["mae"], got["rmse"], round(got["r2"], 3)) == (0.557, 0.709, 0.722)
    # SW docs/verification.md:24 — 불량: AUC 0.868 / AP 0.781 / Brier 0.127.
    # 재현값 0.8686 / 0.7823 / 0.1261 — 차이 ≤ 0.0013 (D-17 허용폭 ±10% 안). 회귀 · 불량률 · 필터 건수가 정확히 같으므로
    # 입력 행은 같고, 차이는 원천 문서값과 원천 실행 결과 사이의 것으로 본다(원천 실행 금지라 확인 불가 → decisions.md D-52).
    for k, ref in (("roc_auc", 0.868), ("pr_auc", 0.781), ("brier", 0.127)):
        assert abs(got[k] - ref) <= 0.0015, (k, got[k], ref)
        assert abs(got[k] - ref) / ref <= 0.10


# ── 3. 범주 · 시드 · fixture ───────────────────────────────────────────────────────────────

def test_neutral_categories_give_same_rows_as_tenant(ks_frame):
    # pack-contract §4 · D-34 — 팩은 회사 범주값을 모른다. rng.choice 는 목록 길이로만 뽑으므로 같은 길이면 같은 행.
    pack = packs.load_pack("press")
    neutral = packs.load_synth(pack, "remaining_hours")(720, 42)
    cats = (yaml.safe_load((ROOT / "tenants" / "ks.yaml").read_text(encoding="utf-8")) or {})["categories"]
    mapped = neutral.copy()
    for col, values in cats.items():
        mapped[col] = mapped[col].map(dict(zip(sorted(set(neutral[col])), values)))
    pd.testing.assert_frame_equal(mapped, ks_frame)


@pytest.mark.parametrize("pack_code,task", [("press", "remaining_hours"), ("press", "failure_24h"), ("press", "sensor_ood"),
                                            ("textile", "delta_e"), ("textile", "defect_risk"), ("textile", "print_ood"),
                                            ("_template", "target_value"), ("_template", "target_risk")])
def test_generator_shape_and_determinism(pack_code, task):
    pack = packs.load_pack(pack_code)
    spec = packs.synth_spec(pack, task)
    gen = packs.load_synth(pack, task)
    a, b = gen(spec.rows, spec.seed), gen(spec.rows, spec.seed)
    pd.testing.assert_frame_equal(a, b)
    assert not gen(spec.rows, spec.seed + 1).equals(a)
    t = pack.tasks[task]
    for col in ["entity_id", "ts", *t["features"]] + ([t["target"]["name"]] if t.get("target") else []):
        assert col in a.columns, col
    assert len(a) == spec.rows


@pytest.mark.parametrize("code", ["ks", "sw"])
def test_fixture_snapshot_is_regenerated_not_edited(code):
    # tests/fixtures/README.md — fixture 는 손질하지 않는다. 생성 명령(migration/make_fixtures.py)의 결과와 같아야 한다.
    first = next(iter(tenants.load_and_merge(code).tasks))
    want = _frame(code, first)
    got = pd.read_parquet(ROOT / "tests" / "fixtures" / code / "snapshot.parquet")
    pd.testing.assert_frame_equal(got, want)
    csv = pd.read_csv(ROOT / "tests" / "fixtures" / code / "snapshot.csv", encoding="utf-8-sig", float_precision="round_trip")
    csv["ts"] = pd.to_datetime(csv["ts"]).dt.tz_convert("Asia/Seoul")
    pd.testing.assert_frame_equal(csv, want, check_dtype=False)


def test_template_csv_fixture(tmp_path):
    # 새 회사용 CSV — _template 과제 변수(x1 · x2 · c1 · target_value · target_risk)에 맞춘다 (D-51: 커밋 위치는 G-S06 과 충돌해 시험 시 생성)
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_fixtures", ROOT / "migration" / "make_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--kind", "template_csv", "--out", str(tmp_path)]) == 0
    raw = (tmp_path / "snapshot.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    d = pd.read_csv(tmp_path / "snapshot.csv", encoding="utf-8-sig")
    pack = packs.load_pack("_template")
    need = {"entity_id", "ts", *pack.features}
    for t in pack.tasks.values():
        need.add(t["target"]["name"])
    assert need <= set(d.columns)
    assert len(d) == pack.meta["synth"]["rows"]
    assert set(d["c1"]) <= set(pack.features["c1"]["values"])
