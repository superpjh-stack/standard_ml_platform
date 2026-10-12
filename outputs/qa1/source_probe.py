"""QA1 G-S05 — 읽기 전용 우회 시도 (SQL 주입 · 다문장 · 허용목록 밖 · 쓰기 · 비 GET). QA 전용 DB ml_qa1_db 의 qa_src 스키마만 쓴다.
실행: source outputs/qa1/env.sh && uv run python outputs/qa1/source_probe.py"""
import sys, os
from pathlib import Path
import psycopg
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from mlcore.data.sources import GatewaySource, MesSource, DataPlatformSource, SourceDisconnected
from mlcore.data.sources.readonly_db import ReadOnlyDb
DSN = "dbname=ml_qa1_db host=/tmp"
with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("DROP SCHEMA IF EXISTS qa_src CASCADE; CREATE SCHEMA qa_src;"
              "CREATE TABLE qa_src.readings (id int, ts timestamptz, eq text, v float);"
              "INSERT INTO qa_src.readings SELECT g, now() - g * interval '1 hour', 'E' || (g % 3), g FROM generate_series(1, 50) g;"
              "CREATE TABLE qa_src.secret (x int); INSERT INTO qa_src.secret VALUES (1),(2);")
def counts():
    with psycopg.connect(DSN) as c:
        return tuple(c.execute(f"SELECT count(*) FROM qa_src.{t}").fetchone()[0] for t in ("readings", "secret"))
before = counts()
conn = lambda: psycopg.connect(DSN)
res = []
def attempt(name, fn, expect_block=True):
    try:
        out = fn()
        res.append((name, "FAIL" if expect_block else "PASS", f"막지 않음 → {str(out)[:80]}"))
    except SourceDisconnected as e:
        res.append((name, "PASS" if expect_block else "FAIL", f"SourceDisconnected: {e.reason[:80]}"))
    except Exception as e:
        res.append((name, "PASS" if expect_block else "FAIL", f"{type(e).__name__}: {str(e)[:80]}"))
db = ReadOnlyDb("gateway", connect=conn, allow=("qa_src.readings",))
attempt("허용 테이블 SELECT", lambda: len(db.select("qa_src.readings")), expect_block=False)
attempt("허용목록 밖 테이블", lambda: db.select("qa_src.secret"))
attempt("시스템 카탈로그", lambda: db.select("pg_catalog.pg_user"))
bad = "qa_src.readings; DROP TABLE qa_src.secret"
attempt("다문장(허용목록에 있어도)", lambda: ReadOnlyDb("gateway", connect=conn, allow=(bad,)).select(bad))
attempt("인용부호 탈출 테이블명", lambda: ReadOnlyDb("gateway", connect=conn, allow=('readings" ; DELETE FROM "secret',)).select('readings" ; DELETE FROM "secret'))
attempt("ts_column 주입", lambda: db.select("qa_src.readings", ts_column="ts; DELETE FROM qa_src.secret --", ts_from="2020-01-01"))
attempt("ts_from 값 주입", lambda: len(db.select("qa_src.readings", ts_column="ts", ts_from="2020-01-01'; DELETE FROM qa_src.secret; --")))
def write_through():
    c = db.connect(); 
    try: c.execute("INSERT INTO qa_src.secret VALUES (99)")
    finally: c.close()
attempt("연결 객체로 INSERT", write_through)
def toggle():
    c = db.connect()
    try:
        c.execute("SET default_transaction_read_only = off"); c.execute("INSERT INTO qa_src.secret VALUES (98)"); return "쓰기 성공"
    finally: c.close()
attempt("세션 read_only 끄고 INSERT (연결 객체 직접 — 어댑터 API 밖)", toggle)
attempt("Gateway 허용목록 = table 하나", lambda: GatewaySource("qa_src.readings", connect=conn).db.select("qa_src.secret"))
attempt("Mes 대응표가 허용목록 밖 테이블", lambda: MesSource(["qa_src.readings"], connect=conn)._used({"qa_src.secret.x": "f"}) if False else MesSource(["readings"], connect=conn)._used({"secret.x": "f"}))
after = counts()
res.append(("원천 행 수 diff", "PASS" if before == after else "FAIL", f"전 {before} 후 {after} (98 행이 생겼다면 어댑터 밖 우회)"))
# dataplatform: 전송 주입으로 메서드 · 본문 관찰
seen = []
import urllib.request
orig = urllib.request.urlopen
def fake(req, timeout=None):
    seen.append((req.get_method(), req.data)); raise urllib.error.URLError("qa-offline")
import urllib.error
urllib.request.urlopen = fake
os.environ["QA_DP_URL"] = "http://dp.invalid"; os.environ["QA_DP_KEY"] = "k"
attempt("dataplatform 기본 전송 메서드", lambda: DataPlatformSource(url_env="QA_DP_URL", key_env="QA_DP_KEY", view="v").probe() and seen, expect_block=False)
urllib.request.urlopen = orig
res.append(("dataplatform 요청 메서드 · 본문", "PASS" if seen and all(m == "GET" and d is None for m, d in seen) else "FAIL", f"관찰 {seen}"))
with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("DROP SCHEMA qa_src CASCADE")
for n, s, m in res:
    print(f"G-S05  {n:52s} {s:5s} {m}")
