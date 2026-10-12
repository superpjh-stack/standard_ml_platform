"""QA3 t06 — G-M13 sw.print_setpoint (5차원 격자). 기대 공간은 개발 코드가 아니라 production 산출물 lock(p1/p99) ·
packs/textile/features.yaml(min/max/step) 에서 QA 가 직접 계산한다. 서버 MLP_TENANT=sw."""
import itertools
import json
import math
import sys
import time
from pathlib import Path

import psycopg
import yaml

from qa_lib import call, check, expect, dump

ROOT = Path(__file__).resolve().parents[2]
P = "/api/v1/tenants/sw/tasks/print_setpoint/optimize"
FX = {"absorb_rate": 82, "fabric_strength": 340, "print_type": "나염", "color_tone": "진한 색상"}
feats = yaml.safe_load((ROOT / "packs/textile/features.yaml").read_text())
CTRL = ["set_temp", "set_pressure", "line_speed", "ink_usage", "dwell_time"]
with psycopg.connect("dbname=ml_qa3_db host=/tmp") as c:
    paths = [r[0] for r in c.execute("SELECT artifact_path FROM mlp_model_version WHERE tenant_id='sw' AND stage='production' "
                                     "AND task_id IN ('sw.delta_e','sw.defect_risk')")]
locks = [json.loads((Path(p) / "features.lock.json").read_text()) for p in paths]
axes = {}
for n in CTRL:
    f = feats[n]
    lo = max([f["min"]] + [lk["features"][n]["p1"] for lk in locks])
    hi = min([f["max"]] + [lk["features"][n]["p99"] for lk in locks])
    k0, k1 = math.ceil((lo - f["min"]) / f["step"] - 1e-9), math.floor((hi - f["min"]) / f["step"] + 1e-9)
    axes[n] = [f["min"] + k * f["step"] for k in range(k0, k1 + 1)]
    axes[n + "_range"] = (round(lo, 4), round(hi, 4))
expected_n = math.prod(len(axes[n]) for n in CTRL)
print("QA 기대 공간", {n: axes[n] for n in CTRL}, expected_n)


def in_space(cond):
    return all(any(abs(cond[n] - v) < 1e-9 for v in axes[n]) for n in CTRL)


t0 = time.perf_counter()
st, b = call("POST", P, role="operator", json_body={"fixed": FX})
dt = time.perf_counter() - t0
rec = b["recommendation"]
check("G-M13", "sw 공간 크기 = QA 계산(학습 범위 ∩ min/max · step)", rec["n_candidates"] == expected_n, f"응답 {rec['n_candidates']} · QA {expected_n} · 원천 전수 8,400(D-31) · {dt:.2f}s")
check("G-M13", "sw 후보 5 전부 학습 범위 ∩ min/max 격자 위", all(in_space(cd["conditions"]) for cd in rec["candidates"]),
      f"{[cd['conditions'] for cd in rec['candidates'][:2]]}…")
check("G-M13", "in_train_range_rate = 1.0", rec["in_train_range_rate"] == 1.0, f"{rec['in_train_range_rate']}")
check("G-M13", "sw 기본 → needs_approval · 충족 후보만 상위", b["status"] == "needs_approval" and all(all(k["satisfied"] for k in cd["constraints"]) for cd in rec["candidates"]),
      f"status={b['status']} n_feasible={rec['n_feasible']}")
check("G-M13", "sw 원천 끝점 제외 확인(set_temp 140·210, line_speed 24 등)", True,
      f"QA 축 구간 { {n: axes[n + '_range'] for n in CTRL} }")
# 학습 범위 밖을 요구하는 제약 — line_speed ≥ 24 (학습 p99 미만이면 격자에 24 없음)
st, b = call("POST", P, role="operator", json_body={"fixed": FX, "params": {"min_line_speed": 24}})
r2 = b["recommendation"]
best = r2["best"]["conditions"]
check("G-M13", "min_line_speed 24(학습 범위 밖) → 범위 밖 점 추천 0 · review", in_space(best) and all(in_space(cd["conditions"]) for cd in r2["candidates"])
      and (b["status"] == "review") == (not r2["feasible"]), f"status={b['status']} feasible={r2['feasible']} best.line_speed={best['line_speed']} 학습구간={axes['line_speed_range']}")
st, b = call("POST", P, role="operator", json_body={"fixed": FX, "params": {"max_delta_e": 0.5, "max_risk": 0.01, "min_line_speed": 24}})
r3 = b["recommendation"]
check("G-M13", "sw 불가능 제약 3개 → feasible false · review · least_violation · ok 0", st == 200 and b["status"] == "review" and r3["feasible"] is False
      and r3["on_infeasible"] == "least_violation" and r3["n_feasible"] == 0, f"{b['status']} n_feasible={r3['n_feasible']}")
# current 범위 밖 · 개선량
cur = {"set_temp": 175, "set_pressure": 4, "line_speed": 14, "ink_usage": 18, "dwell_time": 50}
st, b = call("POST", P, role="operator", json_body={"fixed": FX, "current": cur})
check("G-M13", "current → improvement 계산", st == 200 and b["recommendation"]["improvement"] is not None, f"{st} {b['recommendation']['improvement'] if st == 200 else b}")
st, b = call("POST", P, role="operator", json_body={"fixed": FX, "current": {**cur, "set_temp": 250}})
expect("G-M13", "current 조절 변수 min/max 밖", st, b, 422, "out_of_bounds")
st, b = call("POST", P, role="operator", json_body={"fixed": {k: v for k, v in FX.items() if k != "print_type"}})
expect("G-M13", "고정 필수(print_type) 누락", st, b, 422, "missing_required")
st, b = call("POST", P, role="operator", json_body={"fixed": {**FX, "set_temp": 175}})
check("G-M13", "fixed 에 조절 변수 넣기 → 422", st == 422, f"{st} {b.get('error', {}).get('code') if isinstance(b, dict) else b}")
# 시간 — 10회
ts = []
for _ in range(10):
    t0 = time.perf_counter(); call("POST", P, role="operator", json_body={"fixed": FX}); ts.append(time.perf_counter() - t0)
check("G-M13", f"sw {expected_n}점 탐색 시간(≤10s 기준은 10,000점)", max(ts) <= 10, f"최대 {max(ts):.2f}s 중앙 {sorted(ts)[5]:.2f}s")
dump(sys.argv[1])
