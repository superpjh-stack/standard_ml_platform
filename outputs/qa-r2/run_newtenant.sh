#!/bin/bash
# QA-R2 — G-M10 새 회사(QA3 t10 절차): 빈 tmp 등록부 → make tenant → seed → doctor → 서버 8204 → t10
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"; source outputs/qa-r2/env.sh
S=$QAR2_SCRATCH/yn; rm -rf $S; mkdir -p $S/reg $S/up
H0=$(find src packs tenants -type f -not -path '*/__pycache__/*' -exec shasum {} + | shasum)
uv run python migration/make_fixtures.py --kind template_csv --out $S/up >/dev/null
MLP_TENANTS_DIR=$S/reg make -s tenant NEW=yn PACK=_template CSV=$S/up/snapshot.csv
echo "생성 파일: $(cd $S/reg && find . -type f)"
MLP_TENANTS_DIR=$S/reg uv run python -c "
from mlcore.registry import tenants; from mlcore.db.conn import connect
m=tenants.load_and_merge('yn'); cfg=m.tenant.config
with connect() as c:
    c.execute('INSERT INTO mlp_tenant (tenant_id,name,pack,mode) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',('yn',cfg['name'],cfg['pack'],cfg['mode']))
    for tid,td in m.tasks.items(): c.execute('INSERT INTO mlp_task (tenant_id,task_id,pack_task_id,type,def_hash,approver_role) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',('yn',tid,td.pack_id,td.type,td.def_hash,td.raw['approver_role']))
print('seed yn', list(m.tasks))"
MLP_TENANTS_DIR=$S/reg make -s doctor TENANT=yn 2>&1 | grep -v -i warn
uv run python - <<PY
import json,sys; sys.path.insert(0,'outputs/qa-r2/qa3')
from mlcore import auth; from mlcore.db.conn import connect
ks=json.load(open('$QAR2_SCRATCH/keys.json')); ks['yn']={}
with connect() as c:
    for role in ('viewer','operator','approver','admin'):
        raw,h=auth.new_key()
        c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES ('yn',%s,%s,%s,%s::jsonb,%s)",(h,raw[:8],role,json.dumps(['owner','ml_lead','quality','maintenance_lead','line_lead'] if role=='approver' else []),'qar2-'+role))
        ks['yn'][role]=raw
json.dump(ks,open('$QAR2_SCRATCH/keys.json','w'))
PY
MLP_TENANT=yn MLP_TENANTS_DIR=$S/reg uv run uvicorn mlcore.api.main:app --host 127.0.0.1 --port 8204 > $S/server.log 2>&1 & PID=$!
for i in $(seq 1 60); do curl -s -o /dev/null 127.0.0.1:8204/api/v1/health && break; sleep 0.25; done
cd outputs/qa-r2/qa3 && QAR2_KEYS=$QAR2_SCRATCH/keys.json QAR2_TENANT=yn MLP_TENANTS_DIR=$S/reg uv run python t10_new_tenant.py r10.txt 2>&1 | grep -vi "warning:" | cut -c1-260
cd "$ROOT"; kill $PID; sleep 1; pkill -f "port 8204"
H1=$(find src packs tenants -type f -not -path '*/__pycache__/*' -exec shasum {} + | shasum)
echo "저장소 src·packs·tenants 해시 전후 같음: $([ "$H0" = "$H1" ] && echo yes || echo no)"
