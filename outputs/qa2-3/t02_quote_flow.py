"""견적 흐름 (goal2 §3.3 QA3 · G2-Q01 · §2.1) — 실제 uvicorn(8213) · ml_qa23_db. 사용: t02_quote_flow.py kd|ot
업로드 → 초안(사람 수정 = overrides) → 수정 2회(되돌림 포함) → 확정 요청(422 2종) → 대기 중 수정 409 → 반려 → 초안 복귀 →
재요청 → 만료(QA DB 에서 expires_at 과거로) → 초안 복귀 · 409 → 재요청 → 두 탭 동시 승인 200/409 → 확정 → 재수정 409 ·
재확정 409 → CSV → uses 모델 교체(새 학습 → 승인) → 확정 금액 · CSV 불변. 동시 확정 요청 · 동시 수정도."""
import hashlib, json, subprocess, sys, threading
from pathlib import Path
from qa_lib import Server, call, check, expect, dump, ROOT, code_of
from mlcore.db.conn import connect

t = sys.argv[1]
G = "Q"
CFG = {
    "kd": {"extract": "kd.drawing_regions", "quote": "kd.quote", "uses": "kd.labor_hours",
           "dxf": ROOT / "tenants/kd/samples/KD-demo-reactor.dxf"},
    "ot": {"extract": "ot.cad_objects", "quote": "ot.quote", "uses": "ot.machining_minutes",
           "dxf": ROOT / "packs/rollform-quote/samples/sample.dxf"},
}[t]
Q = f"/api/v1/tenants/{t}/tasks/{CFG['quote']}/quotes"


def body_for(doc, change=0):
    if t == "kd":
        lines = [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"], "price_kg": "6500"}
                 for b in doc["bom_rows"]]
        if change:
            lines[0]["quantity"] = int(lines[0]["quantity"]) + change          # 사람 수정 (인식 BOM ≠ 확정 BOM)
        inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
                  "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
        return {"doc_id": doc["doc_id"], "inputs": inputs, "lines": lines}
    rec_h = doc["counts"].get("hole", 0)
    inputs = {"part_length_mm": 1200, "blank_width_mm": 160, "sheet_thickness_mm": 2, "hole_count": rec_h + change,
              "slot_count": doc["counts"].get("slot", 0), "bend_count": 2, "steel_grade": "SPCC", "section_profile": "잔넬", "quantity": 100}
    return {"doc_id": doc["doc_id"], "inputs": inputs}


def money_snapshot(q):
    return {k: q[k] for k in ("total", "costs", "lines", "predictions", "model_versions", "rates", "inputs", "overrides")}


def para(fns):
    out = [None] * len(fns); bar = threading.Barrier(len(fns))
    def run(i, f):
        bar.wait(); out[i] = f()
    th = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [x.start() for x in th]; [x.join() for x in th]
    return out


s = Server(t)
try:
    raw = CFG["dxf"].read_bytes()
    st, doc = call("POST", f"/api/v1/tenants/{t}/tasks/{CFG['extract']}/documents", t=t, role="operator",
                   files={"file": (CFG["dxf"].name, raw, "application/dxf")})
    check(G, f"{t} 도면 업로드 201", st == 201, f"HTTP {st} labels={doc.get('labels')} metrics={doc.get('metrics')} regions={len(doc.get('regions', []))} bom={len(doc.get('bom_rows', []))} objects={len(doc.get('objects', []))} counts={doc.get('counts')}")
    check(G, f"{t} 라벨 없음 → labels none · metrics null", doc.get("labels") == "none" and doc.get("metrics") is None, f"labels={doc.get('labels')} metrics={doc.get('metrics')}")
    st, d2 = call("GET", f"/api/v1/tenants/{t}/tasks/{CFG['extract']}/documents/{doc['doc_id']}", t=t, role="operator")
    check(G, f"{t} 문서 재조회 같은 인식값", st == 200 and d2.get("raw_sha256") == doc["raw_sha256"] and d2.get("bom_rows") == doc.get("bom_rows") and d2.get("counts") == doc.get("counts"), f"HTTP {st}")

    # 1. 초안 — 사람 수정 1칸
    b = body_for(doc, change=1)
    st, q1 = call("POST", Q, t=t, role="operator", json_body={**b, "reviewed": False})
    check(G, f"{t} 초안 201 draft rev1", st == 201 and q1.get("status") == "draft" and q1.get("revision") == 1, f"HTTP {st} {str(q1)[:160] if st != 201 else ''} total={q1.get('total')} ov={len(q1.get('overrides', []))}")
    qid = q1["quote_id"]
    check(G, f"{t} 금액 = 원 단위 문자열", isinstance(q1["total"], str) and q1["total"].isdigit() and all(isinstance(v, str) for v in q1["costs"].values()), f"total={q1['total']!r} costs={q1['costs']}")
    check(G, f"{t} 사람 수정 → overrides 1+", len(q1["overrides"]) >= 1, json.dumps(q1["overrides"], ensure_ascii=False)[:200])
    ov1 = q1["overrides"]
    # 2. 수정 — 다른 값
    b2 = body_for(doc, change=2)
    st, q2 = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b2, "reviewed": False})
    check(G, f"{t} 수정 201 rev2", st == 201 and q2.get("revision") == 2 and q2.get("status") == "draft", f"HTTP {st} ov={len(q2.get('overrides', []))} total={q2.get('total')}")
    check(G, f"{t} 수정 뒤 이전 overrides 유지(누적)", all(x in q2["overrides"] for x in ov1) and len(q2["overrides"]) > len(ov1), f"{len(ov1)} → {len(q2['overrides'])}")
    # 3. 수정 — 인식값으로 되돌림 (그래도 이력은 남아야)
    b3 = body_for(doc, change=0)
    st, q3 = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b3, "reviewed": False})
    check(G, f"{t} 인식값으로 되돌린 수정 뒤에도 overrides 이력 유지", st == 201 and all(x in q3["overrides"] for x in q2["overrides"]), f"HTTP {st} rev={q3.get('revision')} ov={len(q3.get('overrides', []))}")
    # 다시 사람 수정
    st, q4 = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b2, "reviewed": False})
    st_g, g = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 처음 quote_id 로 조회 = 최신 revision", st_g == 200 and g["revision"] == q4["revision"] == 4, f"HTTP {st_g} rev={g.get('revision')}")
    # 4. 확정 요청 오류
    st, e = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"review_note": "검토 완료했습니다"})
    expect(G, f"{t} 확정 요청 reviewed 없음", st, e, 422, "missing_required", (e.get("error", {}).get("detail") or {}).get("field") == "reviewed", f"field={(e.get('error', {}).get('detail') or {}).get('field')}")
    st, e = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": " ab  "})
    expect(G, f"{t} 확정 요청 메모 < 5자", st, e, 422, "missing_required", (e.get("error", {}).get("detail") or {}).get("field") == "review_note")
    st, e = call("POST", f"{Q}/{qid}/confirm", t=t, role="viewer", json_body={"reviewed": True, "review_note": "검토 완료했습니다"})
    expect(G, f"{t} viewer 확정 요청", st, e, 403, "forbidden")
    # 5. 확정 요청 → 대기
    st, a1 = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "BOM 수량 확인 완료"})
    check(G, f"{t} 확정 요청 202 pending", st == 202 and a1.get("state") == "pending", f"HTTP {st} {a1}")
    st, g = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 상태 pending_confirm", g.get("status") == "pending_confirm" and g.get("approval_id") == a1.get("approval_id"), f"status={g.get('status')}")
    st, e = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b2})
    expect(G, f"{t} 확정 대기 중 수정", st, e, 409, "quote_locked")
    st, e = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "BOM 수량 확인 완료"})
    expect(G, f"{t} 확정 대기 중 재확정 요청", st, e, 409, "quote_locked")
    st, e = call("POST", f"/api/v1/approvals/{a1['approval_id']}/decide", t=t, role="operator", json_body={"decision": "approve", "reason": "x"})
    expect(G, f"{t} operator 확정 결정(✕ — D2-04)", st, e, 403, "forbidden")
    st, e = call("POST", f"/api/v1/approvals/{a1['approval_id']}/decide", t=t, role="approver_other", json_body={"decision": "approve", "reason": "x"})
    expect(G, f"{t} 다른 과제 담당 approver 결정", st, e, 403, "forbidden")
    # 6. 반려 → 초안 복귀
    st, d = call("POST", f"/api/v1/approvals/{a1['approval_id']}/decide", t=t, role="approver", json_body={"decision": "reject", "reason": "단가 재확인 필요"})
    check(G, f"{t} 반려 200", st == 200 and d.get("state") == "rejected", f"HTTP {st} {d}")
    st, g = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 반려 뒤 초안 복귀 · overrides 유지", g.get("status") == "draft" and all(x in g["overrides"] for x in q4["overrides"]) and g.get("total") == q4["total"], f"status={g.get('status')} reviewed={g.get('reviewed')} ov={len(g['overrides'])} total={g.get('total')}")
    st, e = call("POST", f"/api/v1/approvals/{a1['approval_id']}/decide", t=t, role="approver", json_body={"decision": "approve", "reason": "재결정"})
    expect(G, f"{t} 반려된 확정 재결정", st, e, 409, "already_decided")
    st, q5 = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b2, "reviewed": False})
    check(G, f"{t} 반려 뒤 다시 고칠 수 있음", st == 201 and q5.get("status") == "draft", f"HTTP {st} rev={q5.get('revision')}")
    # 7. 만료 → 초안 복귀
    st, a2 = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "단가 재확인 완료"})
    with connect() as c:
        c.execute("UPDATE mlp_approval SET expires_at = now() - interval '1 minute' WHERE approval_id = %s", (a2["approval_id"],))
    st, lst = call("GET", f"/api/v1/tenants/{t}/approvals?state=expired", t=t, role="approver")
    ids = [x.get("approval_id") for x in lst.get("items", [])] if isinstance(lst, dict) else []
    check(G, f"{t} 만료 승인 = state expired 목록", a2["approval_id"] in ids, f"HTTP {st} n={len(ids)}")
    st, g = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 만료 뒤 초안 복귀 · overrides 유지", g.get("status") == "draft" and all(x in g["overrides"] for x in q4["overrides"]), f"status={g.get('status')} ov={len(g['overrides'])}")
    st, e = call("POST", f"/api/v1/approvals/{a2['approval_id']}/decide", t=t, role="approver", json_body={"decision": "approve", "reason": "만료 뒤"})
    expect(G, f"{t} 만료된 확정 결정", st, e, 409, "already_decided")
    # 8. 재요청 → 두 탭 동시 승인
    st, a3 = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "최종 검토 완료함"})
    check(G, f"{t} 만료 뒤 재요청 → 새 승인 ID", st == 202 and a3["approval_id"] not in (a1["approval_id"], a2["approval_id"]), f"HTTP {st}")
    st, pend = call("GET", f"{Q}/{qid}", t=t, role="operator")
    before_money = money_snapshot(pend)
    res = para([lambda: call("POST", f"/api/v1/approvals/{a3['approval_id']}/decide", t=t, role="approver", json_body={"decision": "approve", "reason": "탭 A"}),
                lambda: call("POST", f"/api/v1/approvals/{a3['approval_id']}/decide", t=t, role="admin", json_body={"decision": "approve", "reason": "탭 B"})])
    codes = sorted(r[0] for r in res)
    check(G, f"{t} 두 탭 동시 확정 → 200 1 · 409 1", codes == [200, 409] and any(code_of(r[1]) == "already_decided" for r in res), f"codes={codes}")
    with connect() as c:
        n_conf = c.execute("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id=%s AND status='confirmed' AND approval_id=%s", (t, a3["approval_id"])).fetchone()["n"]
        n_aud = c.execute("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id=%s AND action='quote.confirmed' AND detail::text LIKE %s", (t, f"%{a3['approval_id']}%")).fetchone()["n"]
    check(G, f"{t} confirmed 행 1 · 감사 1", n_conf == 1 and n_aud == 1, f"confirmed rows={n_conf} audit={n_aud}")
    st, qc = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 확정 · 확정자 · 시각", qc.get("status") == "confirmed" and qc.get("confirmed_by") and qc.get("confirmed_at") and qc.get("reviewed") is True, f"status={qc.get('status')} by={qc.get('confirmed_by')}")
    check(G, f"{t} 확정 금액 = 확정 요청 때 금액", money_snapshot(qc) == before_money, f"total {before_money['total']} → {qc['total']}")
    check(G, f"{t} 확정 뒤 overrides 유지", all(x in qc["overrides"] for x in q4["overrides"]), f"ov={len(qc['overrides'])}")
    st, e = call("POST", f"{Q}/{qid}/revisions", t=t, role="operator", json_body={**b2})
    expect(G, f"{t} 확정 견적 재수정", st, e, 409, "quote_locked")
    st, e = call("POST", f"{Q}/{qid}/revisions", t=t, role="admin", json_body={**b2})
    expect(G, f"{t} 확정 견적 재수정(admin)", st, e, 409, "quote_locked")
    st, e = call("POST", f"{Q}/{qid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "다시 확정 요청"})
    expect(G, f"{t} 확정 견적 재확정", st, e, 409, "quote_locked")
    for old in (q1["quote_id"], q2["quote_id"]):
        st, e = call("POST", f"{Q}/{old}/revisions", t=t, role="operator", json_body={**b2})
        expect(G, f"{t} 옛 revision ID 로 재수정(우회)", st, e, 409, "quote_locked")
    r = call("GET", f"{Q}/{qid}.csv", t=t, role="operator", raw=True)
    csv1 = r.content
    check(G, f"{t} CSV 200 · BOM · 합계", r.status_code == 200 and csv1.startswith(b"\xef\xbb\xbf") and qc["total"].encode() in csv1, f"HTTP {r.status_code} bytes={len(csv1)} sha={hashlib.sha256(csv1).hexdigest()[:12]}")
    # 9. 모델 교체 → 확정 금액 불변
    st, b0 = call("POST", f"/api/v1/tenants/{t}/tasks/{CFG['uses']}/train", t=t, json_body={"source_role": "demo", "seed": 777})
    subprocess.run([sys.executable, "-m", "mlcore.train.jobs", "--pending"], cwd=ROOT, capture_output=True)
    st, run = call("GET", f"/api/v1/runs/{b0['run_id']}", t=t)
    ver = run.get("version")
    call("POST", f"/api/v1/tenants/{t}/tasks/{CFG['uses']}/models/{ver}/stage", t=t)
    st, pr = call("POST", f"/api/v1/tenants/{t}/tasks/{CFG['uses']}/models/{ver}/promote", t=t, role="approver", json_body={"reason": "교체"})
    st, dd = call("POST", f"/api/v1/approvals/{pr['approval_id']}/decide", t=t, role="approver", json_body={"decision": "approve", "reason": "교체 승인"})
    check(G, f"{t} uses 모델 교체 → production {ver}", st == 200 and dd.get("production_version") == ver and ver != "v1", f"HTTP {st} {dd}")
    st, qa = call("GET", f"{Q}/{qid}", t=t, role="operator")
    check(G, f"{t} 모델 교체 뒤 확정 견적 금액 · 예측 · 모델 버전 불변", money_snapshot(qa) == money_snapshot(qc) and qa.get("status") == "confirmed", f"total {qc['total']} → {qa['total']} versions={qa['model_versions']}")
    csv2 = call("GET", f"{Q}/{qid}.csv", t=t, role="operator", raw=True).content
    check(G, f"{t} 모델 교체 뒤 CSV 바이트 동일", csv1 == csv2, f"{hashlib.sha256(csv2).hexdigest()[:12]}")
    st, lst = call("GET", f"{Q}?limit=100", t=t, role="operator")
    row = [x for x in lst.get("items", []) if x.get("total") and x.get("status") == "confirmed"]
    check(G, f"{t} 목록의 확정 견적 금액 불변", any(x["total"] == qc["total"] for x in row), f"confirmed in list={len(row)}")
    st, qn = call("POST", Q, t=t, role="operator", json_body={**b2, "reviewed": False})
    check(G, f"{t} 새 초안은 새 모델 버전 사용", st == 201 and any(mv.get("version") == ver for mv in qn.get("model_versions", [])), f"HTTP {st} versions={qn.get('model_versions')} total={qn.get('total')} (확정 {qc['total']})")
    # 10. 같은 초안에 동시 확정 요청 · 동시 수정
    nid = qn["quote_id"]
    res = para([lambda: call("POST", f"{Q}/{nid}/confirm", t=t, role="operator", json_body={"reviewed": True, "review_note": "동시 요청 탭 A"}),
                lambda: call("POST", f"{Q}/{nid}/confirm", t=t, role="admin", json_body={"reviewed": True, "review_note": "동시 요청 탭 B"})])
    codes = sorted(r[0] for r in res)
    with connect() as c:
        n_pend = c.execute("SELECT count(*) AS n FROM mlp_approval a WHERE tenant_id=%s AND kind='quote' AND state='pending' AND evidence->>'quote_id' IN "
                           "(WITH RECURSIVE s AS (SELECT quote_id FROM mlp_quote WHERE quote_id=%s UNION ALL SELECT q.quote_id FROM mlp_quote q JOIN s ON q.supersedes=s.quote_id) SELECT quote_id FROM s)", (t, nid)).fetchone()["n"]
    check(G, f"{t} 동시 확정 요청 → 202 1 · 409 1 · 대기 승인 1", codes == [202, 409] and n_pend == 1, f"codes={codes} pending approvals={n_pend}")
    st, qn2 = call("POST", Q, t=t, role="operator", json_body={**b2, "reviewed": False})
    n2 = qn2["quote_id"]
    res = para([lambda: call("POST", f"{Q}/{n2}/revisions", t=t, role="operator", json_body={**body_for(doc, 3), "reviewed": False}),
                lambda: call("POST", f"{Q}/{n2}/revisions", t=t, role="admin", json_body={**body_for(doc, 4), "reviewed": False})])
    codes = sorted(r[0] for r in res)
    st, g = call("GET", f"{Q}/{n2}", t=t, role="operator")
    with connect() as c:
        revs = [r["revision"] for r in c.execute("WITH RECURSIVE s AS (SELECT * FROM mlp_quote WHERE quote_id=%s UNION ALL SELECT q.* FROM mlp_quote q JOIN s ON q.supersedes=s.quote_id) SELECT revision FROM s ORDER BY 1", (n2,)).fetchall()]
    check(G, f"{t} 동시 수정 → 사슬 분기 없음 · revision 중복 0", len(revs) == len(set(revs)) and codes in ([201, 409], [201, 201]), f"codes={codes} revisions={revs}")
    # 11. §2.1 문서 오류
    E = f"/api/v1/tenants/{t}/tasks/{CFG['extract']}/documents"
    st, e = call("POST", E, t=t, role="operator", files={"file": ("x.dxf", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "application/dxf")})
    expect("2.1", f"{t} DXF 아님(PNG 바이트)", st, e, 422, "invalid_document", extra=f"rule={(e.get('error', {}).get('detail') or {}).get('rule') if isinstance(e, dict) else e}")
    st, e = call("POST", E, t=t, role="operator", files={"file": ("x.pdf", raw, "application/pdf")})
    expect("2.1", f"{t} 확장자 아님(.pdf)", st, e, 422, "invalid_document")
    st, e = call("POST", E, t=t, role="operator", files={"file": ("x.dxf", raw[: len(raw) // 2], "application/dxf")})
    expect("2.1", f"{t} 깨진 DXF(절반)", st, e, 422, "invalid_document", extra=f"rule={(e.get('error', {}).get('detail') or {}).get('rule') if isinstance(e, dict) else ''}")
    st, e = call("POST", E, t=t, role="operator", files={"file": ("x.dxf", b"AC1018 binary\x00\x01", "application/dxf")})
    expect("2.1", f"{t} 바이너리/잡음 DXF", st, e, 422, "invalid_document")
    big = b"999\n" + b"x" * (5 * 1024 * 1024 + 10) + b"\n0\nEOF\n"
    st, e = call("POST", E, t=t, role="operator", files={"file": ("big.dxf", big, "application/dxf")})
    expect("2.1", f"{t} 5 MiB 초과", st, e, 413, "document_too_large", extra=f"rule={(e.get('error', {}).get('detail') or {}).get('rule') if isinstance(e, dict) else ''}")
    ents = "".join("0\nPOINT\n8\n0\n10\n%d.0\n20\n0.0\n30\n0.0\n" % i for i in range(20001))
    many = ("0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n" + ents + "0\nENDSEC\n0\nEOF\n").encode()
    st, e = call("POST", E, t=t, role="operator", files={"file": ("many.dxf", many, "application/dxf")})
    expect("2.1", f"{t} 20,000 엔티티 초과({len(many)//1024} KiB)", st, e, 413, "document_too_large", extra=f"rule={(e.get('error', {}).get('detail') or {}).get('rule') if isinstance(e, dict) else ''}")
    st, e = call("POST", E, t=t, role="viewer", files={"file": ("x.dxf", raw, "application/dxf")})
    expect("2.1", f"{t} viewer 업로드", st, e, 403, "forbidden")
    st, e = call("GET", f"{E}/doc_00000000000000000000000000", t=t, role="operator")
    expect("2.1", f"{t} 없는 문서", st, e, 404, "not_found")
    st, e = call("POST", Q, t=t, role="operator", json_body={**b2, "reviewed": True, "review_note": "abc"})
    expect("2.1", f"{t} 초안에 reviewed true + 메모 3자", st, e, 422, "missing_required")
finally:
    s.close()
dump(f"rows_t02_{t}.txt")
