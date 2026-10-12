"""G-M07 · G-M11 — 추가만 테이블 보호 = 트리거 + 권한 분리 (DEF-QA2-009 · 이슈 #16 · D-123). 소유 개발3(이번 회전 아키텍트 몫).

QA2 재현: 소유자 · 슈퍼유저가 `SET session_replication_role = replica` 로 트리거를 건너뛰어 mlp_audit UPDATE 성공,
`mlp_app` 역할은 만들기만 하고 권한이 맞지 않았다.
기대:
- 앱 역할 `mlp_app` 은 추가만 테이블(mlp_prediction · mlp_audit · mlp_quote)에 SELECT · INSERT 만 — UPDATE · DELETE · TRUNCATE 거부(권한).
- 나머지 테이블도 DELETE · TRUNCATE 없음(앱 코드에 DELETE 0 — 필요한 GRANT 만).
- 트리거는 `ENABLE ALWAYS` — replica 모드에서도 돈다.
- 권한 구간(`-- @grants-begin` 이후)은 **데이터를 지우지 않고** 기존 DB 에 다시 적용된다(`make db-grants`).

전용 DB `ml_grants_check_db` 를 쓴다(없으면 만들고 schema.sql 을 처음 한 번 적용 — 새 DB 확인). 이미 있으면 schema.sql 을
다시 적용하지 않는다(DROP 0). ml_db · ml_test_db 는 건드리지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = [pytest.mark.gate("G-M07")]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "mlcore" / "db" / "schema.sql"
DB = os.environ.get("MLP_GRANTS_DB") or "ml_grants_check_db"     # 새 DB 확인: MLP_GRANTS_DB=<없는 이름>
HOST = "/tmp"
APPEND_ONLY = ("mlp_prediction", "mlp_audit", "mlp_quote")
MUTABLE = ("mlp_tenant", "mlp_task", "mlp_source", "mlp_snapshot", "mlp_train_run", "mlp_model_version", "mlp_actual",
           "mlp_recommendation", "mlp_review_item", "mlp_document", "mlp_monitor_daily", "mlp_approval", "mlp_api_key")


def grants_section() -> str:
    text = SCHEMA.read_text(encoding="utf-8")
    i = text.index("\n-- @grants-begin")           # 줄 머리 표지 (Makefile db-grants 의 sed 와 같다)
    return text[i + 1:]


def _conn(db: str = DB, **kw):
    return psycopg.connect(f"dbname={db} host={HOST}", connect_timeout=3, **kw)


@pytest.fixture(scope="module")
def db():
    if shutil.which("psql") is None:
        pytest.fail("psql 없음 — PostgreSQL 17 클라이언트가 필요하다")
    try:
        with _conn("postgres", autocommit=True) as c:
            exists = c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone()
            if not exists:
                c.execute(f'CREATE DATABASE "{DB}"')
    except psycopg.OperationalError:
        pytest.fail("PostgreSQL(/tmp) 연결 불가")
    fresh = not exists
    if fresh:                                    # 새 DB — 스키마 전체를 처음 한 번
        r = subprocess.run(["psql", "-h", HOST, "-v", "ON_ERROR_STOP=1", "-q", "-d", DB, "-f", str(SCHEMA)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    else:                                        # 기존 DB — 보호 구간만(비파괴) 적용한 상태에서 본다
        r = subprocess.run(["psql", "-h", HOST, "-v", "ON_ERROR_STOP=1", "-q", "-d", DB], input=grants_section(),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    return {"fresh": fresh}


def _seed_one(c) -> str:
    tid = "g" + uuid.uuid4().hex[:6]
    c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s, 'grants', 'textile', 'demo')", (tid,))
    c.execute("INSERT INTO mlp_audit (tenant_id, actor, action) VALUES (%s, 'grants-test', 'seed')", (tid,))
    return tid


def test_grants_section_reapplies_without_data_loss(db):
    with _conn() as c:
        tid = _seed_one(c)
        before = c.execute("SELECT count(*) FROM mlp_audit").fetchone()[0]
    sql = grants_section()
    assert "DROP TABLE" not in sql and "TRUNCATE mlp" not in sql
    r = subprocess.run(["psql", "-h", HOST, "-v", "ON_ERROR_STOP=1", "-q", "-d", DB], input=sql, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["psql", "-h", HOST, "-v", "ON_ERROR_STOP=1", "-q", "-d", DB], input=sql, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr                                             # 두 번 적용해도 같다(멱등)
    with _conn() as c:
        assert c.execute("SELECT count(*) FROM mlp_audit").fetchone()[0] == before
        assert c.execute("SELECT 1 FROM mlp_tenant WHERE tenant_id = %s", (tid,)).fetchone()


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_app_role_cannot_modify_append_only(db, table):
    with _conn() as c:
        for priv in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not c.execute("SELECT has_table_privilege('mlp_app', %s, %s)", (table, priv)).fetchone()[0], (table, priv)
        for priv in ("SELECT", "INSERT"):
            assert c.execute("SELECT has_table_privilege('mlp_app', %s, %s)", (table, priv)).fetchone()[0], (table, priv)


def test_app_role_denied_at_runtime(db):
    with _conn() as c:
        tid = _seed_one(c)
    for sql in ("UPDATE mlp_audit SET action = 'x' WHERE tenant_id = %s", "DELETE FROM mlp_audit WHERE tenant_id = %s",
                "TRUNCATE mlp_audit", "DELETE FROM mlp_tenant WHERE tenant_id = %s"):
        with _conn() as c:
            c.execute("SET ROLE mlp_app")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql, (tid,) if "%s" in sql else None)
    with _conn() as c:                                                             # 앱이 할 일은 된다
        c.execute("SET ROLE mlp_app")
        c.execute("INSERT INTO mlp_audit (tenant_id, actor, action) VALUES (%s, 'grants-test', 'app-insert')", (tid,))
        c.execute("UPDATE mlp_tenant SET name = 'grants2' WHERE tenant_id = %s", (tid,))
        assert c.execute("SELECT count(*) FROM mlp_audit WHERE tenant_id = %s", (tid,)).fetchone()[0] == 2


def test_no_delete_or_truncate_on_mutable_tables(db):
    with _conn() as c:
        for table in MUTABLE:
            for priv in ("DELETE", "TRUNCATE"):
                assert not c.execute("SELECT has_table_privilege('mlp_app', %s, %s)", (table, priv)).fetchone()[0], (table, priv)
            for priv in ("SELECT", "INSERT", "UPDATE"):
                assert c.execute("SELECT has_table_privilege('mlp_app', %s, %s)", (table, priv)).fetchone()[0], (table, priv)


def test_replica_mode_does_not_skip_append_only_trigger(db):
    """QA2 재현: 소유자가 session_replication_role=replica 로 UPDATE 성공 → 이제 트리거가 ALWAYS 로 돈다."""
    with _conn() as c:
        tid = _seed_one(c)
    with _conn() as c:
        c.execute("SET session_replication_role = replica")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append_only"):
            c.execute("UPDATE mlp_audit SET action = 'x' WHERE tenant_id = %s", (tid,))
    with _conn() as c:
        c.execute("SET session_replication_role = replica")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append_only"):
            c.execute("TRUNCATE mlp_prediction")
