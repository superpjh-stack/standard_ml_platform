"""QA2-2 실서버(127.0.0.1:8214 · MLP_TENANT=kd · ml_qa2r2_db) — 상한 안 최악 꼴 도면 1건의 시간 · RSS · 응답 크기, 50 MiB 청크 업로드.
키는 scratch 파일에서 읽고 출력하지 않는다. 결과 → server_dos-result.json"""
import json, os, subprocess, sys, threading, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import importlib
key = Path(sys.argv[1]).read_text().strip()
pid = int(subprocess.check_output(["lsof", "-tiTCP:8214", "-sTCP:LISTEN"]).split()[0])
def rss():
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)]).strip()) / 1024
def dxf(ents):
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "4"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), *ents, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode()
def rect(i):
    out = [(0, "LWPOLYLINE"), (8, "BOM"), (90, "4"), (70, "1")]
    for px, py in [(-i-1, -i-1), (i+1, -i-1), (i+1, i+1), (-i-1, i+1)]:
        out += [(10, str(px)), (20, str(py))]
    return out
res = {}
for n in (5000, 10000):
    ents = [e for i in range(n) for e in rect(i)] + [e for i in range(n) for e in [(0, "TEXT"), (8, "BOM"), (10, str(i + .5)), (20, "0"), (1, "BOM")]]
    raw = dxf(ents)
    bnd = "QA22"
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"w.dxf\"\r\nContent-Type: application/dxf\r\n\r\n").encode() + raw + f"\r\n--{bnd}--\r\n".encode()
    peak = [rss()]; stop = [False]
    def watch():
        while not stop[0]:
            try: peak.append(rss())
            except Exception: pass
            time.sleep(0.2)
    th = threading.Thread(target=watch); th.start()
    t0 = time.perf_counter()
    req = urllib.request.Request("http://127.0.0.1:8214/api/v1/tenants/kd/tasks/kd.drawing_regions/documents", data=body, method="POST",
                                 headers={"X-API-Key": key, "Content-Type": f"multipart/form-data; boundary={bnd}"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            status, size = r.status, len(r.read())
    except urllib.error.HTTPError as e:
        status, size = e.code, len(e.read())
    except Exception as e:
        status, size = f"{type(e).__name__}", 0
    dt = time.perf_counter() - t0
    stop[0] = True; th.join()
    res[f"entities_{2*n}"] = {"file_MB": round(len(raw) / 2**20, 2), "status": status, "sec": round(dt, 1), "resp_MB": round(size / 2**20, 1),
                               "rss_before_MB": round(peak[0]), "rss_peak_MB": round(max(peak))}
    print(json.dumps(res, ensure_ascii=False))
# 50 MiB 청크(Content-Length 없음)
def gen():
    head = b"--QA22\r\nContent-Disposition: form-data; name=\"file\"; filename=\"big.dxf\"\r\n\r\n"
    yield head
    for _ in range(50):
        yield b"0\nLINE\n" * (2**20 // 7)
import http.client
c = http.client.HTTPConnection("127.0.0.1", 8214, timeout=60)
t0 = time.perf_counter()
try:
    c.putrequest("POST", "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents")
    c.putheader("X-API-Key", key); c.putheader("Content-Type", "multipart/form-data; boundary=QA22"); c.putheader("Transfer-Encoding", "chunked")
    c.endheaders()
    sent = 0
    for ch in gen():
        c.send(f"{len(ch):x}\r\n".encode() + ch + b"\r\n"); sent += len(ch)
    c.send(b"0\r\n\r\n")
    r = c.getresponse(); res["chunked_50MiB"] = {"status": r.status, "sec": round(time.perf_counter() - t0, 2), "sent_MB": round(sent / 2**20)}
except Exception as e:
    res["chunked_50MiB"] = {"error": type(e).__name__, "sec": round(time.perf_counter() - t0, 2)}
res["rss_end_MB"] = round(rss())
print(json.dumps(res, ensure_ascii=False))
(Path(__file__).parent / "server_dos-result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
