"""QA-R2 — DB 권한 분리 회귀: 앱이 mlp_app 구성원 LOGIN 역할로 붙어도 정상 경로(학습 → 등록 → stage → 승인 → predict ·
batch · optimize · actuals · trace · 감사 · 만료 · 감시)가 도는가. 실행: MLP_DB_DSN/MLP_TEST_DB_DSN 에 user=<임시 로그인 역할>."""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT / "tests"))
assert "user=" in os.environ["MLP_TEST_DB_DSN"] and "ml_qar2_db" in os.environ["MLP_TEST_DB_DSN"]
import _dev2 as h
from mlcore import approval
tmp = Path(tempfile.mkdtemp(prefix="qar2-role-"))
out = []
def rec(n, ok, m): out.append((n, ok)); print(f"ROLE-PATH  {'PASS' if ok else 'FAIL'}  {n} :: {json.dumps(m, ensure_ascii=False, default=str)[:300]}")
try:
    ks = h.make_tenant("ks", tmp); rec("tenant · task INSERT", True, ks.tenant.code)
    K = h.keys(ks); KS = ks.tenant.code
    res = {}
    with h.use_tenants_dir(ks):
        for s in ("remaining_hours", "failure_24h"):
            res[s] = h.real_production(ks, f"{KS}.{s}")
    rec("학습 · 등록 · stage · 승인 → production(2과제)", True, {s: r[0].version for s, r in res.items()})
    c = h.client(ks); op = h.hdr(K["operator"])
    lock = h.lock_of(res["remaining_hours"][0]); X = h.mid_inputs(lock, lock["order"])
    r = c.post(f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict", json={"inputs": X, "entity_id": "RP-1"}, headers=op)
    rec("predict 200", r.status_code == 200, r.status_code); pid = r.json().get("prediction_id")
    r = c.post(f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict:batch", json={"items": [{"inputs": X}] * 3}, headers=op)
    rec("batch 200", r.status_code == 200, r.status_code)
    r = c.post(f"/api/v1/tenants/{KS}/tasks/remaining_hours/actuals", json={"entity_id": "RP-1", "value": 50.0, "observed_at": "2026-10-01T00:00:00+09:00"}, headers=op)
    rec("actuals", r.status_code in (200, 201), (r.status_code, r.text[:120]))
    r = c.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(K["admin"]))
    rec("trace 200 + actuals 연결", r.status_code == 200 and bool(r.json().get("actuals")), r.status_code)
    lk2 = h.lock_of(res["failure_24h"][0])
    r = c.post(f"/api/v1/tenants/{KS}/tasks/maintenance_timing/optimize", json={"fixed": h.mid_inputs(lock, lock["order"])}, headers=op)
    rec("optimize(추천 · 승인 요청 INSERT)", r.status_code == 200, (r.status_code, r.text[:200]))
    r = c.get(f"/api/v1/tenants/{KS}/approvals?state=pending", headers=h.hdr(K["approver"]))
    rec("승인 목록(expire_due UPDATE)", r.status_code == 200, r.status_code)
    items = r.json().get("items") or []
    if items:
        r = c.post(f"/api/v1/approvals/{items[0]['approval_id']}/decide", json={"decision": "reject", "reason": "qa"}, headers=h.hdr(K["approver"]))
        rec("추천 반려 decide", r.status_code == 200, r.status_code)
    r = c.get(f"/api/v1/tenants/{KS}/tasks/remaining_hours/monitor", headers=h.hdr(K["admin"]))
    rec("monitor GET", r.status_code == 200, r.status_code)
    r = c.get(f"/api/v1/tenants/{KS}/doctor", headers=h.hdr(K["admin"]))
    rec("doctor GET", r.status_code == 200, r.status_code)
    n = h.count("SELECT count(*) n FROM mlp_audit WHERE tenant_id=%s", (KS,))
    rec("감사 행 INSERT", n > 0, n)
except Exception as e:
    rec(f"예외 {type(e).__name__}", False, str(e)[:300])
print("total", len(out), "FAIL", sum(not ok for _, ok in out))
