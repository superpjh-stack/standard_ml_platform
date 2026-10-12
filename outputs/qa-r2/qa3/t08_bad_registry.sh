#!/bin/bash
# QA3 t08 — 불량 등록부 5종을 실제 uvicorn 기동(포트 8204)으로 시험. tmp 등록부 루트(MLP_TENANTS_DIR)만 쓴다 — tenants/ 에 파일 0.
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$ROOT"; source outputs/qa-r2/env.sh
TMP=$(mktemp -d); OUT=${1:-outputs/qa-r2/qa3/r08.txt}; : > "$OUT"
boot() {  # $1 이름 $2 등록부 루트 $3 회사 코드
  MLP_TENANT=$3 MLP_TENANTS_DIR=$2 uv run uvicorn mlcore.api.main:app --host 127.0.0.1 --port 8204 > "$TMP/$1.log" 2>&1 &
  local pid=$!; local st="exit"
  for i in $(seq 1 40); do
    if ! kill -0 $pid 2>/dev/null; then st="exit"; break; fi
    if curl -s -o /dev/null 127.0.0.1:8204/api/v1/health; then st="up"; break; fi
    sleep 0.25
  done
  echo "$st"
  [ "$st" = up ] && echo "$pid" > "$TMP/pid" || rm -f "$TMP/pid"
}
stop() { [ -f "$TMP/pid" ] && kill $(cat "$TMP/pid") 2>/dev/null; sleep 1; pkill -f "port 8204" 2>/dev/null; sleep 0.5; }
for d in tests/fixtures/bad_registry/r*/; do
  n=$(basename $d); code=$(awk '/^code:/{print $2}' $d/tenant.yaml); base=$TMP/$n; mkdir -p $base/$code
  cp $d/tenant.yaml $base/$code.yaml; [ -d $d/tasks ] && cp -r $d/tasks $base/$code/; [ -d $d/formulas ] && cp -r $d/formulas $base/$code/
  st=$(boot $n $base $code)
  reason=$(grep -oE "RegistryRejected[^\"]{0,120}|R[1-5][^\"]{0,0}" $TMP/$n.log | head -1)
  extra=""
  if [ "$st" = up ]; then extra=$(curl -s 127.0.0.1:8204/api/v1/health | head -c 300); fi
  if [ "$n" = r4_live_synthetic ]; then
    verdict=$([ "$st" = up ] && echo PASS || echo FAIL)   # D-27: 기동하되 과제 disabled
  else
    verdict=$([ "$st" = exit ] && echo PASS || echo FAIL)
  fi
  echo "G-S02  불량 등록부 $n 실기동  $verdict  기동=$st $(grep -m1 -oE 'R[1-5][^\n]{0,90}' $TMP/$n.log | tr -d '\n' | head -c 140) $extra" | tee -a "$OUT"
  stop
done
# ks 등록부를 mode: live 로 바꾼 사본 — DB 의 ks production 은 합성 스냅숏 모델 (R4 실경로)
base=$TMP/kslive; mkdir -p $base; sed 's/^mode: demo/mode: live/' tenants/ks.yaml > $base/ks.yaml
st=$(boot kslive $base ks)
if [ "$st" = up ]; then
  H=$(curl -s 127.0.0.1:8204/api/v1/health)
  echo "health: $H" > $TMP/kslive.health
fi
echo "$st" > $TMP/kslive.st; cp $TMP/kslive.log outputs/qa-r2/qa3/kslive.log 2>/dev/null
echo "KSLIVE_STATE=$st TMP=$TMP"
