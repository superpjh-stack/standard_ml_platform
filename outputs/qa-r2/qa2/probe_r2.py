"""QA-R2 (QA2 관점) — TOCTOU 재현(해시를 잰 바이트 뒤 바꿔치기) · 422 필드 위치 회귀 · batch 건별 · 감사 미들웨어(읽기 · 실패) · health 반영
· 새 치명 공격(다른 회사 · 모델 없이 값). 전용 DB ml_qar2_db 만.
실행: source outputs/qa-r2/env.sh && uv run python outputs/qa-r2/qa2/probe_r2.py"""
from __future__ import annotations
import json, os, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
assert "ml_qar2_db" in (os.environ.get("MLP_TEST_DB_DSN") or "")
import _dev2 as h  # noqa: E402
from mlcore.registry import artifacts  # noqa: E402
from mlcore import audit  # noqa: E402
OUT = []
def rec(cid, item, ok, measured):
    v = "PASS" if ok is True else ("FAIL" if ok is False else "WARN")
    OUT.append({"id": cid, "item": item, "verdict": v, "measured": measured})
    print(f"{cid:8s} {v:5s} {item} :: {json.dumps(measured, ensure_ascii=False, default=str)[:420]}")
tmp = Path(tempfile.mkdtemp(prefix="qar2-"))
ks = h.make_tenant("ks", tmp); sw = h.make_tenant("sw", tmp)
res = {}
for m, tasks in ((ks, ["remaining_hours", "failure_24h"]), (sw, ["delta_e"])):
    with h.use_tenants_dir(m):
        for s in tasks:
            res[f"{m.tenant.code}.{s}"] = h.real_production(m, f"{m.tenant.code}.{s}")
KS, SW = ks.tenant.code, sw.tenant.code
K = {KS: h.keys(ks), SW: h.keys(sw)}
c = h.client(ks)
def inp(t):
    lock = h.lock_of(res[t][0]); return h.mid_inputs(lock, lock["order"])
P = f"/api/v1/tenants/{KS}/tasks/remaining_hours"
op = h.hdr(K[KS]["operator"])
base_in = inp(f"{KS}.remaining_hours")
# ── A. TOCTOU: 해시를 잰 바이트를 읽은 직후 파일을 바꿔치기 ────────────────────────────
ref = res[f"{KS}.remaining_hours"][0]
d = artifacts.resolve_dir(ref.artifact_path); bak = tmp / "bak"; shutil.copytree(d, bak)
other = artifacts.resolve_dir(res[f"{KS}.failure_24h"][0].artifact_path)
artifacts._CACHE.clear()
v0 = c.post(f"{P}/predict", json={"inputs": base_in}, headers=op).json()["prediction"]["value"]
artifacts._CACHE.clear()
real = artifacts.bytes_sha256; sw_ = {"n": 0}
def swap_after(blobs):
    out = real(blobs)
    if not sw_["n"]:
        shutil.copy(other / "model.joblib", d / "model.joblib"); sw_["n"] = 1
    return out
artifacts.bytes_sha256 = swap_after
try:
    r = c.post(f"{P}/predict", json={"inputs": base_in}, headers=op)
finally:
    artifacts.bytes_sha256 = real
rec("TOCTOU", "해시 측정(읽은 바이트) 직후 디스크 바꿔치기 → 검증된 바이트로만 응답", r.status_code == 200 and r.json()["prediction"]["value"] == v0,
    {"status": r.status_code, "v0": v0, "v": (r.json().get("prediction") or {}).get("value"), "swapped": sw_["n"]})
r2 = c.post(f"{P}/predict", json={"inputs": base_in}, headers=op)
rec("TOCTOU", "다음 요청(디스크는 바뀐 상태) → 503 mismatch", r2.status_code == 503, {"status": r2.status_code, "code": (r2.json().get("error") or {}).get("code")})
hl = c.get("/api/v1/health").json()
hr = [t for t in hl["tasks"] if t["task"].endswith("remaining_hours")][0]
rec("HEALTH", "변조 상태 health model_ready=false + error", hr["model_ready"] is False and bool(hr.get("error")), hr)
shutil.rmtree(d); shutil.copytree(bak, d); artifacts._CACHE.clear()
hr = [t for t in c.get("/api/v1/health").json()["tasks"] if t["task"].endswith("remaining_hours")][0]
rec("HEALTH", "복구 뒤 health model_ready=true", hr["model_ready"] is True, hr)
# 제자리 같은 크기 · mtime 유지 변조 → 캐시 키(stat) 동일 → 캐시 응답(검증된 메모리)인지
st = os.stat(d / "model.joblib"); b = bytearray((d / "model.joblib").read_bytes()); b[-1] ^= 1
(d / "model.joblib").write_bytes(bytes(b)); os.utime(d / "model.joblib", ns=(st.st_atime_ns, st.st_mtime_ns))
c.post(f"{P}/predict", json={"inputs": base_in}, headers=op)
r = c.post(f"{P}/predict", json={"inputs": base_in}, headers=op)
rec("ART", "제자리 1바이트 변조(mtime · 크기 · inode 유지) → 캐시는 검증된 메모리 모델", r.status_code in (200, 503),
    {"status": r.status_code, "same_value": (r.json().get("prediction") or {}).get("value") == v0})
shutil.rmtree(d); shutil.copytree(bak, d); artifacts._CACHE.clear()
# ── B. 422 필드 위치 규칙 — 정상 오류 위치는 남는가 · 임의 키는 * ─────────────────────────
cases = {
  "변수 값이 리스트": {"inputs": {**base_in, "press_force": [1]}},
  "변수 값이 문자열": {"inputs": {**base_in, "press_force": "abc"}},
  "explain 문자열": {"inputs": base_in, "explain": "yes"},
  "entity_id 숫자": {"inputs": base_in, "entity_id": 5},
  "최상위 모르는 키(<b>x)": {"inputs": base_in, "<b>x": 1},
  "inputs 임의 키 + 객체 값": {"inputs": {**base_in, "ZZ<script>": {"a": 1}}},
  "inputs 가 리스트": {"inputs": [1, 2]},
  "모르는 키 이름 = 계약 필드명(reason)": {"inputs": base_in, "reason": 1},
}
for n, body in cases.items():
    r = c.post(f"{P}/predict", json=body, headers=op)
    raw = r.text
    errs = (r.json().get("error") or {}).get("detail", {})
    echo = any(s in raw for s in ("<b>x", "ZZ<script>", "abc"))
    rec("FIELD", n, r.status_code == 422 and not echo, {"status": r.status_code, "code": (r.json().get("error") or {}).get("code"), "detail": errs})
r = c.post("/api/v1/approvals/apr_x/decide", json={"decision": "maybe"}, headers=h.hdr(K[KS]["admin"]))
rec("FIELD", "decide decision 잘못(정상 위치 'decision' 이 남는가)", r.status_code == 422, {"status": r.status_code, "detail": (r.json().get("error") or {}).get("detail")})
# ── C. batch 건별 ───────────────────────────────────────────────────────────────
items = [{"inputs": base_in}, {"inputs": {**base_in, "press_force": float("nan")}}, {"inputs": {**base_in, "zz": 1}},
         {"inputs": {**base_in, "press_force": 9999}}, {"inputs": [1]}, {"nope": 1}, {"inputs": base_in, "entity_id": "E" * 200}]
raw = json.dumps({"items": items}, allow_nan=True)
r = c.post(f"{P}/predict:batch", content=raw, headers={**op, "Content-Type": "application/json"})
shape = [("ok" if "prediction" in it else (it.get("error") or {}).get("code")) for it in (r.json().get("items") or [])] if r.status_code == 200 else r.json()
rec("BATCH", "7건 혼합(정상 · NaN · 모르는 키 · min/max 밖 · inputs 리스트 · 모르는 최상위 · entity_id 길이) → 건별", r.status_code == 200 and shape[0] == "ok" and len(shape) == 7, shape)
r = c.post(f"{P}/predict:batch", json={"items": []}, headers=op)
rec("BATCH", "빈 items", r.status_code in (200, 422), {"status": r.status_code, "body": r.text[:200]})
r = c.post(f"{P}/predict:batch", json={"items": {"a": 1}}, headers=op)
rec("BATCH", "items 가 객체 → 전체 422", r.status_code == 422, {"status": r.status_code})
# ── D. 감사 미들웨어 ──────────────────────────────────────────────────────────────
def na(t=None):
    return h.count("SELECT count(*) AS n FROM mlp_audit" + (" WHERE tenant_id=%s" if t else ""), (t,) if t else ())
a0 = na()
for path in (f"/api/v1/tenants/{KS}/tasks", f"{P}/models", f"/api/v1/tenants/{KS}/approvals", f"{P}/overview", "/api/v1/health"):
    c.get(path, headers=h.hdr(K[KS]["admin"]))
rec("AUDIT", "읽기(GET 5건) 는 감사하지 않는다", na() == a0, {"added": na() - a0})
a0 = na("-")
c.post(f"{P}/predict", json={"inputs": base_in})
rec("AUDIT", "키 없는 쓰기 401 → tenant '-' anonymous 1행", na("-") == a0 + 1, {"added": na("-") - a0})
a0, b0 = na(KS), na(SW)
r = c.post(f"{P}/predict", json={"inputs": base_in}, headers=h.hdr(K[SW]["operator"]))
rec("AUDIT", "다른 회사 키 쓰기 404 → 키의 회사(sw) 감사 1행 · ks 0", r.status_code == 404 and na(SW) == b0 + 1 and na(KS) == a0,
    {"status": r.status_code, "sw_added": na(SW) - b0, "ks_added": na(KS) - a0})
real_w = audit.write
def boom(**kw): raise RuntimeError("audit down")
audit.write = boom
try:
    n0 = h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (KS,))
    r = c.post(f"{P}/predict", json={"inputs": base_in}, headers=op)
    n1 = h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (KS,))
finally:
    audit.write = real_w
rec("AUDIT", "감사 쓰기 실패 → 응답은 깨지지 않음(200) · 예측 기록됨", r.status_code == 200 and n1 == n0 + 1, {"status": r.status_code, "pred_added": n1 - n0})
rec("AUDIT", "감사 실패 시 쓰기가 감사 없이 성공(관찰)", None, {"note": "middleware 가 audit 실패를 log.error 로만 남김 — 쓰기는 커밋됨"})
# ── E. 새 치명 공격: 다른 회사 예측이 보였다 / 모델 없이 값 ──────────────────────────────
pid = c.post(f"{P}/predict", json={"inputs": base_in, "entity_id": "QA-E1"}, headers=op).json()["prediction_id"]
r = c.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(K[SW]["admin"]))
rec("ISO", "sw admin 으로 ks 예측 trace", r.status_code == 404, {"status": r.status_code})
r = c.post(f"/api/v1/tenants/{SW}/tasks/delta_e/actuals", json={"entity_id": "QA-E1", "value": 1.0, "observed_at": "2026-10-01T00:00:00+09:00"}, headers=h.hdr(K[SW]["operator"]))
tr = c.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(K[KS]["admin"])).json()
rec("ISO", "sw 가 같은 entity_id 로 actuals → ks trace 에 섞이지 않음", not tr.get("actuals"), {"sw_status": r.status_code, "ks_actuals": tr.get("actuals")})
r = c.post(f"/api/v1/tenants/{KS}/tasks/delta_e/predict", json={"inputs": inp(f"{SW}.delta_e")}, headers=op)
rec("ISO", "ks 키로 ks 경로 + sw 과제 이름(delta_e)", r.status_code == 404, {"status": r.status_code})
r = c.post(f"/api/v1/tenants/{KS}/tasks/{SW}.delta_e/predict", json={"inputs": inp(f"{SW}.delta_e")}, headers=op)
rec("ISO", "ks 경로에 과제 칸 = 'sw.delta_e' 전체 id", r.status_code == 404, {"status": r.status_code, "body": r.text[:160]})
apr = c.get(f"/api/v1/tenants/{SW}/approvals", headers=h.hdr(K[SW]["admin"])).json()
r = c.get(f"/api/v1/tenants/{SW}/approvals", headers=h.hdr(K[KS]["admin"]))
rec("ISO", "ks 키로 sw 승인 목록", r.status_code == 404, {"status": r.status_code})
r = c.post(f"{P}/predict", json={"inputs": base_in, "model_version": "v1"}, headers=h.hdr(K[KS]["admin"]))
rec("NOMODEL", "admin model_version=v1(production) → 200", r.status_code == 200, {"status": r.status_code})
# production 을 rollback 으로 archived 만들 수 없으니: 새 후보 v2 승격 뒤 archived v1 지정
with h.use_tenants_dir(ks):
    ref2, _ = h.real_production(ks, f"{KS}.remaining_hours")
r = c.post(f"{P}/predict", json={"inputs": base_in, "model_version": "v1"}, headers=h.hdr(K[KS]["admin"]))
rec("NOMODEL", "admin model_version=v1(archived) → 값 나가지 않음(404)", r.status_code == 404, {"status": r.status_code, "prod": ref2.version, "body": r.text[:160]})
Path(__file__).with_name("probe_r2-result.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
print("total", len(OUT), "FAIL", sum(o["verdict"] == "FAIL" for o in OUT))
