"""6개사 학습 과제 전부: API train(demo) → 작업자(make worker 와 같은 모듈) → stage → promote(승인 요청) → approver decide.
사용: t01_train_all.py [tenants...]"""
import subprocess, sys, time
from qa_lib import Server, call, check, dump, ROOT
TRAINABLE = ("regression", "risk", "anomaly", "extract", "review_queue")
for t in sys.argv[1:] or ["ks", "sw", "krs", "pc", "ot", "kd"]:
    s = Server(t)
    try:
        st, tasks = call("GET", f"/api/v1/tenants/{t}/tasks", t=t, role="viewer")
        items = tasks["items"]
        ready = {x["task"]: x["model_ready"] for x in call("GET", "/api/v1/health", t=t, role=None)[1]["tasks"]}
        runs = {}
        for it in items:
            tid, ty = it["task"], it["type"]
            if ty not in TRAINABLE or ready.get(tid):
                continue
            st, b = call("POST", f"/api/v1/tenants/{t}/tasks/{tid}/train", t=t, json_body={"source_role": "demo"})
            check("T01", f"{tid} train 접수", st in (200, 202), f"HTTP {st} {str(b)[:120]}", warn=True)
            if st in (200, 202):
                runs[tid] = b["run_id"]
                r = subprocess.run([sys.executable, "-m", "mlcore.train.jobs", "--pending"], cwd=ROOT, capture_output=True, text=True)
                check("T01", f"{tid} 작업자", r.returncode == 0, (r.stdout + r.stderr)[-160:].replace("\n", " | "))
        for tid, rid in runs.items():
            st, run = call("GET", f"/api/v1/runs/{rid}", t=t)
            ver = run.get("version") if isinstance(run, dict) else None
            check("T01", f"{tid} 학습", st == 200 and run.get("status") == "succeeded", f"status={run.get('status')} champion={run.get('champion')} beats={run.get('beats_baseline')} v={ver} err={str(run.get('error'))[:80]}", warn=True)
            if not ver:
                continue
            st, b = call("POST", f"/api/v1/tenants/{t}/tasks/{tid}/models/{ver}/stage", t=t)
            check("T01", f"{tid} stage {ver}", st == 200, f"HTTP {st} {str(b)[:120]}", warn=True)
            st, b = call("POST", f"/api/v1/tenants/{t}/tasks/{tid}/models/{ver}/promote", t=t, role="approver", json_body={"reason": "QA2-r3 운영 승격"})
            check("T01", f"{tid} promote 요청", st == 202, f"HTTP {st} {str(b)[:120]}", warn=True)
            if st == 202:
                st, d = call("POST", f"/api/v1/approvals/{b['approval_id']}/decide", t=t, role="approver", json_body={"decision": "approve", "reason": "QA2-r3 승인"})
                check("T01", f"{tid} 승인", st == 200 and d.get("production_version") == ver, f"HTTP {st} {str(d)[:120]}", warn=True)
        st, hl = call("GET", "/api/v1/health", t=t, role=None)
        check("T01", f"{t} health model_ready", st == 200, str([(x["task"], x["model_ready"]) for x in hl["tasks"]]))
    finally:
        s.close()
dump("rows_t01_r3.txt")
