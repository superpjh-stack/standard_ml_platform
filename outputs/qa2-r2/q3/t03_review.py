"""검토 대기열 (goal2 §3.3 · §2.1 · §6) — krs · pc: 목록 · 출처 · 동시 검토 · 재검토 409 · 역할 · 회사 범위 · type_route."""
import sys, threading
from qa_lib import Server, call, check, expect, dump, code_of
from mlcore.db.conn import connect
G = "R"
for t, other in (("krs", "pc"), ("pc", "krs")):
    task = f"{t}.residual_review"
    R = f"/api/v1/tenants/{t}/tasks/{task}/review"
    s = Server(t)
    try:
        st, b = call("GET", R + "?state=open&limit=100", t=t, role="operator")
        items = b.get("items", [])
        check(G, f"{t} open 목록 operator 조회", st == 200 and len(items) > 0 and set(b) >= {"items", "next_cursor"}, f"HTTP {st} n={len(items)} total={b.get('total')}")
        check(G, f"{t} 항목 출처 = test_split/live_residual 만", all(i["origin"] in ("test_split", "live_residual") for i in items), str(sorted({i['origin'] for i in items})))
        rule = {"krs": "abs_residual_ge", "pc": "top_quantile"}[t]
        check(G, f"{t} 규칙 {rule} · |잔차| ≥ 임계값", all(i["rule"] == rule and abs(float(i["residual"])) >= float(i["threshold"]) - 1e-9 for i in items), f"thr={items[0]['threshold']} min|r|={min(abs(float(i['residual'])) for i in items):.3f}")
        st, e = call("GET", R, t=t, role="viewer")
        expect(G, f"{t} viewer 목록(✕)", st, e, 403, "forbidden")
        st, b2 = call("GET", R + "?limit=5", t=t, role="operator")
        st3, b3 = call("GET", R + f"?limit=5&cursor={b2.get('next_cursor')}", t=t, role="operator") if b2.get("next_cursor") else (None, {"items": []})
        check(G, f"{t} 커서 페이지 겹침 0", not ({i['item_id'] for i in b2['items']} & {i['item_id'] for i in b3['items']}), f"p1={len(b2['items'])} p2={len(b3.get('items', []))} cursor={'있음' if b2.get('next_cursor') else '없음'}")
        it = items[0]["item_id"]
        P = f"{R}/{it}"
        st, e = call("PATCH", P, t=t, role="operator", json_body={"state": "false_alarm", "note": "오탐"})
        expect(G, f"{t} operator 검토(✕)", st, e, 403, "forbidden")
        st, e = call("PATCH", P, t=t, role="approver_other", json_body={"state": "false_alarm", "note": "오탐"})
        expect(G, f"{t} 다른 과제 approver 검토(✕)", st, e, 403, "forbidden")
        st, e = call("PATCH", P, t=t, role="approver", json_body={"state": "closed", "note": "x"})
        expect(G, f"{t} 모르는 state", st, e, 422, "invalid_input")
        st, e = call("PATCH", P, t=t, role="approver", json_body={"state": "false_alarm", "note": ""})
        check(G, f"{t} 빈 메모(계약 ≥1자)", st == 422, f"HTTP {st} code={code_of(e)}", warn=True)
        st, e = call("PATCH", P, t=other, role="approver", json_body={"state": "false_alarm", "note": "다른 회사"})
        expect(G, f"{t} 다른 회사 키로 검토", st, e, 404, "not_found")
        st, e = call("PATCH", f"/api/v1/tenants/{other}/tasks/{task}/review/{it}", t=other, role="approver", json_body={"state": "false_alarm", "note": "경로 바꿔치기"})
        expect(G, f"{t} 다른 회사 경로 + 자기 키", st, e, 404, "not_found")
        # 두 탭 동시 검토
        out = [None, None]; bar = threading.Barrier(2)
        def go(i, role, state):
            bar.wait(); out[i] = call("PATCH", P, t=t, role=role, json_body={"state": state, "note": f"탭 {i}"})
        th = [threading.Thread(target=go, args=(0, "approver", "confirmed_issue")), threading.Thread(target=go, args=(1, "admin", "false_alarm"))]
        [x.start() for x in th]; [x.join() for x in th]
        codes = sorted(o[0] for o in out)
        with connect() as c:
            row = c.execute("SELECT state, decided_by, note FROM mlp_review_item WHERE tenant_id=%s AND item_id=%s", (t, it)).fetchone()
        win = [o[1] for o in out if o[0] == 200]
        check(G, f"{t} 두 탭 동시 검토 → 200 1 · 409 1 · 결과 = 이긴 쪽", codes == [200, 409] and win and win[0]["state"] == row["state"], f"codes={codes} db={row['state']}")
        st, e = call("PATCH", P, t=t, role="admin", json_body={"state": "confirmed_issue", "note": "재검토"})
        expect(G, f"{t} 닫힌 항목 재검토", st, e, 409, "already_decided")
        st, b4 = call("GET", R + "?state=open&limit=100", t=t, role="operator")
        check(G, f"{t} 닫힌 항목 open 목록에서 빠짐", it not in {i['item_id'] for i in b4['items']} and len(b4['items']) == len(items) - 1, f"{len(items)} → {len(b4['items'])}")
        st, e = call("GET", f"/api/v1/tenants/{t}/tasks/{t}.joint_strength/review" if t == "krs" else f"/api/v1/tenants/{t}/tasks/{t}.sensory_score/review", t=t, role="operator")
        expect("2.1", f"{t} review 경로를 회귀 과제로(type_route)", st, e, 404, "not_found", (e.get("error", {}).get("detail") or {}).get("rule") == "type_route")
        st, e = call("POST", f"/api/v1/tenants/{t}/tasks/{task}/predict", t=t, role="operator", json_body={"inputs": {}})
        expect("2.1", f"{t} 대기열 과제에 predict(type_route)", st, e, 404, "not_found", (e.get("error", {}).get("detail") or {}).get("rule") == "type_route")
        st, e = call("PATCH", f"{R}/rvw_doesnotexist", t=t, role="approver", json_body={"state": "false_alarm", "note": "없음"})
        expect("2.1", f"{t} 없는 항목", st, e, 404, "not_found")
    finally:
        s.close()
dump("rows_t03.txt")
