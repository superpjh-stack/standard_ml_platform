"""QA3 — API 로 stage → promote → decide (운영 모델 준비). 사용: promote.py <tenant> <task_short>... (서버의 MLP_TENANT 회사만)"""
import sys
from qa_lib import call
t = sys.argv[1]
for task in sys.argv[2:]:
    P = f"/api/v1/tenants/{t}/tasks/{task}"
    st, b = call("GET", f"{P}/models", tenant=t, role="admin")
    v = [i["version"] for i in b["items"] if i["stage"] == "candidate"][0]
    s1 = call("POST", f"{P}/models/{v}/stage", tenant=t, role="admin")
    s2 = call("POST", f"{P}/models/{v}/promote", tenant=t, role="approver", json_body={"reason": "qa3"})
    s3 = call("POST", f"/api/v1/approvals/{s2[1]['approval_id']}/decide", tenant=t, role="approver", json_body={"decision": "approve", "reason": "qa3"})
    print(task, v, s1[0], s2[0], s3)
