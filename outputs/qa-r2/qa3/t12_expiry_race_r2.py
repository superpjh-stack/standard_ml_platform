"""QA-R2 — 승인 만료 경계 경합: 만료 직전 · 직후에 decide(approve) 두 탭 + 목록 조회(expire_due) 를 몰아친다.
기대: 최종 상태 1개 · approved 면 감사 approved 1 · production 1회 변경, expired 면 production 불변 · 200 응답 ≤ 1."""
import sys, threading, time
import psycopg
from psycopg.rows import dict_row
from qa_lib import call, check, dump
DSN = "dbname=ml_qar2_db host=/tmp"
def db(sql, p=()):
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        cur = c.execute(sql, p); return cur.fetchall() if cur.description else None
for trial, delay in enumerate((0.8, 1.0, 1.2, 0.9)):
    rows = db("SELECT approval_id, task_id, ref_id FROM mlp_approval WHERE tenant_id='ks' AND kind='model' AND state='pending' ORDER BY requested_at")
    if not rows:
        check("G-M09", f"만료 경합 {trial}", False, "pending 승인 없음", warn=True); break
    a = rows[0]
    prod0 = db("SELECT version FROM mlp_model_version WHERE tenant_id='ks' AND task_id=%s AND stage='production'", (a["task_id"],))
    db("UPDATE mlp_approval SET expires_at = now() + %s * interval '1 second' WHERE approval_id=%s", (delay, a["approval_id"]))
    codes = []; stop = time.time() + delay + 0.6
    def hit(role):
        while time.time() < stop:
            st, b = call("POST", f"/api/v1/approvals/{a['approval_id']}/decide", role=role, json_body={"decision": "approve", "reason": "경합"})
            codes.append(st)
            if st != 409 and st != 200: break
    def lister():
        while time.time() < stop:
            call("GET", "/api/v1/tenants/ks/approvals?state=pending", role="approver")
    th = [threading.Thread(target=hit, args=(r,)) for r in ("approver", "admin")] + [threading.Thread(target=lister)]
    time.sleep(max(0, delay - 0.03))
    [t.start() for t in th]; [t.join() for t in th]
    st = db("SELECT state, decided_by FROM mlp_approval WHERE approval_id=%s", (a["approval_id"],))[0]
    aud = db("SELECT action, count(*) n FROM mlp_audit WHERE detail->>'approval_id'=%s GROUP BY 1", (a["approval_id"],))
    prod1 = db("SELECT version FROM mlp_model_version WHERE tenant_id='ks' AND task_id=%s AND stage='production'", (a["task_id"],))
    n200 = codes.count(200)
    ok = (n200 <= 1 and len(prod1) == 1 and all(r["n"] == 1 for r in aud)
          and ((st["state"] == "approved" and n200 == 1 and prod1[0]["version"] == a["ref_id"]) or (st["state"] == "expired" and n200 == 0 and prod1 == prod0)))
    check("G-M09", f"만료 경계 경합 #{trial}(만료 {delay}s)", ok, f"state={st} 200={n200} 409={codes.count(409)} 기타={[c for c in codes if c not in (200, 409)]} 감사={aud} production {prod0}→{prod1}")
dump(sys.argv[1])
