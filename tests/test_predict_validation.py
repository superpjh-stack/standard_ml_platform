"""goal §2.3 오류 계약(추론분) — 입력 검증 3단 · 결측 보정 · max_imputed · 학습 범위 · reject 정책 (개발2)."""

from __future__ import annotations

import json

import jsonschema
import pytest

import _dev2 as h

pytestmark = [pytest.mark.gate("G-M04"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
SCHEMA = h.response_schema()
SECRET = 123.456789   # 입력값 되풀이 감시용


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("val")
    m = h.make_tenant("ks", tmp)
    task = f"{m.tenant.code}.remaining_hours"
    ref, res = h.to_production(m, task)
    return m, task, ref, res, h.keys(m)


@pytest.fixture
def post(world):
    m, task, ref, res, k = world
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict"

    def _post(inputs=None, raw: str | None = None, **extra):
        if raw is not None:
            return tc.post(url, headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=raw)
        return tc.post(url, headers=h.hdr(k["operator"]), json={"inputs": inputs, **extra})
    return _post


def base(world):
    return h.safe_inputs(world[3])


def numeric_names(world):
    m, task = world[0], world[1]
    f = h.task_features(m, task)
    return [n for n, d in f.items() if d["dtype"] != "category"]


def err(r, code):
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    assert str(SECRET) not in r.text and "123.45" not in r.text            # 입력값을 되풀이하지 않는다
    return body["error"]["detail"]


def test_unknown_key(world, post):
    d = err(post({**base(world), "bogus_key": SECRET}), "invalid_input")
    assert d["field"] == "bogus_key" and d["rule"] == "unknown_key"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nan_inf(world, post, token):
    n = numeric_names(world)[0]
    inputs = json.dumps({**base(world), n: 0}).replace(f'"{n}": 0', f'"{n}": {token}')
    err(post(raw=json.dumps({"inputs": "__X__"}).replace('"__X__"', inputs)), "invalid_input")


@pytest.mark.parametrize("bad", ["12", True, [1], {"a": 1}])
def test_type_mismatch(world, post, bad):
    n = numeric_names(world)[0]
    err(post({**base(world), n: bad}), "invalid_input")


def test_number_for_category(world, post):
    err(post({**base(world), "machine_code": 3}), "invalid_input")


def test_extra_top_level_key(world, post):
    err(post(base(world), surprise=1), "invalid_input")


def test_out_of_bounds_min_max(world, post):
    m, task = world[0], world[1]
    f = h.task_features(m, task)
    n = numeric_names(world)[0]
    d = err(post({**base(world), n: f[n]["max"] + 1}), "out_of_bounds")
    assert d == {"field": n, "rule": "max"}
    d = err(post({**base(world), n: f[n]["min"] - 1}), "out_of_bounds")
    assert d["rule"] == "min"
    err(post({**base(world), n: 1e308}), "out_of_bounds")
    err(post({**base(world), "machine_code": "모르는-설비-ü"}), "out_of_bounds")


def test_missing_required(world, post):
    inputs = base(world)
    inputs.pop("machine_code")
    d = err(post(inputs), "missing_required")
    assert d["field"] == "machine_code" and d["rule"] == "required"
    err(post({**base(world), "machine_code": None}), "missing_required")


def test_max_imputed_boundary(world, post):
    nums = numeric_names(world)
    three = {k: v for k, v in base(world).items() if k not in nums[:3]}
    r = post(three)
    assert r.status_code == 200, r.text
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert body["imputed_fields"] == nums[:3]
    assert [w["field"] for w in body["warnings"] if w["code"] == "imputed"] == nums[:3]
    four = {k: v for k, v in base(world).items() if k not in nums[:4]}
    d = err(post(four), "missing_required")
    assert d["rule"] == "max_imputed"


def test_out_of_training_range_is_200_with_status(world, post):
    m, task, ref, res, k = world
    n = numeric_names(world)[0]
    p99 = res.lock["features"][n]["p99"]
    fmax = h.task_features(m, task)[n]["max"]
    r = post({**base(world), n: (p99 + fmax) / 2})          # 검증 범위 안 · 학습 범위 밖
    assert r.status_code == 200
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert body["status"] == "out_of_range" and body["out_of_range_fields"] == [n]
    assert {"code": "out_of_range", "field": n, "message": "학습 범위(p1~p99) 밖입니다"} in body["warnings"]
    assert body["prediction"]["value"] is not None            # predict_with_warning: 예측은 한다


def test_near_range_is_watch(world, post):
    m, task, ref, res, k = world
    n = numeric_names(world)[0]
    lo, hi = res.lock["features"][n]["p1"], res.lock["features"][n]["p99"]
    r = post({**base(world), n: hi - (hi - lo) * 0.005})
    body = r.json()
    assert n in [w["field"] for w in body["warnings"] if w["code"] == "near_range"]
    assert body["status"] in ("watch", "review")


def test_reject_policy_returns_rejected_without_value(tmp_path):
    m = h.make_tenant("ks", tmp_path, overrides={"remaining_hours": {"out_of_range": "reject"}})
    task = f"{m.tenant.code}.remaining_hours"
    _, res = h.to_production(m, task)
    k, tc = h.keys(m), h.client(m)
    feats = h.task_features(m, task)
    n = next(x for x, d in feats.items() if d["dtype"] != "category")
    val = (res.lock["features"][n]["p99"] + feats[n]["max"]) / 2
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                json={"inputs": {**h.safe_inputs(res), n: val}})
    assert r.status_code == 200
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert body["status"] == "rejected" and body["prediction"]["value"] is None and body["prediction"]["interval"] is None
    assert body["prediction_id"].startswith("prd_")


def test_validation_errors_are_not_recorded(world, post):
    m = world[0]
    before = h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (m.tenant.code,))
    post({**base(world), "bogus": 1})
    post({**base(world), "machine_code": None})
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (m.tenant.code,)) == before
