"""QA3 — ml_qa3_db 에 역할별 API 키를 만든다. 평문은 scratchpad 의 keys.json 에만(저장소에 남기지 않는다)."""
import json, sys
from mlcore import auth
from mlcore.db.conn import connect
out_path = sys.argv[1]
roles_by_tenant = {}
keys = {}
with connect() as c:
    for t in ("yn",):
        ar = sorted({r["approver_role"] for r in c.execute("SELECT approver_role FROM mlp_task WHERE tenant_id=%s", (t,)).fetchall()})
        keys[t] = {}
        for role in ("viewer", "operator", "approver", "admin"):
            raw, h = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                      (t, h, raw[:8], role, json.dumps(ar if role == "approver" else []), f"qa3-{role}"))
            keys[t][role] = raw
        raw, h = auth.new_key()
        c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,'approver','[\"nobody\"]'::jsonb,'qa3-other')", (t, h, raw[:8]))
        keys[t]["approver_other"] = raw
json.dump(keys, open(out_path, "w"))
print("ok", {t: list(v) for t, v in keys.items()})
