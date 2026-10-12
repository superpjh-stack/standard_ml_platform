"""QA3 t04 — G-M13 ks.maintenance_timing (1차원 결정 변수 격자): 경계 · 불가능 제약 · 추천 승인이 production 을 바꾸지 않는지."""
import sys
import time

import psycopg
from psycopg.rows import dict_row

from qa_lib import call, check, expect, dump

DSN = "dbname=ml_qa3_db host=/tmp"
P = "/api/v1/tenants/ks/tasks/maintenance_timing/optimize"
X = {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39, "cycle_time": 9.5,
     "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}


def db(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else None


def prod_map():
    return {(r["task_id"], r["version"]) for r in db("SELECT task_id, version FROM mlp_model_version WHERE stage='production'")}


t0 = time.perf_counter()
st, b = call("POST", P, role="operator", json_body={"fixed": X})
dt = time.perf_counter() - t0
rec = b.get("recommendation") or {}
pts = [c["conditions"]["stop_after_hours"] for c in rec.get("candidates", [])]
check("G-M13", "기본 params → needs_approval · 후보 5", st == 200 and b["status"] == "needs_approval" and rec["feasible"] and len(pts) == 5,
      f"{st} status={b.get('status')} n_candidates={rec.get('n_candidates')} n_feasible={rec.get('n_feasible')} {dt:.2f}s")
check("G-M13", "결정 변수 점 수 = 0..48 step 0.5 = 97", rec.get("n_candidates") == 97, f"n_candidates={rec.get('n_candidates')}")
check("G-M13", "후보 결정 변수 ∈ [0, max_delay_hours]", all(0 <= p <= 48 and (p * 2).is_integer() for p in pts), f"{pts}")
check("G-M13", "후보 전부 제약 충족", all(all(c["satisfied"] for c in cd["constraints"]) for cd in rec["candidates"]),
      f"{[[c['satisfied'] for c in cd['constraints']] for cd in rec['candidates']]}")
check("G-M13", "응답 키 18 · prediction/model/prediction_id null · uses 배열", len(b) == 18 and b["prediction"] is None and b["model"] is None
      and b["prediction_id"] is None and isinstance(b["uses"], list), f"keys={len(b)} uses={b.get('uses')}")
rid = rec.get("rec_id")
row = db("SELECT status, feasible FROM mlp_recommendation WHERE rec_id=%s", (rid,))
apr = db("SELECT approval_id, state, kind, approver_role FROM mlp_approval WHERE ref_id=%s", (rid,))
check("G-M13", "mlp_recommendation needs_approval + 승인 요청(kind=recommendation)", row and row[0]["status"] == "needs_approval" and apr and apr[0]["state"] == "pending",
      f"rec={row} approval={apr}")
# 불가능 제약
st, b = call("POST", P, role="operator", json_body={"fixed": X, "params": {"reserve_hours": 150, "max_cost_index": 1, "max_delay_hours": 72}})
rec2 = b.get("recommendation") or {}
check("G-M13", "불가능 제약 → feasible=false · status review · least_violation", st == 200 and b["status"] == "review" and rec2.get("feasible") is False
      and rec2.get("on_infeasible") == "least_violation" and any(w["code"] == "infeasible" for w in b["warnings"]),
      f"{st} status={b.get('status')} feasible={rec2.get('feasible')} on_infeasible={rec2.get('on_infeasible')} n_feasible={rec2.get('n_feasible')}")
check("G-M13", "불가능 제약에서 ok/needs_approval 0", b.get("status") not in ("ok", "needs_approval"), f"status={b.get('status')}")
unmet = [c["name"] for c in rec2["best"]["constraints"] if not c["satisfied"]]
check("G-M13", "least_violation best 의 미충족 제약 표시", bool(unmet) and all(any(w["code"] == "constraint_unmet" and w.get("field") == u for w in b["warnings"]) for u in unmet),
      f"unmet={unmet}")
vs = [c["violation"] for c in rec2["candidates"]]
check("G-M13", "least_violation 후보 위반 오름차순", vs == sorted(vs), f"{vs}")
rid2 = rec2.get("rec_id")
row2 = db("SELECT status, feasible FROM mlp_recommendation WHERE rec_id=%s", (rid2,))
check("G-M13", "불가능 추천도 needs_approval 로 기록(설비 미적용)", row2 and row2[0]["feasible"] is False and row2[0]["status"] == "needs_approval", f"{row2}")
# 한쪽 제약만 불가능
st, b = call("POST", P, role="operator", json_body={"fixed": X, "params": {"reserve_hours": 150}})
check("G-M13", "reserve 150h(예측 잔여수명보다 큼) → review", st == 200 and b["status"] == "review" and not b["recommendation"]["feasible"],
      f"{st} {b.get('status')} best={b['recommendation']['best']['conditions'] if st == 200 else b}")
# decision_vars · params 경계
for prm, val, want in (({"max_delay_hours": 72}, None, 145), ({"max_delay_hours": 0}, None, 1), ({"max_delay_hours": 0.4}, None, 1),
                       ({"max_delay_hours": 72.5}, "out_of_bounds", None), ({"max_delay_hours": -0.5}, "out_of_bounds", None),
                       ({"reserve_hours": 0}, "out_of_bounds", None), ({"max_cost_index": 501}, "out_of_bounds", None),
                       ({"zz_param": 1}, "invalid_input", None), ({"reserve_hours": "12"}, "invalid_input", None),
                       ({"reserve_hours": True}, "invalid_input", None)):
    st, b = call("POST", P, role="operator", json_body={"fixed": X, "params": prm})
    if want is not None:
        n = (b.get("recommendation") or {}).get("n_candidates")
        mx = max(c["conditions"]["stop_after_hours"] for c in b["recommendation"]["candidates"]) if st == 200 else None
        check("G-M13", f"decision_vars 경계 {prm}", st == 200 and n == want and (mx is None or mx <= prm["max_delay_hours"]), f"{st} n={n} max={mx}")
    else:
        expect("G-M13", f"params 경계 {prm}", st, b, 422, val)
# current: 결정 변수 범위 밖 값
st, b = call("POST", P, role="operator", json_body={"fixed": X, "current": {"stop_after_hours": 1000}})
check("G-M13", "current.stop_after_hours=1000(결정 변수 max 72 밖) 거부", st == 422, f"{st} status={b.get('status') if isinstance(b, dict) else b} "
      f"current={((b.get('recommendation') or {}).get('current') or {}).get('conditions') if isinstance(b, dict) and st == 200 else None}", warn=True)
st, b = call("POST", P, role="operator", json_body={"fixed": X, "current": {"stop_after_hours": -5}})
check("G-M13", "current.stop_after_hours=-5 거부", st == 422, f"{st}", warn=True)
# 고정 입력 학습 범위 밖
st, b = call("POST", P, role="operator", json_body={"fixed": {**X, "press_force": 181}})
check("G-M13", "고정 입력 학습 범위 밖 → review + out_of_range 경고", st == 200 and b["status"] == "review" and "press_force" in b["out_of_range_fields"],
      f"{st} {b.get('status')} {b.get('out_of_range_fields')}")
st, b = call("POST", P, role="operator", json_body={"fixed": {**X, "press_force": 999}})
expect("G-M13", "고정 입력 min/max 밖", st, b, 422, "out_of_bounds")
st, b = call("POST", P, role="viewer", json_body={"fixed": X})
expect("§6", "viewer optimize", st, b, 403, "forbidden")
# 추천 승인 → production 불변 · 재결정 409
before = prod_map()
aid = apr[0]["approval_id"]
st, b = call("POST", f"/api/v1/approvals/{aid}/decide", role="approver", json_body={"decision": "approve", "reason": "qa3 추천 승인"})
after = prod_map()
rs = db("SELECT status FROM mlp_recommendation WHERE rec_id=%s", (rid,))[0]["status"]
check("G-M13", "추천 승인 → production 불변 · rec approved · production_version null", st == 200 and before == after and rs == "approved"
      and b.get("production_version") is None, f"{st} {b} rec={rs} production 변화={before ^ after}")
st, b = call("POST", f"/api/v1/approvals/{aid}/decide", role="admin", json_body={"decision": "reject", "reason": "재결정"})
expect("2.3", "추천 승인 재결정", st, b, 409, "already_decided")
aud = db("SELECT count(*) n FROM mlp_audit WHERE action IN ('recommendation.approved','recommendation.rejected') AND detail->>'approval_id'=%s", (aid,))[0]["n"]
check("G-M13", "추천 결정 감사 1행", aud == 1, f"{aud}")
# 추천 결정 두 탭 동시
import threading
st, b = call("POST", P, role="operator", json_body={"fixed": X})
aid3 = db("SELECT approval_id FROM mlp_approval WHERE ref_id=%s", (b["recommendation"]["rec_id"],))[0]["approval_id"]
res, bar = {}, threading.Barrier(2)
def go(n, role, d):
    bar.wait(); res[n] = call("POST", f"/api/v1/approvals/{aid3}/decide", role=role, json_body={"decision": d, "reason": n})[0]
ths = [threading.Thread(target=go, args=("A", "approver", "approve")), threading.Thread(target=go, args=("B", "admin", "approve"))]
[t.start() for t in ths]; [t.join() for t in ths]
check("G-M13", "추천 승인 두 탭 동시 → 200 1 · 409 1", sorted(res.values()) == [200, 409], f"{res}")
# 설비 · MES 쓰기 0 — 감사/추천 외 테이블 변화 없음은 코드 경로로: optimize._record 는 mlp_* 만 INSERT
dump(sys.argv[1])
