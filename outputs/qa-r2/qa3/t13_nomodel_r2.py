"""QA-R2 — '모델 없는데 값' 새 공격: archived · candidate · 없는 버전 지정, 산출물 폴더 삭제 뒤 optimize(uses), 같은 키 반복."""
import sys, shutil, os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from qa_lib import call, check, expect, code_of, dump
DSN = "dbname=ml_qar2_db host=/tmp"
def db(sql, p=()):
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        cur = c.execute(sql, p); return cur.fetchall() if cur.description else None
X = {"press_force": 245, "vibration": 2.1, "motor_current": 48, "equip_temp": 47, "mold_temp": 39, "cycle_time": 9.5,
     "shot_count": 65000, "machine_code": "PRS-01", "product_type": "FRONT SHELL"}
P = "/api/v1/tenants/ks/tasks/remaining_hours"
vs = {r["version"]: r for r in db("SELECT version, stage, artifact_path FROM mlp_model_version WHERE tenant_id='ks' AND task_id='ks.remaining_hours'")}
for v, r in sorted(vs.items()):
    if r["stage"] in ("archived", "candidate", "rejected"):
        st, b = call("POST", f"{P}/predict", role="admin", json_body={"inputs": X, "model_version": v})
        check("NOMODEL", f"model_version={v}({r['stage']}) → 값 없음", st == 404 and not (isinstance(b, dict) and "prediction" in b), f"HTTP {st} code={code_of(b)}")
        st, b = call("POST", f"{P}/predict:batch", role="admin", json_body={"items": [{"inputs": X, "model_version": v}]})
        item = (b.get("items") or [{}])[0] if isinstance(b, dict) else {}
        check("NOMODEL", f"batch model_version={v}({r['stage']}) → 값 없음", (st == 404) or (st == 200 and "error" in item and item.get("prediction") is None), f"HTTP {st} {str(item)[:120]}")
for v in ("v0", "v999999999999", "V1", "v1 ", "production", "latest"):
    st, b = call("POST", f"{P}/predict", role="admin", json_body={"inputs": X, "model_version": v})
    check("NOMODEL", f"model_version={v!r} → 값 없음", st in (404, 422) and not (isinstance(b, dict) and "prediction" in b), f"HTTP {st} code={code_of(b)}")
# production 산출물 폴더를 치운 뒤 predict · optimize(uses) — 503 이어야
prod = [r for r in vs.values() if r["stage"] == "production"][0]
root = Path(os.environ["MLP_ARTIFACT_DIR"])
p = Path(prod["artifact_path"]); p = p if p.is_absolute() else (Path(__file__).resolve().parents[3] / p)
bak = p.with_name(p.name + ".bak"); shutil.move(str(p), str(bak))
try:
    st, b = call("POST", f"{P}/predict", json_body={"inputs": X})
    expect("NOMODEL", "production 산출물 없음 predict", st, b, 503, "model_artifact_mismatch", extra_ok="prediction" not in (b if isinstance(b, dict) else {}))
    st, b = call("POST", "/api/v1/tenants/ks/tasks/maintenance_timing/optimize", json_body={"fixed": X})
    check("NOMODEL", "production 산출물 없음 optimize(uses) → 503 · 추천 없음", st == 503 and "recommendation" not in (b if isinstance(b, dict) else {}), f"HTTP {st} code={code_of(b)}")
    st, b = call("POST", "/api/maintenance/predict", json_body=X, role="operator")
    check("NOMODEL", "production 산출물 없음 호환 predict → 값 없음", st >= 500 and "remaining_hours" not in (b if isinstance(b, dict) else {}), f"HTTP {st} {str(b)[:150]}")
    st, b = call("GET", "/api/v1/health", role=None)
    t = [x for x in b["tasks"] if x["task"] == "ks.remaining_hours"][0]
    check("NOMODEL", "산출물 없음 health model_ready=false", t["model_ready"] is False, str(t))
finally:
    shutil.move(str(bak), str(p))
st, b = call("POST", f"{P}/predict", json_body={"inputs": X})
check("NOMODEL", "복구 뒤 predict 200", st == 200, f"HTTP {st}")
# 불변식
bad = db("SELECT mv.task_id, mv.version FROM mlp_model_version mv LEFT JOIN mlp_approval a ON a.approval_id = mv.approval_id "
         "WHERE mv.stage='production' AND (a.approval_id IS NULL OR a.state <> 'approved' OR a.ref_id <> mv.version OR a.task_id <> mv.task_id)")
check("INV", "production 전부 = 승인된 같은 버전 승인 행", not bad, str(bad))
dup = db("SELECT detail->>'approval_id' a, count(*) n FROM mlp_audit WHERE action IN ('approval.approved','approval.rejected','approval.expired','recommendation.approved','recommendation.rejected') GROUP BY 1 HAVING count(*) > 1")
check("INV", "승인 결정 감사 중복 0", not dup, str(dup))
pc = db("SELECT tenant_id, task_id, count(*) n FROM mlp_model_version WHERE stage='production' GROUP BY 1,2 HAVING count(*) > 1")
check("INV", "과제당 production ≤ 1", not pc, str(pc))
ls = db("SELECT mv.tenant_id, mv.task_id FROM mlp_model_version mv JOIN mlp_tenant t USING (tenant_id) WHERE mv.stage='production' AND t.mode='live' AND mv.synthetic")
check("INV", "DB 상 live 회사 합성 production 0", not ls, str(ls))
dump(sys.argv[1])
