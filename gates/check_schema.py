"""G-S01 — 스키마. 계약(contracts/db-schema.md) = 실제 DB(ml_db · ml_test_db) 열 단위 일치, 테이블 16 = spec §10.1 행 수,
spec §10.1 주요 열 포함, 전 테이블 tenant_id, production 부분 고유 색인, 추가만 3 테이블 UPDATE/DELETE 거부(실제 시도 · 롤백),
live + synthetic 승격 거부(실제 시도 · 롤백), 추가만 테이블 앱 역할 권한 SELECT · INSERT 만.
"""
from __future__ import annotations

import re

import psycopg

from gatelib import ROOT, Line, read, show

APPEND_ONLY = ("mlp_prediction", "mlp_audit", "mlp_quote")


def contract_columns() -> dict[str, list[tuple[str, str, str]]]:
    text = read(ROOT / "contracts" / "db-schema.md")
    out: dict[str, list] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^### \d+\. `(mlp_[a-z_]+)`", line)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        m = re.match(r"^\| `([a-z_0-9]+)` \| ([a-z ]+) \| ([YN]) \|$", line)
        if m and cur:
            out[cur].append((m.group(1), m.group(2).strip(), "YES" if m.group(3) == "Y" else "NO"))
        elif line.startswith("## ") and cur:
            cur = None
    return out


def spec_tables() -> dict[str, set[str]]:
    text = read(ROOT / "spec.md")
    sec = text[text.index("### 10.1"): text.index("### 10.2")]
    out = {}
    for line in sec.splitlines():
        m = re.match(r"^\| `(mlp_[a-z_]+)` \| [^|]+ \| (.+) \|$", line)
        if not m:
            continue
        cols = set()
        for tok in re.findall(r"`([a-z0-9_/]+)`", m.group(2)):
            if "/" in tok:
                a, b = tok.split("/")
                if a.endswith("_from"):            # ts_from/to
                    cols |= {a, a[: -len("from")] + b}
                elif b.endswith("_at"):            # started/finished_at
                    cols |= {a + "_at", b}
                else:
                    cols |= {a, b}
            else:
                cols.add(tok)
        out[m.group(1)] = cols
    return out


def db_columns(dbname: str) -> dict[str, list[tuple[str, str, str]]]:
    with psycopg.connect(f"dbname={dbname} host=/tmp", connect_timeout=3) as c:
        rows = c.execute("SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
                         "WHERE table_schema='public' AND table_name LIKE 'mlp\\_%' ORDER BY table_name, ordinal_position").fetchall()
    out: dict[str, list] = {}
    for t, col, ty, nl in rows:
        out.setdefault(t, []).append((col, ty, nl))
    return out


def behaviour(dbname: str) -> list[str]:
    """실제 시도 — 한 트랜잭션에서 최소 행을 만들고 금지 동작이 거부되는지 본 뒤 롤백."""
    problems = []
    with psycopg.connect(f"dbname={dbname} host=/tmp", connect_timeout=3, autocommit=False) as c:
        cur = c.cursor()
        cur.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES ('zzgate', 'gate', 'p', 'demo')")
        cur.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                    "VALUES ('zzgate', 'zzgate.t', 'p.t', 'regression', 'h', 'r')")
        cur.execute("INSERT INTO mlp_snapshot (snapshot_id, tenant_id, task_id, rows, columns, sha256, synthetic, path) "
                    "VALUES ('snp_gate', 'zzgate', 'zzgate.t', 1, '[]', %s, true, 'x')", ("0" * 64,))
        cur.execute("INSERT INTO mlp_train_run (run_id, tenant_id, task_id, snapshot_id, config_hash, seed, code_version, status) "
                    "VALUES ('run_gate', 'zzgate', 'zzgate.t', 'snp_gate', 'c', 1, 'g', 'succeeded')")
        model_sql = ("INSERT INTO mlp_model_version (tenant_id, task_id, version, run_id, snapshot_id, algo, metrics, beats_baseline, "
                     "stage, artifact_path, artifact_sha256, env_lock, code_version, synthetic) VALUES "
                     "('zzgate', 'zzgate.t', %s, 'run_gate', 'snp_gate', 'a', '{}', %s, %s, 'x', %s, '{}', 'g', true)")
        cur.execute(model_sql, ("v1", True, "production", "0" * 64))
        cur.execute("INSERT INTO mlp_prediction (prediction_id, tenant_id, task_id, version, inputs, outputs, status, caller, synthetic) "
                    "VALUES ('prd_gate', 'zzgate', 'zzgate.t', 'v1', '{}', '{}', 'ok', 'gate', true)")
        cur.execute("INSERT INTO mlp_audit (tenant_id, actor, action) VALUES ('zzgate', 'gate', 'probe')")
        cur.execute("INSERT INTO mlp_quote (quote_id, tenant_id, task_id, lines, total) VALUES ('q_gate', 'zzgate', 'zzgate.t', '[]', 0)")

        def must_fail(label, sql, params=None):
            cur.execute("SAVEPOINT s")
            try:
                cur.execute(sql, params)
                problems.append(f"{label} 가 허용됨")
            except psycopg.Error:
                pass
            cur.execute("ROLLBACK TO SAVEPOINT s")

        must_fail("두 번째 production", model_sql, ("v2", True, "production", "0" * 64))
        must_fail("기준선 못 이긴 staging", model_sql, ("v3", False, "staging", "0" * 64))
        for t in APPEND_ONLY:
            must_fail(f"{t} UPDATE", f"UPDATE {t} SET tenant_id = tenant_id WHERE tenant_id = 'zzgate'")
            must_fail(f"{t} DELETE", f"DELETE FROM {t} WHERE tenant_id = 'zzgate'")
            must_fail(f"{t} TRUNCATE", f"TRUNCATE {t}")
        # live 전환 → 합성 production 이 있으면 거부, 새 합성 staging 도 거부
        must_fail("live 회사 합성 production 유지", "UPDATE mlp_tenant SET mode = 'live' WHERE tenant_id = 'zzgate'")
        cur.execute("UPDATE mlp_model_version SET stage = 'archived' WHERE tenant_id = 'zzgate'")
        cur.execute("UPDATE mlp_tenant SET mode = 'live' WHERE tenant_id = 'zzgate'")
        must_fail("live 회사 합성 staging", model_sql, ("v4", True, "staging", "0" * 64))
        must_fail("live 회사 합성 production", model_sql, ("v5", True, "production", "0" * 64))
        must_fail("평문 API 키", "INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, consumer) VALUES ('zzgate', 'plain', 'p', 'admin', 'g')")
        c.rollback()
        # 권한 — 앱 역할은 추가만 테이블에 UPDATE · DELETE 가 없다
        for t in APPEND_ONLY:
            r = c.execute("SELECT has_table_privilege('mlp_app', %s, 'UPDATE') OR has_table_privilege('mlp_app', %s, 'DELETE')", (t, t)).fetchone()
            if r[0]:
                problems.append(f"mlp_app 이 {t} UPDATE/DELETE 권한을 가짐")
        idx = c.execute("SELECT indexdef FROM pg_indexes WHERE tablename='mlp_model_version' AND indexdef ILIKE '%%UNIQUE%%' "
                        "AND indexdef ILIKE '%%production%%'").fetchall()
        if not idx:
            problems.append("production 부분 고유 색인 없음")
        c.rollback()
    return problems


def run() -> list[Line]:
    contract = contract_columns()
    spec = spec_tables()
    problems: list[str] = []
    if len(contract) != 16 or len(spec) != 16:
        problems.append(f"테이블 수 계약 {len(contract)} · spec {len(spec)} (기대 16)")
    for t, cols in spec.items():
        have = {c for c, _, _ in contract.get(t, [])}
        missing = cols - have
        if missing:
            problems.append(f"{t}: spec 주요 열 누락 {sorted(missing)}")
    for t, cols in contract.items():
        if "tenant_id" not in {c for c, _, _ in cols}:
            problems.append(f"{t}: tenant_id 없음")
    dbs = {}
    for dbname in ("ml_db", "ml_test_db"):
        try:
            actual = db_columns(dbname)
        except psycopg.Error as e:
            problems.append(f"{dbname} 연결 실패 {type(e).__name__}")
            continue
        dbs[dbname] = len(actual)
        if set(actual) != set(contract):
            problems.append(f"{dbname}: 테이블 차이 계약-DB {sorted(set(contract) - set(actual))} DB-계약 {sorted(set(actual) - set(contract))}")
        for t in contract:
            if t in actual and actual[t] != contract[t]:
                a, b = set(actual[t]), set(contract[t])
                problems.append(f"{dbname}.{t}: 열 차이 DB만 {sorted(a - b)[:2]} 계약만 {sorted(b - a)[:2]}")
        try:
            problems += [f"{dbname}: {p}" for p in behaviour(dbname)]
        except psycopg.Error as e:
            problems.append(f"{dbname}: 동작 시험 오류 {type(e).__name__}: {str(e).splitlines()[0][:80]}")
    ncols = sum(len(v) for v in contract.values())
    if problems:
        return [Line("G-S01", "스키마", "FAIL", f"{len(problems)}건: " + "; ".join(problems[:5]))]
    return [Line("G-S01", "스키마", "PASS",
                 f"테이블 16 = spec 16 = 계약 16 = DB(ml_db {dbs.get('ml_db')} · ml_test_db {dbs.get('ml_test_db')}) · 열 {ncols} 일치 · "
                 f"tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
