"""gateway 어댑터 — Data Gateway 원장 DB 를 읽기 계정 SELECT 로 읽는다 (spec §4.1). 읽기 전용(G-S05).

등록부 `sources.<name>`: `{kind: gateway, table, dsn_env, ts_column?, entity_column?, pivot?, window?, agg?, read_role?}`
- `table` 한 개만 읽는다(허용목록 = 그 테이블). 열 대응은 회사 `feature_map`(ReadSpec.columns_map).
- `pivot: {key, value}` — 원장이 (태그, 값) 세로 형식이면 태그별 열로 편다(같은 시각 · 설비의 중복은 평균).
- `window: "1h"` + `entity_column` — 시간 창 집계(spec §4.1 "평균 · 최대 · 표준편차"). `agg` 기본 mean
  (`mean | max | min | std`, 열별 `agg_by: {열: max}`). entity_id = `<설비>@<창 시작 ISO>`, ts = 창 시작.
원장 열 이름 · 태그 이름은 코어가 모른다 — 전부 등록부에서 온다. 확인 못 한 값은 등록부가 null 로 두고,
그러면 이 어댑터는 SourceDisconnected 로 실패를 보인다(지어내지 않는다).
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from ..frame import health_from_frame, standardize
from .base import ReadSpec, SourceDisconnected, SourceHealth
from .readonly_db import ReadOnlyDb

AGGS = ("mean", "max", "min", "std")


class GatewaySource:
    kind = "gateway"

    def __init__(self, table: str | None, *, dsn_env: str | None = None, connect: Callable | None = None,
                 schema: str | None = None, ts_column: str | None = None, entity_column: str | None = None,
                 pivot: dict | None = None, window: str | None = None, agg: str = "mean", agg_by: dict | None = None,
                 read_role: str | None = None):
        if not table:
            raise SourceDisconnected(self.kind, "table 없음 (등록부 미확인)")
        self.table = table
        self.db = ReadOnlyDb(self.kind, dsn_env=dsn_env, connect=connect, allow=(table,), schema=schema, role=read_role)
        self.ts_column, self.entity_column = ts_column, entity_column
        self.pivot = dict(pivot or {}) or None
        self.window = window
        if agg not in AGGS or any(a not in AGGS for a in (agg_by or {}).values()):
            raise SourceDisconnected(self.kind, f"집계 함수는 {AGGS} 만")
        self.agg, self.agg_by = agg, dict(agg_by or {})
        if window and not entity_column:
            raise SourceDisconnected(self.kind, "window 집계에는 entity_column 이 필요하다")

    @classmethod
    def from_config(cls, cfg: dict, *, connect: Callable | None = None) -> "GatewaySource":
        return cls(cfg.get("table"), dsn_env=cfg.get("dsn_env"), connect=connect, schema=cfg.get("schema"),
                   ts_column=cfg.get("ts_column"), entity_column=cfg.get("entity_column"), pivot=cfg.get("pivot"),
                   read_role=cfg.get("read_role"),
                   window=cfg.get("window"), agg=cfg.get("agg", "mean"), agg_by=cfg.get("agg_by"))

    def source_ref(self) -> dict:
        return {"kind": self.kind, "table": self.table, "window": self.window, "agg": self.agg if self.window else None}

    def _raw(self, spec: ReadSpec | None) -> pd.DataFrame:
        return self.db.select(self.table, ts_column=self.ts_column,
                              ts_from=getattr(spec, "ts_from", None), ts_to=getattr(spec, "ts_to", None))

    def _shape(self, raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.copy()
        keys = [c for c in (self.entity_column, self.ts_column) if c]
        if self.pivot:
            k, v = self.pivot.get("key"), self.pivot.get("value")
            if k not in df.columns or v not in df.columns or not keys:
                raise SourceDisconnected(self.kind, "pivot 열(key · value) 또는 entity/ts 열이 원장에 없다")
            df = df.pivot_table(index=keys, columns=k, values=v, aggfunc="mean").reset_index()
            df.columns = [str(c) for c in df.columns]
        if self.window:
            ts = pd.to_datetime(df[self.ts_column], errors="coerce")
            df["_win"] = ts.dt.floor(self.window)
            num = [c for c in df.columns if c not in (self.entity_column, self.ts_column, "_win")
                   and pd.api.types.is_numeric_dtype(df[c])]
            how = {c: self.agg_by.get(c, self.agg) for c in num}
            df = df.groupby([self.entity_column, "_win"], sort=True).agg(how).reset_index()
            df["entity_id"] = df[self.entity_column].astype(str) + "@" + df["_win"].map(lambda t: t.isoformat())
            df["ts"] = df.pop("_win")
            return df
        if self.ts_column and self.ts_column in df.columns:
            df["ts"] = df[self.ts_column]
        if self.entity_column and self.entity_column in df.columns and self.ts_column:
            df["entity_id"] = df[self.entity_column].astype(str) + "@" + pd.to_datetime(df[self.ts_column]).map(
                lambda t: t.isoformat())
        return df

    def read(self, spec: ReadSpec) -> pd.DataFrame:
        return standardize(self._shape(self._raw(spec)), spec, kind=self.kind,
                           source_ref=f"gateway:{self.table}" + (f"?window={self.window}&agg={self.agg}" if self.window else ""))

    def probe(self, spec: ReadSpec | None = None) -> SourceHealth:
        try:
            if spec is None:
                conn = self.db.connect()
                try:
                    n = self.db.count(self.table, conn=conn)
                    note = self.db.privilege_note(conn)
                finally:
                    conn.close()
                return SourceHealth(self.kind, True, n, None, None, None, None, {}, None, "Gateway 원장 연결" + note)
            frame = self.read(spec)
            note = self.db.privilege_note()
        except SourceDisconnected as e:
            return SourceHealth(self.kind, False, None, None, None, None, None, {}, None, e.reason)
        return health_from_frame(self.kind, frame, spec, "Gateway 원장 연결" + note)
