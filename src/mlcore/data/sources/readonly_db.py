"""읽기 전용 DB 연결 — gateway · mes 어댑터가 같이 쓴다 (interfaces §2 읽기 전용 규칙 · G-S05).

- 연결 직후 `SET default_transaction_read_only = on`(세션) — 이후 모든 문장이 읽기 전용 트랜잭션이다.
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
                 allow: Sequence[str] = (), schema: str | None = None):
        self.kind = kind
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
            cur = conn.execute(q, params)
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
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
            row = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(_ident(table))).fetchone()
        except Exception as e:
            raise SourceDisconnected(self.kind, f"행 수 조회 실패({table}): {type(e).__name__}") from e
        finally:
            if own:
                conn.close()
        return int(row["count"] if isinstance(row, dict) else row[0])
