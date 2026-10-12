"""B02 tasks · B06 overview · B12 records · B14 monitor · doctor API (contracts/api-contract.md) — 개발3 경로.

역할은 std/roles.yaml(goal §6): overview 영역 = 전원 조회, monitor 영역 = operator 조회 이상(viewer 403).
다른 회사 키는 404(미들웨어). 라우터 등록(`api/main.py`)은 개발2 — 등록 전이면 이 시험이 시험 앱에만 붙인다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import _dev3 as h

ROOT = h.ROOT


def _has_ops(app) -> bool:
    scope = {"type": "http", "path": "/api/v1/tenants/x/doctor", "method": "GET", "root_path": ""}
    for r in app.router.routes:
        m, child = r.matches(scope)
        if m.name == "FULL":
            ep = (child or {}).get("endpoint") or getattr(r, "endpoint", None)
            return getattr(ep, "__module__", "") == "mlcore.api.routers.ops"
    return False


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    from mlcore.api import main
    from mlcore.api.routers import ops

    app = main.app
    if not getattr(ops, "_registered", False) and not _has_ops(app):
        # 개발2 가 main.py 에 등록하기 전까지(요청 기록: progress-dev3 §3). 호환 잡이(`/api/{rest}`)보다 앞에 둔다.
        app.include_router(ops.router)
        app.router.routes.insert(0, app.router.routes.pop())
        ops._registered = True
    base = tmp_path_factory.mktemp("tenants")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLP_TENANTS_DIR", str(base))
        code = h.copy_tenant("ks", base)
        other = h.copy_tenant("sw", base)
        m = h.register_db(code)
        mo = h.register_db(other)
        v1 = h.train_to_production(code, f"{code}.remaining_hours")
        k = h.keys(m)
        ko = h.keys(mo)
        tc = h.client(code)
        yield {"code": code, "k": k, "ko": ko, "tc": tc, "v1": v1}
        tc.__exit__(None, None, None)


def test_list_tasks(world):
    code, tc, k = world["code"], world["tc"], world["k"]
    r = tc.get(f"/api/v1/tenants/{code}/tasks", headers=h.hdr(k["viewer"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_cursor"] is None and body["total"] == 4
    items = {i["task"]: i for i in body["items"]}
    assert set(items) == {f"{code}.{n}" for n in ("remaining_hours", "failure_24h", "sensor_ood", "maintenance_timing")}
    assert items[f"{code}.remaining_hours"]["production"]["version"] == world["v1"]
    assert items[f"{code}.failure_24h"]["production"] is None                     # 지어내지 않는다
    assert items[f"{code}.maintenance_timing"]["uses"] == [f"{code}.remaining_hours"]
    assert tc.get(f"/api/v1/tenants/{code}/tasks").status_code == 401


def test_task_detail_for_forms(world):
    code, tc, k = world["code"], world["tc"], world["k"]
    r = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.remaining_hours", headers=h.hdr(k["viewer"]))
    assert r.status_code == 200
    d = r.json()
    feats = {f["name"]: f for f in d["features"]}
    assert list(feats)[:2] == ["press_force", "vibration"] and len(feats) == 9
    assert feats["machine_code"]["values"] == ["PRS-01", "PRS-02", "PRS-03", "PRS-04"]   # values_from: tenant → 회사 값
    assert feats["vibration"]["min"] == 0.4 and d["interval"]["alpha"] == 0.1 and d["target"]["name"] == "remaining_hours"
    r = tc.get(f"/api/v1/tenants/{code}/tasks/maintenance_timing", headers=h.hdr(k["viewer"]))   # 짧은 이름도 받는다
    d = r.json()
    assert d["type"] == "optimize" and len(d["features"]) == 9 and d["controls"] == []
    assert d["decision_vars"]["stop_after_hours"]["step"] == 0.5 and d["params"]["reserve_hours"]["default"] == 12
    assert tc.get(f"/api/v1/tenants/{code}/tasks/{code}.nope", headers=h.hdr(k["viewer"])).status_code == 404


def test_overview_and_monitor_alerts(world):
    from mlcore.monitor import daily

    code, tc, k = world["code"], world["tc"], world["k"]
    task = f"{code}.remaining_hours"
    r = tc.get(f"/api/v1/tenants/{code}/tasks/{task}/overview", headers=h.hdr(k["viewer"]))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["production"]["version"] == world["v1"] and o["model_ready"] is True
    assert o["test_metrics"]["mae"] == pytest.approx(5.568, abs=5e-4) and o["baseline"]["mae"] > o["test_metrics"]["mae"]
    assert o["predictions_yesterday"] == 0 and o["monitor"]["level"] is None and o["monitor"]["note"] == "감시 기록 없음"
    o2 = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.failure_24h/overview", headers=h.hdr(k["viewer"])).json()
    assert o2["production"] is None and o2["model_ready"] is False and o2["test_metrics"] is None
    # 감시 하루 → 경고 배지
    drift = pd.read_parquet(ROOT / "tests" / "fixtures" / "ks" / "drift.parquet")
    daily.run_daily(code, date(2026, 9, 3), frames={task: drift}, submit_retrain=False)
    o = tc.get(f"/api/v1/tenants/{code}/tasks/{task}/overview", headers=h.hdr(k["viewer"])).json()
    assert o["monitor"]["level"] == "retrain" and o["monitor"]["day"] == "2026-09-03"
    assert {"metric": "psi", "feature": "vibration"} in [{x: a[x] for x in ("metric", "feature")} for a in o["monitor"]["alerts"]]
    # 화면 6: 추이
    assert tc.get(f"/api/v1/tenants/{code}/tasks/{task}/monitor", headers=h.hdr(k["viewer"])).status_code == 403
    r = tc.get(f"/api/v1/tenants/{code}/tasks/{task}/monitor", headers=h.hdr(k["operator"]), params={"metric": "psi"})
    assert r.status_code == 200
    mon = r.json()
    assert mon["last_day"] == "2026-09-03" and {i["metric"] for i in mon["items"]} == {"psi"} and len(mon["items"]) == 9
    assert mon["retrain_candidates"] == []
    assert tc.get(f"/api/v1/tenants/{code}/tasks/{task}/monitor", headers=h.hdr(k["operator"]),
                  params={"metric": "bogus"}).status_code == 422


def test_records_paging(world):
    code, tc, k = world["code"], world["tc"], world["k"]
    url = f"/api/v1/tenants/{code}/tasks/{code}.remaining_hours/records"
    p1 = tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 5}).json()
    assert p1["total"] == 720 and len(p1["items"]) == 5 and p1["next_cursor"]
    p2 = tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 5, "cursor": p1["next_cursor"]}).json()
    assert not {i["entity_id"] for i in p1["items"]} & {i["entity_id"] for i in p2["items"]}
    assert p1["items"][0]["ts"] > p2["items"][0]["ts"]                         # 최근 순
    assert set(p1["items"][0]) >= {"entity_id", "ts", "target", "press_force", "machine_code", "_source"}
    one = tc.get(url, headers=h.hdr(k["viewer"]), params={"search": "demo-0001"}).json()
    assert one["total"] == 1 and one["items"][0]["entity_id"] == "DEMO-0001"
    assert tc.get(url, headers=h.hdr(k["viewer"]), params={"cursor": "!!bad"}).status_code == 422
    assert tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 101}).status_code == 422
    opt = tc.get(f"/api/v1/tenants/{code}/tasks/{code}.maintenance_timing/records", headers=h.hdr(k["viewer"]),
                 params={"limit": 1}).json()
    assert opt["total"] == 720                                                    # 최적화 과제 = uses 과제의 LOT


def test_doctor_route(world):
    code, tc, k = world["code"], world["tc"], world["k"]
    assert tc.get(f"/api/v1/tenants/{code}/doctor", headers=h.hdr(k["viewer"])).status_code == 403
    # goal2 §6 화면 7 operator ✕ 가 정본 — doctor 는 sources 권한(admin · approver 조회, DEF-QA23-006 · D2-103)
    assert tc.get(f"/api/v1/tenants/{code}/doctor", headers=h.hdr(k["operator"])).status_code == 403
    r = tc.get(f"/api/v1/tenants/{code}/doctor", headers=h.hdr(k["approver"]))
    assert r.status_code == 200
    s = {x["role"]: x for x in r.json()["sources"]}
    assert s["demo"]["status"] == "연결" and s["train"]["status"] == "미연결" and s["train"]["target"] == "목표 없음"


def test_other_tenant_key_is_404(world):
    code, tc, ko = world["code"], world["tc"], world["ko"]
    for path in ("/tasks", f"/tasks/{code}.remaining_hours", f"/tasks/{code}.remaining_hours/overview",
                 f"/tasks/{code}.remaining_hours/records", f"/tasks/{code}.remaining_hours/monitor", "/doctor"):
        r = tc.get(f"/api/v1/tenants/{code}{path}", headers=h.hdr(ko["admin"]))
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path


def test_records_json_has_no_nat_string():
    """DEF-QA23-003 · D2-103 — 시각 없는 행은 `"ts": null`(문자열 "NaT" 금지, api-contract §2 ISO-8601 또는 null)."""
    import numpy as np
    import pandas as pd

    from mlcore.api.routers import ops

    assert ops._json(pd.NaT) is None and ops._json(np.datetime64("NaT")) is None
    assert ops._json(pd.Timestamp("2026-01-01T00:00:00+09:00")) == "2026-01-01T00:00:00+09:00"
    frame = pd.DataFrame({"entity_id": ["A", "B"], "ts": pd.to_datetime([None, None])})
    assert [{k: ops._json(v) for k, v in r.items()} for r in frame.to_dict("records")] == \
        [{"entity_id": "A", "ts": None}, {"entity_id": "B", "ts": None}]
