"""B02 tasks · B06 overview · B12 records · B14 monitor · doctor (contracts/api-contract.md). 소유 개발3.

화면 1(개요) · 6(감시)과 화면 2 · 3 폼이 쓰는 과제 메타. 코어는 과제 · 변수 이름을 모른다 — 전부 병합된 회사 등록부
(`app.state.registry`)와 DB 행에서 온다. 회사 범위(다른 회사 404)는 미들웨어가, 역할은 `std/roles.yaml` 이 정한다.
`api/main.py` 등록은 개발2(소유) — `app.include_router(ops.router)`.
"""

from __future__ import annotations

import base64
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, Query, Request

from ... import auth
from ...db.conn import connect
from ...serve.catalog import model_required, serving_ready, uses_of
from ...serve.errors import NotFound, ServeError
from ._common import catalog, principal, task_id

router = APIRouter(prefix="/api/v1")
KST = timezone(timedelta(hours=9))
LEVELS = ("ok", "warn", "retrain")


class SourceUnavailable(ServeError):
    status, code, default_message = 503, "source_disconnected", "데이터 소스에 연결할 수 없습니다"


def _iso(ts) -> str | None:
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


def _merged(request: Request):
    return catalog(request).merged


def _task(request: Request, t: str, task: str):
    m = _merged(request)
    tid = task_id(t, task)
    if m.tenant.code != t or tid not in m.tasks:
        raise NotFound("과제를 찾을 수 없습니다")
    return m, m.tasks[tid]


def _feature_meta(m, names: list[str]) -> list[dict]:
    cats = m.tenant.config.get("categories") or {}
    out = []
    for n in names:
        f = dict(m.pack.features.get(n) or {})
        if f.get("values_from") == "tenant":
            f["values"] = list(cats.get(n) or [])
        out.append({"name": n, **f})
    return out


def _production(c, tenant: str, tid: str) -> dict | None:
    row = c.execute("SELECT version, algo, created_at, promoted_at, synthetic, metrics, snapshot_id FROM mlp_model_version "
                    "WHERE tenant_id=%s AND task_id=%s AND stage='production'", (tenant, tid)).fetchone()
    if not row:
        return None
    return {"version": row["version"], "algo": row["algo"], "trained_at": _iso(row["created_at"]),
            "promoted_at": _iso(row["promoted_at"]), "synthetic": row["synthetic"], "snapshot_id": row["snapshot_id"],
            "metrics": row["metrics"] or {}}


# ── B02 tasks ───────────────────────────────────────────────────────────────
@router.get("/tenants/{t}/tasks")
def list_tasks(t: str, request: Request):
    auth.require(principal(request), "overview", write=False)
    m = _merged(request)
    if m.tenant.code != t:
        raise NotFound()
    items = []
    with connect() as c:
        for tid, td in m.tasks.items():
            prod = _production(c, t, tid)
            items.append({"task": tid, "pack_task": td.pack_id, "type": td.type, "title": td.raw.get("title"),
                          "entity": td.raw.get("entity"), "approver_role": td.raw.get("approver_role"),
                          "uses": [f"{t}.{u.split('.', 1)[1]}" for u in td.raw.get("uses") or []] or None,
                          "production": None if prod is None else {k: prod[k] for k in ("version", "algo", "trained_at", "synthetic")}})
    disabled = [{"task": tid, "reason": why} for tid, why in m.disabled.items()]
    return {"items": items, "next_cursor": None, "total": len(items), "disabled": disabled,
            "tenant": {"code": t, "name": m.tenant.config.get("name"), "pack": m.pack.code, "mode": m.tenant.config.get("mode")}}


@router.get("/tenants/{t}/tasks/{task}")
def get_task(t: str, task: str, request: Request):
    auth.require(principal(request), "overview", write=False)
    m, td = _task(request, t, task)
    raw = td.raw
    names = list(raw.get("features") or [])
    if td.type == "optimize":                       # 최적화 폼 = 고정 + 조절 변수
        names = list(dict.fromkeys(list(raw.get("fixed") or []) + list(raw.get("controls") or [])))
    elif td.type == "quote":                        # 견적 폼 = inputs 중 features.yaml 변수(수량 · 단가 입력은 inputs 목록으로)
        names = [n for n in raw.get("inputs") or [] if n in m.pack.features]
    elif td.type == "extract" and isinstance(raw.get("model"), dict):
        names = list((raw.get("model") or {}).get("features") or [])
    spec = catalog(request).get(t, td.id)
    keep = ("target", "thresholds", "interval", "clip", "calibration", "contamination", "controls", "fixed",
            "decision_vars", "params", "objective", "constraints", "search", "on_infeasible", "time_key", "group_key",
            "split", "candidates", "out_of_range", "max_imputed", "approver_role", "monitor", "derived", "input_rules",
            # 2차 유형 (개발2 요청 — 화면 9 가 인식값 · 단가 · 상한을 폼에 채운다). 단가는 10진 문자열 그대로
            "rule", "quantile_from", "origins", "max_items", "reason", "schedule",                       # review_queue
            "document", "extractors", "labels", "outputs", "model",                                     # extract
            "from_extract", "recognized", "inputs", "rates", "rate_tables", "rounding", "currency", "confirm", "csv",
            "input_limits")   # quote
    out = {"task": td.id, "pack_task": td.pack_id, "type": td.type, "title": raw.get("title"), "entity": raw.get("entity"),
           "features": _feature_meta(m, names), "notice": spec.notice,
           "uses": [f"{t}.{u.split('.', 1)[1]}" for u in raw.get("uses") or []] or None,
           "def_hash": td.def_hash}
    out.update({k: raw.get(k) for k in keep if k in raw})
    return out


# ── B06 overview ────────────────────────────────────────────────────────────
def _monitor_state(c, t: str, tid: str) -> dict:
    last = c.execute("SELECT max(day) AS d FROM mlp_monitor_daily WHERE tenant_id=%s AND task_id=%s", (t, tid)).fetchone()["d"]
    if last is None:
        return {"level": None, "day": None, "alerts": [], "note": "감시 기록 없음"}
    rows = c.execute("SELECT metric, feature, value, level FROM mlp_monitor_daily WHERE tenant_id=%s AND task_id=%s AND day=%s "
                     "AND level <> 'ok' ORDER BY level DESC, metric, feature", (t, tid, last)).fetchall()
    level = max((r["level"] for r in rows), key=LEVELS.index, default="ok")
    return {"level": level, "day": last.isoformat(),
            "alerts": [{"metric": r["metric"], "feature": r["feature"] or None, "value": r["value"], "level": r["level"]}
                       for r in rows]}


@router.get("/tenants/{t}/tasks/{task}/overview")
def overview(t: str, task: str, request: Request):
    auth.require(principal(request), "overview", write=False)
    m, td = _task(request, t, task)
    today = datetime.now(KST).date()
    lo = datetime(today.year, today.month, today.day, tzinfo=KST) - timedelta(days=1)
    hi = lo + timedelta(days=1)
    with connect() as c:
        prod = _production(c, t, td.id)
        if td.type == "optimize":
            n = c.execute("SELECT count(*) AS n FROM mlp_recommendation WHERE tenant_id=%s AND task_id=%s AND created_at >= %s "
                          "AND created_at < %s", (t, td.id, lo, hi)).fetchone()["n"]
        else:
            n = c.execute("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id=%s AND task_id=%s AND ts >= %s AND ts < %s",
                          (t, td.id, lo, hi)).fetchone()["n"]
        # 의존 과제(optimize · quote · review_queue)의 운영 버전 — 유형별 상태(C2 D2-94 · DEF-QA23-002, serve.catalog 판정)
        uses = None
        if uses_of(td, t):
            uses = []
            for uid in uses_of(td, t):
                p = _production(c, t, uid)
                uses.append({"task": uid, "version": p["version"] if p else None, "synthetic": p["synthetic"] if p else None})
        mon = _monitor_state(c, t, td.id)
        pending = c.execute("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id=%s AND task_id=%s AND state='pending'",
                            (t, td.id)).fetchone()["n"]
    metrics = (prod or {}).get("metrics") or {}
    return {"task": td.id, "type": td.type, "title": td.raw.get("title"),
            "production": None if prod is None else {k: prod[k] for k in ("version", "algo", "trained_at", "synthetic")},
            "model_required": model_required(td),
            "model_ready": serving_ready(td, t, lambda tid: (prod is not None) if tid == td.id
                                         else any(u["task"] == tid and u["version"] for u in uses or [])),
            "test_metrics": {k: v.get("value") for k, v in metrics.items()} if prod else None,
            "baseline": {k: v.get("baseline") for k, v in metrics.items()} if prod else None,
            "uses": uses, "predictions_yesterday": int(n), "pending_approvals": int(pending), "monitor": mon}


# ── B12 records ─────────────────────────────────────────────────────────────
def _frame(m, td) -> pd.DataFrame:
    """회사 mode 소스의 표준 프레임(읽기만). 최적화 과제는 첫 uses 과제의 프레임."""
    from ...data.features import feature_defs
    from ...data.sources import ReadSpec, SourceDisconnected, SyntheticSource, make_source
    from ...registry import tenants

    if td.type == "optimize":
        uid = f"{m.tenant.code}.{(td.raw.get('uses') or [''])[0].split('.', 1)[-1]}"
        if uid not in m.tasks:
            raise NotFound("과제를 찾을 수 없습니다")
        td = m.tasks[uid]
    cfg = m.tenant.config
    role = cfg["mode"]
    scfg = (cfg.get("sources") or {}).get(role) or {}
    cats = cfg.get("categories") or {}
    try:
        if scfg.get("kind") == "synthetic":
            src = SyntheticSource.from_call(tenants.synth_call(m, td.id, role=role))
        else:
            src = make_source(scfg, pack_dir=m.pack.path, pack_meta=m.pack.meta, categories=cats)
        feats = feature_defs(m.pack.features, td.raw.get("features") or [], cats, m.pack.std_name)
        cmap = {} if scfg.get("kind") == "synthetic" else {**(cfg.get("feature_map") or {}), **(cfg.get("target_map") or {})}
        return src.read(ReadSpec(tenant_id=m.tenant.code, task=td, features=feats, columns_map=cmap))
    except SourceDisconnected as e:
        raise SourceUnavailable(detail={"rule": "source", "kind": e.kind}) from e


def _json(v: Any) -> Any:
    if v is None or v is pd.NaT:                          # 시각 없는 행 → null (문자열 "NaT" 금지 — D2-103)
        return None
    if isinstance(v, pd.Timestamp):
        return v.tz_convert(KST).isoformat() if v.tzinfo else v.isoformat()
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    return v


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        kind, _, n = raw.partition(":")
        if kind != "o" or not n.isdigit():
            raise ValueError
        return int(n)
    except (ValueError, UnicodeDecodeError) as e:
        from ..errors import ApiError
        raise ApiError(422, "invalid_input", "cursor 가 올바르지 않습니다", {"field": "cursor", "rule": "cursor"}) from e


@router.get("/tenants/{t}/tasks/{task}/records")
def records(t: str, task: str, request: Request, search: str = Query(default="", max_length=60),
            limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None, max_length=64)):
    auth.require(principal(request), "overview", write=False)
    m, td = _task(request, t, task)
    frame = _frame(m, td)
    if search:
        frame = frame[frame["entity_id"].astype(str).str.contains(search, case=False, regex=False)]
    frame = frame.sort_values(["ts", "entity_id"], ascending=[False, True], kind="mergesort")
    start = _offset(cursor)
    page = frame.iloc[start:start + limit]
    items = [{k: _json(v) for k, v in row.items()} for row in page.to_dict("records")]
    nxt = _cursor(start + limit) if start + limit < len(frame) else None
    return {"items": items, "next_cursor": nxt, "total": int(len(frame))}


# ── B14 monitor · doctor ────────────────────────────────────────────────────
@router.get("/tenants/{t}/tasks/{task}/monitor")
def monitor(t: str, task: str, request: Request, days: int = Query(default=30, ge=1, le=366),
            metric: str | None = Query(default=None, pattern="^(psi|oor_rate|missing_rate|live_perf|volume|error_rate|source_health)$")):
    auth.require(principal(request), "monitor", write=False)
    m, td = _task(request, t, task)
    with connect() as c:
        last = c.execute("SELECT max(day) AS d FROM mlp_monitor_daily WHERE tenant_id=%s AND task_id=%s", (t, td.id)).fetchone()["d"]
        rows = []
        if last is not None:
            sql = ("SELECT day, metric, feature, value, level, detail FROM mlp_monitor_daily WHERE tenant_id=%s AND task_id=%s "
                   "AND day > %s")
            params: list = [t, td.id, last - timedelta(days=days)]
            if metric:
                sql += " AND metric=%s"
                params.append(metric)
            rows = c.execute(sql + " ORDER BY day, metric, feature", params).fetchall()
        cands = c.execute(
            "SELECT mv.version, mv.stage, mv.beats_baseline, mv.created_at, r.run_id, a.approval_id, a.state "
            "FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
            "LEFT JOIN mlp_approval a ON a.tenant_id = mv.tenant_id AND a.task_id = mv.task_id AND a.kind='model' AND a.ref_id = mv.version "
            "WHERE mv.tenant_id=%s AND mv.task_id=%s AND r.created_by='monitor' ORDER BY mv.created_at DESC LIMIT 20",
            (t, td.id)).fetchall()
    items = [{"day": r["day"].isoformat(), "metric": r["metric"], "feature": r["feature"] or None, "value": r["value"],
              "level": r["level"], "detail": r["detail"]} for r in rows]
    retrain = [{"version": r["version"], "stage": r["stage"], "beats_baseline": r["beats_baseline"], "run_id": r["run_id"],
                "approval_id": r["approval_id"], "approval_state": r["state"], "created_at": _iso(r["created_at"])}
               for r in cands]
    return {"items": items, "next_cursor": None, "total": len(items), "last_day": last.isoformat() if last else None,
            "retrain_candidates": retrain}


@router.get("/tenants/{t}/doctor")
def doctor(t: str, request: Request):
    auth.require(principal(request), "sources", write=False)   # goal2 §6 화면 7 — admin · approver(조회) (D2-103)
    from ...monitor import doctor as dr

    m = _merged(request)
    if m.tenant.code != t:
        raise NotFound()
    rep = dr.doctor(t, merged=m)
    return {"tenant": rep["tenant"], "mode": rep["mode"], "sources": rep["sources"], "warnings": rep["warnings"]}


