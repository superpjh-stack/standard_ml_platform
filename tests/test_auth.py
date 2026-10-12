"""G-M11(일부) — 인증 · 역할 4 · 회사 범위 · CORS (goal §6 · spec §17 · contracts/api-contract.md). 소유 개발2.

기대값은 **goal §6 표를 그대로 옮긴 것**이다(std/roles.yaml 이 아니다) — roles.yaml · auth · 실제 HTTP 가 모두 이 표와 같아야 한다.
배포 쪽(docker compose: DB 포트 · 앱 포트 · 헬스체크 · 768MB)은 gates/check_deploy.py 가 본다.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

import _dev2 as h
from mlcore import auth
from mlcore.db.conn import connect

pytestmark = [pytest.mark.gate("G-M11"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

# goal §6 — ○ allow · R 조회(read) · O own_task(자기 approver_role 과제만) · ✕ deny
GOAL_TABLE = {
    "overview": {"admin": "○", "approver": "○", "operator": "○", "viewer": "○"},
    "predict":  {"admin": "○", "approver": "○", "operator": "○", "viewer": "✕"},
    "optimize": {"admin": "○", "approver": "○", "operator": "○", "viewer": "✕"},
    "train":    {"admin": "○", "approver": "R", "operator": "✕", "viewer": "✕"},
    "approve":  {"admin": "○", "approver": "O", "operator": "R", "viewer": "✕"},
    "monitor":  {"admin": "○", "approver": "○", "operator": "R", "viewer": "✕"},
    "trace":    {"admin": "○", "approver": "✕", "operator": "✕", "viewer": "✕"},
}
ROLES = ("viewer", "operator", "approver", "admin")


@pytest.mark.parametrize("area", list(GOAL_TABLE))
def test_role_table_matches_goal(area):
    for role in ROLES:
        want = GOAL_TABLE[area][role]
        assert auth.allowed(role, area, write=False) == (want != "✕"), (area, role)
        assert auth.allowed(role, area, write=True) == (want in ("○", "O")), (area, role)
    assert set(auth.permissions()) == set(GOAL_TABLE)
    assert auth.ROLES == ROLES


# ── 키 저장 · 401 ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = h.make_tenant("ks", tmp_path_factory.mktemp("auth"))
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, res = h.to_production(m, task)
    other = h.make_tenant("sw", tmp_path_factory.mktemp("auth-other"))
    return m, task, ref, res, h.keys(m), h.keys(other), other


def test_keys_stored_as_hash_only(world):
    m, task, ref, res, k, ko, other = world
    with connect() as c:
        rows = c.execute("SELECT key_hash, key_prefix FROM mlp_api_key WHERE tenant_id = %s", (m.tenant.code,)).fetchall()
    assert rows and all(r["key_hash"].startswith("sha256$") and len(r["key_hash"]) == 7 + 64 for r in rows)
    stored = {r["key_hash"] for r in rows}
    for raw in k.values():
        assert raw not in stored and auth.hash_key(raw) in stored          # 평문 0, 해시로만 조회
        assert all(raw not in str(r) for r in rows)
    with pytest.raises(psycopg.errors.CheckViolation):                       # DB 가 평문 키를 거부한다
        with connect() as c:
            c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer) "
                      "VALUES (%s, 'plain-text-key', 'plain', 'viewer', '[]'::jsonb, 'x')", (m.tenant.code,))


def test_missing_wrong_revoked_key_is_401(world):
    m, task, ref, res, k, ko, other = world
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/models"
    for headers in ({}, {"X-API-Key": ""}, {"X-API-Key": "mlp_wrong"}, {"X-API-Key": k["admin"] + "x"}):
        r = tc.get(url, headers=headers)
        assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required"
    raw, hsh = auth.new_key()
    with connect() as c:
        c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer, revoked_at) "
                  "VALUES (%s,%s,%s,'admin','[]'::jsonb,'revoked', now())", (m.tenant.code, hsh, raw[:8]))
    assert tc.get(url, headers=h.hdr(raw)).status_code == 401
    assert tc.get("/api/v1/health").status_code == 200                       # health 만 인증 없음


# ── 역할 4 — 실제 HTTP 가 goal §6 대로 거부한다 ─────────────────────────────────────────────────────
def _calls(m, task, ref, res, k):
    t = m.tenant.code
    base = f"/api/v1/tenants/{t}/tasks/{task}"
    inputs = h.safe_inputs(res)
    obs = datetime.now(timezone(timedelta(hours=9))).isoformat()
    return [   # (area, write, method, url, body)
        ("predict", True, "POST", f"{base}/predict", {"inputs": inputs}),
        ("predict", True, "POST", f"{base}/predict:batch", {"items": [{"inputs": inputs}]}),
        ("predict", True, "POST", f"{base}/actuals", {"entity_id": "A-1", "value": 1.0, "observed_at": obs}),
        ("optimize", True, "POST", f"/api/v1/tenants/{t}/tasks/{t}.maintenance_timing/optimize", {"fixed": {}}),
        ("train", False, "GET", f"{base}/models", None),
        ("train", True, "POST", f"{base}/models/{ref.version}/stage", None),
        ("train", True, "POST", f"{base}/train", {"source_role": "demo"}),
        ("approve", False, "GET", f"/api/v1/tenants/{t}/approvals", None),
        ("approve", True, "POST", f"{base}/models/{ref.version}/promote", {"reason": "x"}),
        ("approve", True, "POST", f"{base}/models/{ref.version}/rollback", {"reason": "x"}),
        ("approve", True, "POST", "/api/v1/approvals/apr_does_not_exist/decide", {"decision": "approve", "reason": "x"}),
    ]


@pytest.mark.parametrize("role", ROLES)
def test_http_roles_follow_goal_table(world, role, monkeypatch):
    m, task, ref, res, k, ko, other = world
    monkeypatch.setattr("mlcore.serve.training._submit_fn", lambda: (lambda *a, **kw: (_ for _ in ()).throw(KeyError("x"))))
    tc = h.client(m)
    for area, write, method, url, body in _calls(m, task, ref, res, k):
        r = tc.request(method, url, headers=h.hdr(k[role]), json=body)
        want = GOAL_TABLE[area][role]
        allowed = want in ("○", "O") if write else want != "✕"
        if allowed:
            assert r.status_code not in (401, 403), (role, method, url, r.status_code, r.text)
        else:
            assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", (role, method, url, r.status_code)


def test_trace_is_admin_only(world):
    m, task, ref, res, k, ko, other = world
    tc = h.client(m)
    pid = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": h.safe_inputs(res)}).json()["prediction_id"]
    for role in ("viewer", "operator", "approver"):
        assert tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k[role])).status_code == 403
    assert tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k["admin"])).status_code == 200


def test_own_task_approver(world):
    m, task, ref, res, k, ko, other = world
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/models/{ref.version}/promote"
    r = tc.post(url, headers=h.hdr(k["approver_other"]), json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_model_version_pin_needs_approver(world):
    m, task, ref, res, k, ko, other = world
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict"
    body = {"inputs": h.safe_inputs(res), "model_version": ref.version}
    assert tc.post(url, headers=h.hdr(k["operator"]), json=body).status_code == 403
    assert tc.post(url, headers=h.hdr(k["approver"]), json=body).status_code == 200


# ── 회사 범위 — 다른 회사 키는 404 (존재 숨김) ──────────────────────────────────────────────────────
def test_other_tenant_key_is_404(world):
    m, task, ref, res, k, ko, other = world
    tc = h.client(m)
    base = f"/api/v1/tenants/{m.tenant.code}"
    for method, url, body in [("POST", f"{base}/tasks/{task}/predict", {"inputs": h.safe_inputs(res)}),
                              ("GET", f"{base}/tasks/{task}/models", None),
                              ("GET", f"{base}/approvals", None),
                              ("POST", f"{base}/tasks/{task}/models/{ref.version}/promote", {}),
                              ("GET", f"{base}/tasks", None)]:
        r = tc.request(method, url, headers=h.hdr(ko["admin"]), json=body)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (method, url)
    pid = tc.post(f"{base}/tasks/{task}/predict", headers=h.hdr(k["operator"]), json={"inputs": h.safe_inputs(res)}).json()["prediction_id"]
    assert tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(ko["admin"])).status_code == 404
    ref2, _ = h.registered(m, task, seed=5)                                 # 다른 회사 키로 결정해 볼 승인 1건
    from mlcore.registry.models import Registry
    Registry().stage(m.tenant.code, task, ref2.version, actor="a")
    aid = tc.post(f"{base}/tasks/{task}/models/{ref2.version}/promote", headers=h.hdr(k["approver"]), json={}).json()["approval_id"]
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(ko["admin"]), json={"decision": "approve", "reason": "x"})
    assert r.status_code == 404
    with connect() as c:
        assert c.execute("SELECT state FROM mlp_approval WHERE approval_id = %s", (aid,)).fetchone()["state"] == "pending"


# ── CORS — 설정 목록만 ──────────────────────────────────────────────────────────────────────────
def test_cors_only_configured_origins(monkeypatch):
    import mlcore.api.main as main
    from mlcore.settings import get_settings
    from fastapi.testclient import TestClient
    allowed, denied = "http://localhost:5190", "http://localhost:9999"
    try:
        monkeypatch.setenv("MLP_CORS_ORIGINS", f"{allowed},*")
        get_settings.cache_clear()
        app = importlib.reload(main).app
        with TestClient(app) as tc:
            pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-API-Key"}
            ok = tc.options("/api/v1/health", headers={"Origin": allowed, **pre})
            assert ok.headers.get("access-control-allow-origin") == allowed
            bad = tc.options("/api/v1/health", headers={"Origin": denied, **pre})
            assert bad.headers.get("access-control-allow-origin") is None   # '*' 은 설정에 있어도 받지 않는다
            assert tc.get("/api/v1/health", headers={"Origin": denied}).headers.get("access-control-allow-origin") is None
        monkeypatch.delenv("MLP_CORS_ORIGINS")
        get_settings.cache_clear()
        app = importlib.reload(main).app
        with TestClient(app) as tc:                                          # 목록이 비면 CORS 헤더 0
            assert tc.get("/api/v1/health", headers={"Origin": allowed}).headers.get("access-control-allow-origin") is None
    finally:
        monkeypatch.delenv("MLP_CORS_ORIGINS", raising=False)
        get_settings.cache_clear()
        importlib.reload(main)
