"""QA2 재검증(r3) — find_nul 깊이 상한(64단) 밖 NUL 이 실제 저장 경로까지 가는가. 실서버 8215 · ml_qa2r3_db. 고치지 않는다.
옛 경로(krs 예측 · 최적화 · kd 옛 견적)와 표준 경로에서 '맞는 키' 아래 65~80단 중첩 값에 NUL. 결과 행 → rows_nul_deep_r3.txt"""
import json
from qa_lib import SP, Server, call, check, dump


def deep(v, n):
    for _ in range(n):
        v = {"k": v}
    return v


NUL = "a\u0000b"
s = Server("krs", log=f"{SP}/server-krs-nul-deep.log")
try:
    st, smp = call("GET", "/api/ml/samples?limit=1", t="krs", role="operator")
    row = None
    if isinstance(smp, dict):
        for v in smp.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                row = v[0]; break
    elif isinstance(smp, list) and smp:
        row = smp[0]
    check("D", "krs 옛 samples 1행", isinstance(row, dict), f"HTTP {st} keys={sorted(row)[:12] if isinstance(row, dict) else None}")
    if isinstance(row, dict):
        inp = row.get("input") or row.get("inputs") or row
        k0 = next(iter(inp))
        for n in (63, 65, 80):
            st, e = call("POST", "/api/quality/predict", t="krs", role="operator", json_body={**inp, k0: deep(NUL, n)})
            check("D", f"krs 옛 예측 맞는 키 아래 {n}단 NUL", st != 500, f"HTTP {st} {json.dumps(e, ensure_ascii=False)[:160]}")
    for n in (65, 80):
        st, e = call("POST", "/api/v1/tenants/krs/tasks/krs.joint_strength/predict", t="krs", role="operator",
                     json_body={"inputs": {"x": deep(NUL, n)}, "entity_id": "QA-R3-D"})
        check("D", f"krs 표준 예측 inputs {n}단 NUL", st != 500, f"HTTP {st} {json.dumps(e, ensure_ascii=False)[:160]}")
        st, e = call("PATCH", "/api/v1/tenants/krs/tasks/krs.residual_review/review/rvw_x", t="krs", role="approver",
                     json_body={"state": "false_alarm", "note": deep(NUL, n)})
        check("D", f"krs 대기열 note {n}단 NUL", st != 500, f"HTTP {st} {json.dumps(e, ensure_ascii=False)[:160]}")
finally:
    s.close()
log = open(f"{SP}/server-krs-nul-deep.log").read()
check("LOG", "krs 서버 로그 500 · Traceback 0", log.count(" 500 ") == 0 and log.count("Traceback") == 0, f"500 {log.count(' 500 ')} · Traceback {log.count('Traceback')}")
dump("rows_nul_deep_r3.txt")
