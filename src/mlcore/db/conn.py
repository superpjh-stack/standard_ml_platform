"""PostgreSQL 연결 (psycopg 3). 요청마다 짧은 연결 — 회사당 VPS 1대 규모 (spec §1.2)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings


class DbUnavailable(Exception):
    """DB 에 연결할 수 없다 — API 는 503 으로 바꾼다. 조용히 기본값으로 대체하지 않는다."""


def dsn(test: bool = False) -> str:
    s = get_settings()
    return s.test_db_dsn if test else s.db_dsn


@contextmanager
def connect(test: bool = False) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(dsn(test), row_factory=dict_row, connect_timeout=3)
    except psycopg.OperationalError as e:  # 원인은 남기되 DSN 값은 메시지에 넣지 않는다
        raise DbUnavailable(type(e).__name__) from e
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def q(sql: str, params: Any = None, *, test: bool = False) -> list[dict]:
    with connect(test) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def q1(sql: str, params: Any = None, *, test: bool = False) -> dict | None:
    rows = q(sql, params, test=test)
    return rows[0] if rows else None
