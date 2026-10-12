#!/bin/sh
# QA2-1 결정성 — 환경 3벌로 determinism_probe.py 를 돌리고 orig 결과를 견준다.
cd "$(dirname "$0")/../../.." && . outputs/qa2-r2/q1/env.sh
PYTHONHASHSEED=0     OMP_NUM_THREADS=1 uv run python outputs/qa2-r2/q1/determinism_probe.py > outputs/qa2-r2/q1/det_a.json 2>/dev/null
PYTHONHASHSEED=12345 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 uv run python outputs/qa2-r2/q1/determinism_probe.py > outputs/qa2-r2/q1/det_b.json 2>/dev/null
PYTHONHASHSEED=7     OMP_NUM_THREADS=1 uv run python outputs/qa2-r2/q1/determinism_probe.py > outputs/qa2-r2/q1/det_c.json 2>/dev/null
uv run python - <<'PY'
import json
a,b,c=[json.load(open(f"outputs/qa2-r2/q1/det_{x}.json")) for x in "abc"]
bad=0
for tid in a:
    o=[d[tid]["orig"] for d in (a,b,c)]
    same=all(x==o[0] for x in o); sh=all(all(d[tid]["shuffled_same"].values()) for d in (a,b,c))
    if not (same and sh): bad+=1
    print(f"{tid:28s} status={o[0]['status']:9s} champ={o[0]['champion']!s:16s} env3_same={same} shuffle_same={sh}" + ("" if sh else f" {a[tid]['shuffled_same']}"))
print("tasks",len(a),"bad",bad)
PY
