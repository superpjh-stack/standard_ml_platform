#!/bin/bash
# QA-R2 — R4 실경로: A) live + 합성 production → 기동 시 disabled · 503   B) live 로 기동 뒤 승인된 합성 → 503
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"; source outputs/qa-r2/env.sh
S=$QAR2_SCRATCH/r4; rm -rf $S; mkdir -p $S/a $S/b; Q=outputs/qa-r2/qa3
X='{"inputs":{"set_temp":175,"set_pressure":4,"line_speed":15,"ink_usage":18,"dwell_time":50,"absorb_rate":82,"fabric_strength":340,"print_type":"나염","color_tone":"진한 색상"}}'
boot() { MLP_TENANT=$1 MLP_TENANTS_DIR=$2 uv run uvicorn mlcore.api.main:app --host 127.0.0.1 --port 8204 > $S/$1.log 2>&1 & echo $! > $S/pid
  for i in $(seq 1 60); do curl -s -o /dev/null 127.0.0.1:8204/api/v1/health && return 0; sleep 0.25; done; echo BOOTFAIL; tail -5 $S/$1.log; }
stop() { kill $(cat $S/pid) 2>/dev/null; sleep 1; pkill -f "port 8204" 2>/dev/null; sleep 0.5; }
key() { uv run python -c "
from mlcore import auth; from mlcore.db.conn import connect
raw,h=auth.new_key()
with connect() as c: c.execute(\"INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,'operator','[]'::jsonb,'qar2-op')\",('$1',h,raw[:8]))
print(raw)"; }
# A
uv run python $Q/t09_r4_r2.py setup $S/a qz4a delta_e defect_risk print_ood 2>&1 | grep -v -i warn | cut -c1-200
cp $S/a/qz4a.yaml $S/qz4a-demo.yaml; uv run python $Q/t09_r4_r2.py live $S/a qz4a
boot qz4a $S/a; KA=$(key qz4a)
echo "A health: $(curl -s 127.0.0.1:8204/api/v1/health)"
echo "A tasks: $(curl -s -H "X-API-Key: $KA" 127.0.0.1:8204/api/v1/tenants/qz4a/tasks | head -c 600)"
echo "A predict: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KA" -H 'Content-Type: application/json' -d "$X" 127.0.0.1:8204/api/v1/tenants/qz4a/tasks/delta_e/predict)"
echo "A batch: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KA" -H 'Content-Type: application/json' -d "{\"items\":[$X]}" 127.0.0.1:8204/api/v1/tenants/qz4a/tasks/delta_e/predict:batch | head -c 300)"
echo "A compat: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KA" -H 'Content-Type: application/json' -d "$(echo $X | sed 's/{"inputs"://; s/}$//')" 127.0.0.1:8204/api/quality/predict | head -c 400)"
stop
# B
uv run python $Q/t09_r4_r2.py setup $S/b qz4b delta_e defect_risk print_ood 2>&1 | grep -v -i warn | cut -c1-200
cp $S/b/qz4b.yaml $S/qz4b-demo.yaml; uv run python $Q/t09_r4_r2.py live $S/b qz4b
boot qz4b $S/b; KB=$(key qz4b)
echo "B health(기동 직후): $(curl -s 127.0.0.1:8204/api/v1/health)"
uv run python $Q/t09_r4_r2.py approve $S/b qz4b delta_e defect_risk print_ood 2>&1 | grep -v -i warn | cut -c1-200
echo "B health(승인 뒤): $(curl -s 127.0.0.1:8204/api/v1/health)"
echo "B predict: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KB" -H 'Content-Type: application/json' -d "$X" 127.0.0.1:8204/api/v1/tenants/qz4b/tasks/delta_e/predict)"
echo "B batch: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KB" -H 'Content-Type: application/json' -d "{\"items\":[$X]}" 127.0.0.1:8204/api/v1/tenants/qz4b/tasks/delta_e/predict:batch | head -c 300)"
echo "B compat: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KB" -H 'Content-Type: application/json' -d "$(echo $X | sed 's/{"inputs"://; s/}$//')" 127.0.0.1:8204/api/quality/predict | head -c 400)"
echo "B model_version=v1: $(curl -s -w ' HTTP%{http_code}' -H "X-API-Key: $KB" -H 'Content-Type: application/json' -d "$(echo $X | sed 's/}$/,"model_version":"v1"}/')" 127.0.0.1:8204/api/v1/tenants/qz4b/tasks/delta_e/predict | head -c 300)"
stop
