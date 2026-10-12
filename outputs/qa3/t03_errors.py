"""QA3 t03 — goal §2.3 오류 계약 전수(각 행을 실제 HTTP 요청으로). 서버 = MLP_TENANT=ks · ml_qa3_db.
산출물 바꿔치기는 QA 전용 scratchpad 산출물 폴더에서만 하고 원래대로 되돌린다."""
import json
import shutil
import sys
from pathlib import Path

import psycopg

from qa_lib import call, check, expect, dump

P = "/api/v1/tenants/ks/tasks/remaining_hours"
X = {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39, "cycle_time": 9.5,
     "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}
ECHO = "QA3ECHO_7731"


def no_echo(b) -> bool:
    return ECHO not in json.dumps(b, ensure_ascii=False)


def body(**over):
    d = dict(X)
    d.update(over)
    return {"inputs": d}


# 1) 모르는 키 · NaN · Infinity → 422 invalid_input, 입력 되풀이 없음
st, b = call("POST", f"{P}/predict", json_body={"inputs": {**X, "zz_unknown": ECHO}})
expect("2.3", "모르는 입력 키", st, b, 422, "invalid_input", extra_ok=no_echo(b), extra=f"echo={not no_echo(b)}")
st, b = call("POST", f"{P}/predict", json_body={**body(), ECHO: 1})
expect("2.3", "모르는 최상위 키(이름=반사 문자열)", st, b, 422, "invalid_input", extra_ok=no_echo(b), extra=f"echo={not no_echo(b)}")
raw = json.dumps(body()).replace('"press_force": 245', '"press_force": NaN')
st, b = call("POST", f"{P}/predict", content=raw)
expect("2.3", "NaN", st, b, 422, "invalid_input")
for lit in ("Infinity", "-Infinity", "1e400"):
    raw = json.dumps(body()).replace('"press_force": 245', f'"press_force": {lit}')
    st, b = call("POST", f"{P}/predict", content=raw)
    expect("2.3", f"{lit}", st, b, 422, "invalid_input" if lit != "1e400" else None,
           extra_ok=st == 422, extra="(1e400 은 invalid_input · out_of_bounds 어느 쪽이든 422)" if lit == "1e400" else "")
st, b = call("POST", f"{P}/predict", json_body=body(press_force=ECHO))
expect("2.3", "숫자 자리에 문자열(반사 문자열)", st, b, 422, "invalid_input", extra_ok=no_echo(b), extra=f"echo={not no_echo(b)}")
st, b = call("POST", f"{P}/predict", json_body=body(machine_code=ECHO))
expect("2.3", "범주 목록 밖 값(반사 문자열) → out_of_bounds(D-55)", st, b, 422, "out_of_bounds", extra_ok=no_echo(b), extra=f"echo={not no_echo(b)}")
st, b = call("POST", f"{P}/predict", content='{"inputs": {"press_force": 245,')
expect("2.3", "깨진 JSON", st, b, 422, "invalid_input")
# 2) 필수 누락 · max_imputed 초과
d = dict(X); d.pop("machine_code")
st, b = call("POST", f"{P}/predict", json_body={"inputs": d})
expect("2.3", "필수 변수(machine_code) 누락", st, b, 422, "missing_required")
d = dict(X)
for k in ("press_force", "vibration", "motor_current"):
    d.pop(k)
st, b = call("POST", f"{P}/predict", json_body={"inputs": d})
check("2.3", "선택 변수 3개 누락(= max_imputed 3) → 200 보정", st == 200 and len(b.get("imputed_fields", [])) == 3, f"{st} imputed={b.get('imputed_fields') if isinstance(b, dict) else b}")
d.pop("equip_temp")
st, b = call("POST", f"{P}/predict", json_body={"inputs": d})
expect("2.3", "선택 변수 4개 누락(> max_imputed 3)", st, b, 422, "missing_required")
st, b = call("POST", f"{P}/predict", json_body=body(press_force=None, vibration=None, motor_current=None, equip_temp=None))
expect("2.3", "null 4개(> max_imputed)", st, b, 422, "missing_required")
# 3) min/max 밖
for k, v in (("press_force", 320.0001), ("press_force", 179.9), ("shot_count", 180001), ("vibration", -1)):
    st, b = call("POST", f"{P}/predict", json_body=body(**{k: v}))
    expect("2.3", f"min/max 밖 {k}={v}", st, b, 422, "out_of_bounds", extra_ok=isinstance(b, dict) and b["error"]["detail"].get("field") == k)
st, b = call("POST", f"{P}/predict", json_body=body(press_force=320))
check("2.3", "max 경계값 320 → 422 아님", st == 200, f"{st} status={b.get('status') if isinstance(b, dict) else b}")
# 4) 학습 범위 밖 (검증 범위 안)
st, b = call("POST", f"{P}/predict", json_body=body(press_force=181))
check("2.3", "학습 범위 밖(181 < p1 182.39) → 200 out_of_range + 경고", st == 200 and b["status"] == "out_of_range" and "press_force" in b["out_of_range_fields"]
      and any(w.get("code") == "out_of_range" for w in b["warnings"]) and b["prediction"]["value"] is not None,
      f"{st} status={b.get('status')} oor={b.get('out_of_range_fields')}")
st, b = call("POST", f"{P}/predict", json_body=body())
check("2.3", "학습 범위 안 → status ok/watch", st == 200 and b["status"] in ("ok", "watch", "review"), f"{st} status={b.get('status')} synthetic={b.get('synthetic')}")
check("2.3", "합성 모델 응답 synthetic=true + 경고", b.get("synthetic") is True and any("synthetic" in (w.get("code") or "") for w in b["warnings"]),
      f"synthetic={b.get('synthetic')} warnings={[w.get('code') for w in b['warnings']]}")
pid = b.get("prediction_id")
# batch 501 → 422
st, b = call("POST", f"{P}/predict:batch", json_body={"items": [body()] * 501})
expect("2.3", "batch 501건", st, b, 422, "invalid_input")
st, b = call("POST", f"{P}/predict:batch", json_body={"items": [body(), body(press_force=999)]})
check("2.3", "batch 안 한 건 out_of_bounds", st in (200, 422), f"{st} {str(b)[:160]}", warn=True)
# 5) 역할 · 회사 · 없는 것
st, b = call("POST", f"{P}/predict", role="viewer", json_body=body())
expect("2.3", "viewer predict(역할 밖)", st, b, 403, "forbidden")
st, b = call("POST", f"{P}/predict", role=None, json_body=body())
expect("2.3", "키 없음", st, b, 401, "auth_required")
st, b = call("POST", f"{P}/predict", role=None, headers={"X-API-Key": "mlp_wrong"}, json_body=body())
expect("2.3", "틀린 키", st, b, 401, "auth_required")
st, b = call("POST", f"{P}/predict", tenant="sw", role="admin", json_body=body())
expect("2.3", "다른 회사 키(sw)로 ks predict", st, b, 404, "not_found")
st, b = call("POST", "/api/v1/tenants/ks/tasks/no_such_task/predict", json_body=body())
expect("2.3", "없는 과제", st, b, 404, "not_found")
st, b = call("POST", "/api/v1/tenants/sw/tasks/delta_e/predict", json_body=body())
expect("2.3", "ks 키로 sw 경로", st, b, 404, "not_found")
st, b = call("GET", "/api/v1/predictions/prd_00000000000000000000000000/trace")
expect("2.3", "없는 예측 ID trace", st, b, 404, "not_found")
st, b = call("GET", f"/api/v1/predictions/{pid}/trace", tenant="sw", role="admin")
expect("2.3", "다른 회사 키로 실제 예측 trace", st, b, 404, "not_found")
st, b = call("GET", f"/api/v1/predictions/{pid}/trace", role="approver")
expect("§6", "approver trace(admin 전용)", st, b, 403, "forbidden")
st, b = call("POST", "/api/v1/tenants/ks/tasks/remaining_hours/optimize", json_body={"fixed": X})
expect("2.3", "optimize 아닌 과제에 optimize", st, b, 404, "not_found")
# 6) 2차 경로 501
for m, path, jb in (("GET", "/api/v1/tenants/ks/tasks/remaining_hours/review", None),
                    ("PATCH", "/api/v1/tenants/ks/tasks/remaining_hours/review/x1", {}),
                    ("POST", "/api/v1/tenants/ks/tasks/remaining_hours/documents", {}),
                    ("GET", "/api/v1/tenants/ks/tasks/remaining_hours/documents/d1", None),
                    ("POST", "/api/v1/tenants/ks/tasks/remaining_hours/quotes", {}),
                    ("GET", "/api/v1/tenants/ks/tasks/remaining_hours/quotes", None),
                    ("GET", "/api/v1/tenants/ks/tasks/remaining_hours/quotes/q1.csv", None)):
    st, b = call(m, path, json_body=jb)
    expect("2.3", f"2차 {m} {path.split('/remaining_hours/')[1]}", st, b, 501, "not_implemented")
# 7) 학습 — 소스 실패 · 멱등
st, b = call("POST", f"{P}/train", json_body={"source_role": "train"})
expect("2.3", "소스 실패 train(dataplatform 미연결)", st, b, 503, "source_disconnected")
st, b = call("POST", f"{P}/train", json_body={"source_role": "demo"})
check("2.3", "같은 스냅숏 · 설정 재요청 → 200 + 기존 run_id", st == 200 and b.get("reused") is True and b.get("run_id") == "run_ad500feb6aadbfe8",
      f"{st} {b}")
st, b = call("POST", f"{P}/train", role="approver", json_body={"source_role": "demo"})
expect("§6", "approver train", st, b, 403, "forbidden")
st, b = call("GET", "/api/v1/tenants/ks/doctor", role="operator")
srcs = {s["role"]: s["status"] for s in b.get("sources", [])} if st == 200 else {}
check("2.3", "doctor 200 + 소스별 미연결", st == 200 and srcs.get("train") == "미연결" and srcs.get("demo") == "연결", f"{st} {srcs}")
tg = [s.get("target") for s in b.get("sources", [])]
check("G-M08", "doctor 목표 없음 표기(D-33)", "목표 없음" in tg, f"target={tg}")

# 8) 산출물 해시 불일치 — QA 산출물 폴더에서 report.json 1바이트 바꿈 → 503, 되돌림
with psycopg.connect("dbname=ml_qa3_db host=/tmp") as c:
    ap = c.execute("SELECT artifact_path FROM mlp_model_version WHERE tenant_id='ks' AND task_id='ks.failure_24h' AND stage='production'").fetchone()[0]
rep = Path(ap) / "report.json"
bak = rep.read_bytes()
FP = "/api/v1/tenants/ks/tasks/failure_24h"
st0, _ = call("POST", f"{FP}/predict", json_body=body())
rep.write_bytes(bak + b" ")
try:
    st, b = call("POST", f"{FP}/predict", json_body=body())
    expect("2.3", "산출물 해시 불일치(이미 적재된 모델)", st, b, 503, "model_artifact_mismatch", extra=f"(바꾸기 전 {st0})")
finally:
    rep.write_bytes(bak)
st, b = call("POST", f"{FP}/predict", json_body=body())
check("2.3", "되돌린 뒤 다시 200", st == 200, f"{st}")
el = Path(ap) / "env.lock"
bak2 = el.read_bytes()
e = json.loads(bak2); first = sorted(e)[0]
el.write_text(json.dumps({**e, "numpy": "0.0.1"}))
try:
    st, b = call("POST", f"{FP}/predict", json_body=body())
    expect("2.3", "env.lock 패키지 버전 바꿈", st, b, 503, "model_artifact_mismatch")
finally:
    el.write_bytes(bak2)
dump(sys.argv[1])
