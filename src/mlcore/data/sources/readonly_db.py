"""읽기 전용 DB 연결 — gateway · mes 어댑터가 같이 쓴다 (interfaces §2 읽기 전용 규칙 · G-S05).

- 연결 직후 `SET default_transaction_read_only = on`(세션) — 이후 모든 문장이 읽기 전용 트랜잭션이다.
- 이중화(DEF-QA1-009 · D-88): 어댑터의 조회는 세션 설정과 별도로 **명시 트랜잭션 + `SET TRANSACTION READ ONLY`** 안에서 돈다
  (연결을 쥔 코드가 세션 기본값을 꺼도 어댑터 조회는 쓰기를 못 한다 — SELECT 가 부르는 쓰기 함수 · 뷰 포함).
  등록부 `read_role`(선택)이 있으면 연결 직후 `SET ROLE` 로 그 읽기 역할로 바꾼다(실패 → SourceDisconnected).
  `write_privileges()` 는 지금 계정(역할)이 허용목록 테이블에 쓰기 권한을 가졌는지 보고, probe 문구에 경고로 낸다 —
  권장 구성은 SELECT 권한만 있는 DB 역할이다(실 계정 권한 자체는 사람이 정한다, D-13).
- 조회는 SELECT 만, 테이블 이름은 식별자로만 넣는다(문자열 이어 붙이기 없음). 허용목록 밖 테이블은 거부한다.
- DSN 값은 등록부에 없다 — 등록부의 환경변수 **이름**(`dsn_env`)으로 프로세스 환경에서만 읽는다.
  실패 사유 문구에 DSN · 호스트 · 키를 넣지 않는다(예외 종류 이름만).
- 시험은 `connect=` 로 연결 함수를 주입한다(fixture 원천 사본 DB). 실 원천은 부르지 않는다(D-13).
"""

from __future__ import annotations

import os
from typing import Callable, Sequence

import pandas as pd

from .base import SourceDisconnected


def _ident(name: str):
    from psycopg import sql

    parts = [p for p in str(name).split(".") if p]
    if not parts or len(parts) > 2:
        raise SourceDisconnected("db", "테이블 이름 형식이 올바르지 않다")
    return sql.Identifier(*parts)


class ReadOnlyDb:
    def __init__(self, kind: str, *, dsn_env: str | None = None, connect: Callable | None = None,
                 allow: Sequence[str] = (), schema: str | None = None, role: str | None = None):
        self.kind = kind
        self.role = role
        self.dsn_env = dsn_env
        self._connect_fn = connect
        self.allow = tuple(allow)
        self.schema = schema

    # ── 연결 ──────────────────────────────────────────────
    def connect(self):
        import psycopg

        try:
            if self._connect_fn is not None:
                conn = self._connect_fn()
            else:
                if not self.dsn_env:
                    raise SourceDisconnected(self.kind, "dsn_env 없음 (등록부)")
                value = os.environ.get(self.dsn_env)
                if not value:
                    raise SourceDisconnected(self.kind, f"환경변수 {self.dsn_env} 가 비어 있다 (D-13 — 사람이 넣는다)")
                conn = psycopg.connect(value, connect_timeout=3, autocommit=True)
        except SourceDisconnected:
            raise
        except Exception as e:  # 연결 실패를 숨기지 않는다 — 사유는 예외 종류만(DSN 값 금지)
            raise SourceDisconnected(self.kind, f"연결 실패: {type(e).__name__}") from e
        if self.role:
            from psycopg import sql

            try:
                conn.autocommit = True
                conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(self.role)))
            except Exception as e:
                conn.close()
                raise SourceDisconnected(self.kind, f"읽기 역할 전환 실패: {type(e).__name__}") from e
        try:
            conn.autocommit = True
            conn.execute("SET default_transaction_read_only = on")
            if self.schema:
                from psycopg import sql

                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        except Exception as e:
            conn.close()
            raise SourceDisconnected(self.kind, f"읽기 전용 설정 실패: {type(e).__name__}") from e
        return conn

    @staticmethod
    def _read_only(conn, q, params=()):
        """명시 읽기 전용 트랜잭션 안에서 한 문장 → (열 이름, 행). 세션 기본값과 무관하다."""
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            cur = conn.execute(q, params)
            return [d.name for d in cur.description], cur.fetchall()

    def write_privileges(self, conn=None) -> list[str]:
        """허용목록 테이블 중 지금 계정(역할)이 쓰기 권한(INSERT · UPDATE · DELETE · TRUNCATE 중 하나)을 가진 것."""
        from psycopg import sql

        own = conn is None
        conn = conn or self.connect()
        try:
            out = []
            for t in self.allow:
                name = _ident(t).as_string(conn)
                _, rows = self._read_only(conn, "SELECT to_regclass(%s) IS NOT NULL AND "
                                                "has_table_privilege(to_regclass(%s), %s)",
                                          (name, name, "INSERT,UPDATE,DELETE,TRUNCATE"))
                r = rows[0]
                if (r[0] if not isinstance(r, dict) else next(iter(r.values()))):
                    out.append(t)
            return out
        except SourceDisconnected:
            raise
        except Exception as e:
            raise SourceDisconnected(self.kind, f"권한 조회 실패: {type(e).__name__}") from e
        finally:
            if own:
                conn.close()

    def privilege_note(self, conn=None) -> str:
        """probe 문구 덧붙임 — 쓰기 권한 계정이면 경고(숨기지 않는다). 확인 실패도 그대로 적는다."""
        try:
            w = self.write_privileges(conn)
        except SourceDisconnected as e:
            return f" · {e.reason}"
        return f" · 경고: 쓰기 권한 있는 계정(허용 테이블 {len(w)}개) — 읽기 전용 역할 권장" if w else " · 읽기 전용 계정"

    def _check(self, table: str) -> None:
        if self.allow and table not in self.allow:
            raise SourceDisconnected(self.kind, f"허용목록 밖 테이블 {table}")

    # ── 조회 (SELECT 만) ─────────────────────────────────
    def select(self, table: str, *, ts_column: str | None = None, ts_from=None, ts_to=None,
               limit: int | None = None, conn=None) -> pd.DataFrame:
        from psycopg import sql

        self._check(table)
        where, params = [], []
        if ts_column and ts_from is not None:
            where.append(sql.SQL("{} >= %s").format(sql.Identifier(ts_column)))
            params.append(ts_from)
        if ts_column and ts_to is not None:
            where.append(sql.SQL("{} <= %s").format(sql.Identifier(ts_column)))
            params.append(ts_to)
        q = sql.SQL("SELECT * FROM {}").format(_ident(table))
        if where:
            q = q + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where)
        if ts_column:
            q = q + sql.SQL(" ORDER BY {}").format(sql.Identifier(ts_column))
        if limit is not None:
            q = q + sql.SQL(" LIMIT %s")
            params.append(int(limit))
        own = conn is None
        conn = conn or self.connect()
        try:
            cols, rows = self._read_only(conn, q, params)
        except SourceDisconnected:
            raise
        except Exception as e:
            raise SourceDisconnected(self.kind, f"조회 실패({table}): {type(e).__name__}") from e
        finally:
            if own:
                conn.close()
        return pd.DataFrame([tuple(r.values()) if isinstance(r, dict) else tuple(r) for r in rows], columns=cols)

    def count(self, table: str, conn=None) -> int:
        from psycopg import sql

        self._check(table)
        own = conn is None
        conn = conn or self.connect()
        try:
            row = self._read_only(conn, sql.SQL("SELECT count(*) FROM {}").format(_ident(table)))[1][0]
        except Exception as e:
            raise SourceDisconnected(self.kind, f"행 수 조회 실패({table}): {type(e).__name__}") from e
        finally:
            if own:
                conn.close()
        return int(row["count"] if isinstance(row, dict) else row[0])
