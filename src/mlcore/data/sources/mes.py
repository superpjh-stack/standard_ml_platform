"""mes 어댑터 — MES DB 읽기 계정, **허용목록 테이블만** (spec §4.1 · 표준 MES · Agent 플랫폼 SQL 가드). 읽기 전용(G-S05).

등록부 `sources.<name>`: `{kind: mes, tables: [허용목록], dsn_env, join_on?, ts_column?, entity_column?, read_role?}`
- 허용목록 밖 테이블은 조회하지 않는다(SourceDisconnected). 자유 SQL 은 받지 않는다 — 테이블 단위 SELECT 만.
- 열 대응은 회사 `feature_map` · `target_map`(`<테이블>.<열>` → 팩 변수). 대응에 나온 테이블만 읽고,
  둘 이상이면 `join_on` 열로 왼쪽 결합(허용목록 순서). 결합 키가 등록부에 없으면 지어내지 않고 실패를 보인다.
테이블 · 열 이름은 코어가 모른다 — 전부 등록부에서 온다.
"""

from __future__ import annotations

from typing import Callable, Sequence

import pandas as pd

from ..frame import health_from_frame, standardize
from .base import ReadSpec, SourceDisconnected, SourceHealth
from .readonly_db import ReadOnlyDb


class MesSource:
    kind = "mes"

    def __init__(self, tables: Sequence[str], *, dsn_env: str | None = None, connect: Callable | None = None,
                 schema: str | None = None, join_on: str | None = None, ts_column: str | None = None,
                 entity_column: str | None = None, read_role: str | None = None):
        if not tables:
            raise SourceDisconnected(self.kind, "허용목록(tables) 없음")
        self.tables = tuple(tables)
        self.db = ReadOnlyDb(self.kind, dsn_env=dsn_env, connect=connect, allow=self.tables, schema=schema, role=read_role)
        self.join_on, self.ts_column, self.entity_column = join_on, ts_column, entity_column

    @classmethod
    def from_config(cls, cfg: dict, *, connect: Callable | None = None) -> "MesSource":
        return cls(cfg.get("tables") or (), dsn_env=cfg.get("dsn_env"), connect=connect, schema=cfg.get("schema"),
                   join_on=cfg.get("join_on"), ts_column=cfg.get("ts_column"), entity_column=cfg.get("entity_column"),
                   read_role=cfg.get("read_role"))

    def source_ref(self) -> dict:
        return {"kind": self.kind, "tables": list(self.tables), "join_on": self.join_on}

    def _used(self, columns_map: dict) -> list[str]:
        named = {str(k).split(".", 1)[0] for k in columns_map if "." in str(k)}
        outside = sorted(named - set(self.tables))
        if outside:
            raise SourceDisconnected(self.kind, f"대응표가 허용목록 밖 테이블을 가리킨다: {outside}")
        return [t for t in self.tables if t in named] or [self.tables[0]]

    def _joined(self, spec: ReadSpec) -> pd.DataFrame:
        cmap = dict(spec.columns_map)
        used = self._used(cmap)
        if len(used) > 1 and not self.join_on:
            raise SourceDisconnected(self.kind, f"테이블 {len(used)}개 결합 키(join_on) 미확인")
        conn = self.db.connect()
        try:
            out = None
            for t in used:
                df = self.db.select(t, conn=conn)
                ren = {str(k).split(".", 1)[1]: v for k, v in cmap.items()
                       if str(k).startswith(t + ".") and str(k).split(".", 1)[1] in df.columns}
                keep = [c for c in df.columns if c in ren or c in (self.join_on, self.ts_column, self.entity_column)]
                df = df[keep].rename(columns=ren)
                if out is None:
                    out = df
                else:
                    if self.join_on not in df.columns or self.join_on not in out.columns:
                        raise SourceDisconnected(self.kind, f"결합 키 {self.join_on} 가 테이블 {t} 에 없다")
                    df = df.drop(columns=[c for c in df.columns if c in out.columns and c != self.join_on])
                    out = out.merge(df, how="left", on=self.join_on, validate="many_to_one")
        except pd.errors.MergeError as e:
            raise SourceDisconnected(self.kind, f"결합 키가 유일하지 않다: {type(e).__name__}") from e
        finally:
            conn.close()
        if self.ts_column and self.ts_column in out.columns:
            out["ts"] = out[self.ts_column]
        key = self.entity_column or self.join_on
        if key and key in out.columns:
            out["entity_id"] = out[key].astype(str)
        return out

    def read(self, spec: ReadSpec) -> pd.DataFrame:
        frame = standardize(self._joined(spec), spec, kind=self.kind, source_ref="mes:" + "+".join(self._used(spec.columns_map)))
        return frame

    def probe(self, spec: ReadSpec | None = None) -> SourceHealth:
        try:
            if spec is None:
                conn = self.db.connect()
                try:
                    n = self.db.count(self.tables[0], conn=conn)
                    note = self.db.privilege_note(conn)
                finally:
                    conn.close()
                return SourceHealth(self.kind, True, n, None, None, None, None, {}, None, "MES 읽기 계정 연결" + note)
            frame = self.read(spec)
            note = self.db.privilege_note()
        except SourceDisconnected as e:
            return SourceHealth(self.kind, False, None, None, None, None, None, {}, None, e.reason)
        return health_from_frame(self.kind, frame, spec, "MES 읽기 계정 연결" + note)
