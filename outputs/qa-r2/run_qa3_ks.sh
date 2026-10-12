#!/bin/bash
# QA-R2 — QA3 재현(ks 단계): 키 → ks 학습 3 → 서버 8204 → t01 → t02 → 나머지 운영 → t03 · t04 · t05 · t07 · t07b · t11
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"; source outputs/qa-r2/env.sh
Q=outputs/qa-r2/qa3; S=$QAR2_SCRATCH; mkdir -p $S
export QAR2_KEYS=$S/keys.json QAR2_TENANT=ks
cd $Q
[ -f $S/keys.json ] || uv run python mkkeys.py $S/keys.json
for t in ks.remaining_hours ks.failure_24h ks.sensor_ood; do uv run python -m mlcore.train.jobs --submit ks $t 2>/dev/null | tail -1 | cut -c1-200; done
start() { MLP_TENANT=$1 uv run uvicorn mlcore.api.main:app --host 127.0.0.1 --port 8204 > $S/server-$1.log 2>&1 & echo $! > $S/server.pid
  for i in $(seq 1 60); do curl -s -o /dev/null 127.0.0.1:8204/api/v1/health && return 0; sleep 0.25; done; echo "기동 실패"; return 1; }
stop() { kill $(cat $S/server.pid) 2>/dev/null; sleep 1; pkill -f "port 8204" 2>/dev/null; sleep 0.5; }
start ks
uv run python t01_not_ready.py r01.txt
uv run python t02_approval.py r02.txt
uv run python promote.py ks failure_24h sensor_ood
uv run python t03_errors.py r03.txt
uv run python t04_optimize_ks.py r04.txt
uv run python t05_ui.py r05.txt
uv run python t07_drift.py r07.txt
uv run python t07b_below_baseline.py r07b.txt
uv run python t11_compat_cover.py r11ks.txt
stop
