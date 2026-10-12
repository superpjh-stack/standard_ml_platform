"""QA3 t09 — R4 실경로: demo 로 합성 모델을 운영에 올린 회사(qz4, tmp 등록부)의 등록부를 live 로 바꿔 기동했을 때 그 과제가 꺼지는가."""
import os, sys
from mlcore.db.conn import connect
from mlcore.registry import tenants
from mlcore.registry.models import Registry
from mlcore.serve import training
from mlcore import approval
base = sys.argv[1]
m = tenants.load_and_merge("qz4", tenants_base=base)
with connect() as c:
    c.execute("INSERT INTO mlp_tenant (tenant_id,name,pack,mode) VALUES ('qz4','QA3 R4','textile','demo') ON CONFLICT DO NOTHING")
    for tid, td in m.tasks.items():
        c.execute("INSERT INTO mlp_task (tenant_id,task_id,pack_task_id,type,def_hash,approver_role) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                  ("qz4", tid, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
os.environ["MLP_TENANTS_DIR"] = base
rid = training.submit("qz4", "qz4.delta_e", actor="qa3", source_role="demo", seed=None)["run_id"]
res, ref = training.run_and_register(rid)
reg = Registry()
reg.stage("qz4", "qz4.delta_e", ref.version, actor="qa3")
aid = reg.request_promotion("qz4", "qz4.delta_e", ref.version, actor="qa3", action="promote", reason=None)
print(approval.decide(aid, actor="qa3", actor_role="approver", approve=True, reason="qa3 R4"))
print("synthetic", reg.get("qz4", "qz4.delta_e").synthetic)
