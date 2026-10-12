"""QA2 보조 사냥 — reject 정책 응답 모양 · 모델 없음 503 · model_version · 헤더 · health 노출 (고치지 않는다).

실행: MLP_TEST_DB_DSN="dbname=ml_qar2_db host=/tmp" OMP_NUM_THREADS=1 uv run python outputs/qa-r2/qa2/probe2.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
assert "ml_qar2_db" in (os.environ.get("MLP_TEST_DB_DSN") or "")
import _dev2 as h  # noqa: E402
import jsonschema  # noqa: E402

V = jsonschema.Draft202012Validator(h.response_schema())
OUT = []


def rec(cid, item, ok, measured, expect=""):
    v = "PASS" if ok is True else ("FAIL" if ok is False else "WARN")
    OUT.append({"id": cid, "item": item, "verdict": v, "measured": measured, "expect": expect})
    print(f"{cid:8s} {v:5s} {item} :: {json.dumps(measured, ensure_ascii=False, default=str)[:400]}")


tmp = Path(tempfile.mkdtemp(prefix="qa2b-"))

# 1. 모델 없음 — 과제 8 전부 503 model_not_ready (값 없음), batch · optimize · 호환 포함
for src in ("ks", "sw"):
    m = h.make_tenant(src, tmp)
    k = h.keys(m)
    c = h.client(m)
    code = m.tenant.code
    for t, td in m.tasks.items():
        short = t.split(".", 1)[1]
        feats = h.task_features(m, t)
        if td.type == "optimize":
            fixed = {n: (feats[n].get("values") or [None])[0] if feats[n]["dtype"] == "category" else feats[n]["default"]
                     for n in td.raw.get("fixed") or []}
            r = c.post(f"/api/v1/tenants/{code}/tasks/{short}/optimize", json={"fixed": fixed}, headers=h.hdr(k["operator"]))
        else:
            inp = {n: (f.get("values") or [None])[0] if f["dtype"] == "category" else f["default"] for n, f in feats.items()}
            r = c.post(f"/api/v1/tenants/{code}/tasks/{short}/predict", json={"inputs": inp}, headers=h.hdr(k["operator"]))
            rb = c.post(f"/api/v1/tenants/{code}/tasks/{short}/predict:batch", json={"items": [{"inputs": inp}]}, headers=h.hdr(k["operator"]))
            rec("NOMODEL", f"{src}.{short} batch 모델 없음 → 503", rb.status_code == 503 and "items" not in rb.json(), {"status": rb.status_code, "body": rb.json()})
        b = r.json()
        rec("NOMODEL", f"{src}.{short} ({td.type}) 모델 없음 → 503 model_not_ready · 값 없음", r.status_code == 503 and
            b.get("error", {}).get("code") == "model_not_ready" and "prediction" not in b and "recommendation" not in b, {"status": r.status_code, "body": b})
    r = c.get("/api/v1/health")
    rec("NOMODEL", f"{src} health model_ready 전부 false", r.status_code == 200 and not any(x["model_ready"] for x in r.json()["tasks"]), r.json())
    rec("HEALTH", f"{src} 키 없는 /api/v1/health 가 노출하는 값", None, {"keys": list(r.json()), "tenant": r.json().get("tenant"),
        "task_ids": [x["task"] for x in r.json()["tasks"]]}, "공개 경로 — 회사 코드 · 과제 이름 · 버전 노출 범위 확인")
    croute = [x for x in m.tenant.config["compat"]["routes"] if x.endswith("predict")][0]
    r = c.post(croute, json={}, headers=h.hdr(k["operator"]))
    rec("NOMODEL", f"{src} 호환 predict 모델 없음(빈 본문)", r.status_code in (422, 503), {"status": r.status_code, "body": r.text[:150]})
    c.__exit__(None, None, None)

# 2. reject 정책 응답 모양 (회사 덮어쓰기 out_of_range: reject) — 유형 3
m = h.make_tenant("ks", tmp, overrides={"remaining_hours": {"out_of_range": "reject"}, "failure_24h": {"out_of_range": "reject"},
                                        "sensor_ood": {"out_of_range": "reject"}})
k = h.keys(m)
code = m.tenant.code
res = {}
for t in (f"{code}.remaining_hours", f"{code}.failure_24h"):
    res[t] = h.to_production(m, t)
try:
    with h.use_tenants_dir(m):
        res[f"{code}.sensor_ood"] = h.real_production(m, f"{code}.sensor_ood")
except Exception as e:  # noqa: BLE001
    rec("REJ", "sensor_ood 실제 학습", False, repr(e)[:200])
c = h.client(m)
for t, (ref, rr) in res.items():
    lock = h.lock_of(ref)
    inp = h.mid_inputs(lock, lock["order"])
    n0 = [n for n in lock["order"] if lock["features"][n]["dtype"] != "category"][0]
    f0 = m.pack.features[n0]
    inp[n0] = f0["max"]
    r = c.post(f"/api/v1/tenants/{code}/tasks/{t.split('.', 1)[1]}/predict", json={"inputs": inp}, headers=h.hdr(k["operator"]))
    b = r.json()
    errs = [e.message[:100] for e in V.iter_errors(b)] if r.status_code == 200 else [r.text[:200]]
    val = (b.get("prediction") or {}).get("value") if b.get("prediction") else (b.get("anomaly") or {}).get("score")
    rec("REJ", f"{t.split('.', 1)[1]} reject 정책 · 범위 밖 → 200 rejected · 18키 · 값 null", r.status_code == 200 and b.get("status") == "rejected"
        and not errs and val is None and (b.get("probability") is None), {"status": r.status_code, "st": b.get("status"), "errs": errs[:3],
                                                                       "prediction": b.get("prediction"), "anomaly": b.get("anomaly"), "prob": b.get("probability")})
    pid = b.get("prediction_id")
    if pid:
        rt = c.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k["admin"]))
        rec("REJ", f"{t.split('.', 1)[1]} rejected 도 mlp_prediction 기록 · trace", rt.status_code == 200, {"status": rt.status_code,
            "keys": list(rt.json()) if rt.status_code == 200 else rt.text[:100]})

# 3. model_version 지정
t = f"{code}.remaining_hours"
ref, rr = res[t]
lock = h.lock_of(ref)
inp = h.mid_inputs(lock, lock["order"])
ref2, _ = h.registered(m, t)    # candidate v2
for who, ver, want in (("approver", ref.version, 200), ("approver", ref2.version, 404), ("approver", "v99", 404), ("admin", "v99", 404)):
    r = c.post(f"/api/v1/tenants/{code}/tasks/remaining_hours/predict", json={"inputs": inp, "model_version": ver}, headers=h.hdr(k[who]))
    rec("MVER", f"{who} model_version={ver} ({'candidate' if ver == ref2.version else 'production' if ver == ref.version else '없음'})",
        r.status_code == want, {"status": r.status_code, "code": (r.json().get("error") or {}).get("code")}, str(want))

# 4. X-Request-Id — 길이 · 문자 제한 없이 감사에 저장되는가
for rid in ("a" * 8000, "qa2-<script>-id"):
    r = c.post(f"/api/v1/tenants/{code}/tasks/remaining_hours/predict", json={"inputs": inp}, headers={**h.hdr(k["operator"]), "X-Request-Id": rid})
    got = h.count("SELECT count(*) AS n FROM mlp_audit WHERE request_id = %s", (rid,))
    rec("REQID", f"X-Request-Id 길이 {len(rid)} 그대로 응답 헤더 · 감사 저장", None,
        {"status": r.status_code, "echo_header": r.headers.get("x-request-id") == rid, "audit_rows": got}, "형식 · 길이 제한 권장")

# 5. health 가 산출물 불일치를 model_ready=true 로 보이는가
from mlcore.registry import artifacts  # noqa: E402
d = artifacts.resolve_dir(ref.artifact_path)
(d / "report.json").write_text("{}")
artifacts._CACHE.clear()
r = c.get("/api/v1/health")
mr = {x["task"]: x["model_ready"] for x in r.json()["tasks"]}
rp = c.post(f"/api/v1/tenants/{code}/tasks/remaining_hours/predict", json={"inputs": inp}, headers=h.hdr(k["operator"]))
rec("HEALTH", "산출물 변조 상태에서 health model_ready", None, {"health_model_ready": mr.get(t), "predict": rp.status_code},
    "health 는 DB 만 본다 — 503 인데 ready=true 면 화면 1 이 정상으로 보임")
c.__exit__(None, None, None)
Path(__file__).with_name("probe2-result.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
print("total", len(OUT), "FAIL", sum(r["verdict"] == "FAIL" for r in OUT))
