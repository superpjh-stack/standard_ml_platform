"""일일 감시 — `mlp_monitor_daily` (spec §9 · interfaces §9 · D-06). 소유 개발3.

과제마다(학습 과제 · production 있는 것만) 학습 스냅숏(기대) 대 그날 운영 입력(실제)을 비교한다:
`psi`(변수별) · `oor_rate`(변수별 + 과제 '') · `missing_rate`(변수별, 기대 대비 증가 %p) ·
`live_perf`(실측 연결된 예측의 과제 선정 지표, 창 `perf_window_days`) · `volume` · `error_rate`.
임계값은 코드 상수가 아니라 `pack.yaml monitor` + 과제 `monitor` 덮어쓰기에서만 온다.

**재학습 후보까지만.** 어느 지표든 `retrain` 이면 `data.jobs.submit` 으로 학습을 접수한다(작업자가
`run_and_register` → candidate). 승인 요청은 `monitor.retrain.request_approvals` 가 `Registry.request_promotion`
으로만 만든다. 이 모듈은 production 을 바꾸지 않는다(G-M09 · check_no_autopromote).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..db.conn import connect
from ..registry import packs, tenants
from ..settings import ROOT
from . import stats as m

KST = timezone(timedelta(hours=9))
THRESHOLD_KEYS = ("psi_warn", "psi_retrain", "oor_warn", "missing_warn_pp", "perf_drop", "perf_window_days")
LEARNED = ("regression", "risk", "anomaly")
MONITOR_ACTOR = "monitor"


class MonitorConfigMissing(Exception):
    """pack.yaml · 과제 monitor 에 임계값이 없다 — 코드 기본값으로 채우지 않는다."""


def thresholds(merged: tenants.Merged, task: tenants.TaskDef) -> dict[str, float]:
    th = {**(merged.pack.meta.get("monitor") or {}), **(task.raw.get("monitor") or {})}
    missing = [k for k in THRESHOLD_KEYS if th.get(k) is None]
    if missing:
        raise MonitorConfigMissing(f"{task.id}: monitor 임계값 없음 {missing}")
    return {k: float(th[k]) for k in THRESHOLD_KEYS}


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=KST)
    return start, start + timedelta(days=1)


# ── 기대(학습) 쪽 ─────────────────────────────────────────────────────────────
def production(tenant_id: str, task_id: str, *, conn=None) -> dict | None:
    sql = ("SELECT mv.version, mv.snapshot_id, mv.metrics, mv.artifact_path, s.ranges, s.missing_rates "
           "FROM mlp_model_version mv JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id "
           "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.stage='production'")
    if conn is not None:
        return conn.execute(sql, (tenant_id, task_id)).fetchone()
    with connect() as c:
        return c.execute(sql, (tenant_id, task_id)).fetchone()


def training_ranges(prod: dict) -> dict[str, dict]:
    """serve 와 같은 학습 범위 — production 산출물 features.lock.json(학습+검증 구간). 없으면 스냅숏 ranges."""
    p = Path(prod.get("artifact_path") or "")
    p = p if p.is_absolute() else ROOT / p
    lock = p / "features.lock.json"
    if lock.is_file():
        feats = json.loads(lock.read_text(encoding="utf-8")).get("features") or {}
        out = {}
        for name, f in feats.items():
            if f.get("values") is not None:
                out[name] = {"values": list(f["values"])}
            elif f.get("p1") is not None and f.get("p99") is not None:
                out[name] = {"p1": f["p1"], "p99": f["p99"]}
        if out:
            return out
    return dict(prod.get("ranges") or {})


def expected_frame(prod: dict) -> pd.DataFrame:
    from ..data import snapshot

    return snapshot.load(prod["snapshot_id"])


# ── 실제(운영) 쪽 ─────────────────────────────────────────────────────────────
def operational_inputs(tenant_id: str, task_id: str, day: date, *, conn) -> pd.DataFrame:
    lo, hi = day_bounds(day)
    rows = conn.execute("SELECT inputs FROM mlp_prediction WHERE tenant_id=%s AND task_id=%s AND ts >= %s AND ts < %s "
                        "ORDER BY ts, prediction_id", (tenant_id, task_id, lo, hi)).fetchall()
    return pd.DataFrame([r["inputs"] for r in rows])


def error_rate(tenant_id: str, task_id: str, day: date, *, conn) -> tuple[float | None, int]:
    """그날 이 과제 predict 호출 중 4xx · 5xx 비율 (감사 미들웨어 기록)."""
    lo, hi = day_bounds(day)
    rows = conn.execute("SELECT detail FROM mlp_audit WHERE tenant_id=%s AND ts >= %s AND ts < %s "
                        "AND action LIKE 'POST %%/predict%%' AND (target LIKE %s OR target LIKE %s)",
                        (tenant_id, lo, hi, f"%/tasks/{task_id}/predict%", f"%/tasks/{task_id.split('.', 1)[-1]}/predict%")
                        ).fetchall()
    if not rows:
        return None, 0
    bad = sum(1 for r in rows if int((r["detail"] or {}).get("status", 200)) >= 400)
    return bad / len(rows), len(rows)


def _class_of(actual, classes: list[str]) -> str | None:
    """실측 값 → 클래스 이름. mlp_actual.value 는 수치라 클래스 색인(classes 순서)으로 적는다 — 범위 밖 · 비정수는 None."""
    try:
        f = float(actual)
    except (TypeError, ValueError):
        return None
    if not classes or not f.is_integer() or not 0 <= int(f) < len(classes):
        return None
    return classes[int(f)]


def live_performance(tenant_id: str, task: tenants.TaskDef, day: date, window_days: int, prod: dict,
                     *, conn) -> dict:
    """실측이 연결된 예측(창 안)의 선정 지표 대 production 시험 지표. 실측 없으면 value=None · '실측 없음'."""
    ttype = packs.std("task_types")["types"][task.type]
    metric = ttype.get("selection_metric")
    if not metric:
        return {"value": None, "level": "ok", "detail": {"note": "라벨 없는 유형 — 실측 성능 없음"}}
    lo = day_bounds(day)[1] - timedelta(days=window_days)
    hi = day_bounds(day)[1]
    rows = conn.execute(
        "SELECT p.outputs, a.value FROM mlp_prediction p JOIN LATERAL ("
        "  SELECT value FROM mlp_actual a WHERE a.tenant_id=p.tenant_id AND a.task_id=p.task_id AND a.entity_id=p.entity_id "
        "  ORDER BY observed_at DESC LIMIT 1) a ON true "
        "WHERE p.tenant_id=%s AND p.task_id=%s AND p.version=%s AND p.entity_id IS NOT NULL AND p.ts >= %s AND p.ts < %s",
        (tenant_id, task.id, prod["version"], lo, hi)).fetchall()
    test = ((prod.get("metrics") or {}).get(metric) or {}).get("value")
    if metric == "macro_f1":
        # extract(모델 추출기): 예측 label 과 실측 label(클래스 이름) 짝 — 예측 기록에 label 이 없으면(문서 추출은
        # mlp_document 에 남고 mlp_prediction · 실측 짝이 없다) 실측 없음으로 보인다. 숫자 실측과 짝짓지 않는다.
        pairs_c = [(((r["outputs"] or {}).get("prediction") or {}).get("label"), r["value"]) for r in rows]
        classes = [str(c) for c in (task.raw.get("model") or {}).get("classes") or []]
        pairs_c = [(str(p), _class_of(a, classes)) for p, a in pairs_c if p is not None and _class_of(a, classes) is not None]
        if not pairs_c:
            return {"value": None, "level": "ok", "detail": {"metric": metric, "n": 0, "test": test, "note": "실측 없음"}}
        from sklearn.metrics import f1_score
        live = float(f1_score([a for _, a in pairs_c], [p for p, _ in pairs_c], labels=classes or None,
                              average="macro", zero_division=0))
        pairs = pairs_c
    else:
        pairs = [((r["outputs"] or {}).get("prediction") or {}).get("value") for r in rows]
        pairs = [(float(p), float(r["value"])) for p, r in zip(pairs, rows) if p is not None]
        if not pairs:
            return {"value": None, "level": "ok", "detail": {"metric": metric, "n": 0, "test": test, "note": "실측 없음"}}
        pred = pd.Series([p for p, _ in pairs])
        act = pd.Series([a for _, a in pairs])
        if metric == "mae":
            live = float((pred - act).abs().mean())
        elif metric == "brier":
            live = float(((pred - act) ** 2).mean())
        else:  # 다른 선정 지표가 std 에 생기면 여기서 실패를 보인다
            raise NotImplementedError(f"live_perf 지표 {metric}")
    direction = packs.std("metrics")["metrics"][metric]["direction"]
    drop = None
    if test not in (None, 0):
        drop = (live - test) / abs(test) if direction == "lower" else (test - live) / abs(test)
    return {"value": live, "drop": drop, "detail": {"metric": metric, "n": len(pairs), "test": test, "drop": drop}}


# ── 한 과제 ──────────────────────────────────────────────────────────────────
def task_rows(merged: tenants.Merged, task: tenants.TaskDef, day: date, *, expected: pd.DataFrame,
              actual: pd.DataFrame, ranges: Mapping[str, dict], th: Mapping[str, float],
              exp_missing: Mapping[str, float] | None = None) -> list[dict]:
    """순수 계산 — mlp_monitor_daily 행 모양 dict 목록(DB 를 모른다)."""
    rows: list[dict] = []
    base = {"tenant_id": merged.tenant.code, "task_id": task.id, "day": day}
    feats = list(task.raw.get("features") or [])
    any_oor = pd.Series(False, index=actual.index)
    for f in feats:
        fdef = merged.pack.features.get(f, {})
        cat = fdef.get("dtype") == "category"
        a = actual[f] if f in actual.columns else pd.Series([None] * len(actual), dtype=object)
        e = expected[f] if f in expected.columns else pd.Series([], dtype=float)
        v = m.psi(e, a, categorical=cat)
        rows.append({**base, "metric": "psi", "feature": f, "value": None if math.isnan(v) else v,
                     "level": m.level(v, th["psi_warn"], th["psi_retrain"]),
                     "detail": {"n_actual": int(a.notna().sum()), "n_expected": int(e.notna().sum()),
                                **({"note": "운영 값 없음"} if math.isnan(v) else {})}})
        if f in ranges:
            r = m.oor_rate(a, ranges[f])
            rows.append({**base, "metric": "oor_rate", "feature": f, "value": None if math.isnan(r) else r,
                         "level": m.level(r, th["oor_warn"]), "detail": {"range": ranges[f]}})
            vals = a[a.notna()]
            if len(vals):
                if "values" in ranges[f]:
                    hit = ~vals.astype(str).isin({str(x) for x in ranges[f]["values"]})
                else:
                    x = vals.astype(float)
                    hit = (x < float(ranges[f]["p1"])) | (x > float(ranges[f]["p99"]))
                any_oor = any_oor | hit.reindex(actual.index, fill_value=False)
        mr = m.missing_rate(a)
        em = (exp_missing or {}).get(f)
        if em is None:
            em = m.missing_rate(e) if len(e) else 0.0
        diff = None if math.isnan(mr) else mr - float(em)
        rows.append({**base, "metric": "missing_rate", "feature": f, "value": None if math.isnan(mr) else mr,
                     "level": m.level(diff, th["missing_warn_pp"]), "detail": {"expected": float(em), "diff_pp": diff}})
    n = len(actual)
    task_oor = float(any_oor.mean()) if n else None
    rows.append({**base, "metric": "oor_rate", "feature": "", "value": task_oor,
                 "level": m.level(task_oor, th["oor_warn"]), "detail": {"rows": n, "rule": "변수 하나라도 학습 범위 밖"}})
    rows.append({**base, "metric": "volume", "feature": "", "value": float(n), "level": "ok", "detail": {}})
    return rows


def _write(rows: list[dict], *, conn) -> None:
    for r in rows:
        conn.execute(
            "INSERT INTO mlp_monitor_daily (tenant_id, task_id, day, metric, feature, value, level, detail) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (tenant_id, task_id, day, metric, feature) DO UPDATE SET "
            "value=EXCLUDED.value, level=EXCLUDED.level, detail=EXCLUDED.detail, created_at=now()",
            (r["tenant_id"], r["task_id"], r["day"], r["metric"], r["feature"], r["value"], r["level"],
             json.dumps(r["detail"], ensure_ascii=False, default=str)))


def run_daily(tenant_id: str, day: date, *, frames: Mapping[str, pd.DataFrame] | None = None,
              retrain_source: str | None = None, submit_retrain: bool = True,
              merged: tenants.Merged | None = None) -> list[dict]:
    """하루치 감시. frames(과제 → 운영 입력 프레임)가 있으면 그것(fixture 모드), 없으면 그날 mlp_prediction 입력.

    반환: 쓴 mlp_monitor_daily 행 + 과제별 요약 행(`metric='_summary'`, DB 에는 쓰지 않음 —
    retrain 여부 · 접수한 run_id · 건너뛴 사유)."""
    merged = merged or tenants.load_and_merge(tenant_id)
    out: list[dict] = []
    for task_id, task in merged.tasks.items():
        summary: dict[str, Any] = {"tenant_id": tenant_id, "task_id": task_id, "day": day, "metric": "_summary"}
        from ..data.taskview import has_model, learn_view
        if task.type == "extract" and has_model(task):
            task = learn_view(task)          # 모델 추출기 — model: 블록의 설명자 · 라벨로 감시(실측 성능 = macro_f1)
        elif task.type not in LEARNED:
            out.append({**summary, "skipped": "학습 과제가 아님(uses 과제 감시로 본다)"})
            continue
        with connect() as c:
            prod = production(tenant_id, task_id, conn=c)
        if prod is None:
            out.append({**summary, "skipped": "운영 모델 없음 (model_not_ready)"})
            continue
        th = thresholds(merged, task)
        with connect() as c:
            actual = (frames.get(task_id, pd.DataFrame()) if frames is not None
                      else operational_inputs(tenant_id, task_id, day, conn=c))
            rows = task_rows(merged, task, day, expected=expected_frame(prod), actual=actual,
                             ranges=training_ranges(prod), th=th, exp_missing=prod.get("missing_rates") or {})
            er, n_calls = error_rate(tenant_id, task_id, day, conn=c)
            rows.append({"tenant_id": tenant_id, "task_id": task_id, "day": day, "metric": "error_rate", "feature": "",
                         "value": er, "level": "ok", "detail": {"calls": n_calls}})
            lp = live_performance(tenant_id, task, day, int(th["perf_window_days"]), prod, conn=c)
            lp_level = "retrain" if lp.get("drop") is not None and lp["drop"] >= th["perf_drop"] else "ok"
            rows.append({"tenant_id": tenant_id, "task_id": task_id, "day": day, "metric": "live_perf", "feature": "",
                         "value": lp["value"], "level": lp_level, "detail": lp["detail"]})
            _write(rows, conn=c)
        reasons = [f"{r['metric']}:{r['feature'] or '-'}" for r in rows if r["level"] == "retrain"]
        summary.update(production_version=prod["version"], retrain=bool(reasons), reasons=reasons, run_id=None)
        if reasons and submit_retrain:
            try:
                summary["run_id"] = submit(tenant_id, task_id, source_role=retrain_source)
            except Exception as e:  # noqa: BLE001 — 숨기지 않는다: 요약 행에 사유를 남기고 다음 과제로
                summary["submit_error"] = {"type": type(e).__name__, "message": str(e)[:200]}
        out.extend(rows)
        out.append(summary)
    return out


def submit(tenant_id: str, task_id: str, *, source_role: str | None = None) -> str:
    """재학습 접수 — 학습은 API 밖 작업자가 한다(D-57). 같은 스냅숏 · 설정이면 기존 run_id(멱등)."""
    from ..data import jobs

    return jobs.submit(tenant_id, task_id, actor=MONITOR_ACTOR, source_role=source_role)
