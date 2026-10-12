"""QA2-2 §H Agent 도구 4 + 별칭 쓰기 0 · 승인 요청 0 · §I 대기열(B09) 역할 · 회사 범위 · 감사 · §J 허브 내보내기 비밀값 · 실데이터 · 경로.
고치지 않는다. 회사 pc 사본(팩 kimchi — 회귀 · 최적화 · 대기열). 결과 → probe_agent_review_hub-result.json"""
from __future__ import annotations

import json
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import OUT, ROOT, client, count, h, rec, save

KST = timezone(timedelta(hours=9))
SENTINEL_ENTITY = "QA22-SENTINEL-LOT-7781"


def writes(code: str) -> dict:
    with h.connect() as c:
        n = lambda sql: c.execute(sql, (code,)).fetchone()["n"]  # noqa: E731
        return {"approval": n("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id=%s"),
                "stages": tuple(r["stage"] for r in c.execute("SELECT stage FROM mlp_model_version WHERE tenant_id=%s ORDER BY task_id, version",
                                                              (code,)).fetchall()),
                "train_run": n("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s"),
                "actual": n("SELECT count(*) AS n FROM mlp_actual WHERE tenant_id=%s"),
                "review_open": n("SELECT count(*) AS n FROM mlp_review_item WHERE tenant_id=%s AND state='open'"),
                "review_all": n("SELECT count(*) AS n FROM mlp_review_item WHERE tenant_id=%s"),
                "quote": n("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id=%s"),
                "document": n("SELECT count(*) AS n FROM mlp_document WHERE tenant_id=%s"),
                "recommendation_needs_approval": n("SELECT count(*) AS n FROM mlp_recommendation WHERE tenant_id=%s AND status='needs_approval'"),
                "prediction": n("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s"),
                "recommendation": n("SELECT count(*) AS n FROM mlp_recommendation WHERE tenant_id=%s")}


def main():
    from mlcore.integrations import agent_tools as at
    from mlcore.monitor import review as job
    base = Path(tempfile.mkdtemp(prefix="qa22-agent-"))
    m = h.make_tenant("pc", base / "a")
    t = m.tenant.code
    k = h.keys(m)
    tc = client(m)
    tasks = {td.type: tid for tid, td in m.tasks.items()}
    reg, opt, queue = tasks["regression"], tasks.get("optimize"), tasks["review_queue"]
    with h.use_tenants_dir(m):
        ref, _ = h.real_production(m, reg)
    lock = h.lock_of(ref)
    inputs = h.mid_inputs(lock, lock["order"])

    def tp(key):
        def send(method, path, body):
            r = tc.request(method, path, headers=h.hdr(key), json=body)
            return r.status_code, (r.json() if r.content else {})
        return send

    # ── §H Agent 도구 4 + 별칭 4 + LLM 이름 ────────────────────────────────────────────────
    with h.use_tenants_dir(m):
        list(job.run_review(t, date(2026, 10, 2), merged=m))      # 대기열 항목(시험 구간) 먼저 — 도구 전후 비교 대상
    names = list(at.NAMES) + list(at.ALIASES) + [n.replace(".", "__") for n in at.NAMES]
    before = writes(t)
    calls = []
    pred_id = None
    for name in names:
        canon = at.resolve(name)
        if canon == "ml.calculate_prediction":
            args = {"task": reg, "inputs": inputs, "entity_id": SENTINEL_ENTITY, "explain": True}
        elif canon == "ml.get_explanation":
            args = {"prediction_id": pred_id or "prd_00000000000000000000000000"}
        elif canon == "ml.calculate_recommendation":
            fixed = {n: inputs[n] for n in (m.tasks[opt].raw.get("fixed") or []) if n in inputs} if opt else {}
            args = {"task": opt or reg, "fixed": fixed}
        else:
            args = {}
        res = at.call(name, args, tenant=t, transport=tp(k["operator"]))
        if canon == "ml.calculate_prediction" and res.rows:
            pred_id = res.rows[0].get("prediction_id")
        calls.append({"name": name, "status": res.status, "summary": res.summary[:80], "cites": len(res.cite)})
    after = writes(t)
    same = {kk: (before[kk], after[kk]) for kk in before if kk not in ("prediction", "recommendation") and before[kk] != after[kk]}
    rec("G2-I01", "도구 4 · 별칭 4 · LLM 이름 4 = 12 호출 → 쓰기 0(승인 · 단계 · 학습 · 실측 · 대기열 · 견적 · 문서)", not same,
        {"calls": calls, "changed": same, "prediction_delta": after["prediction"] - before["prediction"],
         "recommendation_delta": after["recommendation"] - before["recommendation"]})
    rec("G2-I01", "도구 호출 상태(ok 기대)", all(c["status"] in ("ok", "empty") for c in calls),
        [(c["name"], c["status"], c["summary"]) for c in calls if c["status"] not in ("ok", "empty")])
    # 승인 요청 유도 시도 — 인자에 request_approval · 다른 회사 · 쓰기 경로 문자열
    tries = {
        "추천 top-level request_approval": ("ml.recommend", {"task": opt or reg, "fixed": {}, "request_approval": True}),
        "추천 params.request_approval=true": ("ml.recommend", {"task": opt or reg, "fixed": {}, "params": {"request_approval": True}}),
        "추천 params.request_approval=1": ("ml.recommend", {"task": opt or reg, "fixed": {}, "params": {"request_approval": 1}}),
        "추천 current 에 request_approval": ("ml.recommend", {"task": opt or reg, "fixed": {}, "current": {"request_approval": True}}),
        "예측 task 경로 주입": ("ml.predict", {"task": f"{t}.x/../../models/v1/promote", "inputs": {}}),
        "예측 task 줄바꿈": ("ml.predict", {"task": f"{reg}\n", "inputs": inputs}),
        "다른 회사 과제": ("ml.predict", {"task": "zz.sensory_score", "inputs": inputs}),
        "견적 과제(quote 유형)": ("ml.predict", {"task": f"{t}.quote", "inputs": {}}),
        "대기열 과제": ("ml.predict", {"task": queue, "inputs": {}}),
        "모르는 도구 ml.draft_promote": ("ml.draft_promote", {}),
        "action.propose": ("action.propose", {}),
    }
    b2 = writes(t)
    out = {}
    for label, (name, args) in tries.items():
        res = at.call(name, args, tenant=t, transport=tp(k["admin"]))
        out[label] = res.status
    a2 = writes(t)
    ch = {kk: (b2[kk], a2[kk]) for kk in b2 if kk not in ("prediction", "recommendation") and b2[kk] != a2[kk]}
    rec("G2-I01", "승인 요청 유도 · 경로 주입 11종(admin 키) → 승인 · 단계 변화 0", not ch and a2["recommendation_needs_approval"] == b2["recommendation_needs_approval"],
        {"results": out, "changed": ch})
    rec("G2-I01", "ToolMeta readonly 4 · 이름 규칙", all(td.meta.readonly for td in at.TOOLS.values()) and all(at.NAME_RE.match(n) for n in at.NAMES),
        {n: at.TOOLS[n].meta.readonly for n in at.NAMES})
    res = at.call("ml.predict", {"task": reg, "inputs": inputs}, tenant=t, transport=tp(k["viewer"]))
    rec("G2-I01", "viewer 키 → denied", res.status == "denied", {"status": res.status})
    res = at.call("ml.explain", {"prediction_id": pred_id}, tenant=t, transport=tp(k["operator"]))
    blob = json.dumps([r for r in res.rows], ensure_ascii=False, default=str)
    rec("G2-I01", "explain 결과에 원천 ref · 입력값 · 경로 없음", "fixture" not in blob and "/Users" not in blob and "var/" not in blob,
        {"status": res.status, "keys": sorted(res.rows[0]) if res.rows else None})

    # ── §I 대기열 B09 — 역할 · 재검토 409 · 회사 범위 · 감사 ─────────────────────────────────
    Q = f"/api/v1/tenants/{t}/tasks/{queue}/review"
    for role, want in (("viewer", 403), ("operator", 200), ("approver", 200), ("admin", 200), ("approver_other", 200)):
        r = tc.get(Q, headers=h.hdr(k[role]))
        rec("G2-A01", f"GET review · {role}", r.status_code == want, {"status": r.status_code}, want)
    items = tc.get(Q, headers=h.hdr(k["operator"]), params={"state": "open", "limit": 100}).json().get("items") or []
    rec("G2-A01", "대기열 열린 항목", len(items) >= 2, {"n": len(items), "origins": sorted({i["origin"] for i in items})})
    if len(items) >= 2:
        i0, i1 = items[0]["item_id"], items[1]["item_id"]
        for role, want in (("viewer", 403), ("operator", 403), ("approver_other", 403)):
            r = tc.patch(f"{Q}/{i0}", headers=h.hdr(k[role]), json={"state": "false_alarm", "note": "역할 시험"})
            rec("G2-A01", f"PATCH review · {role}", r.status_code == want, {"status": r.status_code}, want)
        a0 = count("mlp_audit", "tenant_id=%s AND action LIKE 'review.%%'", (t,))
        r = tc.patch(f"{Q}/{i0}", headers=h.hdr(k["approver"]), json={"state": "confirmed_issue", "note": "실제 이상"})
        rec("G2-A01", "PATCH review · approver(자기 과제)", r.status_code == 200, {"status": r.status_code})
        a1 = count("mlp_audit", "tenant_id=%s AND action LIKE 'review.%%'", (t,))
        rec("감사", "대기열 결정 → review.<state> 감사 1행", a1 - a0 == 1, {"delta": a1 - a0})
        r = tc.patch(f"{Q}/{i0}", headers=h.hdr(k["admin"]), json={"state": "false_alarm", "note": "재검토"})
        rec("G2-A01", "닫힌 항목 재검토 → 409 already_decided", r.status_code == 409 and r.json()["error"]["code"] == "already_decided", {"status": r.status_code})
        for bad, label in (({"state": "open", "note": "x"}, "state=open"), ({"state": "false_alarm"}, "note 없음"),
                           ({"state": "false_alarm", "note": "x", "decided_by": "boss"}, "모르는 키 decided_by"),
                           ({"state": "false_alarm", "note": "x" * 5000}, "note 5000자")):
            r = tc.patch(f"{Q}/{i1}", headers=h.hdr(k["approver"]), json=bad)
            rec("G2-A01", f"PATCH review 잘못된 본문 · {label}", r.status_code == 422, {"status": r.status_code})
        m2 = h.make_tenant("pc", base / "b")
        k2 = h.keys(m2)
        r = tc.get(Q, headers=h.hdr(k2["admin"]))
        rec("G2-A01", "다른 회사 admin · GET review", r.status_code == 404, {"status": r.status_code})
        r = tc.patch(f"{Q}/{i1}", headers=h.hdr(k2["admin"]), json={"state": "false_alarm", "note": "남의 회사"})
        rec("G2-A01", "다른 회사 admin · PATCH review", r.status_code == 404, {"status": r.status_code})
        t2 = m2.tenant.code
        r = tc.patch(f"/api/v1/tenants/{t2}/tasks/{t2}.residual_review/review/{i1}", headers=h.hdr(k2["admin"]),
                     json={"state": "false_alarm", "note": "내 경로 · 남의 ID"})
        rec("G2-A01", "다른 회사 경로 · 남의 item_id", r.status_code == 404, {"status": r.status_code})
        st = tc.get(Q, headers=h.hdr(k["operator"]), params={"state": "open", "limit": 100}).json()
        rec("G2-A01", "남의 시도 뒤 항목 그대로 open", any(i["item_id"] == i1 for i in st["items"]), {"open": len(st["items"])})
    r = tc.get(f"/api/v1/tenants/{t}/tasks/{reg}/review", headers=h.hdr(k["operator"]))
    rec("G2-A01", "대기열 아닌 과제 review → 404 type_route", r.status_code == 404, {"status": r.status_code})

    # ── §J 허브 내보내기 — 이 DB · 오늘 날짜(예측 · 감사 있음) ─────────────────────────────────
    from mlcore.monitor import hub_export
    today = datetime.now(KST).date()
    outdir = Path(tempfile.mkdtemp(prefix="qa22-hub-"))
    path = hub_export.write(today, out_dir=outdir)
    text6 = path.read_text(encoding="utf-8")
    with h.connect() as c:                       # 시험 회사(예측 · 감사 · 대기열 · 승인이 있는 회사)도 같은 함수로
        mine = hub_export.company(m, today, conn=c)
    doc6 = json.loads(text6)
    doc = {**doc6, "companies": doc6["companies"] + [mine]}
    text = hub_export.dumps(doc)
    pats = {
        "IPv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "URL": r"https?://", "DSN": r"(dbname=|host=|postgres(ql)?://|password|passwd|secret|token)",
        "API 키": r"mlp_[A-Za-z0-9_-]{16,}|sha256\$", "절대 경로": r"(/Users/|/home/|/private/|/tmp/|[A-Za-z]:\\\\)",
        "var/ 경로": r"var/(documents|snapshots|artifacts|export)", "env 이름": r"_env\b|MLP_[A-Z_]+|AGENT_[A-Z_]+",
        "센티널 entity": re.escape(SENTINEL_ENTITY), "파일 이름 .dxf": r"\.dxf\b", "doc_/qte_/prd_ ID": r"\b(doc|qte|prd|apr)_[0-9A-Z]{26}\b",
    }
    hits = {kk: sorted(set(m_.group(0) for m_ in re.finditer(p, text)))[:5] for kk, p in pats.items()}
    hits = {kk: v for kk, v in hits.items() if v}
    rec("G2-I02", "허브 내보내기 금지 패턴(키 · DSN · URL · IP · 경로 · 입력값 · ID)", not hits,
        {"file_bytes": len(text), "companies": [c["company"] for c in doc["companies"]], "hits": hits})
    # 입력값 · 예측값이 숫자로 섞였는지 — 우리 predict 입력값을 그대로 찾는다
    vals = [str(v) for v in inputs.values() if isinstance(v, float)]
    leaked = [v for v in vals if v in text]
    rec("G2-I02", "예측 입력값(학습 범위 중앙값) 문자열이 파일에 없음", not leaked, {"leaked": leaked[:5], "checked": len(vals)})
    srcs = sorted({u["source_ref"] for c in doc["companies"] for u in c["consumers"] + c["usages"] + c["datasets"]})
    bad_ref = [s for s in srcs if s.startswith("/") or ".." in s]
    rec("G2-I02", "source_ref 는 저장소 상대 경로:줄 만", not bad_ref, {"n": len(srcs), "bad": bad_ref[:5], "sample": srcs[:4]})
    ds = sorted({d["physical_name"] for c in doc["companies"] for d in c["datasets"]})
    rec("G2-I02", "datasets(원천 테이블 이름 — 정의만)", "INFO", {"physical_names": ds})
    pc_usage = mine
    rec("G2-I02", "api_usage 는 집계 숫자만(이 회사)", "INFO", {"company": pc_usage["company"], "api_usage": pc_usage["api_usage"]})
    # 비교: 저장소 정본 출력 대상(6개사) — 임시 회사가 섞였는가
    codes = [c["company"] for c in doc6["companies"]]
    rec("G2-I02", "내보내기 범위 = 등록부 6개사(_template · 임시 회사 제외)", sorted(codes) == sorted(["kd", "krs", "ks", "ot", "pc", "sw"]), {"codes": codes})
    (OUT / "hub-export-sample.json").write_text(text, encoding="utf-8")
    save("probe_agent_review_hub-result.json")


if __name__ == "__main__":
    main()
