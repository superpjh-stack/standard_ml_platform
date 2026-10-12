"""데이터 소스 어댑터 (contracts/interfaces.md §2 · spec §4.1). 전부 읽기 전용(G-S05).

5종: synthetic · csv · gateway(원장 DB SELECT) · dataplatform(REST GET) · mes(허용목록 테이블 SELECT).
DB · HTTP 어댑터의 연결 · 전송은 주입할 수 있다(`connect=` · `transport=`) — 시험은 fixture 사본 · 가짜 전송만 쓴다.
"""

from __future__ import annotations

from pathlib import Path

from .base import DataSource, ReadSpec, SourceDisconnected, SourceHealth, SourceKind
from .csv import CsvSource
from .dataplatform import DataPlatformSource
from .gateway import GatewaySource
from .mes import MesSource
from .synthetic import SyntheticSource

__all__ = ["DataSource", "ReadSpec", "SourceDisconnected", "SourceHealth", "SourceKind", "CsvSource",
           "DataPlatformSource", "GatewaySource", "MesSource", "SyntheticSource", "make_source"]


def make_source(src_cfg: dict, *, pack_dir: str | Path, pack_meta: dict, categories: dict | None = None,
                connect=None, transport=None) -> DataSource:
    """회사 등록부 `sources.<name>` 한 항목 → 어댑터."""
    kind = (src_cfg or {}).get("kind")
    if kind == "synthetic":
        synth = pack_meta.get("synth") or {}
        if not synth.get("module"):
            raise SourceDisconnected("synthetic", "pack.yaml synth.module 없음")
        seed = src_cfg.get("seed") if src_cfg.get("seed") is not None else synth.get("seed")
        rows = src_cfg.get("rows") if src_cfg.get("rows") is not None else synth.get("rows")
        if seed is None or rows is None:
            raise SourceDisconnected("synthetic", "합성 시드 · 행 수 없음 (pack.yaml synth)")
        return SyntheticSource(pack_dir, synth["module"], seed=int(seed), rows=int(rows), categories=categories)
    if kind == "csv":
        if not src_cfg.get("path"):
            raise SourceDisconnected("csv", "path 없음")
        return CsvSource(src_cfg["path"], encoding=src_cfg.get("encoding", "utf-8-sig"), units=src_cfg.get("units"))
    if kind == "gateway":
        return GatewaySource.from_config(src_cfg, connect=connect)
    if kind == "mes":
        return MesSource.from_config(src_cfg, connect=connect)
    if kind == "dataplatform":
        return DataPlatformSource.from_config(src_cfg, transport=transport)
    raise SourceDisconnected(str(kind), "알 수 없는 소스 종류")
