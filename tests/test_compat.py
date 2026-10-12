"""G-M04 C — 호환 라우터: ks · sw 옛 경로 · 옛 응답 키 (spec §15 M4 · D-18 · predict-contract §7). 소유 개발2.

기대값은 **원천 저장소 파일을 읽어 옮긴** `tests/compat_expected.yaml`(파일:줄 근거)이다 — 개발 코드가 아니다.
옛 값은 같은 요청의 표준 응답(`/api/v1 … /predict`)을 옛 규칙(반올림 · 상태 문구 · 장비 이름)으로 바꾼 것과 같아야 한다.
모델은 개발1 실제 학습기 → 승인 → production (tests/_dev2.py real_production). 원천 서비스는 실행하지 않는다.
"""

from __future__ import annotations

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
