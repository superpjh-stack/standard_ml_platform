"""QA2 재검증(r2) — 새 치명 사냥 (goal §3.3 · goal2 §3.3). 실서버 8214 · ml_qa2r2_db · scratch 등록부(t05 가 만든 qn4 · qn5).
  A  확정 견적 뒤 회사 단가표 덮어쓰기 변경 + 재기동 → 확정 금액 · CSV 불변 (새 초안만 새 단가)
  A2 수정 사슬 — NUL 500 뒤 다음 수정의 revision 연속 · overrides 유지
  B  합성 production 이 있는 회사를 mode: live 로 바꿔 기동 → 합성 모델로 예측이 나가는가
  C  채움 파일 tasks 덮어쓰기로 approver_role · confirm · line_limits 를 바꿀 수 있는가(make tenant)
결과 → rows_crit_r2.txt"""
import os, re, shutil, subprocess, sys
from pathlib import Path
import yaml
from qa_lib import BASE, KEYS, ROOT, SP, Server, call, check, code_of, dump
from mlcore.db.conn import connect

G = "CRIT"
env = dict(os.environ)

# ── A · A2 (qn5 rollform-quote) ─────────────────────────────────────────────────────────────
reg5 = Path(SP) / "tenreg-qn5"
code = "qn5"


def quote_body(info, doc_id):
    fe = {f["name"]: f for f in info.get("features", [])}
    inputs = {}
    for n in info.get("inputs", []):
        f = fe.get(n)
        if f is None:
            inputs[n] = {"quantity": 1, "labor_rate": 45000, "outsource_cost": 0}.get(n, 1)
        elif f.get("dtype") == "category":
            inputs[n] = (f.get("values") or [None])[0]
        else:
            inputs[n] = f["default"] if f.get("default") is not None else round((float(f["min"]) + float(f["max"])) / 2)
    return {"doc_id": doc_id, "inputs": inputs, "reviewed": True, "review_note": "r2 치명 사냥 검토"}


s = Server(code, tenants_dir=reg5)
try:
    st, tl = call("GET", f"/api/v1/tenants/{code}/tasks", t=code, role="viewer")
    tasks = {x["task"]: x["type"] for x in tl["items"]}
    qt = next(k for k, v in tasks.items() if v == "quote"); ex = next(k for k, v in tasks.items() if v == "extract")
    raw = (ROOT / "packs/rollform-quote/samples/sample.dxf").read_bytes()
    st, doc = call("POST", f"/api/v1/tenants/{code}/tasks/{ex}/documents", t=code, role="operator", files={"file": ("sample.dxf", raw, "application/dxf")})
    st, info = call("GET", f"/api/v1/tenants/{code}/tasks/{qt}", t=code, role="viewer")
    Q = f"/api/v1/tenants/{code}/tasks/{qt}/quotes"
    body = quote_body(info, doc.get("doc_id"))
    st, q = call("POST", Q, t=code, role="operator", json_body={**body, "reviewed": False})
    qid = q["quote_id"]
    # A2: 수정 → NUL 수정(500?) → 수정 — revision 연속 · overrides
    st1, r1 = call("POST", f"{Q}/{qid}/revisions", t=code, role="operator", json_body={**body, "reviewed": False, "review_note": "첫 수정 메모"})
    st2, r2 = call("POST", f"{Q}/{qid}/revisions", t=code, role="operator", json_body={**body, "reviewed": False, "review_note": "NUL a\u0000b 메모"})
    st3, r3 = call("POST", f"{Q}/{qid}/revisions", t=code, role="operator", json_body={**body, "reviewed": False, "review_note": "세 번째 수정"})
    revs = [x.get("revision") if isinstance(x, dict) else None for x in (q, r1, r3)]
    check(G, "A2 수정 사슬: NUL 수정 실패 뒤 revision 연속(1,2,3) · 누락 0", st1 == 201 and st3 == 201 and revs == [1, 2, 3], f"NUL 수정 HTTP {st2} · revisions {revs}")
    st, cr = call("POST", f"{Q}/{qid}/confirm", t=code, role="operator", json_body={"reviewed": True, "review_note": "확정 요청 r2"})
    st, d = call("POST", f"/api/v1/approvals/{cr.get('approval_id')}/decide", t=code, role="approver", json_body={"decision": "approve", "reason": "r2 확정"})
    st, conf = call("GET", f"{Q}/{qid}", t=code, role="operator")
    csv0 = call("GET", f"{Q}/{qid}.csv", t=code, role="operator", raw=True).content
    check(G, "A 확정", conf.get("status") == "confirmed", f"status={conf.get('status')} total={conf.get('total')}")
finally:
    s.close()
qf = reg5 / code / "tasks" / "quote.yaml"
orig = qf.read_text(encoding="utf-8")
y = yaml.safe_load(orig)
y["rates"]["price_kg"] = {k: str(int(v) * 3) for k, v in y["rates"]["price_kg"].items()}
qf.write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
s = Server(code, tenants_dir=reg5)
try:
    st, conf2 = call("GET", f"{Q}/{qid}", t=code, role="operator")
    csv1 = call("GET", f"{Q}/{qid}.csv", t=code, role="operator", raw=True).content
    st, new = call("POST", Q, t=code, role="operator", json_body={**body, "reviewed": False})
    check(G, "A 회사 단가표 ×3 + 재기동 → 확정 금액 · CSV 불변", conf2.get("total") == conf.get("total") and csv1 == csv0,
          f"confirmed {conf.get('total')} → {conf2.get('total')} · csv_same={csv1 == csv0} · 새 초안 {new.get('total') if isinstance(new, dict) else new}")
    check(G, "A 새 초안은 새 단가(변경이 실제로 먹었는지)", isinstance(new, dict) and new.get("total") != conf.get("total"), f"new={new.get('total') if isinstance(new, dict) else st}")
finally:
    s.close()
    qf.write_text(orig, encoding="utf-8")

# ── B (qn4 kimchi — 합성 production 있음) → mode: live ────────────────────────────────────────
reg4 = Path(SP) / "tenreg-qn4"
y4 = reg4 / "qn4.yaml"
orig4 = y4.read_text(encoding="utf-8")
y4.write_text(re.sub(r"^mode: \w+", "mode: live", orig4, flags=re.M), encoding="utf-8")
try:
    try:
        s = Server("qn4", tenants_dir=reg4, log=f"{SP}/server-qn4-live.log")
    except Exception as e:  # noqa: BLE001
        check(G, "B live 전환 → 기동 거부(합성 운영 차단)", True, f"기동 거부: {e} · {open(f'{SP}/server-qn4-live.log').read()[-200:]!r}")
        s = None
    if s:
        try:
            st, hl = call("GET", "/api/v1/health", t="qn4", role=None)
            st, info = call("GET", "/api/v1/tenants/qn4/tasks/qn4.sensory_score", t="qn4", role="viewer")
            X = {f["name"]: (f["default"] if f.get("default") is not None else ((f.get("values") or [None])[0] if f.get("dtype") == "category"
                 else (float(f["min"]) + float(f["max"])) / 2)) for f in info.get("features", [])}
            st, p = call("POST", "/api/v1/tenants/qn4/tasks/qn4.sensory_score/predict", t="qn4", role="operator", json_body={"inputs": X})
            val = (p.get("prediction") or {}).get("value") if isinstance(p, dict) else None
            check(G, "B live 전환 → 합성 production 으로 예측 0", st != 200 or val is None,
                  f"health={[(x['task'], x['model_ready']) for x in hl.get('tasks', [])]} predict HTTP {st} {code_of(p)} value={val}")
        finally:
            s.close()
finally:
    y4.write_text(orig4, encoding="utf-8")

# ── C 채움 파일 tasks 덮어쓰기로 안전 장치 바꾸기 ──────────────────────────────────────────────
kd = yaml.safe_load((ROOT / "tenants/kd.yaml").read_text(encoding="utf-8"))
for label, over in [("approver_role → operator", {"quote": {"approver_role": "operator"}}),
                    ("confirm.requires 비움", {"quote": {"confirm": {"requires": [], "review_note_min": 0, "approver_role": "estimating_lead"}}}),
                    ("line_limits 풀기", {"quote": {"line_limits": {"min_items": 0, "max_items": 100000}}}),
                    ("input_limits 풀기", {"quote": {"input_limits": {"quantity": {"min": -1000, "max": 1e12}}}}),
                    ("rounding 바꾸기", {"quote": {"rounding": "ROUND_DOWN"}}),
                    ("labor_hours out_of_range", {"labor_hours": {"out_of_range": "predict"}})]:
    reg = Path(SP) / "tenreg-c"
    shutil.rmtree(reg, ignore_errors=True); reg.mkdir()
    fp = Path(SP) / "fill-c.yaml"
    fp.write_text(yaml.safe_dump({"categories": kd["categories"], "material_aliases": kd.get("material_aliases") or {}, "tasks": over}, allow_unicode=True), encoding="utf-8")
    r = subprocess.run(["make", "tenant", "NEW=qc1", "PACK=eto", f"CATEGORIES={fp}"], cwd=ROOT, env={**env, "MLP_TENANTS_DIR": str(reg)}, capture_output=True, text=True)
    files = sorted(str(p.relative_to(reg)) for p in reg.rglob("*") if p.is_file())
    msg = (r.stdout + r.stderr).strip().splitlines()
    check(G, f"C 채움 tasks 덮어쓰기 {label} → 거부", r.returncode != 0 and "qc1.yaml" not in files,
          f"rc={r.returncode} files={files} {msg[-2][:180] if len(msg) > 1 else ''}", warn=label in ("rounding 바꾸기", "labor_hours out_of_range"))
dump("rows_crit_r2.txt")
