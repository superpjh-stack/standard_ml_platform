"""QA-R2 — DEF-QA1-009 추가 공격: 허용 '뷰' 가 쓰기 함수를 부르면? probe 의 쓰기 권한 경고 · read_role 실패 처리."""
import sys
from pathlib import Path
import psycopg
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.data.sources import GatewaySource, SourceDisconnected
from mlcore.data.sources.readonly_db import ReadOnlyDb
DSN = "dbname=ml_qar2_db host=/tmp"
with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("DROP SCHEMA IF EXISTS qa_src2 CASCADE; CREATE SCHEMA qa_src2;"
              "CREATE TABLE qa_src2.log (x int); CREATE TABLE qa_src2.r (id int, ts timestamptz, v float);"
              "INSERT INTO qa_src2.r SELECT g, now(), g FROM generate_series(1,5) g;"
              "CREATE FUNCTION qa_src2.w() RETURNS int LANGUAGE sql VOLATILE AS 'INSERT INTO qa_src2.log VALUES (1) RETURNING 1';"
              "CREATE VIEW qa_src2.v AS SELECT r.*, qa_src2.w() AS side FROM qa_src2.r r;")
conn = lambda: psycopg.connect(DSN)
db = ReadOnlyDb("gateway", connect=conn, allow=("qa_src2.v",))
try:
    out = db.select("qa_src2.v"); print("쓰기 함수 뷰 SELECT: 막지 않음", len(out))
except SourceDisconnected as e:
    print("쓰기 함수 뷰 SELECT: PASS 거부 —", e.reason[:90])
with psycopg.connect(DSN) as c:
    print("log 행 수(0 이어야):", c.execute("SELECT count(*) FROM qa_src2.log").fetchone()[0])
g = GatewaySource("qa_src2.r", connect=conn)
try:
    p = g.probe(); print("probe:", {k: p.get(k) for k in ("status", "message", "reason")} if isinstance(p, dict) else p)
except Exception as e:
    print("probe 예외", type(e).__name__, e)
try:
    g2 = GatewaySource("qa_src2.r", connect=conn, read_role="qa_no_such_role")
    print("read_role 없는 역할:", g2.probe())
except TypeError as e:
    print("read_role 인자 없음:", e)
except SourceDisconnected as e:
    print("read_role 없는 역할: PASS", e.reason[:80])
with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("DROP SCHEMA qa_src2 CASCADE")
