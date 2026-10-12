"""QA3 t10 — G-M10 새 회사 yn: (make tenant · db-seed · doctor 는 셸에서) API train(eval CSV) → 작업자 → stage → 승인 → predict."""
import os, subprocess, sys, time
from qa_lib import call, check, expect, dump
P = "/api/v1/tenants/yn/tasks"
st, b = call("GET", "/api/v1/health", role=None)
check("G-M10", "yn 기동 · 과제 2 · model_ready false", st == 200 and len(b["tasks"]) == 2 and not any(t["model_ready"] for t in b["tasks"]), f"{b}")
st, b = call("GET", "/api/v1/tenants/yn/doctor", role="operator")
check("G-M10", "doctor API(eval 연결 · train 미연결)", st == 200 and {s["role"]: s["status"] for s in b["sources"]}.get("eval") == "연결", f"{[(s['role'], s['status']) for s in b['sources']]}")
st, b = call("GET", f"{P}/target_value", role="viewer")
feats = {f["name"]: f for f in b["features"]}
X = {n: (f["default"] if f.get("default") is not None else (f.get("values") or [None])[0]) for n, f in feats.items()}
for task in ("target_value", "target_risk"):
    st, b = call("POST", f"{P}/{task}/predict", role="operator", json_body={"inputs": X})
    expect("G-M10", f"학습 전 yn.{task} predict", st, b, 503, "model_not_ready")
    st, b = call("POST", f"{P}/{task}/train", json_body={"source_role": "eval"})
    check("G-M10", f"yn.{task} train(eval CSV) 접수 202", st == 202 and b.get("status") == "queued", f"{st} {b}")
w = subprocess.run([sys.executable, "-m", "mlcore.train.jobs", "--pending"], capture_output=True, text=True)
check("G-M10", "작업자(make worker) 실행", w.returncode == 0, w.stdout.strip()[-300:] or w.stderr[-300:])
for task in ("target_value", "target_risk"):
    st, b = call("GET", f"{P}/{task}/models", role="admin")
    cands = [i for i in b["items"] if i["stage"] == "candidate"]
    if not cands:
        check("G-M10", f"yn.{task} candidate", False, f"{b}")
        continue
    v = cands[0]["version"]
    st1, b1 = call("POST", f"{P}/{task}/models/{v}/stage", role="admin")
    st2, b2 = call("POST", f"{P}/{task}/models/{v}/promote", role="approver", json_body={"reason": "qa3 새 회사"})
    st3, b3 = call("POST", f"/api/v1/approvals/{b2.get('approval_id')}/decide", role="approver", json_body={"decision": "approve", "reason": "qa3"})
    check("G-M10", f"yn.{task} {v} stage→승인→production", st1 == 200 and st2 == 202 and st3 == 200 and b3.get("production_version") == v,
          f"{st1} {b1 if st1 != 200 else ''} {st2} {st3} {b3}  synthetic={cands[0]['synthetic']} beats={cands[0]['beats_baseline']}")
    st, b = call("POST", f"{P}/{task}/predict", role="operator", json_body={"inputs": X})
    check("G-M10", f"yn.{task} predict 200 · 18키 · 모델 {v}", st == 200 and len(b) == 18 and b["model"]["version"] == v, f"{st} status={b.get('status')} model={b.get('model')}")
dump(sys.argv[1])
