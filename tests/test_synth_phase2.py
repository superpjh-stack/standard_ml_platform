"""2차 팩 합성 생성기 행 일치 (G2-P01 · G-M12 6사 · pack-contract §4 · §6). 원천 코드는 import · 실행하지 않는다.

- eto(kd): 원천 학습 절차(`api/ml_service.py:44-58` — 행 순서 540/180/180 · 후보 4 · 검증 MAE 선정 · 학습+검증 재적합)를
  이 파일 안에 읽은 그대로 다시 써서, 시험 지표가 원천 문서값(`docs/verification.md:23` MAE 4.1071 · RMSE 5.0456 · R² 0.9956)과
  소수 4자리까지 같은지 본다 — 같은 sklearn 1.6.1 · numpy 1.26.4 에서 입력 행이 같다는 강한 증거(1차 test_synth 와 같은 방법).
- kimchi(pc): 원천 문서에 지표 기록이 없다(D2-12) → 원천 `_demo_data()`(`api/ml_service.py:36-55`)를 읽은 그대로 이 파일에
  다시 쓴 참조와 값 · 순서가 100% 같은지 본다. 원천 시험(`tests/test_api.py`)의 단정(행 420 · 결측 15)도 함께.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from mlcore.registry import tenants

pytestmark = [pytest.mark.gate("G2-P01")]

ETO_RENAME = {"total_mass_kg": "mass_kg", "main_material": "material", "product_family": "product", "labor_hours": "hours"}
ETO_NUM = ["mass_kg", "cut_m", "weld_m", "thickness_mm", "complexity"]
ETO_CAT = ["material", "product"]


def frame(code: str, task: str, **kw) -> pd.DataFrame:
    m = tenants.load_and_merge(code)
    return tenants.synth_call(m, task).generate(**kw)


# ── eto (kd) ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def kd_jobs() -> pd.DataFrame:
    return frame("kd", "kd.labor_hours").rename(columns=ETO_RENAME)


def test_eto_shape_missing_and_columns(kd_jobs):
    # 원천 시험 :119 — missing_cells == 12 (FEATURES 기준), split [540,180,180]
    assert len(kd_jobs) == 900 and int(kd_jobs[ETO_NUM + ETO_CAT].isna().sum().sum()) == 12
    assert kd_jobs.cut_m.isna().sum() == 12 and kd_jobs.iloc[540:].cut_m.notna().all()
    assert kd_jobs.ts.isna().all()                                   # 시각을 지어내지 않는다(D2-21)
    assert list(kd_jobs.entity_id[:2]) == ["DEMO-0001", "DEMO-0002"]
    assert (kd_jobs.hours >= 1).all()


def test_eto_source_procedure_reproduces_reported_test_metrics(kd_jobs):
    def pipeline(est):
        pre = ColumnTransformer([
            ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), ETO_NUM),
            ("categorical", OneHotEncoder(handle_unknown="error", sparse_output=False), ETO_CAT)])
        return Pipeline([("prepare", pre), ("model", est)])

    feats = ETO_NUM + ETO_CAT
    train, valid, test = kd_jobs.iloc[:540], kd_jobs.iloc[540:720], kd_jobs.iloc[720:]
    ests = {"Ridge": Ridge(alpha=1), "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=160, max_depth=3, random_state=42)}
    res = []
    for name, est in ests.items():
        p = pipeline(clone(est)).fit(train[feats], train.hours).predict(valid[feats])
        res.append((round(float(mean_absolute_error(valid.hours, p)), 4), name))
    champion = sorted(res)[0][1]
    assert champion == "Ridge"                                       # docs/verification.md:23
    fitted = pipeline(clone(ests[champion])).fit(kd_jobs.iloc[:720][feats], kd_jobs.iloc[:720].hours)
    pred = fitted.predict(test[feats])
    got = (round(float(mean_absolute_error(test.hours, pred)), 4), round(float(np.sqrt(mean_squared_error(test.hours, pred))), 4),
           round(float(r2_score(test.hours, pred)), 4))
    assert got == (4.1071, 5.0456, 0.9956)
    row = {"mass_kg": 650, "cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3,
           "material": "STS316L", "product": "반응기"}            # 원천 저장 견적의 입력 조건
    assert round(max(.1, float(fitted.predict(pd.DataFrame([row])[feats])[0])), 4) == 58.146   # verification.md:29


def test_eto_neutral_categories_map_to_tenant_frame(kd_jobs):
    m = tenants.load_and_merge("kd")
    neutral = tenants.synth_call(m, "kd.labor_hours").spec
    from mlcore.registry.packs import load_synth
    gen = load_synth(m.pack, neutral.task)
    n = gen(900, 42)
    cats = m.tenant.config["categories"]
    for col, src in (("main_material", "material"), ("product_family", "product")):
        mapping = {f"{'M' if col == 'main_material' else 'P'}{i + 1}": v for i, v in enumerate(cats[col])}
        n[col] = n[col].map(mapping)
    n = n.rename(columns=ETO_RENAME)
    pd.testing.assert_frame_equal(n, kd_jobs)


# ── kimchi (pc) ───────────────────────────────────────────────────────────────

def reference_pc(rows: int = 420, seed: int = 42) -> pd.DataFrame:
    """원천 _demo_data()(api/ml_service.py:36-55)를 읽은 그대로 다시 쓴 참조 — 원천 이름 · 원천 범주 값."""
    LIMITS = {"cabbage_pct": (66.0, 76.0), "radish_pct": (5.0, 11.0), "seasoning_pct": (15.0, 23.0), "salt_pct": (1.2, 2.6),
              "brine_salinity_pct": (9.0, 13.0), "brining_hours": (8.0, 16.0), "fermentation_temp_c": (2.0, 8.0),
              "fermentation_hours": (18.0, 72.0), "storage_temp_c": (-1.0, 4.0)}
    rng = np.random.default_rng(seed)
    cabbage = rng.uniform(*LIMITS["cabbage_pct"], rows); radish = rng.uniform(*LIMITS["radish_pct"], rows)
    salt = rng.uniform(*LIMITS["salt_pct"], rows)
    seasoning = 100 - cabbage - radish - salt
    valid = (seasoning >= LIMITS["seasoning_pct"][0]) & (seasoning <= LIMITS["seasoning_pct"][1])
    while not valid.all():
        n = int((~valid).sum()); cabbage[~valid] = rng.uniform(*LIMITS["cabbage_pct"], n)
        radish[~valid] = rng.uniform(*LIMITS["radish_pct"], n); salt[~valid] = rng.uniform(*LIMITS["salt_pct"], n)
        seasoning = 100 - cabbage - radish - salt
        valid = (seasoning >= LIMITS["seasoning_pct"][0]) & (seasoning <= LIMITS["seasoning_pct"][1])
    salinity = rng.uniform(*LIMITS["brine_salinity_pct"], rows); brining = rng.uniform(*LIMITS["brining_hours"], rows)
    ferment_temp = rng.uniform(*LIMITS["fermentation_temp_c"], rows); ferment_hours = rng.uniform(*LIMITS["fermentation_hours"], rows)
    storage_temp = rng.uniform(*LIMITS["storage_temp_c"], rows)
    origin = rng.choice(["평창", "강릉", "기타계약"], rows, p=[.68, .20, .12]); line = rng.choice(["K1", "K2"], rows, p=[.58, .42])
    score = (86 - abs(salinity - 11.1) * 2 - abs(brining - 12) * .65 - abs(ferment_temp - 4.8) * 1.15
             - abs(ferment_hours - 42) * .13 - abs(storage_temp - 1) * .8 - abs(seasoning - 19.5) * .45
             + (origin == "평창") * .8 + (line == "K2") * .25 + rng.normal(0, 1.8, rows))
    f = pd.DataFrame({"lot_id": [f"PC-K-{i+1:04d}" for i in range(rows)],
                      "produced_at": pd.date_range("2025-01-02", periods=rows, freq="12h"),
                      "cabbage_pct": cabbage, "radish_pct": radish, "seasoning_pct": seasoning, "salt_pct": salt,
                      "brine_salinity_pct": salinity, "brining_hours": brining, "fermentation_temp_c": ferment_temp,
                      "fermentation_hours": ferment_hours, "storage_temp_c": storage_temp, "cabbage_origin": origin, "line": line,
                      "sensory_score": score})
    for col in ["brine_salinity_pct", "fermentation_temp_c", "storage_temp_c"]:
        f.loc[rng.choice(rows, 5, replace=False), col] = np.nan
    return f


def test_kimchi_rows_match_source_generator_100pct():
    ours = frame("pc", "pc.sensory_score")
    ref = reference_pc()
    assert len(ours) == len(ref) == 420 and int(ours.isna().sum().sum()) == 15
    ref = ref.rename(columns={"lot_id": "entity_id", "produced_at": "ts", "line": "prod_line"})
    ref["entity_id"] = ref.entity_id.str.replace("PC-K-", "DEMO-", regex=False)   # 회사 접두어 = compat.entity_prefix
    ref["ts"] = ref.ts.dt.tz_localize("Asia/Seoul")
    pd.testing.assert_frame_equal(ours.reset_index(drop=True), ref[list(ours.columns)].reset_index(drop=True))


def test_kimchi_composition_and_time():
    f = frame("pc", "pc.sensory_score")
    comp = f[["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]].sum(axis=1)
    assert np.allclose(comp, 100) and f.seasoning_pct.between(15, 23).all()
    assert (f.ts.diff().dropna() == pd.Timedelta(hours=12)).all() and str(f.ts.dt.tz) == "Asia/Seoul"
    assert f.entity_id.is_unique


def test_kimchi_category_list_length_guard():
    m = tenants.load_and_merge("pc")
    from mlcore.registry.packs import load_synth
    gen = load_synth(m.pack, "sensory_score")
    with pytest.raises(ValueError):
        gen(10, 1, categories={"cabbage_origin": ["a", "b"]})       # 원천 난수 소비(3값 확률)와 다르면 거부
