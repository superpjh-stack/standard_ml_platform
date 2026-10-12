"""G-M04 C — 호환 라우터: ks · sw 옛 경로 · 옛 응답 키 (spec §15 M4 · D-18 · predict-contract §7). 소유 개발2.

기대값은 **원천 저장소 파일을 읽어 옮긴** `tests/compat_expected.yaml`(파일:줄 근거)이다 — 개발 코드가 아니다.
옛 값은 같은 요청의 표준 응답(`/api/v1 … /predict`)을 옛 규칙(반올림 · 상태 문구 · 장비 이름)으로 바꾼 것과 같아야 한다.
모델은 개발1 실제 학습기 → 승인 → production (tests/_dev2.py real_production). 원천 서비스는 실행하지 않는다.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
import yaml

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.gate("G-M04"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

EXP = yaml.safe_load((h.ROOT / "tests" / "compat_expected.yaml").read_text(encoding="utf-8"))
SOURCES = ["ks", "sw"]


@pytest.fixture(scope="module", params=SOURCES)
def world(request, tmp_path_factory):
    source = request.param
    m = h.make_tenant(source, tmp_path_factory.mktemp(f"compat-{source}"))
    refs = {t: h.real_production(m, t)[0] for t, td in m.tasks.items() if td.type != "optimize"}
    return source, m, refs, h.keys(m), EXP[source]


def _std(m, k, refs, inputs):
    """같은 입력의 표준 응답 — 유형별."""
    tc = h.client(m)
    out = {}
    for t, td in m.tasks.items():
        if td.type == "optimize":
            continue
        feats = [f for f in td.raw["features"]]
        r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{t}/predict", headers=h.hdr(k["operator"]),
                    json={"inputs": {n: inputs[n] for n in feats}})
        assert r.status_code == 200, r.text
        out[td.type] = r.json()
    return out


def _new_inputs(e, record):
    ren = e["request_rename"]
    return {ren.get(k2, k2): v for k2, v in record.items()}


def _old_422(r):
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"detail"} and isinstance(body["detail"], list) and body["detail"]
    assert all(set(d) == {"loc", "msg", "type"} for d in body["detail"])
    return body


def test_registry_lists_source_routes(world):
    source, m, refs, k, e = world
    assert set(e["routes"].values()) <= set(m.tenant.config["compat"]["routes"])


def test_bundle_predict_old_keys_and_values(world):
    source, m, refs, k, e = world
    tc = h.client(m)
    r = tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json=e["default_record"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == e["predict_keys"]                                    # 옛 키 · 순서 그대로
    std = _std(m, k, refs, _new_inputs(e, e["default_record"]))
    reg_key = e["predict_keys"][0]
    assert body[reg_key] == round(std["regression"]["prediction"]["value"], e["round"][reg_key])
    assert body["risk_probability"] == round(std["risk"]["probability"], e["round"]["risk_probability"])
    assert body["anomaly"] is std["anomaly"]["anomaly"]["flag"]
    assert body["status"] == (e["status_text"]["review"] if body["warnings"] else e["status_text"]["ok"])
    assert all(isinstance(w, str) for w in body["warnings"]) and body["imputed_fields"] == []
    assert body["model"] == std["regression"]["model"]["name"] and body["risk_model"] == std["risk"]["model"]["name"]
    assert body["version"] == std["regression"]["model"]["version"] and body["notice"] == std["regression"]["notice"]
    with connect() as c:                                                      # 표준 과제 3개가 기록된다
        n = c.execute("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id = %s AND channel = 'compat'",
                      (m.tenant.code,)).fetchone()["n"]
    assert n >= 3


def test_bundle_equipment_by_category(world):
    source, m, refs, k, e = world
    if "equipment" not in e:
        pytest.skip("이 원천에는 장비 키가 없다")
    tc = h.client(m)
    cat = next(n for n in e["default_record"] if isinstance(e["default_record"][n], str) and e["default_record"][n] in e["equipment"])
    for value, name in e["equipment"].items():
        r = tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json={**e["default_record"], cat: value})
        assert r.status_code == 200 and r.json()["equipment"] == name


@pytest.mark.parametrize("i", range(6))
def test_bundle_invalid_inputs_old_422(world, i):
    source, m, refs, k, e = world
    if i >= len(e["invalid_422"]):
        pytest.skip("케이스 없음")
    key, value = e["invalid_422"][i]
    r = h.client(m).post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json={**e["default_record"], key: value})
    body = _old_422(r)
    if isinstance(value, str):
        assert value not in r.text                                            # 입력값을 되풀이하지 않는다


def test_bundle_missing_and_finite(world):
    source, m, refs, k, e = world
    tc = h.client(m)
    rec = {**e["default_record"], **{n: None for n in e["missing_ok"]}}
    r = tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json=rec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["imputed_fields"]) == len(e["missing_ok"]) and body["warnings"]
    assert body["status"] == e["status_text"]["review"]
    _old_422(tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json={**rec, e["missing_fail_extra"]: None}))
    num = e["missing_ok"][0]
    _old_422(tc.post(e["routes"]["predict"], headers={**h.hdr(k["operator"]), "Content-Type": "application/json"},
                     content=json.dumps({**e["default_record"], num: 1.0}).replace("1.0", "Infinity")))
    _old_422(tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]), json={**e["default_record"], "unknown": 1}))
    _old_422(tc.post(e["routes"]["predict"], headers=h.hdr(k["operator"]),
                     json={k2: v for k2, v in e["default_record"].items() if k2 != num}))     # 키 누락(옛 모델은 키 필수)


def test_optimize_old_keys(world):
    source, m, refs, k, e = world
    tc = h.client(m)
    body = {"record": e["default_record"], **e["optimize_params"]}
    r = tc.post(e["routes"]["optimize"], headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert list(d) == e["optimize_keys"]
    assert d["feasible"] and not d["unmet_constraints"] and d["feasible_count"] > 0
    assert d["recommendation"] == d["alternatives"][0] and len(d["alternatives"]) <= 5
    assert d["recommendation"]["violation"] == 0
    if source == "ks":
        assert d["candidate_count"] == e["optimize_candidate_count"]           # 0.5h 격자 97점 — 원천과 같다
    else:
        assert d["candidate_count"] < e["optimize_candidate_count"]            # 학습 범위 ∩ (D-31, differs)
    inf = tc.post(e["routes"]["optimize"], headers=h.hdr(k["operator"]),
                  json={"record": e["default_record"], **{**e["optimize_params"], **e["optimize_infeasible"]}}).json()
    assert inf["feasible"] is False and inf["feasible_count"] == 0 and inf["unmet_constraints"]
    ranked = [a["violation"] for a in inf["alternatives"]]
    assert ranked == sorted(ranked) and ranked[0] > 0
    # 행 안 키 · 문구 · 목적 — 원천 api/ml_service.py 를 읽은 기대값 (DEF-QA2-001)
    for res in (d, inf):
        for row in [res["recommendation"], *res["alternatives"]]:
            assert list(row) == e["optimize_row_keys"], list(row)              # 옛 행 키 · 순서 그대로
            for key, nd in e["optimize_row_round"].items():
                assert row[key] == round(row[key], nd), (key, row[key])
            for key, (left, op, right) in e["optimize_row_relation"].items():
                lv = res["prediction"][left.split(".", 1)[1]] if left.startswith("prediction.") else row[left]
                assert op == "minus" and abs(row[key] - (lv - row[right])) <= 0.011, (key, row)
            if "anomaly" in row:
                assert isinstance(row["anomaly"], bool)
        assert res["objective"] == e["optimize_objective"]
    texts = e["optimize_unmet_text"]
    assert inf["unmet_constraints"] and set(inf["unmet_constraints"]) <= set(texts.values()), inf["unmet_constraints"]
    assert [x for x in texts.values() if x in inf["unmet_constraints"]] == inf["unmet_constraints"]   # 제약 순서
    if "optimize_anomaly_warning" in e:
        flagged = d["recommendation"].get("anomaly")
        assert (e["optimize_anomaly_warning"] in d["warnings"]) is bool(flagged)


@pytest.mark.parametrize("i", range(4))
def test_optimize_invalid_params_old_422(world, i):
    source, m, refs, k, e = world
    if i >= len(e["optimize_invalid_422"]):
        pytest.skip("케이스 없음")
    key, value = e["optimize_invalid_422"][i]
    body = {"record": e["default_record"], **e["optimize_params"], key: value}
    _old_422(h.client(m).post(e["routes"]["optimize"], headers=h.hdr(k["operator"]), json=body))


def test_overview_old_keys(world):
    source, m, refs, k, e = world
    r = h.client(m).get(e["routes"]["overview"], headers=h.hdr(k["viewer"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(e["overview_keys"]) <= set(d)
    # 원천 키 전부 — 내지 않는 키는 differs 에 사유와 함께 (DEF-QA2-010)
    omitted = set(e["differs"].get("overview_omitted") or [])
    assert omitted and e["differs"].get("overview")
    missing = [x for x in e["overview_source_keys"] if x not in d and x not in omitted]
    assert not missing, missing
    assert not omitted & set(d), omitted & set(d)                            # 사유를 단 키는 정말로 빠진다
    for key, values in e["overview_values"].items():
        assert d[key] == values, (key, d[key])
    if "overview_controls" in e:
        assert d["controls"] == e["overview_controls"]
    assert isinstance(d["missing_cells"], int) and isinstance(d["duplicate_lots"], int) and d["impossible_cells"] == 0
    assert d["duplicate_lots"] == 0 and d["missing_cells"] > 0                # 원천 합성 생성기: 결측 주입 · LOT 중복 0
    assert d["evaluated"] == e["split"]["test"]
    assert d["importance"] and all(list(x) == ["feature", "label", "mae_increase"] and x["mae_increase"] >= 0
                                   for x in d["importance"])
    assert d["rows"] == 720 and {kk: d["split"][kk] for kk in ("train", "validation", "test")} == e["split"]
    assert d["metrics"] and all(list(x) == e["overview_metric_keys"] for x in d["metrics"])
    assert d["risk_metrics"] and all(list(x) == e["overview_risk_metric_keys"] for x in d["risk_metrics"])
    assert [x["mae"] for x in d["metrics"]] == sorted(x["mae"] for x in d["metrics"])          # 원천 정렬(MAE ↑)
    assert [x["brier"] for x in d["risk_metrics"]] == sorted(x["brier"] for x in d["risk_metrics"])
    reg = next(t for t, td in m.tasks.items() if td.type == "regression")
    assert d["champion"] == refs[reg].algo and d["metrics"][0]["model"] == d["champion"]
    assert d["version"] == refs[reg].version


def test_records_old_paging_and_detail(world):
    source, m, refs, k, e = world
    tc = h.client(m)
    url = e["routes"]["records"]
    p1 = tc.get(url, headers=h.hdr(k["viewer"])).json()
    assert list(p1) == e["records_keys"] and p1["total"] == e["records_total"] and p1["limit"] == 15 and p1["offset"] == 0
    p2 = tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 15, "offset": 15}).json()
    assert not {r["lot_id"] for r in p1["records"]} & {r["lot_id"] for r in p2["records"]}
    times = [r["recorded_at"] for r in p1["records"]]
    assert times == sorted(times, reverse=True)
    reg_key = e["predict_keys"][0]
    assert all(reg_key in r and "lot_id" in r for r in p1["records"])
    for q in e["records_bad_queries"]:
        _old_422(tc.get(f"{url}?{q}", headers=h.hdr(k["viewer"])))
    assert tc.get(url, headers=h.hdr(k["viewer"]), params={"search": "DOES-NOT-EXIST"}).json()["records"] == []
    assert tc.get(url, headers=h.hdr(k["viewer"]), params={"search": ".*"}).json()["records"] == []
    row = p1["records"][0]
    d = tc.get(f"{url}/{row['lot_id']}", headers=h.hdr(k["viewer"])).json()
    assert list(d) == e["record_detail_keys"] and d["record"] == row
    # 옛 LOT 번호 형식(compat.entity_prefix) · 원천 LOT 번호로 상세 조회 (DEF-QA3-003)
    assert all(r["lot_id"].startswith(e["lot_id_prefix"]) for r in p1["records"] + p2["records"]), p1["records"][0]["lot_id"]
    first = tc.get(f"{url}/{e['lot_id_first']}", headers=h.hdr(k["viewer"]))
    assert first.status_code == 200, first.text[:200]
    assert first.json()["record"]["lot_id"] == e["lot_id_first"]
    found = tc.get(url, headers=h.hdr(k["viewer"]), params={"search": e["lot_id_first"]}).json()
    assert [r["lot_id"] for r in found["records"]] == [e["lot_id_first"]]
    nf = tc.get(f"{url}/DOES-NOT-EXIST", headers=h.hdr(k["viewer"]))
    assert nf.status_code == 404 and set(nf.json()) == {"detail"}


def test_health_old_keys(world):
    source, m, refs, k, e = world
    d = h.client(m).get(e["routes"]["health"]).json()
    assert list(d) == e["health_keys"] and d["model_ready"] is True and d["status"] == "ok"


def test_compat_auth_scope_and_unknown_routes(world):
    source, m, refs, k, e = world
    tc = h.client(m)
    url = e["routes"]["predict"]
    assert tc.post(url, json=e["default_record"]).status_code == 401
    assert tc.post(url, headers=h.hdr(k["viewer"]), json=e["default_record"]).status_code == 403
    other = h.make_tenant("sw" if source == "ks" else "ks", h.tenants_base(m).parent)
    ko = h.keys(other)
    assert tc.post(url, headers=h.hdr(ko["admin"]), json=e["default_record"]).status_code == 404
    other_route = EXP["sw" if source == "ks" else "ks"]["routes"]["predict"]
    r = tc.post(other_route, headers=h.hdr(k["operator"]), json=e["default_record"])   # 이 회사 compat.routes 에 없는 경로
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = tc.get("/api/does-not-exist", headers=h.hdr(k["admin"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ═══════════════════════ 2차 4개사 — 객체 경로 + 회사 모양 플러그인 (api-contract §5 · §6.3 · predict-contract §7.1) ═══════════════════════
# 기대값 = tests/compat_expected.yaml kd · pc (원천 파일:줄). 플러그인 = tenants/<code>/compat.py (등록부 폴더 안 파일 — 시험은 임시 등록부에 복사).

def _with_plugin(source: str, tmp):
    import shutil
    m = h.make_tenant(source, tmp)
    d = h.tenants_base(m) / m.tenant.code
    d.mkdir(exist_ok=True)
    shutil.copy(h.ROOT / "tenants" / source / "compat.py", d / "compat.py")
    return m


def _route_paths(m) -> set:
    return {r["path"] if isinstance(r, dict) else r for r in m.tenant.config["compat"]["routes"]}


@pytest.fixture(scope="module")
def kd(tmp_path_factory):
    m = _with_plugin("kd", tmp_path_factory.mktemp("compat-kd"))
    with h.use_tenants_dir(m):
        ref, _ = h.real_production(m, f"{m.tenant.code}.labor_hours")
        k = h.keys(m)
        tc = h.client(m)
        from importlib.util import module_from_spec, spec_from_file_location
        sp = spec_from_file_location("eto_sample_dxf_compat", h.ROOT / "packs" / "eto" / "synth" / "sample_dxf.py")
        sample = module_from_spec(sp)
        sp.loader.exec_module(sample)
        raw = sample.sample_bytes(m.tenant.config["categories"]["main_material"])
        yield m, k, tc, ref, raw, EXP["kd"]


def _kd_quote_input(e, d):
    return {**e["quote_input"], "drawing_id": d["id"],
            "bom": [{**{kk: r[kk] for kk in ("name", "material", "quantity", "mass_kg")}, "price_kg": e["price_kg"][r["material"]]}
                    for r in d["bom"]]}


def test_kd_registry_routes_and_health(kd):
    m, k, tc, ref, raw, e = kd
    want = {v.replace("{id}", "{drawing_id}" if v.startswith("/api/cad") else "{quote_id}") for v in e["routes"].values()}
    assert want <= _route_paths(m)
    assert not set(e["pending_routes"].values()) & _route_paths(m)              # 아직 없는 것은 없다고(가짜 응답 0)
    d = tc.get(e["routes"]["health"]).json()                                     # 옛 health 만 키 없이 (D-59)
    assert list(d) == e["health_keys"] and d["model_ready"] is True and d["version"] == ref.version


def test_kd_overview_old_keys(kd):
    m, k, tc, ref, raw, e = kd
    assert tc.get(e["routes"]["overview"]).status_code == 401
    d = tc.get(e["routes"]["overview"], headers=h.hdr(k["viewer"])).json()
    assert list(d) == e["overview_keys"]
    omitted = set(e["differs"]["overview_omitted"])
    assert not [x for x in e["overview_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert d["split"] == e["overview_split"] and d["missing_cells"] == e["overview_missing_cells"]
    assert len(d["metrics"]) == e["overview_metric_count"] and all(list(x) == e["overview_metric_keys"] for x in d["metrics"])
    assert d["champion"] == min(d["metrics"], key=lambda x: (x["mae"], x["model"]))["model"] == ref.algo   # tests/test_api.py:116
    assert list(d["features"]) == e["overview_feature_keys"]
    assert d["products"] == m.tenant.config["categories"]["product_family"]
    assert d["recognition"]["measured_accuracy"] is e["recognition_measured_accuracy"]
    assert "NaN" not in tc.get(e["routes"]["overview"], headers=h.hdr(k["viewer"])).text


def test_kd_analyze_and_drawing_old_keys(kd):
    m, k, tc, ref, raw, e = kd
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("KD-demo-reactor.dxf", raw)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert list(d) == e["drawing_keys"]
    omitted = set(e["differs"]["drawing_omitted"])
    assert not [x for x in e["drawing_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert d["counts"] == e["drawing_counts"] and len(d["bom"]) == e["drawing_bom_rows"]
    assert sum(b["quantity"] * b["mass_kg"] for b in d["bom"]) == e["drawing_bom_mass"]
    assert len(d["sha256"]) == 64 and d["mode"] == "uploaded_dxf" and d["scale_to_mm"] == 1.0
    assert all(list(o) == e["drawing_object_keys"] for o in d["objects"])
    assert tc.get(e["routes"]["drawing"].replace("{id}", d["id"]), headers=h.hdr(k["operator"])).json() == d   # :36
    nf = tc.get(e["routes"]["drawing"].replace("{id}", "doc_NOPE"), headers=h.hdr(k["operator"]))
    assert nf.status_code == 404 and nf.json() == {"detail": e["drawing_404_text"]}
    codes = e["analyze_errors"]
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("x.dwg", b"bad")})
    assert r.status_code == codes["wrong_ext"] and r.json() == {"detail": e["analyze_error_text"][415]}
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("x.dxf", b"bad")})
    assert r.status_code == codes["not_dxf"] and isinstance(r.json()["detail"], str)       # main.py:96 HTTPException(422, str)
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("x.dxf", b"x" * (5 * 1024 * 1024 + 1))})
    assert r.status_code == codes["too_big"] and r.json() == {"detail": e["analyze_error_text"][413]}
    assert tc.post(e["routes"]["analyze"], headers=h.hdr(k["viewer"]), files={"file": ("a.dxf", raw)}).status_code == 403


def test_kd_quote_old_keys_and_money_matches_standard(kd):
    m, k, tc, ref, raw, e = kd
    d = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("KD-demo-reactor.dxf", raw)}).json()
    data = _kd_quote_input(e, d)
    data["bom"][0]["name"] = "=malicious()"                                      # tests/test_api.py:41
    r = tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json=data)
    assert r.status_code == 200, r.text
    q = r.json()
    assert list(q) == e["quote_keys"] and q["status"] == e["quote_status_draft"]
    assert all(list(ln) == e["quote_line_keys"] for ln in q["lines"])
    assert q["material_cost"] == sum(ln["cost"] for ln in q["lines"])           # tests/test_api.py:43-46
    assert q["outsource_cost"] == e["quote_outsource_cost"]
    assert q["subtotal"] == q["material_cost"] + q["labor_cost"] + q["outsource_cost"] + q["markup_cost"]
    assert q["total"] == q["subtotal"] + q["vat"]
    assert q["source_bom"] == d["bom"] and q["input"] == data                   # :47
    assert tc.get(e["routes"]["quote"].replace("{id}", q["id"]), headers=h.hdr(k["operator"])).json() == q   # :48
    std = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.quote/quotes/{q['id']}",
                 headers=h.hdr(k["operator"])).json()                            # 같은 견적의 표준 응답 — 금액은 표준 Decimal 결과 그대로
    assert std["status"] == "draft" and str(q["total"]) == std["total"]
    assert [str(ln["cost"]) for ln in q["lines"]] == [ln["amount"] for ln in std["lines"]]
    assert str(q["hours_per_unit"]) == std["predictions"][0]["value"]
    text = tc.get(e["routes"]["quote_csv"].replace("{id}", q["id"]), headers=h.hdr(k["operator"])).content.decode("utf-8-sig")
    assert "'=malicious()" in text and str(q["total"]) in text                  # :50-51
    rows = list(csv.reader(io.StringIO(text)))
    labels = [r[0] for r in rows if r]
    assert all(x in labels for x in e["quote_csv_rows"]) and e["quote_csv_line_head"] in rows
    assert dict(r for r in rows if len(r) == 2)["합계(원)"] == str(q["total"])
    nf = tc.get(e["routes"]["quote"].replace("{id}", "missing"), headers=h.hdr(k["operator"]))
    assert nf.status_code == 404 and nf.json() == {"detail": e["quote_404_text"]}   # :109


@pytest.mark.parametrize("i", range(12))
def test_kd_quote_invalid_old_422(kd, i):
    m, k, tc, ref, raw, e = kd
    d = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("KD-demo-reactor.dxf", raw)}).json()
    change = e["quote_invalid_422"][i]
    _old_422(tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json={**_kd_quote_input(e, d), **change}))


def test_kd_quote_list_paging_and_export_matches_visible(kd):
    m, k, tc, ref, raw, e = kd
    d = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("KD-demo-reactor.dxf", raw)}).json()
    for _ in range(3):
        assert tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json=_kd_quote_input(e, d)).status_code == 200
    params = {"offset": 1, "limit": 1}
    page = tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params=params).json()
    assert list(page) == e["quote_list_keys"] and page["total"] >= 3 and len(page["records"]) == 1   # :102
    assert tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params=params).json() == page   # :103
    ex = tc.get(e["routes"]["export_csv"], headers=h.hdr(k["operator"]), params=params)
    assert ex.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(ex.content.decode("utf-8-sig"))))
    assert rows[0] == e["export_head"] and len(rows) == 2 and rows[1][0] == page["records"][0]["id"]   # :104-105
    assert rows[1][4] == str(page["records"][0]["total"])
    assert tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params={"search": "%"}).json()["total"] == 0   # :106
    for q in e["quote_list_bad_queries"]:
        _old_422(tc.get(f"{e['routes']['quotes']}?{q}", headers=h.hdr(k["operator"])))


def test_kd_quote_old_route_never_confirms(kd):
    """옛 견적 경로는 원천에 확정이 없으므로 draft 만 만든다 — 확정은 표준 경로 · 승인으로만 (api-contract §6.3)."""
    m, k, tc, ref, raw, e = kd
    with connect() as c:
        n = c.execute("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id = %s AND status <> 'draft'",
                      (m.tenant.code,)).fetchone()["n"]
        a = c.execute("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id = %s AND kind = 'quote'",
                      (m.tenant.code,)).fetchone()["n"]
    assert n == 0 and a == 0


@pytest.fixture(scope="module")
def pc(tmp_path_factory):
    m = _with_plugin("pc", tmp_path_factory.mktemp("compat-pc"))
    with h.use_tenants_dir(m):
        k = h.keys(m)
        tc = h.client(m)
        before = tc.get(EXP["pc"]["routes"]["health"]).json()
        ref, _ = h.real_production(m, f"{m.tenant.code}.sensory_score")
        yield m, k, tc, ref, before, EXP["pc"]


def test_pc_registry_routes_and_health(pc):
    m, k, tc, ref, before, e = pc
    assert set(e["routes"].values()) <= _route_paths(m)
    assert not set(e["pending_routes"].values()) & _route_paths(m)
    assert before["model_ready"] is False                                        # 운영 모델 없으면 준비 안 됨 — 지어내지 않는다
    d = tc.get(e["routes"]["health"]).json()
    assert list(d) == e["health_keys"] and d["model_ready"] is True and d["data_mode"] == e["health_data_mode"]
    assert d["product"] == m.tenant.config["name"]                               # tests/test_api.py:9 (회사 이름 = 등록부)


def test_pc_overview_old_keys(pc):
    m, k, tc, ref, before, e = pc
    d = tc.get(e["routes"]["overview"], headers=h.hdr(k["viewer"])).json()
    assert list(d) == e["overview_keys"]
    omitted = set(e["differs"]["overview_omitted"])
    assert not [x for x in e["overview_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert d["data_mode"] == "demo" and len(d["metrics"]) == e["overview_metric_count"]    # tests/test_api.py:10
    assert all(list(x) == e["overview_metric_keys"] for x in d["metrics"])
    assert [x["mae_score"] for x in d["metrics"]] == sorted(x["mae_score"] for x in d["metrics"])   # ml_service.py:78
    assert d["champion"] == d["metrics"][0]["model"] == ref.algo
    assert d["features"] == e["overview_features"] and d["target"] == e["overview_target"]
    assert d["rows"] == e["overview_rows"] and d["missing_cells"] == e["overview_missing_cells"] and d["duplicate_lots"] == 0


def test_pc_predict_old_keys_and_recipe_rules(pc):
    m, k, tc, ref, before, e = pc
    url = e["routes"]["predict"]
    r = tc.post(url, headers=h.hdr(k["operator"]), json=e["valid_record"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == e["predict_keys"] and body["prediction_score"] > 0                 # tests/test_api.py:13
    std = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.sensory_score/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": {("prod_line" if kk == "line" else kk): v for kk, v in e["valid_record"].items()}}).json()
    assert body["prediction_score"] == round(std["prediction"]["value"], e["predict_round"])
    assert body["model"] == std["model"]["name"] and body["notice"] == std["notice"]
    assert body["status"] == (e["status_text"]["review"] if body["warnings"] else e["status_text"]["ok"])
    if std["prediction"]["value"] < m.tasks[f"{m.tenant.code}.sensory_score"].raw["thresholds"]["review_below"]:
        assert e["low_score_text"] in body["warnings"]
    _old_422(tc.post(url, headers=h.hdr(k["operator"]), json={**e["valid_record"], **e["recipe_reject"]}))   # :14
    w = tc.post(url, headers=h.hdr(k["operator"]), json={**e["valid_record"], **e["recipe_warn"]}).json()
    assert e["recipe_warn_text"] in w["warnings"] and w["status"] == e["status_text"]["review"]
    _old_422(tc.post(url, headers=h.hdr(k["operator"]), json={**e["valid_record"], "line": "K3"}))
    _old_422(tc.post(url, headers=h.hdr(k["operator"]), json={kk: v for kk, v in e["valid_record"].items() if kk != "salt_pct"}))
    assert tc.post(url, headers=h.hdr(k["viewer"]), json=e["valid_record"]).status_code == 403
    assert tc.post(url, json=e["valid_record"]).status_code == 401


def test_pc_quality_overview_is_standard_queue(pc):
    from datetime import date
    from mlcore.monitor import review as job
    m, k, tc, ref, before, e = pc
    empty = tc.get(e["routes"]["queue"], headers=h.hdr(k["operator"])).json()
    assert empty["priority_queue"] == [] and empty["residual_review_threshold"] is None   # 대기열이 비면 비었다고
    job.run_review(m.tenant.code, date(2026, 10, 3), merged=m)
    d = tc.get(e["routes"]["queue"], headers=h.hdr(k["operator"])).json()
    assert list(d) == e["queue_keys"] and d["notice"] == e["queue_notice"]
    omitted = set(e["differs"]["queue_omitted"])
    assert not [x for x in e["queue_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert 0 < len(d["priority_queue"]) <= e["queue_top"]
    assert all(list(x) == e["queue_row_keys"] for x in d["priority_queue"])
    res = [x["residual_score"] for x in d["priority_queue"]]
    assert res == sorted(res, reverse=True) and min(res) >= d["residual_review_threshold"] - 0.01
    items = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.residual_review/review",
                   headers=h.hdr(k["operator"]), params={"limit": 100}).json()["items"]
    assert {i["origin"] for i in items} <= {"test_split", "live_residual"}       # 표본 내 채점 항목 0 (G2-R01)
    assert d["residual_review_threshold"] == round(items[0]["threshold"], 2)
    assert tc.get(e["routes"]["queue"], headers=h.hdr(k["viewer"])).status_code == 403   # 대기열 조회는 operator 이상(goal2 §6)


def test_pc_records_old_keys_filters(pc):
    m, k, tc, ref, before, e = pc
    url = e["routes"]["records"]
    b = tc.get(f"{url}?{e['records_query']}", headers=h.hdr(k["viewer"])).json()
    assert list(b) == e["records_keys"] and 0 < len(b["records"]) <= 7                  # tests/test_api.py:22
    assert all(r["line"] == "K1" and r["cabbage_origin"] == "평창" for r in b["records"])
    assert all(list(r) == e["record_key_order"] for r in b["records"])
    times = [r["produced_at"] for r in b["records"]]
    assert times == sorted(times, reverse=True)                                  # main.py:56
    assert tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 100}).json()["total"] == e["records_total"]
    for q in e["records_bad_queries"]:
        _old_422(tc.get(f"{url}?{q}", headers=h.hdr(k["viewer"])))               # :23


@pytest.fixture(scope="module")
def ot(tmp_path_factory):
    import shutil
    overrides = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
                 for p in sorted((h.ROOT / "tenants" / "ot" / "tasks").glob("*.yaml"))}
    m = h.make_tenant("ot", tmp_path_factory.mktemp("compat-ot"), overrides=overrides)
    d = h.tenants_base(m) / m.tenant.code
    shutil.copy(h.ROOT / "tenants" / "ot" / "compat.py", d / "compat.py")
    with h.use_tenants_dir(m):
        ref, _ = h.real_production(m, f"{m.tenant.code}.machining_minutes")
        h.real_production(m, f"{m.tenant.code}.cad_objects")
        yield m, h.keys(m), h.client(m), ref, EXP["ot"]


def _ot_payload(e, d):
    return {**e["quote_payload"], "drawing_id": d["id"]}


def test_ot_registry_routes_health_overview(ot):
    m, k, tc, ref, e = ot
    want = {v.replace("{id}", "{drawing_id}" if v.startswith("/api/cad") else "{quote_id}") for v in e["routes"].values()}
    assert want <= _route_paths(m) and not set(e["pending_routes"].values()) & _route_paths(m)
    d = tc.get(e["routes"]["health"]).json()
    assert list(d) == e["health_keys"] and d["model_ready"] is True and d["version"] == ref.version
    o = tc.get(e["routes"]["overview"], headers=h.hdr(k["viewer"])).json()
    assert list(o) == e["overview_keys"]
    omitted = set(e["differs"]["overview_omitted"])
    assert not [x for x in e["overview_source_keys"] if x not in o and x not in omitted] and not omitted & set(o)
    assert len(o["metrics"]) == e["overview_metric_count"] and sum(o["split"]["jobs"]) == o["job_rows"]   # :149-150
    assert list(o["features"]) == e["overview_feature_keys"] and o["profiles"] == m.tenant.config["categories"]["section_profile"]


def test_ot_demo_sample_analyze_drawing(ot):
    m, k, tc, ref, e = ot
    s = tc.get(e["routes"]["sample_dxf"], headers=h.hdr(k["viewer"]))
    assert s.status_code == 200 and s.headers["content-type"].startswith("application/dxf")
    r = tc.post(e["routes"]["demo"], headers=h.hdr(k["operator"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert list(d) == e["drawing_keys"] and d["data_mode"] == "synthetic_demo"
    omitted = set(e["differs"]["drawing_omitted"])
    assert not [x for x in e["drawing_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert d["counts"] == e["demo_counts"] and d["dimensions"] == e["demo_dimensions"] and len(d["objects"]) == e["demo_objects"]
    assert tc.get(e["routes"]["drawing"].replace("{id}", d["id"]), headers=h.hdr(k["operator"])).json() == {**d, "data_mode": "uploaded_geometry_synthetic_model"}
    for name in e["analyze_415"]:
        r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": (name, s.content)})
        assert r.status_code == 415 and r.json() == {"detail": e["analyze_error_text"][415]}
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("bad.dxf", b"not DXF")})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": ("large.dxf", b"0" * (5 * 1024 * 1024 + 1))})
    assert r.status_code == 413 and r.json() == {"detail": e["analyze_error_text"][413]}
    r = tc.post(e["routes"]["analyze"], headers=h.hdr(k["operator"]), files={"file": (e["path_filename"]["upload"], s.content)})
    assert r.status_code == 200 and r.json()["filename"] == e["path_filename"]["saved"]
    assert r.json()["data_mode"] == "uploaded_geometry_synthetic_model"


def test_ot_quote_accounting_overrides_csv(ot):
    m, k, tc, ref, e = ot
    d = tc.post(e["routes"]["demo"], headers=h.hdr(k["operator"])).json()
    p = {**_ot_payload(e, d), "holes": 7, "review_note": "=SUM(1,2) 수식이 아닌 사용자 확인 내용"}   # tests/test_api.py:48-50
    r = tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json=p)
    assert r.status_code == 200, r.text
    q = r.json()
    assert list(q) == e["quote_keys"]
    assert q["weight_per_piece"] == e["quote_weight_per_piece"] and q["setup_cost"] == e["quote_setup_cost"]
    from decimal import ROUND_HALF_UP, Decimal
    want = (Decimal(str(q["minutes_per_piece"])) * Decimal(str(q["assumptions"]["machine_per_min"])) * p["quantity"]).quantize(
        Decimal(1), rounding=ROUND_HALF_UP)                                    # :55 won(minutes × 단가 × 수량)
    assert q["processing_cost"] == int(want)
    assert q["subtotal"] == q["material_cost"] + q["processing_cost"] + q["setup_cost"] + q["markup_cost"]
    assert q["total"] == q["subtotal"] + q["vat"]
    assert Decimal(str(q["unit_price"])) == (Decimal(q["subtotal"]) / 100).quantize(Decimal("0.01"))   # :58
    assert q["overrides"] == e["quote_override_holes"]                         # :59 — 사람 수정 이력(옛 키)
    assert tc.get(e["routes"]["quote"].replace("{id}", q["id"]), headers=h.hdr(k["operator"])).json() == q   # :60
    std = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.quote/quotes/{q['id']}", headers=h.hdr(k["operator"])).json()
    assert str(q["total"]) == std["total"] and std["status"] == "draft"        # 금액 = 표준 Decimal 결과 그대로
    rows = dict(r for r in csv.reader(io.StringIO(tc.get(e["routes"]["quote_csv"].replace("{id}", q["id"]),
                                                         headers=h.hdr(k["operator"])).content.decode("utf-8-sig"))) if len(r) == 2)
    c = e["quote_csv_checks"]
    assert rows[c["supply"]] == str(q["subtotal"]) and rows[c["holes"]] == "7" and rows[c["note"]].startswith("'=SUM")   # :63-65


@pytest.mark.parametrize("i", range(14))
def test_ot_quote_invalid_old_422(ot, i):
    m, k, tc, ref, e = ot
    d = tc.post(e["routes"]["demo"], headers=h.hdr(k["operator"])).json()
    key, value = e["quote_invalid_422"][i]
    r = tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json={**_ot_payload(e, d), key: value})
    assert r.status_code == 422, (key, value, r.text)


def test_ot_quote_nonfinite_paging_and_404(ot):
    m, k, tc, ref, e = ot
    d = tc.post(e["routes"]["demo"], headers=h.hdr(k["operator"])).json()
    for v in e["quote_nonfinite"]:                                             # :76-83
        body = json.dumps(_ot_payload(e, d)).replace('"thickness": 2', '"thickness": ' + v)
        r = tc.post(e["routes"]["quotes"], headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=body)
        assert r.status_code == 422 and isinstance(r.json()["detail"], list), v
    before = tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"])).json()["total"]
    for _ in range(3):
        assert tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json=_ot_payload(e, d)).status_code == 200
    first = tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params={"limit": 2}).json()
    second = tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params={"limit": 2, "offset": 2}).json()
    assert first["total"] == before + 3 and len(first["records"]) == 2
    assert not {r["id"] for r in first["records"]} & {r["id"] for r in second["records"]}
    assert tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params={"limit": 2}).json() == first
    assert tc.get(e["routes"]["quotes"], headers=h.hdr(k["operator"]), params={"search": "%"}).json()["total"] == 0
    for q in e["quote_list_bad_queries"]:
        _old_422(tc.get(f"{e['routes']['quotes']}?{q}", headers=h.hdr(k["operator"])))
    for path in e["quote_404"]:
        assert tc.get(path, headers=h.hdr(k["operator"])).status_code == 404, path
    r = tc.post(e["routes"]["quotes"], headers=h.hdr(k["operator"]), json={**_ot_payload(e, d), "drawing_id": "doc_01M4RNXVMPYNZGXXNWJZ6CP01R"})
    assert r.status_code == 404 and r.json() == {"detail": "먼저 CAD 도면을 분석하세요."}   # main.py:104


@pytest.fixture(scope="module")
def krs(tmp_path_factory):
    m = _with_plugin("krs", tmp_path_factory.mktemp("compat-krs"))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        before = tc.get(EXP["krs"]["routes"]["health"]).json()
        ref, _ = h.real_production(m, f"{m.tenant.code}.joint_strength")
        yield m, k, tc, ref, before, EXP["krs"]


def test_krs_routes_health_overview(krs):
    m, k, tc, ref, before, e = krs
    assert set(e["routes"].values()) <= _route_paths(m) and not set(e["pending_routes"].values()) & _route_paths(m)
    assert before == {"status": "ok", "model_ready": False}                     # 원천은 늘 true — 표준은 운영 모델이 있어야
    d = tc.get(e["routes"]["health"]).json()
    assert list(d) == e["health_keys"] and d["model_ready"] is True
    o = tc.get(e["routes"]["overview"], headers=h.hdr(k["viewer"])).json()
    assert list(o) == e["overview_keys"]
    omitted = set(e["differs"]["overview_omitted"])
    assert not [x for x in e["overview_source_keys"] if x not in o and x not in omitted] and not omitted & set(o)
    assert list(o["quality"]) == e["overview_quality_keys"] and o["quality"]["missing_cells"] > 0     # tests/test_api.py:12
    assert len(o["models"]) == e["overview_model_count"] and all(list(x) == e["overview_model_keys"] for x in o["models"])
    assert o["models"][0]["rmse"] <= o["models"][-1]["rmse"]                     # :11
    assert o["features"] == e["overview_features"] and o["target"] == e["overview_target"] and o["champion"] == ref.algo


def test_krs_samples_old_keys_and_supplier_codes(krs):
    m, k, tc, ref, before, e = krs
    b = tc.get(e["routes"]["samples"], headers=h.hdr(k["viewer"])).json()
    assert list(b) == e["samples_keys"] and b["total"] == e["samples_total"] and len(b["items"]) == e["samples_default_limit"]
    assert all(list(x) == e["samples_item_keys"] for x in b["items"])
    assert {x["supplier"] for x in b["items"]} <= set(e["old_suppliers"])        # 옛 표기 A · B · C
    _old_422(tc.get(f"{e['routes']['samples']}?limit=0", headers=h.hdr(k["viewer"])))


def test_krs_predict_old_keys_rules_and_warnings(krs):
    m, k, tc, ref, before, e = krs
    url = e["routes"]["predict"]
    r = tc.post(url, headers=h.hdr(k["operator"]), json=e["predict_record"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == e["predict_keys"] and body["predicted_strength"] > 0   # tests/test_api.py:33-35
    std_in = {**e["predict_record"], "supplier": m.tenant.config["categories"]["supplier"][0]}
    std = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.joint_strength/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": std_in}).json()
    assert body["predicted_strength"] == round(std["prediction"]["value"], 2) and body["model"] == std["model"]["name"]
    assert body["status"] == (e["predict_status"]["warn"] if body["warnings"] else e["predict_status"]["ok"])
    no_sup = {kk: v for kk, v in e["predict_record"].items() if kk != "supplier"}
    assert tc.post(url, headers=h.hdr(k["operator"]), json=no_sup).json()["predicted_strength"] == body["predicted_strength"]   # 기본 A
    _old_422(tc.post(url, headers=h.hdr(k["operator"]), json={**e["predict_record"], **e["predict_unbalanced"]}))   # :38-42
    _old_422(tc.post(url, headers=h.hdr(k["operator"]), json={**e["predict_record"], "supplier": "D"}))
    w = tc.post(url, headers=h.hdr(k["operator"]), json={**e["predict_record"], "temperature_c": e["recommended_warn"]["temperature_c"]}).json()
    assert e["recommended_warn"]["text"] in w["warnings"] and w["status"] == e["predict_status"]["warn"]


def test_krs_quality_overview_is_standard_queue(krs):
    from datetime import date
    from mlcore.monitor import review as job
    m, k, tc, ref, before, e = krs
    job.run_review(m.tenant.code, date(2026, 10, 4), merged=m)
    d = tc.get(e["routes"]["queue"], headers=h.hdr(k["operator"])).json()
    assert list(d) == e["queue_keys"] and d["review_threshold"] == e["queue_threshold"]
    omitted = set(e["differs"]["queue_omitted"])
    assert not [x for x in e["queue_source_keys"] if x not in d and x not in omitted] and not omitted & set(d)
    assert d["flagged_lots"] > 0 and d["flagged"] and d["flagged"][0]["absolute_error"] >= d["review_threshold"]   # tests/test_api.py:27-29
    assert all(list(x) == e["queue_row_keys"] for x in d["flagged"]) and len(d["flagged"]) <= 12
    errs = [x["absolute_error"] for x in d["flagged"]]
    assert errs == sorted(errs, reverse=True)
    items = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.residual_review/review",
                   headers=h.hdr(k["operator"]), params={"limit": 100}).json()["items"]
    assert {i["origin"] for i in items} <= {"test_split", "live_residual"}


def test_krs_records_old_keys(krs):
    m, k, tc, ref, before, e = krs
    b = tc.get(e["routes"]["records"], headers=h.hdr(k["viewer"]), params={"limit": 5}).json()
    assert list(b) == e["records_keys"] and len(b["items"]) == 5 and b["total"] == e["samples_total"]   # tests/test_api.py:47-48
    assert all(list(x) == e["records_item_keys"] for x in b["items"])
    assert {x["supplier"] for x in b["items"]} <= set(e["old_suppliers"])
    for q in e["records_bad_queries"]:
        _old_422(tc.get(f"{e['routes']['records']}?{q}", headers=h.hdr(k["viewer"])))
