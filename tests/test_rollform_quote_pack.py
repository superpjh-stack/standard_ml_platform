"""팩 rollform-quote · 회사 ot — 원천 이관 대조 (G2-P01 · G2-E01 · G2-Q01 · G-M12 6사 · goal2 §0.2). 원천 코드는 import · 실행하지 않는다.

1. 합성 생성기 행 일치 100%: 원천 `demo_jobs()`(ml_service.py:43-58) · `geometry_training_data()`(:19-40)를 이 파일 안에 읽은 그대로
   다시 쓴 참조와 값 · 순서가 같다. 원천 절차(행 순서 540/180/180 · 후보 4 · 검증 MAE)를 다시 쓰면 원천 저장 견적의 `test_mae`
   0.3166 이 소수 4자리까지 나온다(입력 행이 같다는 강한 증거 — 1차 test_synth 와 같은 방법).
2. 추출: 팩 샘플 도면(원천 sample_bytes 와 같은 도형)을 규칙 추출기 → 모델 추출기(원천 절차 분류기)로 돌린 결과가 원천 앱이 저장한
   분석 결과(`tests/fixtures/ot/source_drawing.json`, 원천 SQLite 읽기 전용 사본)와 객체 9 개의 점 · 면적 · 둘레 · 라벨 · 점수까지 같다.
   기하 검증 8 사유 · 비지원 · 비평면 · 상한(params) 은 손으로 만든 도면으로.
3. 견적: 팩 견적식(Decimal) = 원천 현행 식(float → Decimal(str) HALF_UP)을 읽은 그대로 쓴 참조와 원 단위 일치. 원천 저장 견적
   726,487 원은 가공비를 반올림 전 분으로 계산한 판에서 나왔다(현행 원천 식 726,484 — D2-60). .5 경계 차이는 D2-07a 사례.
4. 회사 ot 등록부 · API: 실제 팩 · 회사로 학습 → 승인 → 도면 업로드 → 견적 초안(원 단위 · overrides · 채널 quote).
"""

from __future__ import annotations

import importlib.util
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mlcore.registry import packs, tenants
from mlcore.tasks.extract import ExtractError, merge_results

pytestmark = [pytest.mark.gate("G2-P01")]

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packs" / "rollform-quote"
FX = ROOT / "tests" / "fixtures" / "ot"
SRC_DRAWING = json.loads((FX / "source_drawing.json").read_text(encoding="utf-8"))["rows"][0]
SRC_QUOTE = json.loads((FX / "source_quotes.json").read_text(encoding="utf-8"))["rows"][0]
RENAME = {"part_length_mm": "length", "blank_width_mm": "width", "sheet_thickness_mm": "thickness", "hole_count": "holes",
          "slot_count": "slots", "bend_count": "bends", "steel_grade": "material", "section_profile": "profile",
          "machining_minutes": "minutes"}
NUM = ["length", "width", "thickness", "holes", "slots", "bends"]
CAT = ["material", "profile"]
GEOM = ["is_circle", "is_closed", "aspect_ratio", "area_ratio", "circularity", "is_curved"]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PACK / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GX = _load("extractors/geometry_objects.py", "rq_geometry_objects")
OC = _load("extractors/object_classifier.py", "rq_object_classifier")
SD = _load("synth/sample_dxf.py", "rq_sample_dxf")
QF = _load("formulas/quote.py", "rq_quote_formula")


# ── 원천을 읽은 그대로의 참조 (실행 아님) ──────────────────────────────────────────────────────
def source_demo_jobs(materials, profiles) -> pd.DataFrame:
    """OneTouch api/ml_service.py:43-58 demo_jobs() — config.py:4-17 의 FEATURE_META · MATERIALS · PROFILES 순서."""
    meta = {"length": (100, 6000), "width": (30, 600), "thickness": (.5, 6), "holes": (0, 100), "slots": (0, 50), "bends": (0, 12)}
    rng = np.random.default_rng(42)
    n = 900
    frame = pd.DataFrame({k: rng.uniform(lo, hi, n) for k, (lo, hi) in meta.items()})
    for k in ["holes", "slots", "bends"]:
        frame[k] = frame[k].round().astype(int)
    frame["material"] = rng.choice(list(materials), n)
    frame["profile"] = rng.choice(profiles, n)
    factor = frame.material.map(dict(zip(materials, [1, 1.06, 1.4])))
    shape = frame.profile.map(dict(zip(profiles, [.2, .5, .8, .3])))
    frame["minutes"] = (.3 + frame.length / 2200 + frame.width / 1400 + frame.holes * .028 + frame.slots * .095
                        + frame.bends * .16 + frame.thickness ** 1.45 * .12 + shape) * factor + rng.normal(0, .16, n)
    frame["job_id"] = [f"OT-SYN-{i+1:04}" for i in range(n)]
    frame.loc[rng.choice(540, 12, replace=False), "width"] = np.nan
    return frame


def source_geometry():
    """OneTouch api/ml_service.py:19-40 geometry_training_data()."""
    rng = np.random.default_rng(42)
    records, labels = [], []
    for label in ["outer", "hole", "slot", "other"]:
        for _ in range(400):
            if label == "hole":
                row = [1, 1, 1, rng.uniform(.00001, .08), 1, 1]
            elif label == "slot":
                aspect = rng.uniform(1.6, 8)
                area = 4 * (aspect - 1) + np.pi
                perimeter = 4 * (aspect - 1) + 2 * np.pi
                row = [0, 1, aspect, rng.uniform(.0001, .12), 4 * np.pi * area / perimeter ** 2, 1]
            elif label == "outer":
                aspect = rng.uniform(1, 30)
                row = [0, 1, aspect, 1, np.pi * aspect / (aspect + 1) ** 2, rng.choice([0, 1])]
            else:
                row = [0, rng.choice([0, 1]), rng.uniform(1, 30), rng.uniform(.001, .4), rng.uniform(0, .65), 0]
            records.append(row)
            labels.append(label)
    return np.array(records), np.array(labels)


def source_won(value) -> int:
    """OneTouch api/quote.py:6-7."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def source_calculate(p: dict, minutes_raw: float, mat: dict, cost: dict, *, rounded_minutes: bool = True) -> dict:
    """OneTouch api/quote.py:10-23 (계산 부분). rounded_minutes=False = 저장 견적이 만들어진 판(D2-60)."""
    minutes = round(minutes_raw, 4)
    q = p["quantity"]
    weight = p["length"] * p["width"] * p["thickness"] / 1e9 * mat["density"]
    material = source_won(weight * mat["price_kg"] * (1 + cost["scrap_rate"]) * q)
    processing = source_won((minutes if rounded_minutes else minutes_raw) * cost["machine_per_min"] * q)
    setup = source_won(cost["setup_minutes"] * cost["machine_per_min"])
    base = material + processing + setup
    markup = source_won(base * cost["markup"])
    subtotal = base + markup
    tax = source_won(subtotal * cost["vat_rate"])
    return {"material": material, "processing": processing, "setup": setup, "markup": markup, "subtotal": subtotal,
            "vat": tax, "total": subtotal + tax}


def _source_pipeline(est):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    pre = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), NUM),
        ("categorical", OneHotEncoder(handle_unknown="error", sparse_output=False), CAT)])
    return Pipeline([("prepare", pre), ("model", est)])


# ── 픽스처 ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ot():
    return tenants.load_and_merge("ot")


@pytest.fixture(scope="module")
def jobs(ot):
    return tenants.synth_call(ot, "ot.machining_minutes").generate()


@pytest.fixture(scope="module")
def objects_frame(ot):
    return tenants.synth_call(ot, "ot.cad_objects").generate()


@pytest.fixture(scope="module")
def source_regressor(jobs):
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_absolute_error
    j = jobs.rename(columns=RENAME)
    tr, va, te = j.iloc[:540], j.iloc[540:720], j.iloc[720:]
    ests = {"Ridge": Ridge(alpha=1),
            "Random Forest": RandomForestRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, min_samples_leaf=2, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(n_estimators=180, max_depth=3, random_state=42)}
    res = sorted((round(float(mean_absolute_error(va.minutes, _source_pipeline(clone(e)).fit(tr[NUM + CAT], tr.minutes)
                                                  .predict(va[NUM + CAT]))), 4), n) for n, e in ests.items())
    champion = res[0][1]
    fitted = _source_pipeline(clone(ests[champion])).fit(j.iloc[:720][NUM + CAT], j.iloc[:720].minutes)
    test_mae = round(float(mean_absolute_error(te.minutes, fitted.predict(te[NUM + CAT]))), 4)
    return champion, fitted, test_mae


class _SourceModel:
    """원천 절차 분류기(StandardScaler + 검증 macro-F1 최대 · 동률 이름순 · dev 재적합)를 LoadedModel 모양으로."""

    def __init__(self, est):
        self.model, self.lock = self, {"order": GEOM}
        self._est, self.classes_ = est, est.classes_

    def predict_proba(self, X):
        return self._est.predict_proba(X.to_numpy())


@pytest.fixture(scope="module")
def source_recognizer(objects_frame):
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    x, y = objects_frame[GEOM].to_numpy(), objects_frame["label"].to_numpy()
    xdev, xtest, ydev, ytest = train_test_split(x, y, test_size=.2, stratify=y, random_state=42)
    xtr, xva, ytr, yva = train_test_split(xdev, ydev, test_size=.25, stratify=ydev, random_state=42)
    clf = {"Logistic Regression": LogisticRegression(max_iter=2000),
           "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
           "Extra Trees": ExtraTreesClassifier(n_estimators=100, random_state=42)}
    scores = sorted((-round(float(f1_score(yva, Pipeline([("scale", StandardScaler()), ("model", clone(e))]).fit(xtr, ytr)
                                           .predict(xva), average="macro")), 4), n) for n, e in clf.items())
    champ = scores[0][1]
    est = Pipeline([("scale", StandardScaler()), ("model", clone(clf[champ]))]).fit(xdev, ydev)
    return champ, _SourceModel(est), (len(xtr), len(xva), len(xtest))


def run_extract(raw: bytes, model, *, unit="mm", params=None, override=None, max_entities=2000):
    task = packs.load_pack("rollform-quote").tasks["cad_objects"]
    prm = {e["name"]: dict(e.get("params") or {}) for e in task["extractors"]}
    for k, v in (params or {}).items():
        prm[k].update(v)
    limits = {"max_entities": max_entities, "unit_override": override}
    r1 = GX.extract(raw, "t.dxf", unit=unit, limits=limits, context={"params": prm["geometry_objects"], "previous": None})
    prev = merge_results([(GX, r1)])
    r2 = OC.extract(raw, "t.dxf", unit=unit, limits=limits, model=model,
                    context={"params": prm["object_classifier"], "previous": prev})
    return merge_results([(GX, r1), (OC, r2)])


# ── 1. 합성 생성기 행 일치 ─────────────────────────────────────────────────────────────────────
def test_jobs_rows_match_source_generator_100pct(ot, jobs):
    cats = ot.tenant.config["categories"]
    ref = source_demo_jobs(cats["steel_grade"], cats["section_profile"])
    got = jobs.rename(columns=RENAME)
    for col in NUM + CAT + ["minutes"]:
        pd.testing.assert_series_equal(got[col].reset_index(drop=True), ref[col].reset_index(drop=True), check_names=False)
    assert len(got) == 900 and int(got[NUM + CAT].isna().sum().sum()) == 12        # 원천 시험 :156 missing_cells 12
    assert got.width.isna().sum() == 12 and got.iloc[540:].width.notna().all()
    assert got.ts.isna().all() and list(got.entity_id[:2]) == ["DEMO-0001", "DEMO-0002"]   # 시각 · 회사 접두를 지어내지 않는다


def test_neutral_categories_map_to_tenant_frame(ot, jobs):
    gen = _load("synth/jobs.py", "rq_jobs")
    neutral = gen.generate()
    cats = ot.tenant.config["categories"]
    mapped = neutral.copy()
    for col, values in cats.items():
        mapped[col] = mapped[col].map(dict(zip(gen.NEUTRAL_CATEGORIES[col], values)))
    pd.testing.assert_frame_equal(mapped, jobs)
    with pytest.raises(ValueError):
        gen.generate(categories={"steel_grade": ["A", "B"]})                        # 위치 효과 — 길이가 다르면 거부


def test_object_descriptors_match_source_generator_100pct(objects_frame):
    x, y = source_geometry()
    assert len(objects_frame) == 1600 and objects_frame[GEOM].isna().sum().sum() == 0
    np.testing.assert_array_equal(objects_frame[GEOM].to_numpy(), x)
    assert list(objects_frame["label"]) == list(y)
    spec = packs.synth_spec(packs.load_pack("rollform-quote"), "cad_objects")
    assert (spec.rows, spec.seed) == (1600, 42)                                    # pack.yaml synth.tasks (D2-45 ⑤)


def test_source_procedure_reproduces_stored_test_mae(source_regressor):
    champion, fitted, test_mae = source_regressor
    assert champion == "Ridge" and SRC_QUOTE["model"] == "Ridge"
    assert test_mae == SRC_QUOTE["test_mae"] == 0.3166                             # 원천 저장 견적 test_mae — 행 일치 증거
    rec = {"length": 1200.0, "width": 160.0, "thickness": 2.0, "holes": 6, "slots": 2, "bends": 2, "material": "SPCC", "profile": "잔넬"}
    minutes = max(.05, float(fitted.predict(pd.DataFrame([rec])[NUM + CAT])[0]))
    assert round(minutes, 4) == SRC_QUOTE["minutes_per_piece"] == 1.3286


def test_source_recognizer_split_and_metrics(source_recognizer, objects_frame):
    champ, model, sizes = source_recognizer
    assert sizes == (960, 320, 320) and champ == "Extra Trees"                       # 원천 split.objects [960, 320, 320]


# ── 2. 추출 ────────────────────────────────────────────────────────────────────────────────────
def test_sample_drawing_matches_source_stored_analysis(source_recognizer):
    _, model, _ = source_recognizer
    res = run_extract(SD.sample_bytes(), model)
    assert res["counts"] == SRC_DRAWING["counts"] == {"outer": 1, "hole": 6, "slot": 2, "other": 0}
    assert res["dimensions"] == SRC_DRAWING["dimensions"] == {"length": 1200.0, "width": 160.0}
    assert len(res["objects"]) == len(SRC_DRAWING["objects"]) == 9
    for got, want in zip(res["objects"], SRC_DRAWING["objects"]):
        assert got == want, (got["id"], {k: (got.get(k), want.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)})
    # 경고 둘째 문구 · 개수는 같다. 첫 문구는 원천 현행 코드(cad.py:129)의 문구 — 저장 결과는 그 앞 판의 문구(D2-60)
    assert res["warnings"][1:] == SRC_DRAWING["warnings"][1:] and len(res["warnings"]) == len(SRC_DRAWING["warnings"])
    assert res["confidence"] is not None and res["regions"] == [] and res["bom_rows"] == []


def _dxf(ents, insunits=4):
    return SD.dxf_bytes(ents, insunits=insunits)


def _outline(w=1000, h=200):
    return SD._lwpolyline([(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)], "OUTLINE")


def test_geometry_gates_eight_reasons(source_recognizer):
    _, model, _ = source_recognizer
    ents = _outline()
    ents += SD._circle(100, 100, 8, "HOLES")                                         # 정상 홀
    ents += [(0, "LINE"), (8, "X"), (10, "10"), (20, "10"), (30, "0"), (11, "50"), (21, "10"), (31, "0")]   # 열린 도형
    ents += SD._circle(1500, 100, 8, "HOLES")                                        # 외곽 밖
    ents += SD._lwpolyline([(300, 50, 0), (360, 50, 0), (360, 80, 0), (300, 80, 0)], "SLOTS")   # 곡선 없는 사각 — 슬롯/기타
    ents += SD._lwpolyline([(500, 20, 0), (900, 20, 0), (900, 180, 0), (500, 180, 0)], "X")   # 추가 외곽 후보 or 기타
    ents += [(0, "TEXT"), (8, "T"), (10, "1"), (20, "1"), (30, "0"), (40, "3"), (1, "NOTE")]
    ents += [(0, "CIRCLE"), (8, "Z"), (10, "200"), (20, "100"), (30, "5"), (40, "4")]           # 비평면 Z
    ents += [(0, "CIRCLE"), (8, "Z"), (10, "250"), (20, "100"), (30, "0"), (40, "4"), (210, "0"), (220, "0"), (230, "-1")]  # 뒤집힌 OCS
    res = run_extract(_dxf(ents), model)
    by = {o["id"]: o for o in res["objects"]}
    reasons = [o["review_reason"] for o in res["objects"]]
    assert by["OBJ-001"]["label"] == "outer" and by["OBJ-002"]["label"] == "hole"
    assert by["OBJ-003"]["review_reason"] == GX.REASON_OPEN and by["OBJ-003"]["label"] == "other"
    assert by["OBJ-004"]["review_reason"] == GX.REASON_OUTSIDE and by["OBJ-004"]["label"] == "other"
    assert all(o["label"] == "other" for o in res["objects"] if o["review_reason"])
    assert res["counts"]["other"] == sum(r is not None for r in reasons) and res["counts"]["hole"] == 1
    assert any("TEXT 1개" in w and "비평면 Z 좌표 1개" in w and "비평면/뒤집힌 OCS 1개" in w for w in res["warnings"])
    assert any(w.startswith("검토 대상") for w in res["warnings"])
    assert {"descriptors", "is_outer", "geometry_reason"}.isdisjoint(by["OBJ-001"])        # 도우미 키는 결과에 남기지 않는다


def test_model_reasons_score_and_shape(source_recognizer):
    _, model, _ = source_recognizer
    raw = SD.sample_bytes()
    strict = run_extract(raw, model, params={"object_classifier": {"score_min": 0.999}})     # 홀 점수 0.99 < 0.999
    holes = [o for o in strict["objects"] if o["entity"] == "CIRCLE"]
    assert all(o["review_reason"] == "분류 점수 99.9% 미만" and o["label"] == "other" for o in holes)
    assert strict["counts"]["hole"] == 0 and strict["counts"]["other"] == 6

    class Flip(_SourceModel):            # 모델이 외곽을 슬롯으로, 원을 외곽으로 — 외곽 불일치 · 추가 외곽
        def __init__(self):
            self.model, self.lock, self.classes_ = self, {"order": GEOM}, np.array(["hole", "other", "outer", "slot"])

        def predict_proba(self, X):
            out = np.zeros((len(X), 4))
            for i, circle in enumerate(X["is_circle"].to_numpy()):
                out[i, 2 if circle else 3] = 0.95
            return out
    res = run_extract(raw, Flip())
    assert res["objects"][0]["review_reason"] == OC.REASON_OUTER_MISMATCH
    assert all(o["review_reason"] == OC.REASON_EXTRA_OUTER for o in res["objects"] if o["entity"] == "CIRCLE")
    assert res["counts"] == {"outer": 0, "hole": 0, "slot": 2, "other": 7}


def test_no_outer_and_units(source_recognizer):
    _, model, _ = source_recognizer
    res = run_extract(_dxf(SD._circle(10, 10, 5, "H")), model)
    assert res["dimensions"] is None and res["objects"][0]["review_reason"] == GX.REASON_NO_OUTER
    assert "외곽을 찾지 못해 치수 자동 입력이 불가능합니다." in res["warnings"]
    inch = run_extract(_dxf(_outline(10, 2), insunits=None), model, unit="inch", override="inch")
    assert inch["dimensions"] == {"length": 254.0, "width": 50.8}
    assert any("사용자가 선택한 inch" in w for w in inch["warnings"])


@pytest.mark.parametrize("case,code,rule", [("vertices", "document_too_large", "vertices"),
                                            ("points", "document_too_large", "points"),
                                            ("empty", "invalid_document", "parse"),
                                            ("coords", "invalid_document", "parse")])
def test_limits_from_params(case, code, rule, source_recognizer):
    _, model, _ = source_recognizer
    params = {}
    if case == "vertices":
        ents = SD._lwpolyline([(i, (i % 2) * 5, 0) for i in range(501)], "P", closed=False)
    elif case == "points":
        ents, params = SD._circle(0, 0, 500, "C"), {"geometry_objects": {"max_points_entity": 20}}
    elif case == "empty":
        ents = [(0, "TEXT"), (8, "T"), (10, "1"), (20, "1"), (30, "0"), (40, "3"), (1, "ONLY TEXT")]
    else:
        ents = SD._lwpolyline([(0, 0, 0), (2e7, 0, 0), (2e7, 5, 0)], "P")
    with pytest.raises(ExtractError) as e:
        run_extract(_dxf(ents), model, params=params)
    assert (e.value.code, e.value.rule) == (code, rule)


def test_extractor_params_come_from_yaml():
    t = packs.load_pack("rollform-quote").tasks["cad_objects"]
    prm = {e["name"]: e["params"] for e in t["extractors"]}
    assert prm["geometry_objects"]["max_vertices"] == 500 and prm["geometry_objects"]["flatten_mm"] == 0.2
    assert prm["object_classifier"]["score_min"] == 0.8 and t["document"]["max_entities"] == 2000
    assert t["labels"] == "synthetic" and t["model"]["classes"] == ["outer", "hole", "slot", "other"]


# ── 3. 견적 ────────────────────────────────────────────────────────────────────────────────────
def _rates(ot):
    raw = ot.tasks["ot.quote"].raw["rates"]
    return {k: ({c: Decimal(x) for c, x in v.items()} if isinstance(v, dict) else Decimal(v)) for k, v in raw.items()}


def _std_inputs(src_input: dict) -> dict:
    inv = {v: k for k, v in RENAME.items()}
    return json.loads(json.dumps({inv[k]: v for k, v in src_input.items() if k in inv} | {"quantity": src_input["quantity"]}),
                      parse_float=Decimal)


def test_rates_are_tenant_tables_matching_source_config(ot):
    r = ot.tasks["ot.quote"].raw
    assert r["rate_tables"] == {"density": "steel_grade", "price_kg": "steel_grade"}
    a = SRC_QUOTE["assumptions"]
    assert r["rates"]["density"]["SPCC"] == str(a["density"]) and r["rates"]["price_kg"]["SPCC"] == str(a["price_kg"])
    for k in ("machine_per_min", "setup_minutes", "scrap_rate", "markup", "vat_rate"):
        assert Decimal(r["rates"][k]) == Decimal(str(a[k])), k
    assert set(r["rates"]["price_kg"]) == set(ot.tenant.config["categories"]["steel_grade"])
    assert not packs.load_pack("rollform-quote").tasks["quote"]["rates"]["price_kg"]           # 팩은 빈 표


def test_stored_quote_reconciliation_to_the_won(ot, source_regressor):
    _, fitted, _ = source_regressor
    src_in = SRC_QUOTE["input"]
    rec = {k: src_in[k] for k in NUM + CAT}
    minutes_raw = max(.05, float(fitted.predict(pd.DataFrame([rec])[NUM + CAT])[0]))
    out = QF.quote(_std_inputs(src_in), [], {"machining_minutes": Decimal(str(minutes_raw))}, _rates(ot))
    std = {k: int(v) for k, v in out["costs"].items()} | {"total": int(out["total"])}
    a = SRC_QUOTE["assumptions"]
    mat = {"density": a["density"], "price_kg": a["price_kg"]}
    now = source_calculate(src_in, minutes_raw, mat, a)
    assert std == now and std["total"] == 726484                                     # 표준 Decimal = 원천 현행 식, 원 단위
    stored = {"material": SRC_QUOTE["material_cost"], "processing": SRC_QUOTE["processing_cost"], "setup": SRC_QUOTE["setup_cost"],
              "markup": SRC_QUOTE["markup_cost"], "subtotal": SRC_QUOTE["subtotal"], "vat": SRC_QUOTE["vat"], "total": SRC_QUOTE["total"]}
    assert stored["total"] == 726487 and source_calculate(src_in, minutes_raw, mat, a, rounded_minutes=False) == stored
    assert std["material"] == stored["material"] and std["setup"] == stored["setup"] and std["vat"] == stored["vat"]
    assert stored["processing"] - std["processing"] == 2 and stored["total"] - std["total"] == 3   # D2-60 — 가공비 단계만
    line = out["lines"][0]
    assert line["weight_per_piece"] == Decimal(str(SRC_QUOTE["weight_per_piece"]))            # 3.0144
    assert line["minutes_per_piece"] == Decimal(str(SRC_QUOTE["minutes_per_piece"]))          # 1.3286
    assert line["total_minutes"] == Decimal(str(SRC_QUOTE["total_minutes"]))                  # 167.86
    assert all(isinstance(v, Decimal) and v == v.to_integral_value() for v in [*out["costs"].values(), out["total"]])


def test_half_boundary_case_is_documented_difference(ot):
    # D2-07a: 정확한 값이 .5 인 단계에서 원천 float 곱은 .4999… 로 내려갈 수 있다 — 표준(Decimal 정확값 HALF_UP)이 1원 많다
    rates = _rates(ot)
    inp = _std_inputs({"length": 1000, "width": 100, "thickness": 1, "holes": 0, "slots": 0, "bends": 0, "material": "SPCC",
                       "profile": "잔넬", "quantity": 5})
    minutes = Decimal("0.0430")                                                       # 0.043 × 900 × 5 = 193.5 (정확)
    out = QF.quote(inp, [], {"machining_minutes": minutes}, rates)
    assert out["costs"]["processing"] == Decimal("194")
    assert 0.043 * 900 * 5 < 193.5 and source_won(0.043 * 900 * 5) == 193           # 원천: float 193.49999999999997 → 193


def test_formula_is_decimal_only_static():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "gates" / "check_decimal.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr


# ── 4. 회사 ot 등록부 · API ────────────────────────────────────────────────────────────────────
def test_tenant_ot_registry(ot):
    assert ot.tenant.config["pack"] == "rollform-quote" and ot.tenant.config["mode"] == "demo"
    assert list(ot.tasks) == ["ot.machining_minutes", "ot.cad_objects", "ot.quote"] and not ot.disabled
    assert ot.tasks["ot.cad_objects"].raw["document"]["max_entities"] == 2000
    assert tenants.synth_call(ot, "ot.cad_objects").rows == 1600 and tenants.synth_call(ot, "ot.machining_minutes").rows == 900


def test_eval_csv_fixture_is_regenerated_not_edited(jobs):
    got = pd.read_parquet(FX / "snapshot.parquet")
    pd.testing.assert_frame_equal(got, jobs)
    csv = pd.read_csv(FX / "snapshot.csv", encoding="utf-8-sig", float_precision="round_trip")
    assert len(csv) == 900 and csv["ts"].isna().all()
    pd.testing.assert_frame_equal(csv.drop(columns=["ts"]), jobs.drop(columns=["ts"]), check_dtype=False)


def test_sample_file_is_generated_not_edited():
    assert (PACK / "samples" / "sample.dxf").read_bytes() == SD.sample_bytes()
