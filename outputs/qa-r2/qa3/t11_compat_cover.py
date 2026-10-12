"""QA3 t11 — task-map 32 단위 중 경로가 있는 단위(엔드포인트 7 × 2)를 실제 HTTP 로 확인. 서버 MLP_TENANT=$QAR2_TENANT."""
import os, sys
from qa_lib import call, check, dump
t = os.environ["QAR2_TENANT"]; up = t.upper()
pred = "/api/maintenance/predict" if t == "ks" else "/api/quality/predict"
for gid, m, p, want in ((f"{up}-E1", "GET", "/api/health", 200), (f"{up}-E2", "GET", "/api/ml/overview", 200),
                        (f"{up}-E5", "GET", "/api/data/records?limit=2", 200), (f"{up}-E6", "GET", f"/api/data/records/{up}-DEMO-0001", 200),
                        (f"{up}-E6", "GET", f"/api/data/records/{up}-DEMO-9999", 404), (f"{up}-E7", "GET", "/", None),
                        (f"{up}-E7", "GET", "/app/overview", 200), (f"{up}-E1(std)", "GET", "/api/v1/health", 200)):
    st, b = call(m, p, role="admin")
    ok = st == want if want else st in (200, 307, 302)
    check("G-M02", f"{gid} {m} {p}", ok, f"HTTP {st} {str(b)[:120] if st >= 400 else ''}")
dump(sys.argv[1])
