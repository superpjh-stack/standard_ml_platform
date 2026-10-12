"""G2-H01 — 1차 잔여(개발2) 회귀 시험 (docs/followups.md · 이슈 #7 · #16 · #20).

| 시험 | 항목 |
|---|---|
| test_compat_records_use_b12_rows | F7-4 (D-81) 호환 /api/data/records = B12 행 함수 |
| test_compat_record_key_order | F7-12 옛 records 행 키 순서(tests/compat_expected.yaml record_key_order) |
| test_compat_bundle_anomaly_null_when_rejected | F7-12 호환 묶음 anomaly — 예측 안 함(flag null)이면 false 가 아니라 null |
| test_optimize_repeat_is_deterministic | F7-11 G-M13 간헐 실패 재확인 — 같은 요청 두 번 같은 추천 |
| test_approver_sees_only_own_task_approvals | F16-8 approver(own_task)는 자기 approver_role 과제 승인만 본다 |
| test_health_live_synthetic_production_not_ready | F20-1 (DEF-QAR2-001) live 회사 + 기동 뒤 합성 승인 → health model_ready false |
| test_compat_disabled_task_is_503_like_standard | F20-2 (DEF-QAR2-002) 꺼진 과제: 호환도 표준처럼 503 model_not_ready |
"""

from __future__ import annotations

import pytest
import yaml

import _dev2 as h

pytestmark = [pytest.mark.gate("G2-H01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

EXP = yaml.safe_load((h.ROOT / "tests" / "compat_expected.yaml").read_text(encoding="utf-8"))


def _of(m, ttype):
    return next(t for t, td in m.tasks.items() if td.type == ttype)


# ── F7-4 · F7-12 records ───────────────────────────────────────────────────
@pytest.fixture(scope="module", params=["ks", "sw"])
def plain(request, tmp_path_factory):
    """운영 모델 없는 회사 사본 — 옛 records 는 운영 모델이 아니라 회사 소스(B12 와 같은 행)를 읽어야 한다."""
    m = h.make_tenant(request.param, tmp_path_factory.mktemp(f"fu-{request.param}"))
    return request.param, m, h.keys(m)


def test_compat_records_use_b12_rows(plain):
    source, m, k = plain
    tc = h.client(m)
    url = EXP[source]["routes"]["records"]
    old = tc.get(url, headers=h.hdr(k["viewer"]), params={"limit": 100})
    assert old.status_code == 200, old.text[:200]          # 운영 모델이 없어도 소스 행은 보인다(B12 와 같다)
    reg = _of(m, "regression")
    std = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{reg}/records", headers=h.hdr(k["viewer"]),
                 params={"limit": 100}).json()
    assert old.json()["total"] == std["total"]
    from mlcore.serve.catalog import TaskCatalog
    from mlcore.serve.compat import Compat
    cmp = Compat(TaskCatalog(m))
    key = cmp._target_key(cmp.bundle["regression"])
    by_lot = {cmp.lot_id(r["entity_id"]): r for r in std["items"]}
    rows = old.json()["records"]
    assert {r["lot_id"] for r in rows} == set(by_lot)       # 같은 정렬(최신 시각 ↓)의 같은 쪽
    for r in rows:
        s = by_lot[r["lot_id"]]
        assert r[key] == pytest.approx(s["target"])
        for f in cmp.bundle["regression"].defs:
            v, w = r[cmp.back.get(f.name, f.name)], s[f.name]
            assert (v is None and w is None) or v == pytest.approx(w) if not isinstance(w, str) else v == w


def test_compat_record_key_order(plain):
    source, m, k = plain
    tc = h.client(m)
    url = EXP[source]["routes"]["records"]
    row = tc.get(url, headers=h.hdr(k["viewer"])).json()["records"][0]
    assert list(row) == EXP[source]["record_key_order"]
    d = tc.get(f"{url}/{row['lot_id']}", headers=h.hdr(k["viewer"])).json()
    assert list(d["record"]) == EXP[source]["record_key_order"]


def test_compat_bundle_anomaly_null_when_rejected(plain):
    source, m, k = plain
    from mlcore.serve.catalog import TaskCatalog
    from mlcore.serve.compat import Compat
    cmp = Compat(TaskCatalog(m))
    base = {"imputed_fields": [], "warnings": [], "notice": "n", "model": {"name": "x", "version": "v1"}}
    outs = {"regression": {**base, "prediction": {"value": 1.0}},
            "anomaly": {**base, "anomaly": {"flag": None}, "status": "rejected"}}
    assert cmp.bundle_response(outs, {})["anomaly"] is None
    outs["anomaly"]["anomaly"]["flag"] = True
    assert cmp.bundle_response(outs, {})["anomaly"] is True
    del outs["anomaly"]
    assert cmp.bundle_response(outs, {})["anomaly"] is None      # 묶음에 anomaly 과제가 없으면 판정 없음


# ── F7-11 optimize 결정성 ──────────────────────────────────────────────────
def test_optimize_repeat_is_deterministic(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    for t, td in m.tasks.items():
        if td.type != "optimize":
            h.real_production(m, t)
    k = h.keys(m)
    tc = h.client(m)
    opt = _of(m, "optimize")
    spec = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{opt}", headers=h.hdr(k["viewer"])).json()
    ref = h.Registry().get(m.tenant.code, _of(m, "regression"))
    fixed_names = spec.get("fixed") or [f["name"] for f in spec["features"] if not f.get("controllable")]
    body = {"fixed": h.mid_inputs(h.lock_of(ref), fixed_names)}
    a = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{opt}/optimize", headers=h.hdr(k["operator"]), json=body)
    b = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{opt}/optimize", headers=h.hdr(k["operator"]), json=body)
    assert a.status_code == b.status_code == 200, (a.text[:200], b.text[:200])
    ra, rb = a.json()["recommendation"], b.json()["recommendation"]
    assert ra["rec_id"] != rb["rec_id"]
    for key in ("best", "candidates", "n_candidates", "n_feasible", "feasible", "in_train_range_rate"):
        assert ra[key] == rb[key], key


# ── F16-8 승인 목록 범위 ───────────────────────────────────────────────────
def test_approver_sees_only_own_task_approvals(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = _of(m, "regression")
    h.to_production(m, task)
    k = h.keys(m)
    tc = h.client(m)
    url = f"/api/v1/tenants/{m.tenant.code}/approvals"
    mine = tc.get(url, headers=h.hdr(k["approver"])).json()["items"]
    assert any(a["task_id"] == task for a in mine)
    assert tc.get(url, headers=h.hdr(k["approver_other"])).json()["items"] == []   # 남의 과제 승인 0
    assert tc.get(url, headers=h.hdr(k["admin"])).json()["items"]                   # admin 은 전부
    assert tc.get(url, headers=h.hdr(k["operator"])).json()["items"]                # operator(조회)는 그대로


# ── F20-1 health ───────────────────────────────────────────────────────────
def test_health_live_synthetic_production_not_ready(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    task = _of(m, "regression")
    h.to_production(m, task, synthetic=True)                 # 기동 뒤 승인된 합성 모델
    m.tenant.config["mode"] = "live"                          # 기동 병합은 이미 끝난 live 회사
    tc = h.client(m)
    row = next(x for x in tc.get("/api/v1/health").json()["tasks"] if x["task"] == task)
    assert row["model_ready"] is False and row.get("error") == "model_not_ready", row
    k = h.keys(m)
    old = tc.get(EXP["ks"]["routes"]["health"]).json()
    assert old["model_ready"] is False                         # 옛 health 도 같은 판정
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task}/predict", headers=h.hdr(k["operator"]), json={"inputs": {}})
    assert r.status_code in (422, 503)


# ── F20-2 꺼진 과제 ─────────────────────────────────────────────────────────
def test_compat_disabled_task_is_503_like_standard(tmp_path):
    m = h.make_tenant("ks", tmp_path)
    reg = _of(m, "regression")
    del m.tasks[reg]
    m.disabled[reg] = "model_not_ready: live 회사의 합성 스냅숏 모델"
    k = h.keys(m)
    tc = h.client(m)
    std = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{reg}/predict", headers=h.hdr(k["operator"]), json={"inputs": {}})
    assert std.status_code == 503 and std.json()["error"]["code"] == "model_not_ready"
    old = tc.post(EXP["ks"]["routes"]["predict"], headers=h.hdr(k["operator"]), json=EXP["ks"]["default_record"])
    assert old.status_code == 503, old.text[:200]
    assert set(old.json()) == {"detail", "code"} and old.json()["code"] == "model_not_ready"   # 옛 오류 모양 + 표준 코드
    rec = tc.get(EXP["ks"]["routes"]["records"], headers=h.hdr(k["viewer"]))
    assert rec.status_code == 503 and rec.json()["code"] == "model_not_ready"


# ── F20-5 (DEF-QAR2-005) — 승인 만료 환경변수 inf · nan · 과대값 · 0 · 음수는 받지 않는다 ─────────────────
@pytest.mark.parametrize("raw", ["inf", "Infinity", "nan", "1e308", "100000", "0", "-5", "abc", ""])
def test_f20_5_ttl_env_rejects_non_finite_and_huge(monkeypatch, raw):
    from mlcore import approval
    monkeypatch.setenv("MLP_APPROVAL_TTL_HOURS_MODEL", raw)
    assert approval.ttl_hours("model") == 168.0
    monkeypatch.setenv("MLP_APPROVAL_TTL_HOURS_RECOMMENDATION", "12.5")
    assert approval.ttl_hours("recommendation") == 12.5
    monkeypatch.setenv("MLP_APPROVAL_TTL_HOURS_RECOMMENDATION", str(approval.TTL_MAX_HOURS))
    assert approval.ttl_hours("recommendation") == approval.TTL_MAX_HOURS
