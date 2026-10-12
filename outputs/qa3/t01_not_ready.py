"""QA3 t01 — production 없음 상태(학습 · candidate 만 있음)에서 503 model_not_ready · 대체 응답 0."""
import sys
from qa_lib import call, check, expect, dump

X = {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39, "cycle_time": 9.5,
     "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}
for task in ("remaining_hours", "failure_24h", "sensor_ood"):
    st, b = call("POST", f"/api/v1/tenants/ks/tasks/{task}/predict", json_body={"inputs": X})
    expect("2.3", f"production 없음 predict ks.{task}", st, b, 503, "model_not_ready",
           extra_ok=not (isinstance(b, dict) and "prediction" in b))
st, b = call("POST", "/api/v1/tenants/ks/tasks/remaining_hours/predict:batch", json_body={"items": [{"inputs": X}]})
expect("2.3", "production 없음 predict:batch", st, b, 503, "model_not_ready")
st, b = call("POST", "/api/v1/tenants/ks/tasks/maintenance_timing/optimize", json_body={"fixed": X})
expect("2.3", "production 없음 optimize(uses 미운영)", st, b, 503, "model_not_ready")
st, b = call("GET", "/api/v1/health", role=None)
check("2.3", "health model_ready 전부 false", st == 200 and all(not t["model_ready"] for t in b["tasks"]), f"{st} {[t['model_ready'] for t in b['tasks']]}")
st, b = call("GET", "/api/v1/tenants/ks/tasks/remaining_hours/overview", role="viewer")
check("2.3", "overview production null", st == 200 and b.get("production") is None, f"{st} production={b.get('production') if isinstance(b, dict) else b}")
dump(sys.argv[1])
