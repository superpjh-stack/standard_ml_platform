"""QA2 재검증(r2) — #30 실서버(127.0.0.1:8214 · MLP_TENANT=kd · ml_qa2r2_db) 추출 경계 · 격리 · 거부 시 파일/행 0.
공격 꼴은 리포트에 적지 않는다(이 스크립트에만). 키는 scratchpad keys.json(출력 안 함). 결과 → server_extract_r2.json
사용: server_extract_r2.py [max_seconds]   (인자를 주면 MLP_EXTRACT_MAX_SECONDS 로 서버를 띄운다)"""
import json, math, os, subprocess, sys, threading, time
from pathlib import Path
import httpx
from qa_lib import BASE, KEYS, SP, Server
from mlcore.db.conn import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "q2"))
DOCS = Path(os.environ["MLP_DOCUMENT_DIR"])
ms = sys.argv[1] if len(sys.argv) > 1 else None
if ms:
    os.environ["MLP_EXTRACT_MAX_SECONDS"] = ms
K = KEYS["kd"]["operator"]
URL = BASE + "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents"


def tree_rss(root: int) -> float:
    out = subprocess.check_output(["ps", "-A", "-o", "pid=,ppid=,rss="]).decode().split("\n")
    rows = [tuple(map(int, l.split())) for l in out if l.strip()]
    kids, rss = {}, {}
    for p, pp, r in rows:
        kids.setdefault(pp, []).append(p); rss[p] = r
    tot, st = 0, [root]
    while st:
        p = st.pop(); tot += rss.get(p, 0); st += kids.get(p, [])
    return tot / 1024


def dxf(ents):
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "4"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), *ents, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode()


def rect(x0, y0, x1, y1, layer="BOM"):
    out = [(0, "LWPOLYLINE"), (8, layer), (90, "4"), (70, "1")]
    for px, py in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        out += [(10, str(px)), (20, str(py))]
    return out


def text(v, x, y, layer="T"):
    return [(0, "TEXT"), (8, layer), (10, str(x)), (20, str(y)), (30, "0"), (40, "3"), (1, v)]


def circle(cx, cy, r):
    return [(0, "CIRCLE"), (8, "C"), (10, str(cx)), (20, str(cy)), (30, "0"), (40, str(r))]


def state():
    with connect() as c:
        n = c.execute("SELECT count(*) AS n FROM mlp_document WHERE tenant_id='kd'").fetchone()["n"]
    files = sum(1 for _ in DOCS.rglob("*") if _.is_file()) if DOCS.exists() else 0
    return n, files


CASES = {}
n = 5000
CASES["nested_10000"] = dxf([e for i in range(n) for e in rect(-i - 1, -i - 1, i + 1, i + 1)] + [e for i in range(n) for e in text("BOM", i + .5, 0, "BOM")])
n = 10000
CASES["nested_20000"] = dxf([e for i in range(n) for e in rect(-i - 1, -i - 1, i + 1, i + 1)] + [e for i in range(n) for e in text("BOM", i + .5, 0, "BOM")])
g = []                                  # 겹치지 않는 격리 영역 6,666 + 텍스트 → 영역 6,666 (items 5,000 초과)
for i in range(6666):
    x, y = (i % 100) * 20, (i // 100) * 20
    g += rect(x, y, x + 10, y + 10) + text("BOM", x + 5, y + 5)
CASES["grid_items_6666"] = dxf(g)
g = []
for i in range(4999):
    x, y = (i % 100) * 20, (i // 100) * 20
    g += rect(x, y, x + 10, y + 10) + text("BOM", x + 5, y + 5)
CASES["grid_items_4999"] = dxf(g)
for nc in (500, 1000, 1500, 2000, 3000, 5000, 19000):   # 원(구멍) 많은 도면 — 미리보기 49점/원
    CASES[f"circles_{nc}"] = dxf(circle(0, 0, 1)[:0] + [e for i in range(nc) for e in circle((i % 150) * 10, (i // 150) * 10, 3)] + rect(-50, -50, 3000, 3000, "TITLE") + text("TITLE BLOCK", 0, 0))
for nl in (5000, 19000):                # 선만
    CASES[f"lines_{nl}"] = dxf([e for i in range(nl) for e in [(0, "LINE"), (8, "L"), (10, str(i)), (20, "0"), (30, "0"), (11, str(i)), (21, "100"), (31, "0")]])
CASES["texts_long_3000"] = dxf([e for i in range(3000) for e in text("X" * 1990, i, 0)])

res = {"max_seconds_env": ms}
s = Server("kd", log=f"{SP}/server-kd-extract-{ms or 'def'}.log")
try:
    pid = s.p.pid
    base_state = state()
    res["state_before"] = base_state
    for name, raw in CASES.items():
        st0 = state()
        peak = [tree_rss(pid)]; stop = [False]
        def watch():
            while not stop[0]:
                try: peak.append(tree_rss(pid))
                except Exception: pass
                time.sleep(0.1)
        th = threading.Thread(target=watch); th.start()
        t0 = time.perf_counter()
        try:
            r = httpx.post(URL, headers={"X-API-Key": K}, files={"file": (f"{name}.dxf", raw, "application/dxf")}, timeout=300)
            status = r.status_code
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            err = (body.get("error") or {}) if isinstance(body, dict) else {}
            info = {"code": err.get("code"), "rule": (err.get("detail") or {}).get("rule"), "resp_KB": round(len(r.content) / 1024, 1)}
            if status == 201:
                info.update(regions=len(body.get("regions") or []), bom=len(body.get("bom_rows") or []))
        except Exception as e:  # noqa: BLE001
            status, info = type(e).__name__, {}
        dt = time.perf_counter() - t0
        stop[0] = True; th.join()
        st1 = state()
        res[name] = {"entities": raw.count(b"\n0\n") , "file_KB": round(len(raw) / 1024), "status": status, **info, "sec": round(dt, 2),
                     "rss_tree_peak_MB": round(max(peak)), "doc_rows_delta": st1[0] - st0[0], "files_delta": st1[1] - st0[1]}
        print(name, json.dumps(res[name], ensure_ascii=False), flush=True)
    res["server_alive"] = s.p.poll() is None
    res["health_after"] = httpx.get(BASE + "/api/v1/health", timeout=5).status_code
    res["rss_tree_end_MB"] = round(tree_rss(pid))
    res["children_after"] = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
finally:
    s.close()
(Path(__file__).parent / f"server_extract_r2{'-' + ms if ms else ''}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
