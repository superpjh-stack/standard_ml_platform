"""QA2 추론 · 계약 · 보안 사냥 스크립트 (고치지 않는다 — 관찰만).

실행: MLP_TEST_DB_DSN="dbname=ml_qar2_db host=/tmp" OMP_NUM_THREADS=1 uv run python outputs/qa-r2/qa2/probe.py
- 전용 DB ml_qar2_db 만 쓴다(tests/_dev2 가 MLP_DB_DSN 을 MLP_TEST_DB_DSN 으로 맞춘다).
- 회사 ks · sw 사본(임시 코드)을 실제 학습기로 학습 → 승인 → production. 결과는 outputs/qa-r2/qa2/probe-result.json.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
assert "ml_qar2_db" in (os.environ.get("MLP_TEST_DB_DSN") or ""), "MLP_TEST_DB_DSN 은 ml_qar2_db 여야 한다"

import _dev2 as h  # noqa: E402
import jsonschema  # noqa: E402

from mlcore.db.conn import connect  # noqa: E402
from mlcore.registry import artifacts  # noqa: E402

OUT: list[dict] = []
SCHEMA = h.response_schema()
VALID = jsonschema.Draft202012Validator(SCHEMA)


def rec(cid: str, item: str, ok: bool | None, measured, expect: str = ""):
    verdict = "PASS" if ok is True else ("FAIL" if ok is False else "WARN")
    OUT.append({"id": cid, "item": item, "verdict": verdict, "measured": measured, "expect": expect})
    print(f"{cid:8s} {verdict:5s} {item} :: {json.dumps(measured, ensure_ascii=False, default=str)[:400]}")


def schema_errs(body) -> list[str]:
    return [f"{'/'.join(map(str, e.path))}: {e.message[:120]}" for e in VALID.iter_errors(body)]


def post_raw(c, path, raw: str, key):
    return c.post(path, content=raw.encode("utf-8"), headers={**h.hdr(key), "Content-Type": "application/json"})


tmp = Path(tempfile.mkdtemp(prefix="qa2-"))
t0 = time.time()
ks = h.make_tenant("ks", tmp)
sw = h.make_tenant("sw", tmp)
res = {}
for m in (ks, sw):
    with h.use_tenants_dir(m):
        for t, td in m.tasks.items():
            if td.type != "optimize":
                res[t] = h.real_production(m, t)
print("train s", round(time.time() - t0, 1))
K = {ks.tenant.code: h.keys(ks), sw.tenant.code: h.keys(sw)}
KS, SW = ks.tenant.code, sw.tenant.code


def inputs_for(t):
    ref, _ = res[t]
    lock = h.lock_of(ref)
    return h.mid_inputs(lock, lock["order"]), lock


# ══ 1. 계약 — 과제 8 predict · batch · optimize 를 JSON Schema 로 ═══════════════════════════════
def contract_suite(m):
    code = m.tenant.code
    c = h.client(m)
    k = K[code]["operator"]
    for t, td in m.tasks.items():
        short = t.split(".", 1)[1]
        base = f"/api/v1/tenants/{code}/tasks/{short}"
        if td.type == "optimize":
            fixed_names = td.raw.get("fixed") or []
            src = res[f"{code}.{td.raw['uses'][0].split('.', 1)[1]}"][0]
            lock = h.lock_of(src)
            fixed = {n: h.mid_inputs(lock, [n])[n] for n in fixed_names}
            for label, body in (("ok", {"fixed": fixed}),
                                ("infeasible", {"fixed": fixed, "params": {p: (spec["max"] if "min" in p or "reserve" in p else spec["min"])
                                                                            for p, spec in (td.raw.get("params") or {}).items()}})):
                r = c.post(base + "/optimize", json=body, headers=h.hdr(k))
                errs = schema_errs(r.json()) if r.status_code == 200 else ["http " + str(r.status_code) + " " + r.text[:200]]
                b = r.json()
                rec("C-OPT", f"{t} optimize({label}) 18키 · 스키마", not errs and len(b) == 18,
                    {"status": r.status_code, "keys": len(b), "errs": errs[:3], "st": b.get("status"),
                     "feasible": (b.get("recommendation") or {}).get("feasible"),
                     "in_range": (b.get("recommendation") or {}).get("in_train_range_rate")})
            r = c.post(base + "/predict", json={"inputs": {}}, headers=h.hdr(k))
            rec("C-OPT", f"{t} predict 경로 → 404", r.status_code == 404, r.status_code)
            continue
        inp, lock = inputs_for(t)
        cases = {"mid": {"inputs": inp},
                 "explain": {"inputs": inp, "explain": True, "entity_id": "QA2-E1"},
                 "imputed3": {"inputs": {**inp, **{n: None for n in [x for x in lock["order"] if lock["features"][x]["dtype"] != "category"][:3]}}},
                 "oor": {"inputs": {**inp, **{n: (m.pack.features[n]["max"]) for n in [x for x in lock["order"] if lock["features"][x]["dtype"] != "category"][:1]}}}}
        for label, body in cases.items():
            r = c.post(base + "/predict", json=body, headers=h.hdr(k))
            b = r.json()
            errs = schema_errs(b) if r.status_code == 200 else ["http " + str(r.status_code) + " " + r.text[:200]]
            rec("C-PRED", f"{t} predict({label}) 18키 · 유형 null 규칙", not errs and len(b) == 18,
                {"status": r.status_code, "keys": len(b), "errs": errs[:3], "st": b.get("status"),
                 "imputed": b.get("imputed_fields"), "oor": b.get("out_of_range_fields")})
        # batch: 정상 2 + 422 1 (모르는 키) + 범주 밖 1
        cat = next((x for x in lock["order"] if lock["features"][x]["dtype"] == "category"), None)
        items = [{"inputs": inp}, {"inputs": {**inp, "zz_unknown": 1}}, {"inputs": inp, "explain": True},
                 {"inputs": {**inp, cat: "QA2_NOT_A_VALUE"}}]
        r = c.post(base + "/predict:batch", json={"items": items}, headers=h.hdr(k))
        b = r.json()
        bad = [i for i, it in enumerate(b.get("items", [])) if "error" not in it and schema_errs(it)]
        shape = [("error" if "error" in it else "ok") for it in b.get("items", [])]
        rec("C-BATCH", f"{t} batch 순서 · 건별 422 · 스키마", r.status_code == 200 and shape == ["ok", "error", "ok", "error"]
            and not bad and set(b) == {"items", "next_cursor"},
            {"status": r.status_code, "shape": shape, "bad_schema": bad, "keys": sorted(b)})
        # batch 안 NaN 1건 — 계약: 한 건의 422 가 다른 건을 막지 않는다
        raw = json.dumps({"items": [{"inputs": inp}, {"inputs": {**inp, lock['order'][0]: "__NAN__"}}]}).replace('"__NAN__"', "NaN")
        r = post_raw(c, base + "/predict:batch", raw, k)
        rec("C-BATCH-NAN", f"{t} batch 2건 중 1건 NaN → 나머지 1건은 답한다(계약 §5 끝)", r.status_code == 200,
            {"status": r.status_code, "body": r.text[:200]}, "200 + items[1].error invalid_input")
        # batch 501
        r = c.post(base + "/predict:batch", json={"items": [{"inputs": inp}] * 501}, headers=h.hdr(k))
        rec("C-BATCH-501", f"{t} batch 501 → 422 invalid_input", r.status_code == 422 and r.json()["error"]["code"] == "invalid_input",
            r.status_code)
        # rejected 모양(정책 reject) 은 1차 과제에 없음 — 별도 시험 생략(D-07)
    c.__exit__(None, None, None)


contract_suite(ks)
contract_suite(sw)


# ══ 2. 이상 입력 ═══════════════════════════════════════════════════════════════════════════════
def weird_inputs(m, t):
    code = m.tenant.code
    c = h.client(m)
    k = K[code]["operator"]
    base = f"/api/v1/tenants/{code}/tasks/{t.split('.', 1)[1]}/predict"
    inp, lock = inputs_for(t)
    num = [x for x in lock["order"] if lock["features"][x]["dtype"] != "category"]
    ints = [x for x in num if lock["features"][x]["dtype"] == "int"]
    cat = [x for x in lock["order"] if lock["features"][x]["dtype"] == "category"]
    n0 = num[0]
    feats = m.pack.features
    SENT = "QA2SENTINEL"

    def body_with(v_raw: str, field=n0) -> str:
        d = {**inp, field: "__X__"}
        return json.dumps({"inputs": d}).replace('"__X__"', v_raw)

    cases = [
        ("NaN", body_with("NaN"), 422, "invalid_input"),
        ("Infinity", body_with("Infinity"), 422, "invalid_input"),
        ("-Infinity", body_with("-Infinity"), 422, "invalid_input"),
        ("1e400(→inf)", body_with("1e400"), 422, "invalid_input"),
        ("1e308 거대 실수", body_with("1e308"), 422, "out_of_bounds"),
        ("10**30 거대 정수", body_with(str(10 ** 30)), 422, "out_of_bounds"),
        ("10**400 거대 정수(float 넘침)", body_with(str(10 ** 400)), 422, "out_of_bounds"),
        ("5000자리 정수(파서 한도)", body_with("9" * 5000), 422, None),
        ("-0.0", body_with("-0.0"), None, None),
        ("빈 문자열(수치 자리)", body_with('""'), 422, "invalid_input"),
        ("문자열 숫자 \"1\"", body_with('"1"'), 422, "invalid_input"),
        ("true(수치 자리)", body_with("true"), 422, "invalid_input"),
        ("중첩 객체", body_with('{"a": 1}'), 422, "invalid_input"),
        ("배열", body_with("[1,2]"), 422, "invalid_input"),
        ("유니코드 키", json.dumps({"inputs": {**inp, "온도℃‮": 1}}), 422, "invalid_input"),
        ("범주 빈 문자열", json.dumps({"inputs": {**inp, cat[0]: ""}}), 422, "out_of_bounds"),
        ("범주 유니코드 반사", json.dumps({"inputs": {**inp, cat[0]: SENT + "<script>"}}), 422, "out_of_bounds"),
        ("범주 숫자", json.dumps({"inputs": {**inp, cat[0]: 1}}), 422, "invalid_input"),
        ("최상위 모르는 키", json.dumps({"inputs": inp, "x": 1}), 422, "invalid_input"),
        ("inputs 가 배열", json.dumps({"inputs": [1]}), 422, "invalid_input"),
        ("본문이 JSON 아님", "{not json", 422, "invalid_input"),
        ("entity_id 129자", json.dumps({"inputs": inp, "entity_id": "E" * 129}), 422, "invalid_input"),
        ("model_version 형식 위반", json.dumps({"inputs": inp, "model_version": "latest"}), 422, "invalid_input"),
        ("explain 문자열", json.dumps({"inputs": inp, "explain": "yes"}), 422, "invalid_input"),
    ]
    if ints:
        cases.append(("정수 변수에 2.5", body_with("2.5", ints[0]), 422, "invalid_input"))
        cases.append(("정수 변수에 65000.0", body_with(f"{float(int(lock['features'][ints[0]]['fill']))}", ints[0]), 200, None))
    # 중복 키: 마지막 값이 이긴다(파이썬 json) — 앞 값이 거부 대상이어도 통과하는지
    dup = json.dumps({"inputs": inp})[:-2] + f', "{n0}": {json.dumps(inp[n0])}' + "}}"
    dup = dup.replace(f'"{n0}": {json.dumps(inp[n0])}', f'"{n0}": "BAD"', 1)
    cases.append(("중복 키(앞=잘못, 뒤=정상)", dup, None, None))
    for label, raw, want_status, want_code in cases:
        r = post_raw(c, base, raw, k)
        try:
            b = r.json()
        except Exception:  # noqa: BLE001
            b = {"_raw": r.text[:200]}
        code_ = (b.get("error") or {}).get("code") if isinstance(b, dict) else None
        echoed = SENT in r.text or "온도℃" in r.text or "<script>" in r.text
        ok = (want_status is None or r.status_code == want_status) and (want_code is None or code_ == want_code) and not echoed
        if want_status is None:
            ok = None if r.status_code == 200 else ok
        extra = {}
        if r.status_code == 200:
            extra = {"st": b.get("status"), "oor": b.get("out_of_range_fields"), "schema": schema_errs(b)[:2]}
        rec("IN", f"{t} {label}", ok, {"status": r.status_code, "code": code_, "echo": echoed,
                                        "detail": (b.get("error") or {}).get("detail") if isinstance(b, dict) else None, **extra},
            f"{want_status} {want_code or ''}".strip())
    # pydantic 단계에서 dict 키가 detail.field 로 되풀이되는가 (NaN + 임의 키)
    raw = json.dumps({"inputs": {**inp, SENT + "<b>키": "__X__"}}).replace('"__X__"', "NaN")
    r = post_raw(c, base, raw, k)
    rec("IN-ECHO", f"{t} 422 가 임의 입력 키를 되풀이하지 않는다(NaN 값 + 임의 키)", SENT not in r.text,
        {"status": r.status_code, "body": r.text[:300]}, "field 에 임의 문자열 없음 (D-75: 변수 이름 꼴만)")
    raw = json.dumps({"inputs": {**inp, SENT + "키": {"a": 1}}})
    r = post_raw(c, base, raw, k)
    rec("IN-ECHO", f"{t} 422 가 임의 입력 키를 되풀이하지 않는다(중첩 객체 값 + 임의 키)", SENT not in r.text,
        {"status": r.status_code, "body": r.text[:300]})
    # ── max_imputed 경계 ──
    mi = int(m.tasks[t].raw.get("max_imputed", 3))
    opt = [x for x in num if not feats[x].get("required", True)]
    for n_null, want in ((mi, 200), (mi + 1, 422)):
        d = {**inp, **{x: None for x in opt[:n_null]}}
        r = c.post(base, json={"inputs": d}, headers=h.hdr(k))
        b = r.json()
        rec("IMP", f"{t} 결측 {n_null}개(null) / max_imputed {mi}", r.status_code == want and
            (want == 200 and len(b["imputed_fields"]) == n_null or want == 422 and b["error"]["code"] == "missing_required"),
            {"status": r.status_code, "imputed": b.get("imputed_fields"), "err": b.get("error")})
    d = {x: v for x, v in inp.items() if x not in opt[:mi + 1]}   # 키를 아예 빼면
    r = c.post(base, json={"inputs": d}, headers=h.hdr(k))
    rec("IMP", f"{t} 결측 {mi + 1}개(키 생략)", r.status_code == 422 and r.json()["error"]["code"] == "missing_required",
        {"status": r.status_code, "err": r.json().get("error")})
    req = [x for x in lock["order"] if feats[x].get("required", True)]
    if req:
        d = {**inp, req[0]: None}
        r = c.post(base, json={"inputs": d}, headers=h.hdr(k))
        rec("IMP", f"{t} 필수 변수 {req[0]} null → 422 missing_required", r.status_code == 422 and r.json()["error"]["code"] == "missing_required",
            {"status": r.status_code, "err": r.json().get("error")})
    # ── 범위 경계 p1 / p99 정확히 같은 값 ──
    for n in num[:3]:
        lo, hi = lock["features"][n]["p1"], lock["features"][n]["p99"]
        span = hi - lo
        for label, v, want_oor in (("p1", lo, False), ("p99", hi, False),
                                   ("p1-ε", math.nextafter(lo, -math.inf), True), ("p99+ε", math.nextafter(hi, math.inf), True)):
            if feats[n].get("min") is not None and v < feats[n]["min"] or feats[n].get("max") is not None and v > feats[n]["max"]:
                continue
            if lock["features"][n]["dtype"] == "int" and not float(v).is_integer():
                continue
            r = c.post(base, json={"inputs": {**inp, n: v}}, headers=h.hdr(k))
            b = r.json()
            got = n in (b.get("out_of_range_fields") or [])
            rec("RNG", f"{t} {n}={label}({v!r})", r.status_code == 200 and got == want_oor,
                {"status": r.status_code, "oor": got, "st": b.get("status"),
                 "near": [w["field"] for w in b.get("warnings", []) if w["code"] == "near_range"]},
                f"out_of_range={want_oor}")
    # 범주: 허용 목록 안이지만 학습에 안 나온 값 → 200 + out_of_range
    c.__exit__(None, None, None)


weird_inputs(ks, f"{KS}.remaining_hours")
weird_inputs(sw, f"{SW}.delta_e")
weird_inputs(ks, f"{KS}.failure_24h")
weird_inputs(sw, f"{SW}.print_ood")


# ══ 3. 산출물 바꿔치기 · env.lock 위조 · 해시 TOCTOU ═══════════════════════════════════════════════
def artifact_attacks():
    t = f"{KS}.remaining_hours"
    ref, _ = res[t]
    d = artifacts.resolve_dir(ref.artifact_path)
    bak = tmp / "bak"
    shutil.copytree(d, bak)
    c = h.client(ks)
    k = K[KS]["operator"]
    base = f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict"
    inp, _ = inputs_for(t)
    r0 = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    v0 = r0.json()["prediction"]["value"]
    other = artifacts.resolve_dir(res[f"{KS}.failure_24h"][0].artifact_path)

    def restore():
        shutil.rmtree(d)
        shutil.copytree(bak, d)

    def n_pred():
        return h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s", (KS,))

    # (a) model.joblib 를 다른 과제 모델로 바꿔치기
    before = n_pred()
    shutil.copy(other / "model.joblib", d / "model.joblib")
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "model.joblib 바꿔치기 → 503 model_artifact_mismatch · 기록 0", r.status_code == 503 and
        r.json()["error"]["code"] == "model_artifact_mismatch" and n_pred() == before,
        {"status": r.status_code, "body": r.json(), "pred_rows_added": n_pred() - before})
    restore()
    # (b) env.lock 위조(패키지 버전 바꿈) — 파일만
    el = json.loads((d / "env.lock").read_text())
    el["packages"]["numpy"] = "0.0.1"
    (d / "env.lock").write_text(json.dumps(el))
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "env.lock 위조(파일) → 503", r.status_code == 503 and r.json()["error"]["code"] == "model_artifact_mismatch",
        {"status": r.status_code, "detail": r.json()["error"].get("detail")})
    restore()
    # (c) features.lock.json 의 p1/p99 를 넓히는 위조 (범위 판정 우회 시도)
    fl = json.loads((d / "features.lock.json").read_text())
    for it in fl["features"].values():
        if "p1" in it:
            it["p1"], it["p99"] = -1e9, 1e9
    (d / "features.lock.json").write_text(json.dumps(fl))
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "features.lock.json 범위 위조 → 503", r.status_code == 503, {"status": r.status_code})
    restore()
    # (d) 같은 크기 · mtime 복원 · 같은 inode 로 내용만 바꿔치기(제자리 쓰기) — 캐시가 검증된 메모리 모델을 쓰는가
    c.post(base, json={"inputs": inp}, headers=h.hdr(k))   # 캐시 데우기
    p = d / "report.json"
    st = p.stat()
    data = bytearray(p.read_bytes())
    i = data.find(b"0")
    data[i:i + 1] = b"1"
    with open(p, "r+b") as f:
        f.write(bytes(data))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "제자리 바꿔치기(크기 · mtime · inode 같음) — 캐시 적중", None,
        {"status": r.status_code, "note": "캐시는 이미 검증한 메모리 모델로 답한다(디스크 변조본은 읽지 않음). 재기동 뒤에는 해시 재측정"},
        "검증된 모델만 쓴다")
    artifacts._CACHE.clear()
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "제자리 바꿔치기 후 캐시 비움(재기동 모사) → 503", r.status_code == 503, {"status": r.status_code})
    restore()
    artifacts._CACHE.clear()
    # (e) TOCTOU — 해시를 잰 뒤 joblib.load 전에 파일을 바꾸면 검증하지 않은 모델이 적재 · 응답되는가
    real_sha = artifacts.artifact_sha256
    swapped = {"done": False}

    def sha_then_swap(vd):
        out = real_sha(vd)
        if Path(vd).resolve() == d.resolve() and not swapped["done"]:
            shutil.copy(other / "model.joblib", d / "model.joblib")   # 해시 측정 직후 바꿔치기(경합 창 모사)
            swapped["done"] = True
        return out

    artifacts.artifact_sha256 = sha_then_swap
    try:
        r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    finally:
        artifacts.artifact_sha256 = real_sha
    body = r.json()
    rec("ART-TOCTOU", "해시 측정 ↔ joblib.load 사이 바꿔치기 → 검증 안 된 모델로 200 응답", r.status_code != 200,
        {"status": r.status_code, "value_before": v0, "value_after": (body.get("prediction") or {}).get("value"),
         "note": "load_artifacts: artifact_sha256(d) 뒤 joblib.load(d/'model.joblib') 를 다시 연다(같은 바이트 검증 아님)"},
        "해시를 잰 바이트에서 적재하거나 적재 뒤 재검증 → 503")
    r2 = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART-TOCTOU", "바꿔치기 다음 요청", None, {"status": r2.status_code, "code": (r2.json().get("error") or {}).get("code")})
    restore()
    artifacts._CACHE.clear()
    # (f) 산출물 폴더 삭제 → 503 (대체 모델 없음)
    shutil.rmtree(d)
    r = c.post(base, json={"inputs": inp}, headers=h.hdr(k))
    rec("ART", "산출물 폴더 없음 → 503 · 값 없음", r.status_code == 503 and "prediction" not in r.json(), {"status": r.status_code, "body": r.json()})
    shutil.copytree(bak, d)
    artifacts._CACHE.clear()
    c.__exit__(None, None, None)


artifact_attacks()


# ══ 4. 회사 격리 · 역할 ═════════════════════════════════════════════════════════════════════════
def isolation_roles():
    c = h.client(ks)
    kk, sk = K[KS], K[SW]
    inp, _ = inputs_for(f"{KS}.remaining_hours")
    r = c.post(f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict", json={"inputs": inp, "entity_id": "QA2-ISO"}, headers=h.hdr(kk["admin"]))
    prd = r.json()["prediction_id"]
    ref = res[f"{KS}.remaining_hours"][0]
    # 승인 하나 만들기 (staging → promote 요청)
    with h.use_tenants_dir(ks):
        ref2, _ = h.registered(ks, f"{KS}.remaining_hours")
    from mlcore.registry.models import Registry
    Registry().stage(KS, f"{KS}.remaining_hours", ref2.version, actor="qa2")
    aid = Registry().request_promotion(KS, f"{KS}.remaining_hours", ref2.version, actor="qa2", action="promote", reason=None)
    probes = [
        ("GET", f"/api/v1/tenants/{KS}/tasks", None),
        ("GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models", None),
        ("POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict", {"inputs": inp}),
        ("POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict:batch", {"items": [{"inputs": inp}]}),
        ("POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/actuals", {"entity_id": "QA2-ISO", "value": 1.0, "observed_at": "2026-10-12T00:00:00+09:00"}),
        ("GET", f"/api/v1/predictions/{prd}/trace", None),
        ("GET", f"/api/v1/runs/{ref.run_id}", None),
        ("GET", f"/api/v1/tenants/{KS}/approvals", None),
        ("POST", f"/api/v1/approvals/{aid}/decide", {"decision": "reject", "reason": "qa2"}),
        ("POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models/{ref2.version}/promote", {}),
        ("GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/monitor", None),
        ("GET", f"/api/v1/tenants/{KS}/doctor", None),
        ("GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/records", None),
    ]
    a0 = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s", (KS,))
    for meth, path, body in probes:
        r = c.request(meth, path, json=body, headers=h.hdr(sk["admin"]))
        # 없는 것과 같은 답인지 — 같은 경로의 없는 id
        rec("ISO", f"다른 회사(admin) 키 {meth} {path.replace(KS, '<A>').replace(prd, '<prd>').replace(aid, '<apr>').replace(ref.run_id, '<run>')}",
            r.status_code == 404 and r.json().get("error", {}).get("code") == "not_found", {"status": r.status_code, "body": r.text[:120]})
    a1 = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s", (KS,))
    for path_a, path_b in ((f"/api/v1/predictions/{prd}/trace", "/api/v1/predictions/prd_00000000000000000000000000/trace"),
                           (f"/api/v1/runs/{ref.run_id}", "/api/v1/runs/run_0000000000000000"),):
        ra = c.get(path_a, headers=h.hdr(sk["admin"]))
        rb = c.get(path_b, headers=h.hdr(sk["admin"]))
        rec("ISO", f"다른 회사 · 없는 ID 응답 동일 {path_b.split('/')[3]}", ra.status_code == rb.status_code and ra.json() == rb.json(),
            {"other": [ra.status_code, ra.json()], "none": [rb.status_code, rb.json()]})
    ra = c.post(f"/api/v1/approvals/{aid}/decide", json={"decision": "reject"}, headers=h.hdr(sk["admin"]))
    rb = c.post("/api/v1/approvals/apr_0000/decide", json={"decision": "reject"}, headers=h.hdr(sk["admin"]))
    rec("ISO", "다른 회사 · 없는 승인 decide 응답 동일", ra.json() == rb.json() and ra.status_code == rb.status_code == 404,
        {"other": ra.json(), "none": rb.json()})
    rec("AUD", "다른 회사 키의 쓰기 시도(404)가 감사에 남는가", a1 > a0, {"audit_rows_added_tenantA": a1 - a0,
        "sw_rows": h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s AND detail->>'status'='404'", (SW,))},
        "거부된 회사 밖 쓰기 시도 기록(권장)")
    # 역할 표 (goal §6)
    exp = [  # (역할, 메서드, 경로, 본문, 기대 코드 집합)
        ("viewer", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict", {"inputs": inp}, {403}),
        ("viewer", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict:batch", {"items": [{"inputs": inp}]}, {403}),
        ("viewer", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/actuals", {"entity_id": "x", "value": 1, "observed_at": "2026-10-12T00:00:00+09:00"}, {403}),
        ("viewer", "POST", f"/api/v1/tenants/{KS}/tasks/maintenance_timing/optimize", {"fixed": {}}, {403}),
        ("viewer", "GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models", None, {403}),
        ("viewer", "GET", f"/api/v1/tenants/{KS}/approvals", None, {403}),
        ("viewer", "GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/monitor", None, {403}),
        ("viewer", "GET", f"/api/v1/tenants/{KS}/doctor", None, {403}),
        ("viewer", "GET", f"/api/v1/tenants/{KS}/tasks", None, {200}),
        ("viewer", "GET", f"/api/v1/predictions/{prd}/trace", None, {403}),
        ("operator", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/train", {}, {403}),
        ("operator", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models/{ref2.version}/stage", None, {403}),
        ("operator", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models/{ref2.version}/promote", {}, {403}),
        ("operator", "POST", f"/api/v1/approvals/{aid}/decide", {"decision": "approve"}, {403}),
        ("operator", "GET", f"/api/v1/tenants/{KS}/approvals", None, {200}),
        ("operator", "GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models", None, {403}),
        ("operator", "GET", f"/api/v1/predictions/{prd}/trace", None, {403}),
        ("operator", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/predict", {"inputs": inp, "model_version": ref2.version}, {403}),
        ("approver", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/train", {}, {403}),
        ("approver", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models/{ref2.version}/stage", None, {403}),
        ("approver", "GET", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models", None, {200}),
        ("approver", "GET", f"/api/v1/predictions/{prd}/trace", None, {403}),
        ("approver_other", "POST", f"/api/v1/approvals/{aid}/decide", {"decision": "approve"}, {403}),
        ("approver_other", "POST", f"/api/v1/tenants/{KS}/tasks/remaining_hours/models/{ref2.version}/promote", {}, {403}),
        ("admin", "GET", f"/api/v1/predictions/{prd}/trace", None, {200}),
    ]
    for role, meth, path, body, want in exp:
        r = c.request(meth, path, json=body, headers=h.hdr(kk[role]))
        rec("ROLE", f"{role} {meth} {path.replace(KS, '<t>').replace(prd, '<prd>').replace(aid, '<apr>')}", r.status_code in want,
            {"status": r.status_code, "code": (r.json().get("error") or {}).get("code") if r.headers.get("content-type", "").startswith("application/json") else None},
            str(sorted(want)))
    r = c.get(f"/api/v1/tenants/{KS}/approvals", headers=h.hdr(kk["approver_other"]))
    rec("ROLE", "approver(다른 과제 담당)가 승인 목록에서 남의 과제 승인을 본다", None,
        {"status": r.status_code, "n_items": len(r.json().get("items", [])),
         "roles_in_items": sorted({it["approver_role"] for it in r.json().get("items", [])})},
        "goal §6: approver 는 자기 approver_role 과제만 — 목록 필터 여부")
    # approver 가 남의 과제를 decide
    r = c.post(f"/api/v1/approvals/{aid}/decide", json={"decision": "approve"}, headers=h.hdr(kk["approver"]))
    rec("ROLE", "approver(담당) decide approve → 200 · production 교체", r.status_code == 200, {"status": r.status_code, "body": r.json()})
    r = c.post(f"/api/v1/approvals/{aid}/decide", json={"decision": "approve"}, headers=h.hdr(kk["approver"]))
    rec("ROLE", "같은 승인 재결정 → 409 already_decided", r.status_code == 409, {"status": r.status_code})
    # 키 없음 · 틀림 · 폐기
    r = c.get(f"/api/v1/tenants/{KS}/tasks")
    rec("AUTH", "키 없음 → 401", r.status_code == 401, r.status_code)
    r = c.get(f"/api/v1/tenants/{KS}/tasks", headers=h.hdr("mlp_wrong"))
    rec("AUTH", "틀린 키 → 401", r.status_code == 401, r.status_code)
    with connect() as cc:
        cc.execute("UPDATE mlp_api_key SET revoked_at = now() WHERE consumer='test-viewer' AND tenant_id=%s", (KS,))
    r = c.get(f"/api/v1/tenants/{KS}/tasks", headers=h.hdr(kk["viewer"]))
    rec("AUTH", "폐기한 키 → 401", r.status_code == 401, r.status_code)
    # 경로 꼴 우회
    for p in (f"/api/v1/tenants/{SW}/tasks/{KS}.remaining_hours/predict", f"/api/v1//tenants/{KS}/tasks/remaining_hours/predict",
              f"/api/v1/tenants/{KS.upper()}/tasks/remaining_hours/predict", f"/api/v1/tenants/{KS}%2F/tasks/remaining_hours/predict"):
        r = c.post(p, json={"inputs": inp}, headers=h.hdr(sk["admin"]))
        rec("ISO", f"경로 꼴 우회 {p.replace(KS, '<A>').replace(SW, '<B>')}", r.status_code in (404, 401, 403, 405) and "prediction_id" not in r.text,
            {"status": r.status_code})
    c.__exit__(None, None, None)




# ══ 5. 호환 라우터 — 옛 키 · 값 · 감사 ════════════════════════════════════════════════════════════
def compat_checks():
    import yaml
    exp = yaml.safe_load((ROOT / "tests" / "compat_expected.yaml").read_text())
    for m, src in ((ks, "ks"), (sw, "sw")):
        code = m.tenant.code
        e = exp[src]
        c = h.client(m)
        k = K[code]["operator"]
        rec_ = dict(e["default_record"])
        a0 = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s", (code,))
        p0 = h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s AND channel='compat'", (code,))
        r = c.post(e["routes"]["predict"], json=rec_, headers=h.hdr(k))
        b = r.json()
        rec("CMP", f"{src} 옛 predict 키 = 원천 ml_service 반환 키", r.status_code == 200 and list(b) == e["predict_keys"],
            {"status": r.status_code, "got": list(b), "want": e["predict_keys"]})
        a1 = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s", (code,))
        p1 = h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s AND channel='compat'", (code,))
        rec("AUD", f"{src} 호환 POST predict 감사 1행 (예측 {p1 - p0}행 기록)", a1 > a0, {"audit_added": a1 - a0, "pred_added": p1 - p0},
            "쓰기 요청(POST) → mlp_audit 1행 (api-contract · middleware docstring)")
        params = e["optimize_params"]
        r = c.post(e["routes"]["optimize"], json={"record": rec_, **params}, headers=h.hdr(k))
        b = r.json()
        a2 = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s", (code,))
        rec("CMP", f"{src} 옛 optimize 최상위 키", r.status_code == 200 and list(b) == e["optimize_keys"],
            {"status": r.status_code, "got": list(b), "want": e["optimize_keys"]})
        rec("AUD", f"{src} 호환 POST optimize(추천 · 승인 행 생성) 감사", a2 > a1, {"audit_added": a2 - a1})
        if r.status_code == 200:
            rec("CMP", f"{src} 옛 optimize recommendation 행 키 · unmet_constraints 값", None,
                {"rec_keys": list(b["recommendation"]), "unmet": b["unmet_constraints"], "objective": b["objective"]})
        r = c.post(e["routes"]["optimize"], json={"record": rec_, **{**params, **e["optimize_infeasible"]}}, headers=h.hdr(k))
        b = r.json()
        if r.status_code == 200:
            rec("CMP", f"{src} 옛 optimize(불가능) unmet_constraints 값 — 원천은 한국어 문구", None,
                {"feasible": b["feasible"], "unmet": b["unmet_constraints"], "rec_keys": list(b["recommendation"])})
        r = c.get(e["routes"]["overview"], headers=h.hdr(k))
        b = r.json()
        rec("CMP", f"{src} 옛 overview 키(원천 전체 대비)", None, {"status": r.status_code, "got": list(b)})
        r = c.get(e["routes"]["records"] + "?limit=2", headers=h.hdr(k))
        b = r.json()
        rec("CMP", f"{src} 옛 records 키 · total", r.status_code == 200 and list(b) == e["records_keys"] and b["total"] == e["records_total"],
            {"status": r.status_code, "keys": list(b), "total": b.get("total"), "rec0_keys": list((b.get("records") or [{}])[0])})
        # 옛 422 가 입력값을 되풀이하는가
        bad = {**rec_, list(rec_)[0]: "QA2SENTINEL"}
        r = c.post(e["routes"]["predict"], json=bad, headers=h.hdr(k))
        rec("CMP", f"{src} 옛 422 모양 · 입력값 되풀이 0", r.status_code == 422 and "QA2SENTINEL" not in r.text and "detail" in r.json(),
            {"status": r.status_code, "body": r.text[:200]})
        r = c.post(e["routes"]["predict"], content=b'{"' + list(rec_)[0].encode() + b'": NaN}', headers={**h.hdr(k), "Content-Type": "application/json"})
        rec("CMP", f"{src} 옛 경로 NaN → 422", r.status_code == 422, {"status": r.status_code, "body": r.text[:160]})
        # 다른 회사 키
        other = K[SW if code == KS else KS]["admin"]
        r = c.post(e["routes"]["predict"], json=rec_, headers=h.hdr(other))
        rec("CMP", f"{src} 옛 predict 다른 회사 키 → 404", r.status_code == 404, r.status_code)
        r = c.post(e["routes"]["predict"], json=rec_, headers=h.hdr(K[code]["viewer"]))
        rec("CMP", f"{src} 옛 predict viewer → 403", r.status_code in (403, 401), r.status_code)
        c.__exit__(None, None, None)


compat_checks()
isolation_roles()   # 승인으로 production 이 시험용 가짜 모델로 바뀌므로 호환 시험 뒤에 둔다


# ══ 6. mlp_prediction · mlp_audit 변경 시도 ══════════════════════════════════════════════════════
def append_only():
    import psycopg
    dsn = os.environ["MLP_TEST_DB_DSN"]
    for sql in ("UPDATE mlp_prediction SET status='ok' WHERE prediction_id IN (SELECT prediction_id FROM mlp_prediction LIMIT 1)",
                "DELETE FROM mlp_prediction WHERE prediction_id IN (SELECT prediction_id FROM mlp_prediction LIMIT 1)",
                "TRUNCATE mlp_prediction",
                "UPDATE mlp_audit SET actor='x' WHERE audit_id IN (SELECT audit_id FROM mlp_audit LIMIT 1)",
                "DELETE FROM mlp_audit WHERE audit_id IN (SELECT audit_id FROM mlp_audit LIMIT 1)",
                "INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, consumer) VALUES ('%s', 'mlp_plaintextkey', 'mlp_', 'admin', 'qa2')" % KS):
        try:
            with psycopg.connect(dsn) as cc:
                cc.execute(sql)
            rec("APPEND", sql[:60], False, "성공함(거부 안 됨)")
        except psycopg.Error as e:
            rec("APPEND", sql[:60], True, type(e).__name__ + ": " + str(e).splitlines()[0][:100])
    with psycopg.connect(dsn) as cc:
        rows = cc.execute("SELECT key_hash, key_prefix FROM mlp_api_key WHERE tenant_id=%s", (KS,)).fetchall()
    plain = [r for r in rows if not r[0].startswith("sha256$") or len(r[0]) != 71]
    rec("KEY", "API 키 저장 형태 = sha256$<64hex> · 평문 0", not plain, {"n": len(rows), "prefix_len": sorted({len(r[1]) for r in rows}),
                                                               "sample": rows[0][0][:12] + "…"})


append_only()


# ══ 7. CORS (설정 목록만) ══════════════════════════════════════════════════════════════════════
def cors():
    import subprocess
    code = r"""
import os, json
from fastapi.testclient import TestClient
from mlcore.api.main import app
c = TestClient(app)
out = {}
for origin in ("http://localhost:5190", "http://evil.invalid"):
    r = c.options("/api/v1/health", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-API-Key"})
    g = c.get("/api/v1/health", headers={"Origin": origin})
    out[origin] = [r.status_code, r.headers.get("access-control-allow-origin"), g.headers.get("access-control-allow-origin"), r.headers.get("access-control-allow-credentials")]
print(json.dumps(out))
"""
    for setting in ("http://localhost:5190", "*", ""):
        env = {**os.environ, "MLP_CORS_ORIGINS": setting, "MLP_DB_DSN": os.environ["MLP_TEST_DB_DSN"]}
        env.pop("MLP_TENANT", None)
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=ROOT)
        try:
            got = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            got = {"err": p.stderr[-300:]}
        evil = got.get("http://evil.invalid", [None, None, None])
        good = got.get("http://localhost:5190", [None, None, None])
        ok = evil[1] is None and evil[2] is None and (good[1] == "http://localhost:5190" if setting == "http://localhost:5190" else good[1] is None)
        rec("CORS", f"MLP_CORS_ORIGINS={setting or '(빈 값)'}", ok, got)


cors()

Path(__file__).with_name("probe-result.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
print("total", len(OUT), "FAIL", sum(r["verdict"] == "FAIL" for r in OUT), "WARN", sum(r["verdict"] == "WARN" for r in OUT))
