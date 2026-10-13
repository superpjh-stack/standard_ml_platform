"""QA2-3 — ml_qa2r3_db 에 6개사 역할별 API 키. 평문은 scratchpad keys.json 에만(저장소에 남기지 않는다)."""
import json, sys
from mlcore import auth
from mlcore.db.conn import connect
out = {}
with connect() as c:
    for t in [r["tenant_id"] for r in c.execute("SELECT tenant_id FROM mlp_tenant ORDER BY 1").fetchall()]:
        ar = sorted({r["approver_role"] for r in c.execute("SELECT approver_role FROM mlp_task WHERE tenant_id=%s", (t,)).fetchall()})
        out[t] = {}
        for role in ("viewer", "operator", "approver", "admin"):
            raw, h = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                      (t, h, raw[:8], role, json.dumps(ar if role == "approver" else []), f"qa23-{role}"))
            out[t][role] = raw
        raw, h = auth.new_key()
        c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,'approver','[\"nobody\"]'::jsonb,'qa23-other')", (t, h, raw[:8]))
        out[t]["approver_other"] = raw
json.dump(out, open(sys.argv[1], "w"))
print("ok", {t: list(v) for t, v in out.items()})
