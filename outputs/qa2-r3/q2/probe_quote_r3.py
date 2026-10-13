"""QA2-2 §C 견적 float 경로(런타임) · §D 확정 뒤 금액 변경 · §E input_limits 경계 · §F CSV 수식 주입 · §G 역할 · 회사 범위 · 감사.
고치지 않는다. 결과 → probe_quote_r3-result.json"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from common import ROOT, client, count, h, rec, save

D = Decimal


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def floats_in(v, path="$"):
    out = []
    if type(v).__name__ == "float" or (hasattr(v, "dtype") and "float" in str(getattr(v, "dtype", ""))):
        out.append(path)
    elif isinstance(v, dict):
        for k, x in v.items():
            out += floats_in(x, f"{path}.{k}")
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            out += floats_in(x, f"{path}[{i}]")
    return out


def main():
    base = Path(tempfile.mkdtemp(prefix="qa22-quote-"))
    m = h.make_tenant("kd", base / "a")
    t = m.tenant.code
    import shutil
    tdir = m.tenant.path.parent / t
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "tenants" / "kd" / "compat.py", tdir / "compat.py")       # 옛 경로 플러그인(시험 회사 폴더로 복사)
    shutil.copytree(ROOT / "tenants" / "kd" / "samples", tdir / "samples")
    k = h.keys(m)
    tc = client(m)
    with h.use_tenants_dir(m):
        h.real_production(m, f"{t}.labor_hours")
    mats = m.tenant.config["categories"]["main_material"]
    sample = load("packs/eto/synth/sample_dxf.py", "qa22q_sample").sample_bytes(mats)
    r = tc.post(f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": ("sample.dxf", sample, "application/dxf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    Q = f"/api/v1/tenants/{t}/tasks/{t}.quote"

    def jpost(url, key, body, raw=None):
        return tc.post(url, headers={**h.hdr(k[key] if key in k else key), "Content-Type": "application/json"},
                       content=raw if raw is not None else json.dumps(body, ensure_ascii=False))

    def lines(price="6500"):
        return [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
                 "price_kg": price} for b in doc["bom_rows"]]

    def body(ls=None, **kw):
        inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
                  "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
        inputs.update(kw)
        return {"doc_id": doc["doc_id"], "inputs": inputs, "lines": lines() if ls is None else ls,
                "reviewed": True, "review_note": "QA 검토 견적"}

    def err(r):
        try:
            e = r.json().get("error") or {}
        except ValueError:
            return (r.status_code, None, None)
        return (r.status_code, e.get("code"), (e.get("detail") or {}).get("field") or (e.get("detail") or {}).get("rule"))

    # ── §C float 경로 런타임 — 견적식 · prepare 에 들어가고 나오는 값의 형 ───────────────────────────
    r = jpost(f"{Q}/quotes", "operator", body())
    assert r.status_code == 201, r.text
    from mlcore.serve import quotes as qmod
    seen = {"prepare_in": [], "quote_in": [], "quote_out": [], "prepare_out": []}
    for key, mod in list(qmod._FORMULAS.items()):
        if getattr(mod, "_qa22", False):
            continue
        oq, op = mod.quote, getattr(mod, "prepare", None)

        def wq(inputs, ls, predicted, rates, _oq=oq):
            seen["quote_in"] += floats_in({"inputs": inputs, "lines": ls, "predicted": predicted, "rates": rates})
            res = _oq(inputs, ls, predicted, rates)
            seen["quote_out"] += floats_in(res)
            return res
        mod.quote = wq
        if op:
            def wp(inputs, ls, _op=op):
                seen["prepare_in"] += floats_in({"inputs": inputs, "lines": ls})
                res = _op(inputs, ls)
                seen["prepare_out"] += floats_in(res)
                return res
            mod.prepare = wp
        mod._qa22 = True
    float_body = body(lines("6500.5"), cut_m=24.5, weld_m=18.25, thickness_mm=6.0, complexity=3.0, labor_rate=45000.5,
                      outsource_cost=12345.67)
    r = jpost(f"{Q}/quotes", "operator", float_body)
    q_float = r.json()
    rec("G2-Q01", "런타임: 견적식 · prepare 입출력에 float 0 (JSON 실수 입력)", r.status_code == 201 and not any(seen.values()),
        {"status": r.status_code, "float_paths": {kk: v[:6] for kk, v in seen.items()}})
    # 응답 금액 = 문자열 · 손 계산 일치
    hours = D(q_float["predictions"][0]["value"]).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
    scrap = D(1) + D(m.tasks[f"{t}.quote"].raw["rates"]["scrap_rate"])
    mat = sum((((D(str(b["mass_kg"])) * D(b["quantity"])) * D("6500.5") * scrap * 1).quantize(D(1), rounding=ROUND_HALF_UP)
               for b in doc["bom_rows"]), D(0))
    rec("G2-Q01", "금액 문자열 · 소재비 손 계산(Decimal) 일치", isinstance(q_float["total"], str) and D(q_float["costs"]["material"]) == mat,
        {"total": q_float.get("total"), "material": q_float["costs"]["material"], "hand": str(mat)})
    raw = r.text
    rec("G2-Q01", "응답 원문에 금액이 JSON 숫자로 나가지 않음", f'"total": "{q_float["total"]}"' in raw or f'"total":"{q_float["total"]}"' in raw,
        {"snippet": raw[raw.find('"total"'):raw.find('"total"') + 30]})
    with h.connect() as c:
        row = c.execute("SELECT pg_typeof(total)::text AS t, jsonb_typeof(costs->'material') AS ct, "
                        "jsonb_typeof(lines->0->'amount') AS lt FROM mlp_quote WHERE quote_id=%s", (q_float["quote_id"],)).fetchone()
    rec("G2-Q01", "DB 저장 형(total numeric · 구성 금액 · 품목 금액)", row["t"] == "numeric" and row["ct"] == "string" and row["lt"] == "string", dict(row))

    # 런타임: 옛 경로 POST /api/quotes (kd) — 같은 감시
    for kk in seen:
        seen[kk] = []
    old = {"drawing_id": doc["doc_id"], "product": "반응기", "material": doc["bom_rows"][0]["material"],
           "bom": [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"], "price_kg": 6500.5}
                   for b in doc["bom_rows"]],
           "quantity": 1, "cut_m": 24.5, "weld_m": 18.25, "thickness_mm": 6.0, "complexity": 3.0, "labor_rate": 45000.5,
           "outsource_cost": 12345.67, "reviewed": True, "review_note": "옛 경로 검토"}
    r = tc.post("/api/quotes", headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=json.dumps(old))
    rec("G2-Q01", "런타임: 옛 /api/quotes 견적식 입출력 float 0", r.status_code == 200 and not any(seen.values()),
        {"status": r.status_code, "float_paths": {kk: v[:6] for kk, v in seen.items()}, "body": r.text[:120] if r.status_code != 200 else None})
    if r.status_code == 200:
        o = r.json()
        rec("G2-Q01", "옛 /api/quotes 합계 = 표준 합계(같은 입력)", int(o["total"]) == int(D(q_float["total"])),
            {"old_total": o["total"], "std_total": q_float["total"], "status": o.get("status")})

    # ── §E input_limits · 품목 경계 ───────────────────────────────────────────────────────
    cases = [
        ("quantity 0", body(quantity=0), 422), ("quantity 1", body(quantity=1), 201), ("quantity 1000", body(quantity=1000), 201),
        ("quantity 1001", body(quantity=1001), 422), ("quantity 1.5", body(quantity=1.5), 422), ("quantity -1", body(quantity=-1), 422),
        ("quantity '1'", body(quantity="1"), 422), ("quantity true", body(quantity=True), 422),
        ("labor_rate 0.99", body(labor_rate=0.99), 422), ("labor_rate 1", body(labor_rate=1), 201),
        ("labor_rate 1000000", body(labor_rate=1000000), 201), ("labor_rate 1000000.01", body(labor_rate=1000000.01), 422),
        ("outsource_cost -1", body(outsource_cost=-1), 422), ("outsource_cost 1e9", body(outsource_cost=1000000000), 201),
        ("outsource_cost 1e9+1", body(outsource_cost=1000000001), 422), ("outsource_cost null", body(outsource_cost=None), 422),
        ("cut_m 1e400 (Decimal 유한 · float inf)", None, 422),
        ("품목 단가 price_kg 음수 -6500", body(lines("-6500")), 422), ("품목 단가 price_kg 0", body(lines("0")), 201),
        ("품목 단가 price_kg 1e12", body(lines("1000000000000")), 422),
        ("품목 단가 문자열 'abc'", body(lines("abc")), 422),
        ("품목 수량 0", body([{**ln, "quantity": 0} for ln in lines()]), 422),
        ("품목 수량 -2", body([{**ln, "quantity": -2} for ln in lines()]), 422),
        ("품목 수량 1.5", body([{**ln, "quantity": 1.5} for ln in lines()]), 422),
        ("품목 중량 0", body([{**ln, "mass_kg": 0} for ln in lines()]), 422),
        ("품목 이름 없음", body([{kk: v for kk, v in ln.items() if kk != "name"} for ln in lines()]), 422),
        ("품목 재질 목록 밖", body([{**ln, "material": "UNOBTAINIUM"} for ln in lines()]), 422),
        ("품목 0행", body([]), 422),
        ("품목 201행", body(lines() * 51), 422),
        ("품목 모르는 키", body([{**ln, "discount": "-99999"} for ln in lines()]), 422),
    ]
    for label, b, want in cases:
        if b is None:
            r = jpost(f"{Q}/quotes", "operator", None, raw=json.dumps(body()).replace('"cut_m": 24', '"cut_m": 1e400'))
        else:
            r = jpost(f"{Q}/quotes", "operator", b)
        got = err(r)
        tot = r.json().get("total") if r.status_code == 201 else None
        sev = r.status_code == want
        rec("G2-Q01", f"경계 · {label}", sev, {"status": r.status_code, "code": got[1], "field": got[2], "total": tot}, want)

    # ── §F CSV 수식 주입 ─────────────────────────────────────────────────────────────────
    evil = ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1", "\r=1", " =1+1", "\n=1+1", "  @x", "＝1+1", "=HYPERLINK(\"http://example.invalid\",\"y\")"]
    ls = lines()
    ls2 = [{**ls[i % len(ls)], "name": v} for i, v in enumerate(evil)]
    r = jpost(f"{Q}/quotes", "operator", {**body(ls2), "review_note": " =cmd|' /C calc'!A0"})
    rec("G2-Q01", "수식 꼴 품목 이름 · 메모로 초안", r.status_code == 201, {"status": r.status_code, "err": err(r)})
    qid_evil = r.json().get("quote_id") if r.status_code == 201 else None
    danger = ("=", "+", "-", "@", "\t", "\r")

    def scan(raw: bytes, label: str):
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        cells = [c for row in csv.reader(io.StringIO(raw.decode("utf-8-sig"))) for c in row]
        strict = [c for c in cells if c.startswith(danger)]
        loose = [c for c in cells if c.lstrip().startswith(danger) and not c.startswith("'")]
        rec("G2-Q01", f"CSV {label}: BOM · 시작 문자 위험 칸 0", has_bom and not strict, {"bom": has_bom, "unsafe": strict[:5]})
        rec("G2-Q01", f"CSV {label}: 앞 공백 · 줄바꿈 뒤 위험 칸 (원천 safe_cell 은 lstrip 후 검사)", not loose,
            {"unsafe_after_lstrip": [repr(x) for x in loose[:6]]}, "원천 KyungDong api/main.py:118-120 `s.lstrip().startswith(...)`")
    if qid_evil:
        r = tc.get(f"{Q}/quotes/{qid_evil}.csv", headers=h.hdr(k["operator"]))
        scan(r.content, "표준 B11")
        r = tc.get(f"/api/quotes/{qid_evil}/csv", headers=h.hdr(k["operator"]))
        if r.status_code == 200:
            scan(r.content, "옛 /api/quotes/{id}/csv")
        else:
            rec("G2-Q01", "옛 /api/quotes/{id}/csv", "INFO", {"status": r.status_code})
        r = tc.get("/api/quotes/export/csv", headers=h.hdr(k["operator"]), params={"limit": 100})
        if r.status_code == 200:
            scan(r.content, "옛 /api/quotes/export/csv")
    # 옛 경로로 앞 공백 품목 이름 → 원천은 str_strip_whitespace 로 공백을 지웠다
    old2 = {**old, "bom": [{**old["bom"][0], "name": " =1+1"}] + old["bom"][1:]}
    r = tc.post("/api/quotes", headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=json.dumps(old2))
    if r.status_code == 200:
        r2 = tc.get(f"/api/quotes/{r.json()['id']}/csv", headers=h.hdr(k["operator"]))
        cells = [c for row in csv.reader(io.StringIO(r2.content.decode("utf-8-sig"))) for c in row]
        rec("G2-Q01", "옛 경로 품목 이름 ' =1+1' → CSV 칸", " =1+1" not in cells, {"cells": [repr(c) for c in cells if "=1+1" in c]})

    # ── §D 확정 흐름 · 확정 뒤 금액 변경 시도 ───────────────────────────────────────────────
    r = jpost(f"{Q}/quotes", "operator", body())
    q1 = r.json()
    qid = q1["quote_id"]
    r = jpost(f"{Q}/quotes/{qid}/revisions", "operator", body(lines("7000")))
    rev = r.json()
    rec("G2-Q01", "수정(revision 2) · overrides 누적", r.status_code == 201 and rev["revision"] == 2, {"status": r.status_code, "total": rev.get("total")})
    for role, want in (("viewer", 403),):
        r = jpost(f"{Q}/quotes/{qid}/confirm", role, {"reviewed": True, "review_note": "확정 요청"})
        rec("G2-A01", f"{role} 확정 요청", r.status_code == want, {"status": r.status_code}, want)
    r = jpost(f"{Q}/quotes/{qid}/confirm", "operator", {"reviewed": True})
    rec("G2-Q01", "메모 없는 확정 → 422 missing_required", err(r)[:2] == (422, "missing_required"), {"err": err(r)})
    r = jpost(f"{Q}/quotes/{qid}/confirm", "operator", {"reviewed": True, "review_note": "확정 요청합니다"})
    aid = r.json().get("approval_id")
    rec("G2-Q01", "operator 확정 요청 → 202 pending", r.status_code == 202 and r.json().get("state") == "pending", r.json())
    r = jpost(f"{Q}/quotes/{qid}/revisions", "operator", body(lines("1")))
    rec("G2-Q01", "확정 대기 중 수정 → 409 quote_locked", err(r)[:2] == (409, "quote_locked"), {"err": err(r)})
    for role, want in (("operator", 403), ("approver_other", 403), ("viewer", 403)):
        r = jpost(f"/api/v1/approvals/{aid}/decide", role, {"decision": "approve", "reason": "x"})
        rec("G2-A01", f"견적 확정 결정 · {role}", r.status_code == want, {"status": r.status_code}, want)
    a0 = count("mlp_audit", "tenant_id=%s AND action IN ('quote.confirmed','approval.approved')", (t,))
    r = jpost(f"/api/v1/approvals/{aid}/decide", "approver", {"decision": "approve", "reason": "견적 확정 승인"})
    rec("G2-A01", "견적 확정 결정 · approver(자기 과제)", r.status_code == 200, {"status": r.status_code, "body": r.json()})
    a1 = count("mlp_audit", "tenant_id=%s AND action IN ('quote.confirmed','approval.approved')", (t,))
    rec("감사", "견적 확정 → 감사(quote.confirmed · approval.approved)", a1 - a0 >= 1, {"delta": a1 - a0})
    conf = tc.get(f"{Q}/quotes/{qid}", headers=h.hdr(k["operator"])).json()
    total0, csv0 = conf["total"], tc.get(f"{Q}/quotes/{qid}.csv", headers=h.hdr(k["operator"])).content
    rec("G2-Q01", "확정 상태 · 금액", conf["status"] == "confirmed" and total0 == rev["total"], {"status": conf["status"], "total": total0})
    attempts = {
        "revisions(최초 ID)": jpost(f"{Q}/quotes/{qid}/revisions", "operator", body(lines("1"))),
        "revisions(admin)": jpost(f"{Q}/quotes/{qid}/revisions", "admin", body(lines("1"))),
        "revisions(rev2 ID)": jpost(f"{Q}/quotes/{rev['quote_id']}/revisions", "operator", body(lines("1"))),
        "revisions(확정 행 ID)": jpost(f"{Q}/quotes/{conf['quote_id']}/revisions", "operator", body(lines("1"))),
        "confirm 재요청": jpost(f"{Q}/quotes/{qid}/confirm", "operator", {"reviewed": True, "review_note": "다시 확정"}),
        "decide 재결정": jpost(f"/api/v1/approvals/{aid}/decide", "approver", {"decision": "reject", "reason": "다시"}),
        "PUT 견적": tc.put(f"{Q}/quotes/{qid}", headers=h.hdr(k["admin"]), json={"total": "1"}),
        "PATCH 견적": tc.patch(f"{Q}/quotes/{qid}", headers=h.hdr(k["admin"]), json={"total": "1"}),
        "DELETE 견적": tc.delete(f"{Q}/quotes/{qid}", headers=h.hdr(k["admin"])),
        "옛 POST /api/quotes/{id}": tc.post(f"/api/quotes/{qid}", headers=h.hdr(k["admin"]), json={"total": 1}),
    }
    for label, r in attempts.items():
        ok = r.status_code in (409, 404, 405) and r.status_code != 200 and r.status_code != 201
        rec("G2-Q01", f"확정 뒤 · {label}", ok, {"status": r.status_code, "err": err(r)[1:]})
    # DB 직접(소유자 계정) — 추가만 트리거
    import psycopg
    for sql in ("UPDATE mlp_quote SET total = 1 WHERE quote_id = %s", "DELETE FROM mlp_quote WHERE quote_id = %s"):
        try:
            with h.connect() as c:
                c.execute(sql, (conf["quote_id"],))
            res = "성공(!)"
        except psycopg.Error as e:
            res = type(e).__name__
        rec("G2-Q01", f"DB {sql.split()[0]} mlp_quote(확정 행)", res != "성공(!)", {"result": res})
    # 모델 교체 뒤 금액 불변
    with h.use_tenants_dir(m):
        ref2, _ = h.to_production(m, f"{t}.labor_hours", seed=7)
    conf2 = tc.get(f"{Q}/quotes/{qid}", headers=h.hdr(k["operator"])).json()
    csv1 = tc.get(f"{Q}/quotes/{qid}.csv", headers=h.hdr(k["operator"])).content
    new = jpost(f"{Q}/quotes", "operator", body(lines("7000"))).json()
    rec("G2-Q01", "운영 모델 교체 뒤 확정 금액 · CSV 불변", conf2["total"] == total0 and csv1 == csv0,
        {"total_before": total0, "total_after": conf2["total"], "csv_same": csv1 == csv0, "new_model": ref2.version,
         "new_quote_model": (new.get("model_versions") or [{}])[0].get("version")})
    # 반려 흐름 → draft · 다시 수정 가능
    r = jpost(f"{Q}/quotes", "operator", body())
    q3 = r.json()["quote_id"]
    a3 = jpost(f"{Q}/quotes/{q3}/confirm", "operator", {"reviewed": True, "review_note": "반려 시험"}).json()["approval_id"]
    r = jpost(f"/api/v1/approvals/{a3}/decide", "approver", {"decision": "reject", "reason": "단가 재검토"})
    st = tc.get(f"{Q}/quotes/{q3}", headers=h.hdr(k["operator"])).json()["status"]
    r2 = jpost(f"{Q}/quotes/{q3}/revisions", "operator", body(lines("6600")))
    rec("G2-Q01", "반려 → draft · 수정 201", r.status_code == 200 and st == "draft" and r2.status_code == 201, {"decide": r.status_code, "status": st, "rev": r2.status_code})
    # approver 가 요청하고 같은 approver 가 결정(자기 승인)
    r = jpost(f"{Q}/quotes", "approver", body())
    q4 = r.json()["quote_id"]
    a4 = jpost(f"{Q}/quotes/{q4}/confirm", "approver", {"reviewed": True, "review_note": "자기 요청"}).json()["approval_id"]
    r = jpost(f"/api/v1/approvals/{a4}/decide", "approver", {"decision": "approve", "reason": "자기 승인"})
    rec("G2-A01", "같은 approver 키가 요청 · 결정(자기 승인)", "INFO", {"decide_status": r.status_code},
        "계약에 4안 원칙 없음 — 관찰")

    # ── §G 역할 (goal2 §6 · 견적 · 문서) ──────────────────────────────────────────────────
    exp = {"viewer": (403, 403, 403, 403), "operator": (201, 200, 201, 200), "approver": (201, 200, 201, 200), "admin": (201, 200, 201, 200)}
    for role, (w_up, w_list, w_q, w_ql) in exp.items():
        r1 = tc.post(f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents", headers=h.hdr(k[role]),
                     files={"file": ("s.dxf", sample, "application/dxf")})
        r2 = tc.get(f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents", headers=h.hdr(k[role]))
        r3 = jpost(f"{Q}/quotes", role, body())
        r4 = tc.get(f"{Q}/quotes", headers=h.hdr(k[role]))
        got = (r1.status_code, r2.status_code, r3.status_code, r4.status_code)
        rec("G2-A01", f"역할 {role}: 문서 올림 · 문서 목록 · 견적 생성 · 견적 목록", got == (w_up, w_list, w_q, w_ql), {"got": got}, (w_up, w_list, w_q, w_ql))
    # trace(화면 10) admin 만 · explain 보기 operator
    pid = q_float["predictions"][0]["prediction_id"]
    for role, want, view in (("operator", 403, None), ("approver", 403, None), ("admin", 200, None), ("operator", 200, "explain"),
                             ("viewer", 403, "explain")):
        r = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k[role]), params={"view": view} if view else None)
        rec("G2-A01", f"trace{'?view=explain' if view else ''} · {role}", r.status_code == want, {"status": r.status_code}, want)

    # ── 다른 회사 키 ────────────────────────────────────────────────────────────────────
    m2 = h.make_tenant("kd", base / "b")
    k2 = h.keys(m2)
    t2 = m2.tenant.code
    other = h.hdr(k2["admin"])
    probes = {
        "GET 견적": tc.get(f"{Q}/quotes/{qid}", headers=other),
        "GET 견적 CSV": tc.get(f"{Q}/quotes/{qid}.csv", headers=other),
        "GET 견적 목록": tc.get(f"{Q}/quotes", headers=other),
        "POST 수정": tc.post(f"{Q}/quotes/{q3}/revisions", headers=other, json=body()),
        "POST 확정 요청": tc.post(f"{Q}/quotes/{q3}/confirm", headers=other, json={"reviewed": True, "review_note": "다른 회사"}),
        "POST 결정(남의 승인)": tc.post(f"/api/v1/approvals/{a4}/decide", headers=h.hdr(k2["approver"]), json={"decision": "approve", "reason": "x"}),
        "GET 내 경로로 남의 견적 ID": tc.get(f"/api/v1/tenants/{t2}/tasks/{t2}.quote/quotes/{qid}", headers=other),
        "GET 옛 /api/quotes/{id}": tc.get(f"/api/quotes/{qid}", headers=other),
        "GET 옛 /api/cad/{id}": tc.get(f"/api/cad/{doc['doc_id']}", headers=other),
    }
    for label, r in probes.items():
        rec("G2-A01", f"다른 회사 키 · {label}", r.status_code == 404, {"status": r.status_code}, 404)
    r = tc.post(f"/api/v1/tenants/{t2}/tasks/{t2}.quote/quotes", headers={**other, "Content-Type": "application/json"},
                content=json.dumps(body()))
    rec("G2-A01", "다른 회사 견적 본문에 내 doc_id → 404", r.status_code in (404, 503), {"status": r.status_code, "err": err(r)},
        "404 not_found(doc) — 운영 모델 없으면 503 이 먼저일 수 있다")

    # ── 감사 — 견적 생성 · 수정 · 확정 요청 · 결정 ─────────────────────────────────────────
    with h.connect() as c:
        rows = c.execute("SELECT action, count(*) AS n FROM mlp_audit WHERE tenant_id=%s GROUP BY action ORDER BY action", (t,)).fetchall()
    acts = {r_["action"]: r_["n"] for r_ in rows}
    need = ["POST /api/v1/tenants/{t}/tasks/{task}/quotes", "POST /api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}/revisions",
            "quote.confirm_requested", "quote.confirmed", "quote.rejected", "POST /api/quotes"]
    rec("감사", "견적 감사 행 종류", all(acts.get(a) for a in need), {"actions": acts})
    save("probe_quote_r3-result.json")


if __name__ == "__main__":
    main()
