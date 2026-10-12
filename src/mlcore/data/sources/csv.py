"""csv 어댑터 — UTF-8(BOM 허용) · 열 대응표(ReadSpec.columns_map) · 단위 배수 (spec §4.1). 읽기 전용."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ...settings import ROOT
from ..frame import missing_rates, standardize
from .base import ReadSpec, SourceDisconnected, SourceHealth


class CsvSource:
    kind = "csv"

    def __init__(self, path: str | Path, *, encoding: str = "utf-8-sig", units: dict[str, float] | None = None):
        p = Path(path)
        self.path = p if p.is_absolute() else ROOT / p
        self.encoding = encoding
        self.units = dict(units or {})        # 팩 변수 → 배수 (원천 단위 × 배수 = 팩 단위)

    def _rel(self) -> str:
        try:
            return str(self.path.relative_to(ROOT))
        except ValueError:
            return self.path.name

    def _load(self) -> pd.DataFrame:
        if not self.path.is_file():
            raise SourceDisconnected(self.kind, f"CSV 없음: {self._rel()}")
        try:
            return pd.read_csv(self.path, encoding=self.encoding)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
            raise SourceDisconnected(self.kind, f"CSV 읽기 실패: {type(e).__name__}") from e

    def source_ref(self) -> dict:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.is_file() else None
        return {"kind": self.kind, "path": self._rel(), "file_sha256": digest}

    def read(self, spec: ReadSpec) -> pd.DataFrame:
        frame = standardize(self._load(), spec, kind=self.kind, source_ref=f"csv:{self._rel()}")
        for name, factor in self.units.items():
            if name in frame.columns:
                frame[name] = frame[name] * float(factor)
        return frame

    def probe(self, spec: ReadSpec | None = None) -> SourceHealth:
        try:
            if spec is None:
                raw = self._load()
                return SourceHealth(self.kind, True, len(raw), None, None, None, None, {}, None, "CSV 정상")
            frame = self.read(spec)
        except SourceDisconnected as e:
            return SourceHealth(self.kind, False, None, None, None, None, None, {}, None, e.reason)
        names = [f.name for f in spec.features]
        cover = sum(bool(frame[n].notna().any()) for n in names) / len(names) if names else None
        needs_target = bool((spec.task.raw.get("target") or {}).get("name"))
        has_target = ("target" in frame.columns and bool(frame["target"].notna().any())) if needs_target else None
        ts = frame["ts"].dropna()
        lag = None
        if len(ts):
            lag = max(0.0, (pd.Timestamp.now(tz=ts.dt.tz) - ts.max()).total_seconds())
        return SourceHealth(self.kind, True, len(frame), ts.min().to_pydatetime() if len(ts) else None,
                            ts.max().to_pydatetime() if len(ts) else None, lag, cover,
                            missing_rates(frame, names), has_target, "목표 없음" if has_target is False else "CSV 정상")
