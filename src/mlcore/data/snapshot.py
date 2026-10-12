"""스냅숏 — 표준 프레임을 Parquet 으로 고정한다 (contracts/interfaces.md §2.2 · spec §4.3).

해시는 Parquet 바이트가 아니라 **정규 CSV 바이트**의 SHA-256 이다 (규칙 v2 — D-87):
열 이름 정렬 → 행 정렬(ts, entity_id, 같은 키가 겹치면 나머지 열 전체의 정규화 값) → 값 정규화(수치 = float repr,
시각 = UTC ISO, 결측 = 빈칸) → 머리줄 `열이름:종류`(num · str · ts · null — 수치와 같은 값의 문자열 열을 구분) → UTF-8.
열 순서 · 정수/실수 표기 · 행 순서(중복 키 행 포함)가 달라도 같은 내용이면 같은 해시다.
v1(종류 표지 · 중복 키 정렬 없음)으로 고정된 기존 파일은 규칙 표지가 없고, `load` 가 v1 으로 검증한다.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..settings import get_settings
from .frame import META_COLUMNS, TZ

META_KEY = b"mlp_sha256"
META_INFO = b"mlp_snapshot"
META_RULE = b"mlp_hash_rule"
HASH_RULE = "v2"


class SnapshotCorrupt(Exception):
    """스냅숏 파일 내용 해시가 기록과 다르다."""


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    tenant_id: str
    task_id: str
    path: str
    sha256: str
    rows: int
    ts_from: datetime | None
    ts_to: datetime | None
    columns: tuple[str, ...]
    missing_rates: dict[str, float]
    ranges: dict[str, dict]
    source_ref: dict
    synthetic: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts_from"] = self.ts_from.isoformat() if self.ts_from else None
        d["ts_to"] = self.ts_to.isoformat() if self.ts_to else None
        d["columns"] = list(self.columns)
        return d


def _base(base_dir: Path | None) -> Path:
    return Path(base_dir) if base_dir is not None else get_settings().snapshot_dir


_SORT_KEYS = ("ts", "entity_id")


def row_order(frame: pd.DataFrame) -> np.ndarray:
    """정규 행 순서(위치) — (ts, entity_id) 안정 정렬, 같은 키 행이 있으면 나머지 열 전체(열 이름 정렬)의 정규화 값으로
    마저 정렬한다. 입력 행 순서와 무관한 전체 순서다(DEF-QA1-007)."""
    df = frame.reset_index(drop=True)
    keys = [k for k in _SORT_KEYS if k in df.columns]
    if keys and not df.duplicated(keys).any():
        return df.sort_values(keys, kind="mergesort").index.to_numpy()
    rest = [c for c in sorted(df.columns, key=str) if c not in keys]
    tb = ["\x1f".join(v) for v in zip(*[_norm_series(df[c]) for c in rest])] if rest else [""] * len(df)
    return df.assign(__mlp_tb=tb).sort_values(keys + ["__mlp_tb"], kind="mergesort").index.to_numpy()


def canonical(frame: pd.DataFrame) -> pd.DataFrame:
    """정규 순서: 열 이름 정렬 · 행 row_order."""
    df = frame.reset_index(drop=True)
    df = df.iloc[row_order(df)]
    return df[sorted(df.columns)].reset_index(drop=True)


def _kind(s: pd.Series) -> str:
    """해시 머리줄의 열 종류 — 정수/실수 · bool 은 같은 num(값 표기가 같다), 문자열 열과는 다르다."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return "ts"
    if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
        return "num"
    inferred = pd.api.types.infer_dtype(s, skipna=True)
    if inferred in ("integer", "floating", "mixed-integer-float", "decimal", "boolean"):
        return "num"
    if inferred in ("datetime64", "datetime"):
        return "ts"
    if inferred == "empty":
        return "null"
    return "str"


def _norm_series(s: pd.Series) -> list[str]:
    if pd.api.types.is_datetime64_any_dtype(s):
        t = s if getattr(s.dt, "tz", None) is not None else s.dt.tz_localize(TZ)
        t = t.dt.tz_convert("UTC")
        return ["" if pd.isna(v) else v.strftime("%Y-%m-%dT%H:%M:%S.%fZ") for v in t]
    if pd.api.types.is_bool_dtype(s):
        return ["1.0" if v else "0.0" for v in s]
    if pd.api.types.is_numeric_dtype(s):
        return ["" if (v is None or (isinstance(v, float) and math.isnan(v))) else repr(float(v)) for v in s.tolist()]
    out = []
    for v in s.tolist():
        if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v is pd.NaT:
            out.append("")
        elif isinstance(v, (bool, np.bool_)):
            out.append("1.0" if v else "0.0")
        elif isinstance(v, (int, float, np.integer, np.floating)):
            out.append(repr(float(v)))
        else:
            out.append(str(v))
    return out


def _quote(v: str) -> str:
    if any(c in v for c in ',"\n\r'):
        return '"' + v.replace('"', '""') + '"'
    return v


def _csv_sha256(df: pd.DataFrame, header: list[str]) -> str:
    cols = [_norm_series(df[c]) for c in df.columns]
    buf = io.StringIO()
    buf.write(",".join(_quote(h) for h in header) + "\n")
    for row in zip(*cols):
        buf.write(",".join(_quote(v) for v in row) + "\n")
    return hashlib.sha256(buf.getvalue().encode("utf-8")).hexdigest()


def content_sha256(frame: pd.DataFrame) -> str:
    """규칙 v2 내용 해시 (모듈 머리 설명)."""
    df = canonical(frame)
    return _csv_sha256(df, [f"{c}:{_kind(df[c])}" for c in df.columns])


def content_sha256_v1(frame: pd.DataFrame) -> str:
    """규칙 v1(9d2febc 까지) — 기존 스냅숏 파일 검증용으로만 남긴다. 새 스냅숏은 만들지 않는다."""
    keys = [k for k in _SORT_KEYS if k in frame.columns]
    df = frame.sort_values(keys, kind="mergesort") if keys else frame
    df = df[sorted(df.columns)].reset_index(drop=True)
    return _csv_sha256(df, [str(c) for c in df.columns])


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in META_COLUMNS]


def ranges(frame: pd.DataFrame, columns=None) -> dict[str, dict]:
    """학습 범위 — 수치 {p1, p99} · 범주 {values}."""
    out = {}
    for c in columns if columns is not None else feature_columns(frame):
        s = frame[c]
        if pd.api.types.is_numeric_dtype(s):
            v = s.dropna().to_numpy(dtype=float)
            out[c] = {"p1": float(np.percentile(v, 1)), "p99": float(np.percentile(v, 99))} if len(v) else {"p1": None, "p99": None}
        else:
            out[c] = {"values": sorted({str(x) for x in s.dropna().tolist()})}
    return out


def _path(base: Path, tenant_id: str, task_id: str, snapshot_id: str) -> Path:
    return base / tenant_id / task_id / f"{snapshot_id}.parquet"


def freeze(frame: pd.DataFrame, *, tenant_id: str, task, source_ref: dict, synthetic: bool,
           base_dir: Path | None = None) -> Snapshot:
    task_id = task.id if hasattr(task, "id") else str(task)
    df = canonical(frame)
    sha = content_sha256(df)
    sid = "snp_" + sha[:16]
    path = _path(_base(base_dir), tenant_id, task_id, sid)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        info = json.dumps({"tenant_id": tenant_id, "task_id": task_id, "source_ref": source_ref,
                           "synthetic": bool(synthetic)}, ensure_ascii=False, sort_keys=True, default=str)
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), META_KEY: sha.encode(),
                                               META_INFO: info.encode(), META_RULE: HASH_RULE.encode()})
        tmp = path.with_suffix(".tmp")
        pq.write_table(table, tmp)
        tmp.replace(path)
    ts = df["ts"].dropna() if "ts" in df.columns else pd.Series([], dtype=object)
    miss_cols = feature_columns(df) + (["target"] if "target" in df.columns else [])
    n = len(df)
    return Snapshot(
        snapshot_id=sid, tenant_id=tenant_id, task_id=task_id, path=str(path), sha256=sha, rows=n,
        ts_from=ts.min().to_pydatetime() if len(ts) else None, ts_to=ts.max().to_pydatetime() if len(ts) else None,
        columns=tuple(df.columns), missing_rates={c: (float(df[c].isna().mean()) if n else 0.0) for c in miss_cols},
        ranges=ranges(df), source_ref=dict(source_ref), synthetic=bool(synthetic))


def find(snapshot_id: str, base_dir: Path | None = None) -> Path:
    hits = sorted(_base(base_dir).glob(f"*/*/{snapshot_id}.parquet"))
    if not hits:
        raise FileNotFoundError(f"스냅숏 {snapshot_id} 파일 없음")
    return hits[0]


def load_info(snapshot_id: str, *, base_dir: Path | None = None) -> dict:
    """스냅숏 파일에 함께 고정한 {tenant_id, task_id, source_ref, synthetic, sha256}."""
    md = pq.read_schema(find(snapshot_id, base_dir)).metadata or {}
    info = json.loads(md.get(META_INFO, b"{}").decode() or "{}")
    info["sha256"] = md.get(META_KEY, b"").decode() or None
    return info


def load(snapshot_id: str, *, base_dir: Path | None = None) -> pd.DataFrame:
    path = find(snapshot_id, base_dir)
    table = pq.read_table(path)
    md = table.schema.metadata or {}
    recorded = md.get(META_KEY, b"").decode()
    df = table.to_pandas()
    # 규칙 표지가 없는 파일 = v1 으로 고정된 기존 스냅숏 → v1 으로 검증(같은 내용이면 그대로 읽힌다)
    sha = content_sha256(df) if md.get(META_RULE) else content_sha256_v1(df)
    if sha[:16] != snapshot_id.removeprefix("snp_") or (recorded and recorded != sha):
        raise SnapshotCorrupt(f"{snapshot_id}: 내용 해시 불일치")
    return canonical(df)


def record(snap: Snapshot, *, test: bool = False) -> None:
    """mlp_snapshot 1행 (멱등)."""
    from ..db.conn import connect

    with connect(test) as c:
        c.execute(
            "INSERT INTO mlp_snapshot (snapshot_id, tenant_id, task_id, rows, ts_from, ts_to, columns, missing_rates, "
            "ranges, sha256, source_ref, synthetic, path) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (snap.snapshot_id, snap.tenant_id, snap.task_id, snap.rows, snap.ts_from, snap.ts_to,
             json.dumps(list(snap.columns), ensure_ascii=False), json.dumps(snap.missing_rates),
             json.dumps(snap.ranges, ensure_ascii=False), snap.sha256,
             json.dumps(snap.source_ref, ensure_ascii=False), snap.synthetic, _relpath(snap.path)))


def _relpath(p: str) -> str:
    from ..settings import ROOT

    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return p
