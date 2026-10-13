"""QA2 재검증(r3) — DEF-QA2R2-002 · 003 · 004 와 #31 회귀를 실서버(127.0.0.1:8215 · ml_qa2r3_db)에서 본다. 고치지 않는다.
  N  JSON 본문 NUL — 결함에 적힌 경로 전부 + 키 · 깊은 중첩 · 날 NUL 바이트 · 결정 · 승격 · 학습 · 대기열 · 옛 경로(kd 견적 · krs 예측/최적화)
     + 조회 문자열(search) NUL(본문 밖 — 관찰)
  F  미래 실측: 서버 +4분 · +4분59초 · +6분 · +30일 · 다른 시간대 표기 · 시간대 없음 → 행 수
  P  linked_prediction_ids 1:1 — 응답 링크 ↔ 대기열 짝 규칙(train.review.pairs_cte / live_pairs) 대조
  Z  품목 · 입력 숫자 정규형 — quantity "5" · inputs.quantity "1" · " 6500 " · "6500.0" · 공백 범주 → 저장값(DB jsonb) · 응답 모양
  Q  #31 품목 422 경우 일부(실서버) — 회귀 확인
결과 행 → rows_server_api_r3.txt · 상세 → server_api_r3.json. 키는 scratchpad keys.json(출력 안 함)."""
import json, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import httpx
from qa_lib import BASE, KEYS, ROOT, SP, Server, call, check, code_of, dump
from mlcore.db.conn import connect

DETAIL: dict = {}
NUL = "a\u0000b"


def det(e):
    if isinstance(e, dict) and isinstance(e.get("error"), dict):
        d = e["error"].get("detail") or {}
        return {"code": e["error"].get("code"), "field": d.get("field"), "rule": d.get("rule")}
    if isinstance(e, dict) and isinstance(e.get("detail"), list):
        return {"old": [{"loc": x.get("loc"), "type": x.get("type")} for x in e["detail"]][:2]}
    return {"body": str(e)[:120]}


def raw_post(path, t, role, raw: bytes):
    r = httpx.post(BASE + path, content=raw, headers={"X-API-Key": KEYS[t][role], "Content-Type": "application/json"}, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text


def deep(v, n):
    for _ in range(n):
        v = {"k": v}
    return v


def counts(t):
    with connect() as c:
        return {tb: c.execute(f"SELECT count(*) AS n FROM {tb} WHERE tenant_id=%s", (t,)).fetchone()["n"]
                for tb in ("mlp_quote", "mlp_actual", "mlp_prediction", "mlp_approval")}


# ═════════════════════════════════ kd ═════════════════════════════════
s = Server("kd", log=f"{SP}/server-kd-api-r3.log")
try:
    spec = importlib.util.spec_from_file_location("qa_r3_sample", ROOT / "packs/eto/synth/sample_dxf.py")
    smod = importlib.util.module_from_spec(spec); spec.loader.exec_module(smod)
    st, ten = call("GET", "/api/v1/tenants/kd/tasks", t="kd", role="viewer")
    import yaml
    mats = yaml.safe_load(open(ROOT / "tenants/kd.yaml"))["categories"]["main_material"]
    r = httpx.post(BASE + "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents", headers={"X-API-Key": KEYS["kd"]["operator"]},
                   files={"file": ("sample.dxf", smod.sample_bytes(mats), "application/dxf")}, timeout=60)
    assert r.status_code == 201, r.text[:300]
    doc = r.json()
    Q = "/api/v1/tenants/kd/tasks/kd.quote"
    U = "/api/v1/tenants/kd/tasks/kd.labor_hours"
    L = [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"], "price_kg": "6500"} for b in doc["bom_rows"]]
    one = lambda **kw: [{**L[0], **kw}] + L[1:]

    def body(ls=None, **kw):
        inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
                  "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
        inputs.update(kw)
        return {"doc_id": doc["doc_id"], "inputs": inputs, "lines": L if ls is None else ls, "reviewed": True, "review_note": "QA r3 검토"}

    good = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
            "product_family": "반응기", "total_mass_kg": 300}
    old = {"drawing_id": doc["doc_id"], "product": "반응기", "material": doc["bom_rows"][0]["material"],
           "bom": [{**{k: v for k, v in x.items()}, "price_kg": 6500} for x in L], "quantity": 1, "cut_m": 24.5, "weld_m": 18.25,
           "thickness_mm": 6.0, "complexity": 3.0, "labor_rate": 45000, "outsource_cost": 0, "reviewed": True, "review_note": "옛 경로 검토"}
    st, base = call("POST", f"{Q}/quotes", t="kd", role="operator", json_body=body())
    assert st == 201, base
    qid = base["quote_id"]
    # 승격 이유 NUL 용 — 현재 운영 버전
    # ── N: NUL ─────────────────────────────────────────────────────────────
    c0 = counts("kd")
    N = [
        ("견적 품목 name", "POST", f"{Q}/quotes", body(one(name=NUL))),
        ("견적 review_note", "POST", f"{Q}/quotes", {**body(), "review_note": "검토 " + NUL}),
        ("견적 inputs 범주 값", "POST", f"{Q}/quotes", body(product_family=NUL)),
        ("견적 inputs 키", "POST", f"{Q}/quotes", {**body(), "inputs": {**body()["inputs"], NUL: 1}}),
        ("견적 품목 material", "POST", f"{Q}/quotes", body(one(material=NUL))),
        ("견적 품목 키", "POST", f"{Q}/quotes", body([{**L[0], NUL: 1}] + L[1:])),
        ("견적 doc_id", "POST", f"{Q}/quotes", {**body(), "doc_id": "doc_" + NUL}),
        ("견적 최상위 모르는 키", "POST", f"{Q}/quotes", {**body(), NUL: "x"}),
        ("견적 깊은 중첩 70단 NUL", "POST", f"{Q}/quotes", body(one(price_kg=deep(NUL, 70)))),
        ("수정 품목 name", "POST", f"{Q}/quotes/{qid}/revisions", body(one(name=NUL))),
        ("수정 review_note", "POST", f"{Q}/quotes/{qid}/revisions", {**body(), "review_note": NUL}),
        ("확정 요청 review_note", "POST", f"{Q}/quotes/{qid}/confirm", {"reviewed": True, "review_note": "확정 " + NUL}),
        ("예측 entity_id(입력 빔)", "POST", f"{U}/predict", {"inputs": {}, "entity_id": NUL}),
        ("예측 entity_id(입력 완전)", "POST", f"{U}/predict", {"inputs": good, "entity_id": NUL}),
        ("예측 inputs 범주 값", "POST", f"{U}/predict", {"inputs": {**good, "product_family": NUL}, "entity_id": "QA-R3-N1"}),
        ("예측 inputs 키", "POST", f"{U}/predict", {"inputs": {**good, NUL: 1}, "entity_id": "QA-R3-N1"}),
        ("예측 model_version", "POST", f"{U}/predict", {"inputs": good, "model_version": "v1" + NUL}),
        ("예측 깊은 중첩 inputs 값", "POST", f"{U}/predict", {"inputs": {**good, "product_family": deep(NUL, 70)}}),
        ("실측 entity_id", "POST", f"{U}/actuals", {"entity_id": NUL, "value": 1.0, "observed_at": datetime.now(timezone.utc).isoformat()}),
        ("실측 observed_at", "POST", f"{U}/actuals", {"entity_id": "QA-R3-N2", "value": 1.0, "observed_at": "2026-10-13T10:00:00" + NUL}),
        ("학습 source_role", "POST", f"{U}/train", {"source_role": "demo" + NUL}),
        ("승격 reason", "POST", f"{U}/models/v1/promote", {"reason": "승격 " + NUL}),
        ("옛 견적 bom name", "POST", "/api/quotes", {**old, "bom": [{**old["bom"][0], "name": NUL}] + old["bom"][1:]}),
        ("옛 견적 review_note", "POST", "/api/quotes", {**old, "review_note": "옛 " + NUL}),
        ("옛 견적 product", "POST", "/api/quotes", {**old, "product": NUL}),
        ("옛 견적 키", "POST", "/api/quotes", {**old, NUL: 1}),
        ("옛 견적 drawing_id", "POST", "/api/quotes", {**old, "drawing_id": NUL}),
    ]
    for label, meth, url, b in N:
        role = "approver" if "승격" in label else ("admin" if "학습" in label else "operator")
        st, e = call(meth, url, t="kd", role=role, json_body=b)
        DETAIL.setdefault("N", {})[label] = {"status": st, **det(e)}
        ok = st == 422
        check("N", f"kd {label}", ok, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
    # 배치 — 한 건만 NUL → 건별 오류(전체 422 아님) · 다른 건 200
    st, e = call("POST", f"{U}/predict:batch", t="kd", role="operator",
                 json_body={"items": [{"inputs": good, "entity_id": "QA-R3-B0"}, {"inputs": good, "entity_id": NUL}]})
    errs = [x for x in (e.get("items") or e.get("results") or []) if isinstance(x, dict) and x.get("error")] if isinstance(e, dict) else []
    DETAIL["N"]["배치 1건 NUL"] = {"status": st, "body": json.dumps(e, ensure_ascii=False)[:400]}
    check("N", "kd 배치 2건 중 1건 entity_id NUL → 200 · 그 건만 오류", st == 200 and len(errs) == 1,
          f"HTTP {st} 오류 건 {len(errs)} {json.dumps([x.get('error') for x in errs], ensure_ascii=False)[:200]}")
    # 날 NUL 바이트(이스케이프 아님 — JSON 규격 위반)
    for label, raw in [("견적 날 NUL 바이트", json.dumps(body(), ensure_ascii=False).replace("QA r3 검토", "QA\x00r3").encode()),
                       ("실측 날 NUL 바이트", ('{"entity_id":"a\x00b","value":1.0,"observed_at":"%s"}' % datetime.now(timezone.utc).isoformat()).encode()),
                       ("옛 견적 날 NUL 바이트", json.dumps(old, ensure_ascii=False).replace("옛 경로 검토", "옛\x00").encode())]:
        path = f"{Q}/quotes" if label.startswith("견적") else (f"{U}/actuals" if label.startswith("실측") else "/api/quotes")
        st, e = raw_post(path, "kd", "operator", raw)
        DETAIL["N"][label] = {"status": st, **det(e)}
        check("N", f"kd {label}", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
    # 결정 reason NUL — 확정 요청 승인 건
    st, cf = call("POST", f"{Q}/quotes/{qid}/confirm", t="kd", role="operator", json_body={"reviewed": True, "review_note": "확정 요청 정상"})
    check("N", "kd NUL 뒤 정상 확정 요청(부분 상태 없음)", st == 202, f"HTTP {st}")
    apr = cf.get("approval_id") if isinstance(cf, dict) else None
    if apr:
        st, e = call("POST", f"/api/v1/approvals/{apr}/decide", t="kd", role="approver", json_body={"decision": "approve", "reason": "승인 " + NUL})
        DETAIL["N"]["결정 reason"] = {"status": st, **det(e)}
        check("N", "kd 승인 결정 reason", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
        st, e = call("POST", f"/api/v1/approvals/{apr}/decide", t="kd", role="approver", json_body={"decision": "approve", "reason": "정상 승인"})
        check("N", "kd NUL 결정 뒤 정상 결정 200(부분 상태 없음)", st == 200, f"HTTP {st} {str(e)[:120]}")
    c1 = counts("kd")
    DETAIL["N_counts"] = {"before": c0, "after": c1}
    check("N", "kd NUL 요청 행 증가 = 정상 요청분만", c1["mlp_actual"] == c0["mlp_actual"] and c1["mlp_quote"] - c0["mlp_quote"] <= 2
          and c1["mlp_prediction"] - c0["mlp_prediction"] <= 1, f"{c0} → {c1}")
    # 조회 문자열 NUL(본문 밖 — 관찰)
    for label, path in [("표준 견적 목록 search", f"{Q}/quotes?search=a%00b"), ("표준 문서 목록 search", "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents?search=a%00b"),
                        ("옛 견적 목록 search", "/api/quotes?search=a%00b"), ("표준 견적 조회 id", f"{Q}/quotes/q%00x"), ("옛 견적 조회 id", "/api/quotes/q%00x")]:
        st, e = call("GET", path, t="kd", role="operator")
        DETAIL.setdefault("N_query", {})[label] = {"status": st, **det(e)}
        check("N-q", f"kd {label} NUL", st != 500, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)[:160]}")

    # ── F: 미래 실측 ──────────────────────────────────────────────────────────
    c0 = counts("kd")
    now = datetime.now(timezone.utc)
    F = [("+4분", now + timedelta(minutes=4), 200), ("+4분50초", now + timedelta(minutes=4, seconds=50), 200),
         ("+5분10초", now + timedelta(minutes=5, seconds=10), 422), ("+6분", now + timedelta(minutes=6), 422),
         ("+30일", now + timedelta(days=30), 422), ("+6분 KST 표기", (now + timedelta(minutes=6)).astimezone(timezone(timedelta(hours=9))), 422),
         ("+6분 -12:00 표기", (now + timedelta(minutes=6)).astimezone(timezone(timedelta(hours=-12))), 422),
         ("+4분 +14:00 표기", (now + timedelta(minutes=4)).astimezone(timezone(timedelta(hours=14))), 200),
         ("-1일(과거)", now - timedelta(days=1), 200)]
    for i, (label, when, want) in enumerate(F):
        st, e = call("POST", f"{U}/actuals", t="kd", role="operator", json_body={"entity_id": f"QA-R3-F{i}", "value": 10.0, "observed_at": when.isoformat()})
        DETAIL.setdefault("F", {})[label] = {"status": st, **det(e)}
        check("F", f"kd 실측 관측 시각 {label}", st == want and (want != 422 or det(e).get("rule") == "future"), f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)} (기대 {want})")
    st, e = call("POST", f"{U}/actuals", t="kd", role="operator", json_body={"entity_id": "QA-R3-FN", "value": 10.0, "observed_at": (now + timedelta(minutes=6)).replace(tzinfo=None).isoformat()})
    check("F", "kd 실측 시간대 없음(+6분)", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
    c1 = counts("kd")
    check("F", "kd 미래 실측 거부 행 0(통과 4건만 증가)", c1["mlp_actual"] - c0["mlp_actual"] == sum(1 for x in F if x[2] == 200), f"실측 {c0['mlp_actual']} → {c1['mlp_actual']}")

    # ── P: linked_prediction_ids 1:1 ─────────────────────────────────────────
    def pred(eid):
        st, b = call("POST", f"{U}/predict", t="kd", role="operator", json_body={"inputs": good, "entity_id": eid})
        assert st == 200, b
        return b["prediction_id"]

    def act(eid, when, v=50.0):
        st, b = call("POST", f"{U}/actuals", t="kd", role="operator", json_body={"entity_id": eid, "value": v, "observed_at": when.isoformat()})
        return st, b

    T = lambda s=1: datetime.now(timezone.utc) + timedelta(seconds=s)
    P = {}
    e1 = "QA-R3-P1"                                  # 예측 2 → 실측 1 → 실측 1 → 예측 1 → 실측 1
    p1 = pred(e1); time.sleep(0.05); p2 = pred(e1); time.sleep(0.05)
    st, a1 = act(e1, T(1)); time.sleep(1.2)
    st, a2 = act(e1, T(1)); time.sleep(1.2)
    p3 = pred(e1); time.sleep(0.05)
    st, a3 = act(e1, T(1)); time.sleep(1.2)
    P["E1"] = {"p": [p1, p2, p3], "a1": a1, "a2": a2, "a3": a3}
    check("P", "kd 예측 2 → 실측 1: 링크 = 뒤 예측 1개", a1.get("linked_prediction_ids") == [p2], f"{a1.get('linked_prediction_ids') == [p2]} n={len(a1.get('linked_prediction_ids') or [])}")
    check("P", "kd 이어진 둘째 실측(새 예측 없음): 링크 0", a2.get("linked_prediction_ids") == [], f"n={len(a2.get('linked_prediction_ids') or [])}")
    check("P", "kd 새 예측 → 실측: 링크 = 새 예측만(앞 예측 다시 안 나옴)", a3.get("linked_prediction_ids") == [p3], f"{a3.get('linked_prediction_ids') == [p3]} n={len(a3.get('linked_prediction_ids') or [])}")
    # 같은 (entity, observed_at) 재등록 — 기존 행 · 같은 링크
    e2 = "QA-R3-P2"
    p4 = pred(e2); w = T(1)
    st, b1 = act(e2, w); st2, b2 = act(e2, w, v=999.0)
    check("P", "kd 같은 (entity, observed_at) 재등록 → 같은 actual_id · 같은 링크", st2 == 200 and b1.get("actual_id") == b2.get("actual_id") and b2.get("linked_prediction_ids") == [p4],
          f"HTTP {st2} same_id={b1.get('actual_id') == b2.get('actual_id')} link={b2.get('linked_prediction_ids') == [p4]}")
    # 예측보다 앞선 관측 시각(과거) 실측 → 링크 0
    e3 = "QA-R3-P3"
    p5 = pred(e3)
    st, b3 = act(e3, datetime.now(timezone.utc) - timedelta(hours=1))
    check("P", "kd 예측 뒤 등록했지만 관측 시각이 예측 전 → 링크 0", st == 200 and b3.get("linked_prediction_ids") == [], f"HTTP {st} n={len(b3.get('linked_prediction_ids') or [])}")
    # 늦게 들어온 더 이른 관측 실측 — 앞 응답 링크가 바뀌는가(관찰)
    e4 = "QA-R3-P4"
    p6 = pred(e4); time.sleep(0.05)
    st, b4 = act(e4, T(3)); st, b5 = act(e4, T(1))
    P["E4"] = {"first_link": b4.get("linked_prediction_ids"), "second_link": b5.get("linked_prediction_ids")}
    time.sleep(3.5)
    # 응답 링크 ↔ 짝 규칙 대조(모든 QA-R3-P* · 대기열 live_pairs 와 같은 SQL)
    from mlcore.train import review as tr
    with connect() as c:
        rows = c.execute(tr.pairs_cte() + " SELECT prediction_id, actual_id, entity_id FROM r WHERE rn = 1 AND entity_id LIKE 'QA-R3-P%%'", ("kd", "kd.labor_hours")).fetchall()
        lp = tr.live_pairs(c, "kd", "kd.labor_hours")
    pairs = {(r["actual_id"], r["prediction_id"]) for r in rows}
    resp = set()
    for a in (a1, a2, a3, b1, b3, b5):
        for pid in a.get("linked_prediction_ids") or []:
            resp.add((a["actual_id"], pid))
    P["pairs_db"] = sorted(pairs); P["pairs_resp"] = sorted(resp)
    P["live_pairs_qa"] = sorted(x["prediction_id"] for x in lp if str(x["entity_id"]).startswith("QA-R3-P"))
    check("P", "kd 응답 링크(최종 응답들) = 짝 규칙 SQL 결과", resp == pairs, f"resp {len(resp)} · db {len(pairs)} · 차이 {len(resp ^ pairs)}")
    check("P", "kd 한 예측이 두 실측에 걸리지 않음(1:1)", len({p for _, p in pairs}) == len(pairs) and len({a for a, _ in pairs}) == len(pairs), f"짝 {len(pairs)}")
    check("P", "kd 늦게 온 더 이른 관측 실측: 앞 실측 응답 링크는 그때 값(관찰)", True,
          f"첫 실측(+3s) 링크 {len(b4.get('linked_prediction_ids') or [])} → 뒤 실측(+1s) 링크 {len(b5.get('linked_prediction_ids') or [])} (짝은 뒤 실측으로 옮겨 감)")
    DETAIL["P"] = P

    # ── Z: 정규화 ────────────────────────────────────────────────────────────
    def saved(qid_):
        with connect() as c:
            row = c.execute("SELECT lines, inputs FROM mlp_quote WHERE tenant_id='kd' AND quote_id=%s ORDER BY revision DESC LIMIT 1", (qid_,)).fetchone()
        return row["lines"][0], row["inputs"]

    Z = [("품목 quantity \"5\"", body(one(quantity="5")), ("line", "quantity", 5)),
         ("inputs.quantity \"1\"", body(quantity="1"), ("input", "quantity", 1)),
         ("inputs.quantity \" 2 \"", body(quantity=" 2 "), ("input", "quantity", 2)),
         ("품목 price_kg \" 6500 \"", body(one(price_kg=" 6500 ")), ("line", "price_kg", 6500)),
         ("품목 price_kg \"6500.0\"", body(one(price_kg="6500.0")), ("line", "price_kg", 6500)),
         ("품목 price_kg 6500.50(숫자)", body(one(price_kg=6500.50)), ("line", "price_kg", 6500.5)),
         ("품목 price_kg \"6500.50\"", body(one(price_kg="6500.50")), ("line", "price_kg", 6500.5)),
         ("품목 mass_kg \" 1.50 \"", body(one(mass_kg=" 1.50 ")), ("line", "mass_kg", 1.5)),
         ("inputs.cut_m \" 24.50 \"", body(cut_m=" 24.50 "), ("input", "cut_m", 24.5)),
         ("inputs.labor_rate \"45000\"", body(labor_rate="45000"), ("input", "labor_rate", 45000)),
         ("inputs.product_family \" 반응기 \"", body(product_family=" 반응기 "), ("input", "product_family", "반응기")),
         ("품목 name \" SHELL \"", body(one(name=" " + L[0]["name"] + " ")), ("line", "name", L[0]["name"])),
         ("품목 price_kg \"1e3\"", body(one(price_kg="1e3")), None),
         ("inputs.quantity \"1e0\"", body(quantity="1e0"), None),
         ("inputs.quantity \"abc\"", body(quantity="abc"), None),
         ("inputs.quantity 1.5", body(quantity=1.5), None)]
    ztab = {}
    for label, b, exp in Z:
        st, e = call("POST", f"{Q}/quotes", t="kd", role="operator", json_body=b)
        row = {"status": st, **(det(e) if st != 201 else {})}
        if st == 201:
            ln, inp = saved(e["quote_id"])
            where, key, want = exp
            got = ln.get(key) if where == "line" else inp.get(key)
            resp_v = (e["lines"][0].get(key) if where == "line" else (e.get("inputs") or {}).get(key))
            row.update(db=got, db_type=type(got).__name__, resp=resp_v, resp_type=type(resp_v).__name__, total=e.get("total"))
            check("Z", f"kd {label} → 201 · 저장 정규형", got == want and not isinstance(got, str) or (isinstance(want, str) and got == want),
                  f"db={got!r}({type(got).__name__}) resp={resp_v!r}({type(resp_v).__name__}) total={e.get('total')}")
        else:
            check("Z", f"kd {label} → {st}", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}", warn=exp is not None)
        ztab[label] = row
    # 같은 뜻 같은 금액: quantity 5 (숫자) vs "5" vs " 5 "
    tots = {}
    for v in (5, "5", " 5 ", "5.0"):
        st, e = call("POST", f"{Q}/quotes", t="kd", role="operator", json_body=body(one(quantity=v)))
        tots[repr(v)] = (st, e.get("total") if st == 201 else det(e))
    check("Z", "kd 품목 quantity 5 · \"5\" · \" 5 \" · \"5.0\" 같은 금액", len({json.dumps(x) for x in tots.values()}) == 1, json.dumps(tots, ensure_ascii=False))
    tots = {}
    for v in (1, "1", " 1 ", "1.0"):
        st, e = call("POST", f"{Q}/quotes", t="kd", role="operator", json_body=body(quantity=v))
        tots[repr(v)] = (st, e.get("total") if st == 201 else det(e))
    check("Z", "kd inputs.quantity 1 · \"1\" · \" 1 \" · \"1.0\" 같은 금액", len({json.dumps(x) for x in tots.values()}) == 1, json.dumps(tots, ensure_ascii=False))
    DETAIL["Z"] = ztab

    # ── Q: #31 품목 422 회귀(실서버 일부) ─────────────────────────────────────
    for label, b in [("음수 단가", body(one(price_kg="-6500"))), ("단가 1e12", body(one(price_kg="1000000000000"))), ("수량 1.5", body(one(quantity=1.5))),
                     ("수량 1001", body(one(quantity=1001))), ("모르는 키 amount", body(one(amount="-1"))), ("재질 목록 밖", body(one(material="UNOBTAINIUM"))),
                     ("0행", body([])), ("101행", body((L * 101)[:101])), ("price NaN 문자열", body(one(price_kg="NaN"))), ("name 81자", body(one(name="가" * 81)))]:
        st, e = call("POST", f"{Q}/quotes", t="kd", role="operator", json_body=b)
        check("Q", f"kd #31 {label}", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
        st, e = call("POST", f"{Q}/quotes/{qid}/revisions", t="kd", role="operator", json_body=b)
        check("Q", f"kd #31 수정 {label}", st in (422, 409), f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
finally:
    s.close()
log = open(f"{SP}/server-kd-api-r3.log").read()
check("LOG", "kd 서버 로그 500 · Traceback 0", log.count(" 500 ") == 0 and log.count("Traceback") == 0, f"500 {log.count(' 500 ')} · Traceback {log.count('Traceback')}")

# ═════════════════════════════════ krs ═════════════════════════════════
from mlcore.monitor import review as job  # noqa: E402
s = Server("krs", log=f"{SP}/server-krs-api-r3.log")
try:
    R = "/api/v1/tenants/krs/tasks/krs.residual_review/review"
    st, b = call("GET", R + "?state=open&limit=5", t="krs", role="operator")
    if not b.get("items"):
        job.run_review("krs", date.today())
        st, b = call("GET", R + "?state=open&limit=5", t="krs", role="operator")
    it = b["items"][0]["item_id"]
    st, e = call("PATCH", f"{R}/{it}", t="krs", role="approver", json_body={"state": "false_alarm", "note": "메모 " + NUL})
    check("N", "krs 대기열 검토 note NUL", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
    st, e = call("PATCH", f"{R}/{it}", t="krs", role="approver", json_body={"state": "false_alarm" + NUL, "note": "x"})
    check("N", "krs 대기열 검토 state NUL", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)}")
    st, e = call("PATCH", f"{R}/{it}", t="krs", role="approver", json_body={"state": "false_alarm", "note": "정상 메모"})
    check("N", "krs NUL 뒤 정상 검토 200(부분 상태 없음)", st == 200, f"HTTP {st}")
    for label, path in [("옛 예측 /api/quality/predict", "/api/quality/predict"), ("옛 최적화 /api/ml/optimize", "/api/ml/optimize")]:
        st, e = call("POST", path, t="krs", role="operator", json_body={"x": NUL})
        check("N", f"krs {label} 값 NUL", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)[:160]}")
        st, e = call("POST", path, t="krs", role="operator", json_body={NUL: 1})
        check("N", f"krs {label} 키 NUL", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)[:160]}")
    st, e = call("POST", "/api/v1/tenants/krs/tasks/krs.recipe_optimize/optimize", t="krs", role="operator", json_body={"fixed": {"x": NUL}})
    check("N", "krs 표준 최적화 fixed 값 NUL", st == 422, f"HTTP {st} {json.dumps(det(e), ensure_ascii=False)[:160]}")
finally:
    s.close()
log = open(f"{SP}/server-krs-api-r3.log").read()
check("LOG", "krs 서버 로그 500 · Traceback 0", log.count(" 500 ") == 0 and log.count("Traceback") == 0, f"500 {log.count(' 500 ')} · Traceback {log.count('Traceback')}")
dump("rows_server_api_r3.txt")
(Path(__file__).parent / "server_api_r3.json").write_text(json.dumps(DETAIL, ensure_ascii=False, indent=1, default=str))
