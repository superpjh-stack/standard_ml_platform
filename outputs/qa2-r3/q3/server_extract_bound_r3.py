"""QA2 재검증(r3) — #34 경계 · 회귀 (실서버 127.0.0.1:8215 · MLP_TENANT=kd · ml_qa2r3_db).
엔티티 20,000 / 20,001 경계(원만 · 원 + 사각 + 텍스트) · 호 20,000 · 원/호 혼합 · 파일 5 MiB 경계 · 판정용 결과 4 MiB 초과(DoS 방어 유지) ·
미리보기 줄임 표시(reduced/omitted)는 팩 추출기를 프로세스 안에서 직접 불러 확인(읽기만).
결과 → server_extract_bound_r3.json. 키는 scratchpad keys.json(출력 안 함). 고치지 않는다."""
import importlib.util, json, os, subprocess, sys, threading, time
from pathlib import Path
import httpx
from qa_lib import BASE, KEYS, ROOT, SP, Server
from mlcore.db.conn import connect

DOCS = Path(os.environ["MLP_DOCUMENT_DIR"])
K = KEYS["kd"]["operator"]
URL = BASE + "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents"


def tree_rss(root):
    out = subprocess.check_output(["ps", "-A", "-o", "pid=,ppid=,rss="]).decode().split("\n")
    rows = [tuple(map(int, l.split())) for l in out if l.strip()]
    kids, rss = {}, {}
    for p, pp, r in rows:
        kids.setdefault(pp, []).append(p); rss[p] = r
    tot, st = 0, [root]
    while st:
        p = st.pop(); tot += rss.get(p, 0); st += kids.get(p, [])
    return tot / 1024


def dxf_from(ents, pad_to=None):
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "4"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), *ents, (0, "ENDSEC"), (0, "EOF")]
    raw = "".join(f"{c}\n{v}\n" for c, v in pairs).encode()
    if pad_to is not None:                      # 앞에 999 주석 한 줄로 정확한 크기 맞추기
        need = pad_to - len(raw) - len("999\n\n")
        raw = ("999\n" + "x" * need + "\n").encode() + raw
        assert len(raw) == pad_to, (len(raw), pad_to)
    return raw


def rect(x0, y0, x1, y1, layer="BOM"):
    out = [(0, "LWPOLYLINE"), (8, layer), (90, "4"), (70, "1")]
    for px, py in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        out += [(10, str(px)), (20, str(py))]
    return out


def text(v, x, y, layer="T"):
    return [(0, "TEXT"), (8, layer), (10, str(x)), (20, str(y)), (30, "0"), (40, "3"), (1, v)]


def circle(cx, cy, r):
    return [(0, "CIRCLE"), (8, "C"), (10, str(cx)), (20, str(cy)), (30, "0"), (40, str(r))]


def arc(cx, cy, r):
    return [(0, "ARC"), (8, "A"), (10, str(cx)), (20, str(cy)), (30, "0"), (40, str(r)), (50, "0"), (51, "270")]


def circles(n):
    return [e for i in range(n) for e in circle((i % 150) * 10, (i // 150) * 10, 3)]


def arcs(n):
    return [e for i in range(n) for e in arc((i % 150) * 10, (i // 150) * 10, 3)]


FRAME = rect(-50, -50, 3000, 3000, "TITLE") + text("TITLE BLOCK", 0, 0)   # 엔티티 2
CASES = {  # 이름: (엔티티 수(설계값), 바이트)
    "circles_only_20000": (20000, dxf_from(circles(20000))),
    "circles_only_20001": (20001, dxf_from(circles(20001))),
    "circles_19998+frame=20000": (20000, dxf_from(circles(19998) + FRAME)),
    "circles_19999+frame=20001": (20001, dxf_from(circles(19999) + FRAME)),
    "arcs_only_20000": (20000, dxf_from(arcs(20000))),
    "circles10000+arcs10000": (20000, dxf_from(circles(10000) + arcs(10000))),
    "circles_3000+frame": (3002, dxf_from(circles(3000) + FRAME)),
    "circles_5000+frame": (5002, dxf_from(circles(5000) + FRAME)),
    "circles_19000_pad_5MiB": (19002, dxf_from(circles(19000) + FRAME, pad_to=5 * 1024 * 1024)),
    "circles_19000_pad_5MiB+1": (19002, dxf_from(circles(19000) + FRAME, pad_to=5 * 1024 * 1024 + 1)),
}
g = []                                       # 판정용 결과가 4 MiB 를 넘는 도면(긴 BOM 텍스트 2,200 영역) — DoS 방어 유지 확인
for i in range(2200):
    x, y = (i % 100) * 20, (i // 100) * 20
    g += rect(x, y, x + 10, y + 10) + text("BOM " + "X" * 1985, x + 5, y + 5, "BOM")
CASES["grid_longtext_2200(판정 결과 > 4MiB)"] = (4400, dxf_from(g))


def state():
    with connect() as c:
        n = c.execute("SELECT count(*) AS n FROM mlp_document WHERE tenant_id='kd'").fetchone()["n"]
    files = sum(1 for _ in DOCS.rglob("*") if _.is_file()) if DOCS.exists() else 0
    return n, files


res = {}
s = Server("kd", log=f"{SP}/server-kd-extract-bound.log")
try:
    pid = s.p.pid
    for name, (n_ent, raw) in CASES.items():
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
            r = httpx.post(URL, headers={"X-API-Key": K}, files={"file": (f"b.dxf", raw, "application/dxf")}, timeout=300)
            status = r.status_code
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            err = (body.get("error") or {}) if isinstance(body, dict) else {}
            info = {"code": err.get("code"), "rule": (err.get("detail") or {}).get("rule"), "resp_KB": round(len(r.content) / 1024, 1)}
            if status == 201:
                info.update(entity_count=body.get("entity_count"), regions=len(body.get("regions") or []),
                            has_preview_key="preview" in body)
        except Exception as e:  # noqa: BLE001
            status, info = type(e).__name__, {}
        dt = time.perf_counter() - t0
        stop[0] = True; th.join()
        st1 = state()
        res[name] = {"entities_design": n_ent, "file_bytes": len(raw), "status": status, **info, "sec": round(dt, 2),
                     "rss_tree_peak_MB": round(max(peak)), "doc_rows_delta": st1[0] - st0[0], "files_delta": st1[1] - st0[1]}
        print(name, json.dumps(res[name], ensure_ascii=False), flush=True)
    res["server_alive"] = s.p.poll() is None
    res["health_after"] = httpx.get(BASE + "/api/v1/health", timeout=5).status_code
    with open(f"{SP}/server-kd-extract-bound.log") as f:
        logtxt = f.read()
    res["server_log_traceback"] = logtxt.count("Traceback")
    res["server_log_500"] = logtxt.count('" 500')
finally:
    s.close()

# 미리보기 줄임 표시 — 팩 추출기 직접 호출(프로세스 안, 읽기만). 예산은 팩 YAML params 그대로
spec = importlib.util.spec_from_file_location("qa_r3_cad", ROOT / "packs/eto/extractors/cad_regions.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
from mlcore.tasks.extract import SPEC_LIMITS, fit_preview, _json_bytes  # noqa: E402
params = {"max_region_texts": 20000, "preview_max_points": 100000}
pv = {}
for name in ("circles_3000+frame", "circles_5000+frame", "circles_only_20000", "arcs_only_20000"):
    out = mod.extract(CASES[name][1], "b.dxf", unit="mm", limits=dict(SPEC_LIMITS), context={"params": params})
    p = out["preview"]
    fitted = fit_preview(out, dict(SPEC_LIMITS))["preview"]
    pv[name] = {"paths": len(p["paths"]), "points": sum(len(x["points"]) for x in p["paths"]), "reduced": p["reduced"],
                "preview_bytes": _json_bytes(p), "judge_bytes": _json_bytes({k: v for k, v in out.items() if k != "preview"}),
                "omitted_marker": fitted.get("omitted", False)}
    print("preview", name, json.dumps(pv[name], ensure_ascii=False), flush=True)
res["preview_direct"] = pv
(Path(__file__).parent / "server_extract_bound_r3.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
