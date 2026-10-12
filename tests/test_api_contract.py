"""G-S04 — API 1차 12 묶음 · 오류 계약 · 403/404/422 · 목록 `{items, next_cursor}` (contracts/api-contract.md · goal §2.3).

전체 API 를 본다(개발1 `/train` `/runs` · 개발3 `/tasks*` `/overview` `/records` `/monitor` `/doctor` `/health` 포함).
**아직 없는 경로는 시험에서 그대로 실패로 남긴다**(가짜 PASS 0). 기대값 출처는 계약 표(api-contract.md §1 · §3)와
std/statuses.yaml error_codes — 코드가 아니다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import _dev2 as h
from mlcore.db.conn import connect

pytestmark = [pytest.mark.gate("G-S04"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

ERROR_CODES = yaml.safe_load((h.ROOT / "std" / "statuses.yaml").read_text(encoding="utf-8"))["error_codes"]


def contract_rows() -> list[dict]:
    rows = []
    for line in (h.ROOT / "contracts" / "api-contract.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (B\d\d) ([a-z]+) \| ([12]) \| (GET|POST|PATCH|PUT|DELETE) \| `([^`]+)` \| ([^|]+) \|", line)
        if m:
            rows.append({"bundle": m[1], "name": m[2], "phase": int(m[3]), "method": m[4], "path": m[5], "role": m[6].strip()})
    return rows


ROWS = contract_rows()
P1 = [r for r in ROWS if r["phase"] == 1]
P2 = [r for r in ROWS if r["phase"] == 2]


PHASE2_BUNDLES = ("B09", "B10", "B11")
TYPED = [r for r in ROWS if r["bundle"] in PHASE2_BUNDLES]


def test_contract_counts():
    """웨이브 P 마감: §1 의 묶음 15 가 전부 단계 1(B09~B11 합침) · 단계 2 행 0."""
    assert len({r["bundle"] for r in P1}) == 15 and len({r["bundle"] for r in ROWS}) == 15 and not P2
    assert {r["bundle"] for r in TYPED} == set(PHASE2_BUNDLES) and len(TYPED) == 11


def _app_routes() -> set[tuple[str, str]]:
    from mlcore.api.main import app
    return {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}


@pytest.mark.parametrize("row", P1, ids=[f"{r['bundle']}-{r['method']}-{r['path']}" for r in P1])
def test_phase1_route_exists(row):
    assert (row["method"], row["path"]) in _app_routes(), f"{row['bundle']} {row['method']} {row['path']} 미구현"


# ── 공용 장치 ─────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = h.make_tenant("ks", tmp_path_factory.mktemp("api"))
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, res = h.to_production(m, task)
    other = h.make_tenant("sw", tmp_path_factory.mktemp("api-other"))
    return m, task, ref, res, h.keys(m), h.keys(other)


def _envelope(r, status: int, code: str):
    assert r.status_code == status, (r.status_code, r.text)
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "detail"}, body
    assert body["error"]["code"] == code and ERROR_CODES[code] == status
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["detail"], dict)
    assert r.headers.get("X-Request-Id")
    return body["error"]


@pytest.mark.parametrize("row", TYPED, ids=[f"{r['bundle']}-{r['method']}-{r['path']}" for r in TYPED])
def test_phase2_routes_exist_and_route_by_type(world, row):
    """웨이브 P(goal2 G2-T01 "2차 유형 경로의 501 은 0"): §1 의 B09~B11 행은 앱에 있고, 1차 유형 과제로 부르면
    501 이 아니라 404 not_found(detail.rule type_route — api-contract §6.1 · D2-20). 아키텍트가 §1 단계를 1 로 바꾸면
    이 행들은 P1 로 옮겨 test_phase1_route_exists 가 본다(그때 P2 = 0)."""
    m, task, ref, res, k, ko = world
    assert (row["method"], row["path"]) in _app_routes()
    path = row["path"].replace("{t}", m.tenant.code).replace("{task}", task)
    path = re.sub(r"\{[a-z_]+\}", "x1", path)
    r = h.client(m).request(row["method"], path, headers=h.hdr(k["admin"]), json={} if row["method"] != "GET" else None)
    e = _envelope(r, 404, "not_found")
    assert e["detail"].get("rule") == "type_route", e


# ── 오류 계약 (goal §2.3) ─────────────────────────────────────────────────────────────────────
def test_401_403_404_envelopes(world):
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    base = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}"
    _envelope(tc.post(f"{base}/predict", json={"inputs": {}}), 401, "auth_required")
    _envelope(tc.post(f"{base}/predict", headers=h.hdr(k["viewer"]), json={"inputs": {}}), 403, "forbidden")
    _envelope(tc.post(f"{base}/predict", headers=h.hdr(ko["admin"]), json={"inputs": {}}), 404, "not_found")   # 다른 회사
    _envelope(tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.nope/predict", headers=h.hdr(k["operator"]),
                      json={"inputs": {}}), 404, "not_found")                                                       # 없는 과제
    _envelope(tc.get("/api/v1/predictions/prd_00000000000000000000000000/trace", headers=h.hdr(k["admin"])), 404, "not_found")
    _envelope(tc.get("/api/v1/does/not/exist", headers=h.hdr(k["admin"])), 404, "not_found")


def test_422_envelopes_do_not_echo_input(world):
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict"
    secret = "ECHO-CANARY-7731"
    cat = next(n for n, v in h.safe_inputs(res).items() if isinstance(v, str))
    num = next(n for n, v in h.safe_inputs(res).items() if not isinstance(v, str))
    cases = [
        ({"inputs": {**h.safe_inputs(res), f"<{secret}>": 1}}, "invalid_input"),     # 모르는 키(변수 이름 꼴 아님 → field null)
        ({"inputs": h.safe_inputs(res), "extra": secret}, "invalid_input"),         # 모르는 최상위 키
        ({"inputs": {**h.safe_inputs(res), cat: secret}}, "out_of_bounds"),          # 범주 밖 (D-55)
        ({"inputs": {**h.safe_inputs(res), num: 1e300}}, "out_of_bounds"),
        ({"inputs": {**h.safe_inputs(res), cat: None}}, "missing_required"),
    ]
    for body, code in cases:
        err = _envelope(tc.post(url, headers=h.hdr(k["operator"]), json=body), 422, code)
        assert secret not in str(err)
    r = tc.post(url, headers={**h.hdr(k["operator"]), "Content-Type": "application/json"},
                content='{"inputs": {"%s": NaN}}' % num)
    assert secret not in r.text
    _envelope(r, 422, "invalid_input")


def test_409_and_503_envelopes(world, tmp_path, monkeypatch):
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    base = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}"
    ref2, _ = h.registered(m, task, seed=11)
    from mlcore.registry.models import Registry
    Registry().stage(m.tenant.code, task, ref2.version, actor="a")
    aid = tc.post(f"{base}/models/{ref2.version}/promote", headers=h.hdr(k["approver"]), json={}).json()["approval_id"]
    assert tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "reject", "reason": "x"}).status_code == 200
    _envelope(tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "x"}),
              409, "already_decided")
    e = _envelope(tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["admin"])), 409, "invalid_transition")
    assert e["detail"]["rule"] == "from_candidate_only"
    e = _envelope(tc.post(f"{base}/models/{ref.version}/rollback", headers=h.hdr(k["approver"]), json={}), 422, "missing_required")
    assert e["detail"]["field"] == "reason"                                  # D-54
    # 학습 동시 실행 초과 → 409 train_busy (detail.rule = tenant_concurrency)
    class TrainBusy(Exception):
        pass
    monkeypatch.setattr("mlcore.serve.training._submit_fn", lambda: (lambda *a, **kw: (_ for _ in ()).throw(TrainBusy())))
    e = _envelope(tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={"source_role": "demo"}), 409, "train_busy")
    assert e["detail"] == {"rule": "tenant_concurrency"}
    monkeypatch.undo()
    # 운영 모델 없음 → 503 model_not_ready (대체 응답 없음)
    fresh = h.make_tenant("ks", tmp_path)
    kf = h.keys(fresh)
    t2 = next(t for t, d in fresh.tasks.items() if d.type == "regression")
    _envelope(h.client(fresh).post(f"/api/v1/tenants/{fresh.tenant.code}/tasks/{t2}/predict", headers=h.hdr(kf["operator"]),
                                   json={"inputs": h.safe_inputs(res)}), 503, "model_not_ready")


# ── 목록 응답 {items, next_cursor} ────────────────────────────────────────────────────────────
LISTS = ["tasks", "models", "approvals", "records", "monitor"]


@pytest.mark.parametrize("name", LISTS)
def test_list_responses_have_items_and_next_cursor(world, name):
    m, task, ref, res, k, ko = world
    t = m.tenant.code
    url = {"tasks": f"/api/v1/tenants/{t}/tasks", "models": f"/api/v1/tenants/{t}/tasks/{task}/models",
           "approvals": f"/api/v1/tenants/{t}/approvals", "records": f"/api/v1/tenants/{t}/tasks/{task}/records",
           "monitor": f"/api/v1/tenants/{t}/tasks/{task}/monitor"}[name]
    r = h.client(m).get(url, headers=h.hdr(k["admin"]))
    assert r.status_code == 200, f"{name}: {r.status_code} {r.text[:120]}"
    body = r.json()
    assert isinstance(body.get("items"), list) and "next_cursor" in body, body
    assert not ({"records", "offset", "q"} & set(body))                       # F2 통일 — 옛 키 없음


def test_approvals_cursor_paging(world):
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    for seed in (21, 22):
        r2, _ = h.registered(m, task, seed=seed)
        from mlcore.registry.models import Registry
        Registry().stage(m.tenant.code, task, r2.version, actor="a")
        tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/models/{r2.version}/promote", headers=h.hdr(k["approver"]), json={})
    url = f"/api/v1/tenants/{m.tenant.code}/approvals"
    p1 = tc.get(url, headers=h.hdr(k["operator"]), params={"limit": 1}).json()
    assert len(p1["items"]) == 1 and p1["next_cursor"]
    p2 = tc.get(url, headers=h.hdr(k["operator"]), params={"limit": 1, "cursor": p1["next_cursor"]}).json()
    assert p2["items"] and p2["items"][0]["approval_id"] != p1["items"][0]["approval_id"]
    _envelope(tc.get(url, headers=h.hdr(k["operator"]), params={"limit": 101}), 422, "invalid_input")


def test_actuals_and_health_shapes(world):
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    pid = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": h.safe_inputs(res), "entity_id": "AC-1"}).json()["prediction_id"]
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/actuals", headers=h.hdr(k["operator"]),
                json={"entity_id": "AC-1", "value": 3.0, "observed_at": datetime.now(timezone(timedelta(hours=9))).isoformat()})
    assert r.status_code == 200 and set(r.json()) == {"actual_id", "linked_prediction_ids"} and pid in r.json()["linked_prediction_ids"]
    hb = tc.get("/api/v1/health").json()
    assert {"status", "db", "version", "tasks"} <= set(hb) and hb["status"] in ("ok", "degraded")
    assert all({"task", "model_ready", "version"} <= set(x) for x in hb["tasks"])
    with connect() as c:
        assert c.execute("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id = %s AND action LIKE 'POST %%actuals'",
                         (m.tenant.code,)).fetchone()["n"] >= 1           # 쓰기 요청 감사


# ── 2차 B09 · B10 · B11 — 역할(goal2 §6) · 회사 범위 · 목록 모양 (G2-A01) ─────────────────────────────────
@pytest.fixture(scope="module")
def world2(tmp_path_factory):
    import _phase2 as p2
    m = p2.make_world(tmp_path_factory.mktemp("api2"))
    h.to_production(m, p2.tid(m, "target_value"))
    other = p2.make_world(tmp_path_factory.mktemp("api2-other"))
    return m, h.keys(m), h.keys(other), p2


def test_phase2_roles_scope_and_lists(world2):
    m, k, ko, p2 = world2
    tc = h.client(m)
    t = m.tenant.code
    rv = f"/api/v1/tenants/{t}/tasks/{p2.tid(m, 'value_review')}/review"
    dc = f"/api/v1/tenants/{t}/tasks/{p2.tid(m, 'drawing')}/documents"
    qt = f"/api/v1/tenants/{t}/tasks/{p2.tid(m, 'estimate')}/quotes"
    item = p2.review_item(m)
    # 화면 8 · B09: viewer ✕ · operator 조회 · approver(자기 과제) · admin 판정
    _envelope(tc.get(rv, headers=h.hdr(k["viewer"])), 403, "forbidden")
    for role in ("operator", "approver", "admin"):
        body = tc.get(rv, headers=h.hdr(k[role])).json()
        assert set(body) == {"items", "next_cursor", "total", "can_decide"}, (role, body)   # can_decide — C2 D2-93
        assert body["can_decide"] is (role != "operator"), (role, body)
    _envelope(tc.patch(f"{rv}/{item}", headers=h.hdr(k["operator"]), json={"state": "false_alarm", "note": "x"}), 403, "forbidden")
    # 화면 9 · B10 · B11: viewer ✕ · operator ○ (확정 결정 ✕ — test_quote.py)
    for url in (dc, qt):
        _envelope(tc.get(url, headers=h.hdr(k["viewer"])), 403, "forbidden")
        for role in ("operator", "approver", "admin"):
            body = tc.get(url, headers=h.hdr(k[role])).json()
            assert set(body) == {"items", "next_cursor", "total"}, (role, url, body)
    assert p2.upload(tc, m, k["operator"], p2.sample_dxf()).status_code == 201
    q = tc.post(qt, headers=h.hdr(k["operator"]), json={"inputs": {"x1": 50, "x2": 50, "c1": "A", "quantity": 1}})
    assert q.status_code == 201, q.text
    # 다른 회사 키 · 401 · 오류 봉투
    for url in (rv, dc, qt, f"{qt}/{q.json()['quote_id']}", f"{qt}/{q.json()['quote_id']}.csv"):
        _envelope(tc.get(url, headers=h.hdr(ko["admin"])), 404, "not_found")
        _envelope(tc.get(url), 401, "auth_required")
    _envelope(tc.post(f"{qt}/{q.json()['quote_id']}/confirm", headers=h.hdr(ko["operator"]),
                      json={"reviewed": True, "review_note": "다른 회사"}), 404, "not_found")
