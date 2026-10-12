"""QA2 재검증(r2) — 다른 회사 노출 새 공격: kd 서버에 kd 키로 pc 예측 추적 · pc 대기열 항목(can_decide 포함) · pc 실측 · 견적/문서 id 를 kd 경로에 끼우기."""
from qa_lib import Server, call, check, dump, code_of
from mlcore.db.conn import connect
G = "XT"
with connect() as c:
    pid = c.execute("SELECT prediction_id FROM mlp_prediction WHERE tenant_id='pc' LIMIT 1").fetchone()
    item = c.execute("SELECT item_id FROM mlp_review_item WHERE tenant_id='pc' LIMIT 1").fetchone()
    qid = c.execute("SELECT quote_id FROM mlp_quote WHERE tenant_id='ot' LIMIT 1").fetchone()
    did = c.execute("SELECT doc_id FROM mlp_document WHERE tenant_id='ot' LIMIT 1").fetchone()
s = Server("kd")
try:
    tests = []
    if pid: tests.append(("GET", f"/api/v1/predictions/{pid['prediction_id']}/trace", None))
    if item: tests += [("PATCH", f"/api/v1/tenants/kd/tasks/kd.quote/review/{item['item_id']}", {"state": "false_alarm", "note": "x"}),
                       ("GET", "/api/v1/tenants/pc/tasks/pc.residual_review/review", None)]
    if qid: tests += [("GET", f"/api/v1/tenants/kd/tasks/kd.quote/quotes/{qid['quote_id']}", None),
                      ("GET", f"/api/v1/tenants/kd/tasks/kd.quote/quotes/{qid['quote_id']}.csv", None),
                      ("POST", f"/api/v1/tenants/kd/tasks/kd.quote/quotes/{qid['quote_id']}/revisions", {"inputs": {}, "reviewed": False}),
                      ("GET", f"/api/quotes/{qid['quote_id']}", None)]
    if did: tests += [("GET", f"/api/v1/tenants/kd/tasks/kd.drawing_regions/documents/{did['doc_id']}", None),
                      ("GET", f"/api/cad/{did['doc_id']}", None),
                      ("POST", "/api/v1/tenants/kd/tasks/kd.quote/quotes", {"doc_id": did["doc_id"], "inputs": {}, "reviewed": False})]
    for m, u, b in tests:
        st, body = call(m, u, t="kd", role="admin", json_body=b)
        leaked = any(x in str(body) for x in ("pc.", "ot.", "PC-", "OT-")) and st < 300
        check(G, f"kd admin → 남의 id {m} {u.split('/')[-2] if u.count('/') > 3 else u}", st in (403, 404, 422) and not leaked, f"HTTP {st} {code_of(body) or ''}")
finally:
    s.close()
dump("rows_xtenant_r2.txt")
