"""웨이브 C 회귀 시험 — QA2 · QA3 결함(개발2 몫). 소유 개발2.

결함마다 먼저 실패하는 시험을 두고 고쳤다(progress-dev2.md §6). 기대값 출처는 계약(api-contract §2 · §3 ·
predict-contract §5 · interfaces §6) · goal §2.3 · QA 리포트 재현 절차 — 개발 코드가 아니다.

| 시험 | 결함 |
|---|---|
| test_422_never_echoes_request_keys | DEF-QA3-002 = DEF-QA2-004 (#16) |
| test_batch_one_malformed_item_does_not_block_others | DEF-QA2-003 |
| test_huge_integer_literal_is_422 | DEF-QA2-006 |
| test_explain_is_strict_bool | DEF-QA2-007 |
| test_unknown_model_version_is_404 | DEF-QA2-008 |
| test_artifact_bytes_hashed_are_bytes_loaded | DEF-QA2-005 |
| test_health_reflects_artifact_check | QA2 관찰(health model_ready) |
| test_write_attempts_are_audited_* | DEF-QA2-002 (#15) |
| test_approval_expiry_* | DEF-QA3-004 (#7 · D-73 → D-130) |
| test_optimize_current_decision_var_bounds | DEF-QA3-006 |
| test_request_id_is_bounded | QA2 관찰(X-Request-Id 8000자 되돌림) |
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import _dev2 as h
from mlcore import approval
from mlcore.db.conn import connect
from mlcore.registry import artifacts
from mlcore.registry.models import Registry

pytestmark = [pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

SENTINEL = "<script>alert(1)</script>"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = h.make_tenant("ks", tmp_path_factory.mktemp("wavec"))
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, res = h.to_production(m, task)
    other = h.make_tenant("sw", tmp_path_factory.mktemp("wavec-other"))
    return m, task, ref, res, h.keys(m), h.keys(other)


def _url(m, task, suffix="predict"):
    return f"/api/v1/tenants/{m.tenant.code}/tasks/{task.split('.', 1)[1]}/{suffix}"


def _raw(tc, url, key, text):
    return tc.post(url, headers={**h.hdr(key), "Content-Type": "application/json"}, content=text)


def _err(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code, body
    return body["error"]


# ── DEF-QA3-002 = DEF-QA2-004 ─────────────────────────────────────────────────────────────────
def test_422_never_echoes_request_keys(world):
    """pydantic 단계 422 도 요청자가 보낸 **키 문자열**을 되돌리지 않는다 — 위치만(goal §2.3 · D-75)."""
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    good = h.safe_inputs(res)
    long_key = "K" * 3000
    cases = [
        (_url(m, task), {"inputs": good, SENTINEL: 1}),                           # 모르는 최상위 키
        (_url(m, task), {"inputs": {**good, "SECRET-VALUE-x y": [1, 2]}}),         # inputs 안 임의 키 + 형 틀림
        (_url(m, task), {"inputs": {**good, long_key: {"a": 1}}}),                 # 3,000자 키
        (_url(m, task), {"inputs": {**good, f"{SENTINEL}키": None}, "explain": False, "zz": SENTINEL}),
        (_url(m, task, "predict:batch"), {"items": [{"inputs": good, SENTINEL: 1}]}),
        (_url(m, task.rsplit(".", 1)[0] + ".maintenance_timing", "optimize"),
         {"fixed": {"SECRET-VALUE-x y": [1]}, SENTINEL: 2}),
        ("/api/v1/approvals/apr_x/decide", {"decision": "approve", SENTINEL: 1}),
    ]
    for url, body in cases:
        r = tc.post(url, headers=h.hdr(k["admin"]), json=body)
        batch = url.endswith(":batch")                        # 배치는 건별 422 → 200 + {index, error}(DEF-QA2-003)
        assert r.status_code == (200 if batch else 422), (url, r.text[:300])
        if batch:
            assert r.json()["items"][0]["error"]["code"] == "invalid_input"
        text = r.text
        for s in (SENTINEL, "SECRET-VALUE", "script", long_key[:64], "키"):
            assert s not in text, (url, s, text[:300])
        assert len(text) < 2000, (url, len(text))
        if url.endswith("/predict") or url.endswith("/optimize") or url.endswith("/decide"):
            e = r.json()["error"]
            assert e["code"] == "invalid_input"
            for item in e["detail"].get("errors", []):
                f = item.get("field")
                assert f is None or all(p == "*" or p.isdigit() or p.isidentifier() and len(p) <= 32
                                        for p in str(f).split(".")), f


# ── DEF-QA2-003 ───────────────────────────────────────────────────────────────────────────────
def test_batch_one_malformed_item_does_not_block_others(world):
    """한 건의 NaN(형식 오류)이 배치 전체를 422 로 만들지 않는다 — 그 자리에 {index, error} (predict-contract §5)."""
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    good = h.safe_inputs(res)
    num = next(n for n, v in good.items() if isinstance(v, (int, float)))
    bad = json.dumps({**good, num: 1.0}).replace(f'"{num}": 1.0', f'"{num}": NaN')
    text = '{"items": [' + json.dumps({"inputs": good}) + ', {"inputs": ' + bad + '}, ' + \
           json.dumps({"inputs": good, "explain": "yes"}) + ', ' + json.dumps({"inputs": good}) + ']}'
    r = _raw(tc, _url(m, task, "predict:batch"), k["operator"], text)
    assert r.status_code == 200, r.text[:400]
    items = r.json()["items"]
    assert len(items) == 4
    assert items[0]["task"] == task and items[3]["task"] == task
    assert items[1] == {"index": 1, "error": items[1]["error"]} and items[1]["error"]["code"] == "invalid_input"
    assert items[2]["index"] == 2 and items[2]["error"]["code"] == "invalid_input"
    assert "NaN" not in json.dumps(items[1]) and "yes" not in json.dumps(items[2])
    # 배치 크기 위반은 여전히 전체 422
    _err(tc.post(_url(m, task, "predict:batch"), headers=h.hdr(k["operator"]), json={"items": []}), 422, "invalid_input")
    _err(_raw(tc, _url(m, task, "predict:batch"), k["operator"], '{"items": [' + ",".join(['{"inputs": {}}'] * 501) + "]}"),
         422, "invalid_input")


# ── DEF-QA2-006 ───────────────────────────────────────────────────────────────────────────────
def test_huge_integer_literal_is_422(world):
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    good = h.safe_inputs(res)
    num = next(n for n, v in good.items() if isinstance(v, (int, float)))
    text = json.dumps({"inputs": {**good, num: 0}}).replace(f'"{num}": 0', f'"{num}": ' + "9" * 5000)
    e = _err(_raw(tc, _url(m, task), k["operator"], text), 422, "invalid_input")
    assert "9999999999" not in json.dumps(e)
    _err(_raw(tc, _url(m, task), k["operator"], '{"inputs": {"a": 1'), 422, "invalid_input")   # 깨진 JSON 도 422 그대로


# ── DEF-QA2-007 ───────────────────────────────────────────────────────────────────────────────
def test_explain_is_strict_bool(world):
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    for v in ("yes", "true", 1, 0):
        _err(tc.post(_url(m, task), headers=h.hdr(k["operator"]), json={"inputs": h.safe_inputs(res), "explain": v}),
             422, "invalid_input")
    r = tc.post(_url(m, task), headers=h.hdr(k["operator"]), json={"inputs": h.safe_inputs(res), "explain": True})
    assert r.status_code == 200 and r.json()["explain"] is not None


# ── DEF-QA2-008 ───────────────────────────────────────────────────────────────────────────────
def test_unknown_model_version_is_404(world):
    """쓸 수 없는 버전(없는 버전 · candidate)은 같은 404 not_found. 버전 지정이 없을 때 production 없음만 503."""
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    cand, _ = h.registered(m, task, seed=7)
    for v in ("v99", cand.version):
        e = _err(tc.post(_url(m, task), headers=h.hdr(k["admin"]), json={"inputs": h.safe_inputs(res), "model_version": v}),
                 404, "not_found")
        assert "v99" not in json.dumps(e)
    batch = tc.post(_url(m, task, "predict:batch"), headers=h.hdr(k["admin"]),
                    json={"items": [{"inputs": h.safe_inputs(res), "model_version": "v99"}]})
    _err(batch, 404, "not_found")


# ── DEF-QA2-005 ───────────────────────────────────────────────────────────────────────────────
class _SwapAfterHash:
    """artifacts 모듈의 hashlib 대역 — 산출물 해시를 다 잰 직후(마지막 hexdigest) model.joblib 을 다른 모델로 바꾼다.
    해시를 잰 바이트와 적재하는 바이트가 다르면(경합 창) 바뀐 모델이 적재된다."""

    def __init__(self, real, target, payload: bytes, after: int):
        self.real, self.target, self.payload, self.after, self.calls = real, target, payload, after, 0

    def sha256(self, *a):
        outer = self
        inner = self.real.sha256(*a)

        class H:
            def update(self, b):
                inner.update(b)

            def hexdigest(self):
                d = inner.hexdigest()
                outer.calls += 1
                if outer.calls == outer.after:
                    outer.target.write_bytes(outer.payload)
                return d
        return H()


def test_artifact_bytes_hashed_are_bytes_loaded(world, monkeypatch, tmp_path):
    m, task, ref, res, k, _ = world
    victim, vres = h.registered(m, task, seed=11)
    other, ores = h.registered(m, task, seed=12)
    vdir = artifacts.resolve_dir(victim.artifact_path)
    model_path = vdir / "model.joblib"
    original = model_path.read_bytes()
    swapped = (artifacts.resolve_dir(other.artifact_path) / "model.joblib").read_bytes()
    assert original != swapped
    import hashlib
    for after in range(1, len(artifacts.FILES) + 2):
        model_path.write_bytes(original)
        artifacts._CACHE.clear()
        spy = _SwapAfterHash(hashlib, model_path, swapped, after)
        monkeypatch.setattr(artifacts, "hashlib", spy)
        try:
            loaded = artifacts.load_artifacts(victim)
        except artifacts.ArtifactMismatch:
            continue                                                  # 바뀐 바이트를 해시했다 → 503 (정상)
        finally:
            monkeypatch.setattr(artifacts, "hashlib", hashlib)
        frame = vres.frame.head(5)
        want = vres_model_predict(original, frame)
        got = np.asarray(loaded.model.predict(frame), dtype=float)
        assert np.allclose(got, want), f"해시 뒤 바뀐 model.joblib 이 적재됐다(after={after})"
    model_path.write_bytes(original)
    artifacts._CACHE.clear()


def vres_model_predict(raw: bytes, frame: pd.DataFrame) -> np.ndarray:
    import io

    import joblib
    return np.asarray(joblib.load(io.BytesIO(raw)).predict(frame), dtype=float)


# ── QA2 관찰: health ───────────────────────────────────────────────────────────────────────────
def test_health_reflects_artifact_check(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, _ = h.to_production(m, task)
    tc = h.client(m)

    def row():
        d = tc.get("/api/v1/health").json()
        return next(t for t in d["tasks"] if t["task"] == task)

    assert row()["model_ready"] is True
    rep = artifacts.resolve_dir(ref.artifact_path) / "report.json"
    keep = rep.read_bytes()
    try:
        rep.write_bytes(keep + b" ")
        r = row()
        assert r["model_ready"] is False and r.get("error") == "model_artifact_mismatch", r
    finally:
        rep.write_bytes(keep)
        artifacts._CACHE.clear()
    assert row()["model_ready"] is True


# ── DEF-QA2-002 ───────────────────────────────────────────────────────────────────────────────
def _audits(tenant: str, request_id: str) -> list[dict]:
    with connect() as c:
        return c.execute("SELECT tenant_id, actor, role, action, target, detail FROM mlp_audit "
                         "WHERE tenant_id = %s AND request_id = %s", (tenant, request_id)).fetchall()


def test_write_attempts_are_audited_cross_tenant_and_unauthenticated(world):
    """거부된 쓰기(다른 회사 키 404 · 키 없음 401)도 감사 1행 — 회사 미상은 '-'(db-schema mlp_audit)."""
    m, task, ref, res, k, ko = world
    tc = h.client(m)
    rid = "qa-cross-" + h.secrets_hex()
    r = tc.post(_url(m, task), headers={**h.hdr(ko["admin"]), "X-Request-Id": rid}, json={"inputs": {}})
    _err(r, 404, "not_found")
    other_code = next(iter(_key_tenants(ko["admin"])))
    rows = _audits(other_code, rid)
    assert len(rows) == 1 and rows[0]["detail"]["status"] == 404 and rows[0]["detail"].get("rule") == "tenant_scope", rows
    rid2 = "qa-anon-" + h.secrets_hex()
    _err(tc.post(_url(m, task), headers={"X-Request-Id": rid2}, json={"inputs": {}}), 401, "auth_required")
    rows = _audits("-", rid2)
    assert len(rows) == 1 and rows[0]["detail"]["status"] == 401 and rows[0]["actor"] == "anonymous", rows
    # GET 은 감사하지 않는다(쓰기만)
    rid3 = "qa-get-" + h.secrets_hex()
    tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks", headers={**h.hdr(ko["admin"]), "X-Request-Id": rid3})
    assert _audits(other_code, rid3) == []


def test_write_attempts_are_audited_compat_paths(tmp_path):
    """호환 경로(/api/... 옛 경로) POST 도 감사 1행 — 성공 · 실패(503 · 401 · 403) 모두."""
    m = h.make_tenant("ks", tmp_path)
    k = h.keys(m)
    tc = h.client(m)
    route = next(r for r in m.tenant.config["compat"]["routes"] if r.endswith("/predict"))
    for key, status in ((k["operator"], 503), (None, 401), (k["viewer"], 403)):
        rid = "qa-compat-" + h.secrets_hex()
        headers = {"X-Request-Id": rid, **(h.hdr(key) if key else {})}
        r = tc.post(route, headers=headers, json={})
        assert r.status_code in (status, 422), r.text   # 본문 검증(422)보다 인증 · 역할이 먼저
        tenant = m.tenant.code if key else "-"
        rows = _audits(tenant, rid)
        assert len(rows) == 1 and rows[0]["detail"]["status"] == r.status_code, (status, rows)
        assert rows[0]["action"].startswith("POST "), rows


def _key_tenants(raw: str) -> set[str]:
    from mlcore import auth
    return {auth.lookup(raw).tenant_id}


# ── X-Request-Id ─────────────────────────────────────────────────────────────────────────────
def test_request_id_is_bounded(world):
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    r = tc.get("/api/v1/health", headers={"X-Request-Id": "x" * 8000})
    assert r.status_code == 200 and len(r.headers["X-Request-Id"]) <= 64
    r = tc.get("/api/v1/health", headers={"X-Request-Id": "abc-123_X.y"})
    assert r.headers["X-Request-Id"] == "abc-123_X.y"
    r = tc.get("/api/v1/health", headers={"X-Request-Id": "<b>x</b>"})
    assert "<" not in r.headers["X-Request-Id"]


# ── DEF-QA3-004 (D-73 → D-130) ──────────────────────────────────────────────────────────────────
def _staged(m, task, seed):
    ref, _ = h.registered(m, task, seed=seed)
    Registry().stage(m.tenant.code, task, ref.version, actor="test-admin")
    return ref.version


def test_approval_expiry_sets_expires_at_and_reissues(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    k = h.keys(m)
    tc = h.client(m)
    v = _staged(m, task, 3)
    short = task.split(".", 1)[1]
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{short}/models/{v}/promote", headers=h.hdr(k["approver"]), json={})
    assert r.status_code == 202
    aid = r.json()["approval_id"]
    row = approval.get(aid)
    assert row["expires_at"] is not None                                         # 만료 시각을 넣는다
    ttl = row["expires_at"] - row["requested_at"]
    assert timedelta(hours=1) <= ttl <= timedelta(days=30), ttl
    with connect() as c:                                                          # 시간이 지났다고 치고
        c.execute("UPDATE mlp_approval SET expires_at = now() - interval '1 minute' WHERE approval_id = %s", (aid,))
    lst = tc.get(f"/api/v1/tenants/{m.tenant.code}/approvals?state=pending", headers=h.hdr(k["approver"])).json()
    assert aid not in {a["approval_id"] for a in lst["items"]}                    # 대기열에서 빠진다
    exp = tc.get(f"/api/v1/tenants/{m.tenant.code}/approvals?state=expired", headers=h.hdr(k["approver"])).json()
    assert aid in {a["approval_id"] for a in exp["items"]}
    _err(tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve"}),
         409, "already_decided")
    assert approval.get(aid)["state"] == "expired"
    r2 = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{short}/models/{v}/promote", headers=h.hdr(k["approver"]), json={})
    assert r2.status_code == 202 and r2.json()["approval_id"] != aid               # 만료 건 재요청 → 새 승인
    out = tc.post(f"/api/v1/approvals/{r2.json()['approval_id']}/decide", headers=h.hdr(k["approver"]),
                  json={"decision": "approve", "reason": "재요청"})
    assert out.status_code == 200 and out.json()["production_version"] == v
    n = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id = %s AND action = 'approval.expired' "
                "AND detail->>'approval_id' = %s", (m.tenant.code, aid))
    assert n == 1


def test_approval_expiry_decide_before_listing(tmp_path):
    """목록을 보지 않고 바로 decide 해도 만료는 409 + state expired (조건부 UPDATE 0행)."""
    m = h.make_tenant("ks", tmp_path)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    v = _staged(m, task, 4)
    aid = Registry().request_promotion(m.tenant.code, task, v, actor="req", action="promote", reason=None)
    with connect() as c:
        c.execute("UPDATE mlp_approval SET expires_at = now() - interval '1 second' WHERE approval_id = %s", (aid,))
    with pytest.raises(approval.AlreadyDecided):
        approval.decide(aid, actor="boss", actor_role="approver", approve=True, reason=None)
    assert approval.get(aid)["state"] == "expired"
    with pytest.raises(Exception):
        Registry().get(m.tenant.code, task)                                       # production 그대로 없음


# ── DEF-QA3-006 ───────────────────────────────────────────────────────────────────────────────
def test_optimize_current_decision_var_bounds(world):
    """current 의 결정 변수도 [min, max | params[max_param]] 밖이면 422 out_of_bounds (조절 변수와 같은 규칙)."""
    m, task, ref, res, k, _ = world
    tc = h.client(m)
    code = m.tenant.code
    opt = next(t for t, d in m.tasks.items() if d.type == "optimize")
    td = m.tasks[opt]
    dv, spec = next(iter(td.raw["decision_vars"].items()))
    fixed = h.safe_inputs(res)
    fixed = {n: fixed.get(n) for n in td.raw["fixed"]}
    url = f"/api/v1/tenants/{code}/tasks/{opt.split('.', 1)[1]}/optimize"
    hi = td.raw["params"][spec["max_param"]]["default"]
    for bad in (1000, hi + spec["step"], spec.get("min", 0) - 5):
        e = _err(tc.post(url, headers=h.hdr(k["operator"]), json={"fixed": fixed, "current": {dv: bad}}), 422, "out_of_bounds")
        assert e["detail"]["field"] == dv
    e = _err(tc.post(url, headers=h.hdr(k["operator"]), json={"fixed": fixed, "current": {dv: True}}), 422, "invalid_input")
    r = tc.post(url, headers=h.hdr(k["operator"]), json={"fixed": fixed, "current": {dv: hi}})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["recommendation"]["current"]["conditions"][dv] == hi


# ── D-120a (개발3 요청, DEF-QA3-001 #17 예측 시점 방어) ─────────────────────────────────────────
def test_disabled_task_predict_is_503(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    k = h.keys(m)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    m.disabled[task] = "model_not_ready: 시험"                                # 병합이 끈 과제
    tc = h.client(m)
    for suffix, body in (("predict", {"inputs": {}}), ("predict:batch", {"items": [{"inputs": {}}]})):
        _err(tc.post(_url(m, task, suffix), headers=h.hdr(k["operator"]), json=body), 503, "model_not_ready")
    opt = next(t for t, d in m.tasks.items() if d.type == "optimize")
    m.disabled[opt] = "model_not_ready: 시험"
    _err(tc.post(_url(m, opt, "optimize"), headers=h.hdr(k["operator"]), json={"fixed": {}}), 503, "model_not_ready")


def test_live_tenant_synthetic_production_is_503(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    k = h.keys(m)
    task = next(t for t, d in m.tasks.items() if d.type == "regression")
    ref, res = h.to_production(m, task)                                        # 합성 스냅숏 모델(demo 때 승인)
    assert ref.synthetic
    m.tenant.config["mode"] = "live"                                           # 기동 뒤 live 로 운영(병합은 이 모델을 못 봤다)
    tc = h.client(m)
    e = _err(tc.post(_url(m, task), headers=h.hdr(k["operator"]), json={"inputs": h.safe_inputs(res)}), 503, "model_not_ready")
    assert e["detail"].get("rule") == "live_synthetic"
    opt = next(t for t, d in m.tasks.items() if d.type == "optimize")
    fixed = {n: h.safe_inputs(res).get(n) for n in m.tasks[opt].raw["fixed"]}
    _err(tc.post(_url(m, opt, "optimize"), headers=h.hdr(k["operator"]), json={"fixed": fixed}), 503, "model_not_ready")
