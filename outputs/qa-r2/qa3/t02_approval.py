"""QA3 t02 — 승인 흐름(G-M09 · §2.3): 두 탭 동시 승인 · 승인/반려 경합 · 재결정 409 · 승인 직후 새 후보 · 되돌리기 · 만료 · 역할.
production 은 approval.decide() 로만 바뀌어야 한다. DB 는 ml_qar2_db 만 본다."""
import subprocess
import sys
import threading

import psycopg
from psycopg.rows import dict_row

from qa_lib import call, check, expect, dump

DSN = "dbname=ml_qar2_db host=/tmp"
T = "ks.remaining_hours"
P = "/api/v1/tenants/ks/tasks/remaining_hours"


def db(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else None


def stages():
    return {r["version"]: r["stage"] for r in db("SELECT version, stage FROM mlp_model_version WHERE tenant_id='ks' AND task_id=%s", (T,))}


def prod():
    r = [v for v, s in stages().items() if s == "production"]
    return r


def train(seed):
    out = subprocess.run([sys.executable, "-m", "mlcore.train.jobs", "--submit", "ks", T, "--seed", str(seed)],
                         capture_output=True, text=True)
    import json
    return json.loads(out.stdout.strip().splitlines()[-1])


def race(aid, a, b):
    """두 탭 — 두 키가 동시에 decide. a/b = (role, decision)."""
    res = {}
    bar = threading.Barrier(2)

    def go(name, role, decision):
        bar.wait()
        res[name] = call("POST", f"/api/v1/approvals/{aid}/decide", role=role,
                         json_body={"decision": decision, "reason": f"qa3 {name}"})
    th = [threading.Thread(target=go, args=("A", *a)), threading.Thread(target=go, args=("B", *b))]
    [t.start() for t in th]
    [t.join() for t in th]
    return res


X = {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39, "cycle_time": 9.5,
     "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}

# ── 1) candidate 를 바로 promote → 409 invalid_transition ──
st, b = call("POST", f"{P}/models/v1/promote", role="approver", json_body={"reason": "qa3"})
expect("G-M09", "candidate 를 promote 요청", st, b, 409, "invalid_transition")
# operator stage → 403
st, b = call("POST", f"{P}/models/v1/stage", role="operator")
expect("G-M09", "operator 가 stage", st, b, 403, "forbidden")
st, b = call("POST", f"{P}/models/v1/stage", role="admin")
check("G-M09", "admin stage v1", st == 200 and b.get("stage") == "staging", f"{st} {b}")
# approver_other(다른 과제 담당) promote → 403
st, b = call("POST", f"{P}/models/v1/promote", role="approver_other", json_body={"reason": "qa3"})
expect("G-M09", "다른 과제 담당 approver 가 promote", st, b, 403, "forbidden")
st, b = call("POST", f"{P}/models/v1/promote", role="approver", json_body={"reason": "qa3"})
aid1 = b.get("approval_id")
check("G-M09", "promote = 승인 요청만(202 pending)", st == 202 and b.get("state") == "pending" and prod() == [],
      f"{st} {b} production={prod()}")
st2, b2 = call("POST", f"{P}/models/v1/promote", role="approver", json_body={"reason": "qa3 dup"})
check("G-M09", "같은 대상 promote 재요청 → 같은 approval_id", st2 == 202 and b2.get("approval_id") == aid1, f"{st2} {b2.get('approval_id')} vs {aid1}")
st, b = call("POST", f"{P}/predict", json_body={"inputs": X})
expect("G-M09", "승인 대기 중 predict", st, b, 503, "model_not_ready")
# 역할 · 회사
st, b = call("POST", f"/api/v1/approvals/{aid1}/decide", role="operator", json_body={"decision": "approve", "reason": "x"})
expect("§6", "operator decide", st, b, 403, "forbidden")
st, b = call("POST", f"/api/v1/approvals/{aid1}/decide", role="viewer", json_body={"decision": "approve", "reason": "x"})
expect("§6", "viewer decide", st, b, 403, "forbidden")
st, b = call("POST", f"/api/v1/approvals/{aid1}/decide", role="approver_other", json_body={"decision": "approve", "reason": "x"})
expect("§6", "다른 과제 approver decide(own_task)", st, b, 403, "forbidden")
st, b = call("POST", f"/api/v1/approvals/{aid1}/decide", tenant="sw", role="admin", json_body={"decision": "approve", "reason": "x"})
expect("2.3", "다른 회사 키로 decide", st, b, 404, "not_found")
st, b = call("POST", "/api/v1/approvals/apr_doesnotexist/decide", role="admin", json_body={"decision": "approve", "reason": "x"})
expect("2.3", "없는 승인 ID decide", st, b, 404, "not_found")
check("G-M09", "역할 거부 뒤 production 그대로", prod() == [] and db("SELECT state FROM mlp_approval WHERE approval_id=%s", (aid1,))[0]["state"] == "pending",
      f"production={prod()}")

# ── 2) 두 탭 동시 승인 (approver · admin) ──
res = race(aid1, ("approver", "approve"), ("admin", "approve"))
codes = sorted(v[0] for v in res.values())
n_aud = db("SELECT count(*) n FROM mlp_audit WHERE tenant_id='ks' AND action LIKE 'approval.approved' AND detail->>'approval_id'=%s", (aid1,))[0]["n"]
check("G-M09", "두 탭 동시 승인 → 200 1 · 409 1", codes == [200, 409] and n_aud == 1 and prod() == ["v1"],
      f"codes={codes} 감사 approved={n_aud} production={prod()}")
st, b = call("POST", f"/api/v1/approvals/{aid1}/decide", role="approver", json_body={"decision": "reject", "reason": "늦은 반려"})
expect("2.3", "이미 결정된 승인 재결정(반려)", st, b, 409, "already_decided", extra_ok=prod() == ["v1"])

# ── 3) 승인 직후 새 후보 도착 ──
r2 = train(11)
st_after = stages()
check("G-M09", "승인 직후 새 후보 도착 → production 불변", st_after.get(r2["version"]) == "candidate" and prod() == ["v1"],
      f"{r2['version']}={st_after.get(r2['version'])} production={prod()}")
st, b = call("POST", f"{P}/predict", json_body={"inputs": X})
check("G-M09", "새 후보 뒤 predict 는 production v1", st == 200 and b["model"]["version"] == "v1", f"{st} model={b.get('model', {}).get('version') if isinstance(b, dict) else b}")
v2 = r2["version"]
call("POST", f"{P}/models/{v2}/stage", role="admin")
st, b = call("POST", f"{P}/models/{v2}/promote", role="approver", json_body={"reason": "v2"})
aid2 = b["approval_id"]
# 승인/반려 경합
res = race(aid2, ("approver", "approve"), ("admin", "reject"))
codes = sorted(v[0] for v in res.values())
final = db("SELECT state FROM mlp_approval WHERE approval_id=%s", (aid2,))[0]["state"]
exp_prod = [v2] if final == "approved" else ["v1"]
check("G-M09", "승인 · 반려 동시 → 하나만", codes == [200, 409] and prod() == exp_prod,
      f"codes={codes} 최종={final} production={prod()}")
if final != "approved":       # 반려가 이겼다면 다시 요청해 승인
    st, b = call("POST", f"{P}/models/{v2}/promote", role="approver", json_body={"reason": "v2 재요청"})
    aid2 = b["approval_id"]
    call("POST", f"/api/v1/approvals/{aid2}/decide", role="approver", json_body={"decision": "approve", "reason": "ok"})
check("G-M09", "v2 승인 → production v2 · v1 archived", prod() == [v2] and stages()["v1"] == "archived", f"{stages()}")

# 대기 중에 새 후보 · 다른 승인
r3 = train(12)
v3 = r3["version"]
call("POST", f"{P}/models/{v3}/stage", role="admin")
st, b = call("POST", f"{P}/models/{v3}/promote", role="approver", json_body={"reason": "v3"})
aid3 = b["approval_id"]

# ── 4) 되돌리기 ──
st, b = call("POST", f"{P}/models/v1/rollback", role="approver", json_body={})
expect("2.3", "사유 없는 rollback", st, b, 422, "missing_required", extra_ok=isinstance(b, dict) and b["error"]["detail"].get("field") == "reason")
st, b = call("POST", f"{P}/models/{v3}/rollback", role="approver", json_body={"reason": "staging 을 되돌림"})
expect("G-M09", "archived 아닌 것을 rollback", st, b, 409, "invalid_transition")
st, b = call("POST", f"{P}/models/v1/rollback", role="approver", json_body={"reason": "v2 이상 — v1 로"})
aidr = b.get("approval_id")
check("G-M09", "rollback = 승인 요청만(production 불변)", st == 202 and prod() == [v2], f"{st} production={prod()}")
st, b = call("POST", f"/api/v1/approvals/{aidr}/decide", role="approver", json_body={"decision": "approve", "reason": "되돌림"})
check("G-M09", "rollback 승인 → v1 production · v2 archived", st == 200 and prod() == ["v1"] and stages()[v2] == "archived",
      f"{st} {b} {stages()}")
st, b = call("GET", f"{P}/models", role="approver")
prod_items = [i for i in b["items"] if i["stage"] == "production"] if st == 200 else []
check("G-M09", "models 목록 production 1개", len(prod_items) == 1, f"{st} production 항목 {len(prod_items)}")
# 되돌린 뒤 남은 v3 promote 승인 — 여전히 결정 가능해야 하고 결정하면 v3 production (사람 결정)
pending3 = db("SELECT state FROM mlp_approval WHERE approval_id=%s", (aid3,))[0]["state"]
check("G-M09", "되돌리기 뒤 대기 중 v3 승인 유지", pending3 == "pending", pending3)

# ── 5) 만료된 승인 ──
db("UPDATE mlp_approval SET expires_at = now() - interval '1 minute' WHERE approval_id=%s", (aid3,))
st, b = call("POST", f"/api/v1/approvals/{aid3}/decide", role="approver", json_body={"decision": "approve", "reason": "만료 뒤"})
expect("2.3", "만료된 승인 결정", st, b, 409, "already_decided", extra_ok=prod() == ["v1"], extra=f"production={prod()}")
st, b = call("GET", "/api/v1/tenants/ks/approvals?state=pending", role="approver")
still = [i for i in b["items"] if i["approval_id"] == aid3]
check("G-M09", "만료된 승인이 대기열(state=pending)에서 빠짐", not still, f"pending 목록에 남음={bool(still)} state={still[0]['state'] if still else '-'}", warn=True)
st, b = call("GET", "/api/v1/tenants/ks/approvals?state=expired", role="approver")
check("G-M09", "state=expired 조회에 만료 승인 보임", any(i["approval_id"] == aid3 for i in b.get("items", [])), f"{st} n={len(b.get('items', []))}", warn=True)
st, b = call("POST", f"{P}/models/{v3}/promote", role="approver", json_body={"reason": "만료 뒤 재요청"})
check("G-M09", "만료 뒤 같은 버전 재요청 → 새 승인", st == 202 and b.get("approval_id") != aid3, f"{st} {b}", warn=True)
exp_cnt = db("SELECT count(*) n FROM mlp_approval WHERE expires_at IS NOT NULL AND approval_id <> %s", (aid3,))[0]["n"]
check("G-M09", "승인 요청에 만료 시각(expires_at) 설정", exp_cnt > 0, f"expires_at 있는 승인 {exp_cnt}건(QA 가 손으로 넣은 1건 제외)", warn=True)

# ── 6) 감사 · 고유성 ──
dup = db("SELECT detail->>'approval_id' a, count(*) n FROM mlp_audit WHERE action IN ('approval.approved','approval.rejected','recommendation.approved','recommendation.rejected') GROUP BY 1 HAVING count(*) > 1")
check("G-M09", "같은 승인 두 번 결정 감사 0", not dup, f"중복 {dup}")
pc = db("SELECT task_id, count(*) n FROM mlp_model_version WHERE stage='production' GROUP BY 1 HAVING count(*) > 1")
check("G-M09", "과제당 production ≤ 1", not pc, f"{pc}")
nonapproved = db("SELECT version FROM mlp_model_version WHERE stage='production' AND approval_id IS NULL")
check("G-M09", "production 전부 approval_id 있음", not nonapproved, f"{nonapproved}")
dump(sys.argv[1])
