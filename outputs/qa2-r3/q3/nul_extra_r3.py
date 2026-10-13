"""QA2 재검증(r3) — 본문 밖 NUL(조회 문자열 · 경로 · 업로드 파일 이름) 범위 확인. 실서버 8215 · ml_qa2r3_db. 고치지 않는다.
결과 행 → rows_nul_extra_r3.txt"""
import importlib.util, json
import httpx
from qa_lib import BASE, KEYS, ROOT, SP, Server, call, check, dump

rows = []
s = Server("kd", log=f"{SP}/server-kd-nul-extra.log")
try:
    for label, path in [("표준 견적 목록 search", "/api/v1/tenants/kd/tasks/kd.quote/quotes?search=a%00b"),
                        ("표준 견적 목록 search(NUL 만)", "/api/v1/tenants/kd/tasks/kd.quote/quotes?search=%00"),
                        ("표준 문서 목록 search", "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents?search=a%00b"),
                        ("옛 견적 목록 search", "/api/quotes?search=a%00b"),
                        ("옛 견적 CSV 내보내기 search", "/api/quotes/export/csv?search=a%00b"),
                        ("표준 견적 CSV id", "/api/v1/tenants/kd/tasks/kd.quote/quotes/q%00x/csv"),
                        ("표준 문서 조회 id", "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents/doc_%00"),
                        ("옛 도면 조회 id", "/api/cad/a%00b"),
                        ("표준 견적 목록 cursor", "/api/v1/tenants/kd/tasks/kd.quote/quotes?cursor=a%00b")]:
        st, e = call("GET", path, t="kd", role="operator")
        check("N-q", f"kd GET {label} NUL", st != 500, f"HTTP {st}")
    spec = importlib.util.spec_from_file_location("qa_r3_sample2", ROOT / "packs/eto/synth/sample_dxf.py")
    smod = importlib.util.module_from_spec(spec); spec.loader.exec_module(smod)
    import yaml
    mats = yaml.safe_load(open(ROOT / "tenants/kd.yaml"))["categories"]["main_material"]
    raw = smod.sample_bytes(mats) + b"\n"          # 앞 업로드와 다른 바이트
    r = httpx.post(BASE + "/api/v1/tenants/kd/tasks/kd.drawing_regions/documents", headers={"X-API-Key": KEYS["kd"]["operator"]},
                   files={"file": ("a\x00b.dxf", raw, "application/dxf")}, timeout=60)
    check("N-f", "kd 업로드 파일 이름 NUL", r.status_code != 500, f"HTTP {r.status_code} {r.text[:120]}")
finally:
    s.close()
log = open(f"{SP}/server-kd-nul-extra.log").read()
check("LOG", "kd 서버 로그 500 수(관찰)", True, f"500 {log.count(' 500 ')} · Traceback {log.count('Traceback')}")
dump("rows_nul_extra_r3.txt")
