"""데이터 소스 계약 (contracts/interfaces.md §2). 모든 어댑터는 읽기 전용이다(G-S05)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, Sequence

import pandas as pd

from ..features import FeatureDef

SourceKind = Literal["synthetic", "csv", "gateway", "dataplatform", "mes"]


@dataclass(frozen=True)
class SourceHealth:
    kind: str
    connected: bool
    rows: int | None
    ts_from: datetime | None
    ts_to: datetime | None
    lag_seconds: float | None
    feature_coverage: float | None
    missing_rates: dict[str, float]
    has_target: bool | None
    message: str


@dataclass(frozen=True)
class ReadSpec:
    tenant_id: str
    task: object                       # TaskDef (registry.tenants) — id · pack_id · type · raw · def_hash
    features: Sequence[FeatureDef]
    ts_from: datetime | None = None
    ts_to: datetime | None = None
    limit: int | None = None
    columns_map: dict[str, str] = field(default_factory=dict)


class DataSource(Protocol):
    kind: str

    def probe(self) -> SourceHealth: ...

    def read(self, spec: ReadSpec) -> pd.DataFrame: ...


class SourceDisconnected(Exception):
    """원천에 닿지 못했다 — API 계층이 503 source_disconnected 로 바꾼다. 합성 값으로 대체하지 않는다."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason = kind, reason
