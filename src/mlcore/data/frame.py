"""표준 프레임 (contracts/interfaces.md §2.1 · spec §4.2).

열: tenant_id · task_id · entity_id · ts(KST tz) · group(선택) · <변수> · target(지도학습) · _source · _source_ref.
열 순서는 의미가 없다. 변수 · 목표 · 시간 · 그룹 열 이름은 과제 정의(TaskDef.raw)에서만 온다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .sources.base import ReadSpec

TZ = "Asia/Seoul"
META_COLUMNS = ("tenant_id", "task_id", "entity_id", "ts", "group", "target", "_source", "_source_ref")


def _map_columns(raw: pd.DataFrame, columns_map: dict[str, str]) -> pd.DataFrame:
    """원천 열 → 팩 변수. 키는 `열` 또는 `테이블.열` (테이블 접두는 원천 위치일 뿐이라 열 이름으로 대조)."""
    if not columns_map:
        return raw
    ren = {}
    for src, dst in columns_map.items():
        if src in raw.columns:
            ren[src] = dst
        else:
            col = str(src).rsplit(".", 1)[-1]
            if col in raw.columns and col not in ren:
                ren[col] = dst
    return raw.rename(columns=ren)


def to_kst(s: pd.Series) -> pd.Series:
    ts = pd.to_datetime(s, errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        return ts.dt.tz_localize(TZ)
    return ts.dt.tz_convert(TZ)


def _kst_ts(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_convert(TZ) if t.tzinfo else t.tz_localize(TZ)


def standardize(raw: pd.DataFrame, spec: "ReadSpec", *, kind: str, source_ref: str) -> pd.DataFrame:
    raw = _map_columns(raw.copy(), dict(spec.columns_map))
    task = spec.task.raw
    n = len(raw)
    out = pd.DataFrame(index=range(n))
    out["tenant_id"] = spec.tenant_id
    out["task_id"] = spec.task.id
    raw = raw.reset_index(drop=True)
    has_entity = "entity_id" in raw.columns
    out["entity_id"] = raw["entity_id"].astype(str) if has_entity else ""
    time_key = task.get("time_key")
    if "ts" in raw.columns:
        out["ts"] = to_kst(raw["ts"])
    elif time_key and time_key in raw.columns:
        out["ts"] = to_kst(raw[time_key])
    else:
        out["ts"] = pd.Series(pd.NaT, index=range(n), dtype=f"datetime64[ns, {TZ}]")
    group_key = task.get("group_key")
    if group_key:
        out["group"] = raw[group_key].astype(str) if group_key in raw.columns else None
    for f in spec.features:
        if f.name not in raw.columns:
            out[f.name] = np.nan if f.numeric else None
            continue
        col = raw[f.name]
        if f.dtype == "category":
            out[f.name] = col.where(col.notna(), None).map(lambda v: None if v is None else str(v)).astype(object)
        elif f.dtype == "bool":
            out[f.name] = pd.to_numeric(col.map({True: 1.0, False: 0.0, "true": 1.0, "false": 0.0}).fillna(col),
                                        errors="coerce").astype(float)
        else:
            out[f.name] = pd.to_numeric(col, errors="coerce").astype(float)
    target = (task.get("target") or {}).get("name")
    if target and target in raw.columns:
        out["target"] = pd.to_numeric(raw[target], errors="coerce").astype(float)
    out["_source"] = kind
    out["_source_ref"] = source_ref
    if not has_entity:
        # entity_id 없는 원천: ROW-n 을 원천 행 순서가 아니라 내용 순서(시각 → 나머지 열 값)로 붙인다 —
        # 같은 행을 다른 순서로 받아도 같은 스냅숏(DEF-QA1-007)
        from .snapshot import row_order

        ids = np.empty(n, dtype=object)
        ids[row_order(out)] = [f"ROW-{i + 1:06d}" for i in range(n)]
        out["entity_id"] = ids
    if spec.ts_from is not None:
        out = out[out["ts"] >= _kst_ts(spec.ts_from)]
    if spec.ts_to is not None:
        out = out[out["ts"] <= _kst_ts(spec.ts_to)]
    out = out.sort_values(["ts", "entity_id"], kind="mergesort").reset_index(drop=True)
    if spec.limit is not None:
        out = out.head(int(spec.limit)).reset_index(drop=True)
    return out


def missing_rates(frame: pd.DataFrame, names) -> dict[str, float]:
    n = len(frame)
    return {c: (float(frame[c].isna().mean()) if n else 0.0) for c in names if c in frame.columns}


def health_from_frame(kind: str, frame: pd.DataFrame, spec: "ReadSpec", ok_message: str, *, lag: bool = True):
    """표준 프레임 → SourceHealth (doctor 용 — 행 수 · 기간 · 지연 · 변수 대응률 · 결측률 · 목표 유무)."""
    from .sources.base import SourceHealth

    names = [f.name for f in spec.features]
    cover = sum(bool(frame[n].notna().any()) for n in names if n in frame.columns) / len(names) if names else None
    needs_target = bool((spec.task.raw.get("target") or {}).get("name"))
    has_target = ("target" in frame.columns and bool(frame["target"].notna().any())) if needs_target else None
    ts = frame["ts"].dropna() if "ts" in frame.columns else pd.Series([], dtype=object)
    lag_s = None
    if lag and len(ts):
        lag_s = max(0.0, (pd.Timestamp.now(tz=ts.dt.tz) - ts.max()).total_seconds())
    return SourceHealth(kind, True, len(frame), ts.min().to_pydatetime() if len(ts) else None,
                        ts.max().to_pydatetime() if len(ts) else None, lag_s, cover, missing_rates(frame, names),
                        has_target, "목표 없음" if has_target is False else ok_message)
