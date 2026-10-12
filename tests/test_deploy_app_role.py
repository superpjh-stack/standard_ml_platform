"""F7-7 · D-123 — compose 앱 계정 = `mlp_app` 구성원 LOGIN 역할 (DEF-QA2-009 잔여 · 이슈 #7 · #16). 소유 개발3.

기대:
- db 컨테이너 첫 기동이 schema.sql(10) 다음에 `docker/initdb/20-app-login.sh`(20)를 돌려 LOGIN 역할을 만든다:
  이름 · 비밀번호는 `.env.deploy` 의 `MLP_DB_APP_USER` · `MLP_DB_APP_PASSWORD`(값은 저장소에 0), `IN ROLE mlp_app`,
  슈퍼유저 · DB 생성 · 역할 생성 · 복제 · RLS 우회 없음, 소유자(POSTGRES_USER)와 다른 이름이어야 한다.
- 앱(MLP_DB_DSN)은 그 역할로 붙는다 — 추가만 테이블 UPDATE · DELETE · TRUNCATE 거부, 테이블 DDL(소유자 권한) 거부, 앱 DML 은 된다.
- 스크립트는 멱등(두 번 돌려도 오류 0 · 역할 하나).
시험은 임시 DB `mlp_tmp_role_<hex>` 와 임시 역할 `mlp_tmp_app_<hex>` 를 만들고 끝나면 지운다(F7-8 — 시험이 만든 것만).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import psycopg
import pytest
import yaml

pytestmark = [pytest.mark.gate("G-M11")]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docker" / "initdb" / "20-app-login.sh"
SCHEMA = ROOT / "src" / "mlcore" / "db" / "schema.sql"
HOST = "/tmp"
TMP_PREFIX = "mlp_tmp_"


def _admin(**kw):
    return psycopg.connect(f"dbname=postgres host={HOST}", connect_timeout=3, autocommit=True, **kw)


def test_compose_mounts_init_script_after_schema():
    cfg = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    vols = cfg["services"]["db"]["volumes"]
    targets = {v.split(":")[1]: v.split(":")[0] for v in vols if ":" in v and v.startswith("./")}
    assert targets["/docker-entrypoint-initdb.d/10-schema.sql"] == "./src/mlcore/db/schema.sql"
    assert targets["/docker-entrypoint-initdb.d/20-app-login.sh"] == "./docker/initdb/20-app-login.sh"
    assert os.access(SCRIPT, os.X_OK)                                   # 엔트리포인트가 source 가 아니라 실행하게
    env = cfg["services"]["app"].get("environment") or {}
    assert not any(re.search(r"PASSWORD|DSN", k) for k in env)          # 비밀은 env_file 만(G-M11)


def test_deploy_env_example_has_names_only():
    lines = (ROOT / "docker" / "deploy.env.example").read_text(encoding="utf-8").splitlines()
    kv = dict(l.split("=", 1) for l in lines if l and not l.startswith("#") and "=" in l)
    assert kv.get("MLP_DB_APP_USER") == "" and kv.get("MLP_DB_APP_PASSWORD") == ""
    assert all(v == "" for v in kv.values())                           # 값 0


def test_script_has_no_literal_secret_and_checks_inputs():
    txt = SCRIPT.read_text(encoding="utf-8")
    assert "\\getenv" in txt and "IN ROLE mlp_app" in txt and "NOSUPERUSER" in txt
    assert "PASSWORD %L" in txt                                         # format %L — 값은 리터럴로만(주입 0)
    assert not re.search(r"PASSWORD\s+'[^%]", txt)


@pytest.fixture()
def tmp_db():
    if shutil.which("psql") is None:
        pytest.fail("psql 없음 — PostgreSQL 17 클라이언트가 필요하다")
    db, role = f"{TMP_PREFIX}role_{secrets.token_hex(4)}", f"{TMP_PREFIX}app_{secrets.token_hex(4)}"
    try:
        with _admin() as c:
            c.execute(f'CREATE DATABASE "{db}"')
    except psycopg.OperationalError:
        pytest.fail("PostgreSQL(/tmp) 연결 불가")
    r = subprocess.run(["psql", "-h", HOST, "-v", "ON_ERROR_STOP=1", "-q", "-d", db, "-f", str(SCHEMA)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    try:
        yield {"db": db, "role": role}
    finally:                                                             # 시험이 만든 것만 지운다(이름 접두 확인)
        assert db.startswith(TMP_PREFIX) and role.startswith(TMP_PREFIX)
        with _admin() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                c.execute(f'DROP ROLE "{role}"')


def run_script(tmp: dict, *, user: str | None = None, password: str | None = "pw-" + secrets.token_hex(6)):
    env = {**os.environ, "PGHOST": HOST, "POSTGRES_DB": tmp["db"], "POSTGRES_USER": os.environ.get("USER", "postgres")}
    env.pop("MLP_DB_APP_USER", None)
    env.pop("MLP_DB_APP_PASSWORD", None)
    if user is not None:
        env["MLP_DB_APP_USER"] = user
    if password is not None:
        env["MLP_DB_APP_PASSWORD"] = password
    return subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)


def test_login_role_created_member_of_mlp_app_and_least_privilege(tmp_db):
    r = run_script(tmp_db, user=tmp_db["role"])
    assert r.returncode == 0, r.stderr
    assert run_script(tmp_db, user=tmp_db["role"]).returncode == 0      # 멱등
    with _admin() as c:
        row = c.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit "
                        "FROM pg_roles WHERE rolname = %s", (tmp_db["role"],)).fetchone()
        assert row == (True, False, False, False, False, False, True)
        assert c.execute("SELECT pg_has_role(%s, 'mlp_app', 'MEMBER')", (tmp_db["role"],)).fetchone()[0]
    with psycopg.connect(f"dbname={tmp_db['db']} host={HOST} user={tmp_db['role']}", connect_timeout=3) as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES ('zz', 'role', 'textile', 'demo')")
        c.execute("INSERT INTO mlp_audit (tenant_id, actor, action) VALUES ('zz', 'role-test', 'insert')")
        c.execute("UPDATE mlp_tenant SET name = 'role2' WHERE tenant_id = 'zz'")
        c.commit()
        for sql in ("UPDATE mlp_audit SET action = 'x'", "DELETE FROM mlp_audit", "TRUNCATE mlp_prediction",
                    "DELETE FROM mlp_tenant", "ALTER TABLE mlp_audit DISABLE TRIGGER ALL", "DROP TABLE mlp_quote",
                    "SET session_replication_role = replica"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
            c.rollback()


def test_script_refuses_missing_values_or_owner_name(tmp_db):
    assert run_script(tmp_db, user=None).returncode != 0
    assert run_script(tmp_db, user=tmp_db["role"], password=None).returncode != 0
    assert run_script(tmp_db, user=tmp_db["role"], password="").returncode != 0
    r = run_script(tmp_db, user=os.environ.get("USER", "postgres"))
    assert r.returncode != 0 and "소유자" in (r.stderr + r.stdout)
    with _admin() as c:
        assert not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (tmp_db["role"],)).fetchone()
