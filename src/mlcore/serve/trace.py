"""예측 추적 — 예측 → 모델 버전 → 학습 실행 → 스냅숏(해시 · 기간 · 행 수) → 소스 참조 → 실측 (G-M07 · api-contract §4)."""

from __future__ import annotations

from datetime import timedelta, timezone

from ..db.conn import connect
from .errors import NotFound

KST = timezone(timedelta(hours=9))


def _iso(ts):
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


def _sources(snap: dict, src_row: dict | None) -> list[dict]:
    """소스 참조 — mlp_source 행이 있으면 그것, 없으면 스냅숏 source_ref 에서. 값(키 · DSN)은 없다(이름만)."""
    if src_row:
        return [{"kind": src_row["kind"], "ref": src_row["ref"]}]
    ref = snap.get("source_ref") or {}
    if isinstance(ref, dict) and isinstance(ref.get("sources"), list):
        return [{"kind": s.get("kind"), "ref": s} for s in ref["sources"] if isinstance(s, dict)]
    if isinstance(ref, dict) and ref.get("kind"):
        return [{"kind": ref["kind"], "ref": ref}]
    return [{"kind": None, "ref": ref}] if ref else []


def trace(prediction_id: str, *, tenant_id: str) -> dict:
    """다른 회사의 예측이면 없는 것과 같다(404 — 존재를 숨긴다)."""
    with connect() as c:
        p = c.execute("SELECT * FROM mlp_prediction WHERE prediction_id = %s AND tenant_id = %s",
                      (prediction_id, tenant_id)).fetchone()
        if not p:
            raise NotFound("예측을 찾을 수 없습니다")
        mv = c.execute("SELECT * FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s AND version=%s",
                       (p["tenant_id"], p["task_id"], p["version"])).fetchone()
        run = c.execute("SELECT * FROM mlp_train_run WHERE run_id = %s", (mv["run_id"],)).fetchone()
        snap = c.execute("SELECT * FROM mlp_snapshot WHERE snapshot_id = %s", (mv["snapshot_id"],)).fetchone()
        src = (c.execute("SELECT kind, ref FROM mlp_source WHERE source_id = %s", (snap["source_id"],)).fetchone()
               if snap.get("source_id") is not None else None)
        acts = (c.execute("SELECT actual_id, entity_id, value, observed_at, source FROM mlp_actual "
                          "WHERE tenant_id=%s AND task_id=%s AND entity_id=%s ORDER BY observed_at, actual_id",
                          (p["tenant_id"], p["task_id"], p["entity_id"])).fetchall()
                if p["entity_id"] is not None else [])
    return {
        "prediction": {"prediction_id": p["prediction_id"], "task": p["task_id"], "version": p["version"],
                       "entity_id": p["entity_id"], "status": p["status"], "caller": p["caller"],
                       "channel": p["channel"], "synthetic": p["synthetic"], "ts": _iso(p["ts"]),
                       "inputs": p["inputs"], "outputs": p["outputs"]},
        "model": {"version": mv["version"], "stage": mv["stage"], "algo": mv["algo"],
                  "artifact_sha256": mv["artifact_sha256"]},
        "run": {"run_id": run["run_id"], "config_hash": run["config_hash"], "seed": run["seed"],
                "code_version": run["code_version"], "started_at": _iso(run["started_at"]),
                "finished_at": _iso(run["finished_at"])},
        "snapshot": {"snapshot_id": snap["snapshot_id"], "sha256": snap["sha256"], "rows": snap["rows"],
                     "ts_from": _iso(snap["ts_from"]), "ts_to": _iso(snap["ts_to"]), "synthetic": snap["synthetic"]},
        "sources": _sources(snap, src),
        "actuals": [{"actual_id": a["actual_id"], "entity_id": a["entity_id"], "value": a["value"],
                     "observed_at": _iso(a["observed_at"]), "source": a["source"]} for a in acts],
    }


# ── 축약 보기 `?view=explain` (agent-tools §4 · std/roles.yaml trace.explain_view) ─────────────────────
def explain_view_rule(role: str) -> str:
    """roles.yaml permissions.trace.explain_view[role] — auth.allowed 는 하위 표를 보지 않으므로 직접 읽는다."""
    from .. import auth
    sub = (auth.permissions().get("trace") or {}).get("explain_view") or {}
    return sub.get(role, "deny")


def explain_view(prediction_id: str, *, tenant_id: str) -> dict:
    """모델 · 스냅숏 · 기여만. 입력값 · 원천 소스 ref · run 설정 해시는 넣지 않는다. 다른 회사 → 404."""
    with connect() as c:
        p = c.execute("SELECT prediction_id, task_id, version, status, synthetic, outputs FROM mlp_prediction "
                      "WHERE prediction_id = %s AND tenant_id = %s", (prediction_id, tenant_id)).fetchone()
        if not p:
            raise NotFound("예측을 찾을 수 없습니다")
        mv = c.execute("SELECT version, stage, algo, created_at, snapshot_id FROM mlp_model_version "
                       "WHERE tenant_id=%s AND task_id=%s AND version=%s", (tenant_id, p["task_id"], p["version"])).fetchone()
        snap = (c.execute("SELECT snapshot_id, rows, ts_from, ts_to, synthetic FROM mlp_snapshot WHERE snapshot_id = %s",
                          (mv["snapshot_id"],)).fetchone() if mv else None)
    out = p["outputs"] or {}
    model_out = out.get("model") or {}
    explain = out.get("explain")
    return {
        "view": "explain",
        "prediction": {"prediction_id": p["prediction_id"], "task": p["task_id"], "version": p["version"],
                       "status": p["status"], "synthetic": p["synthetic"],
                       "explain": explain if isinstance(explain, dict) else None},
        "model": {"version": mv["version"], "stage": mv["stage"], "algo": mv["algo"],
                  "trained_at": model_out.get("trained_at") or _iso(mv["created_at"])} if mv else None,
        "snapshot": {"snapshot_id": snap["snapshot_id"], "rows": snap["rows"], "ts_from": _iso(snap["ts_from"]),
                     "ts_to": _iso(snap["ts_to"]), "synthetic": snap["synthetic"]} if snap else None,
        "notice": out.get("notice") or "",
    }
