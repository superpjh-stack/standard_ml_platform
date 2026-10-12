"""모델 등록부 — 상태 전이 candidate → staging → production → archived (spec §6.1 · contracts/interfaces.md §5). 소유 개발2.

- `register` 는 항상 candidate 를 만든다. 학습기가 쓴 산출물의 해시 · env.lock 을 그 자리에서 잰다.
- `stage` 는 candidate → staging 만 한다(기준선 이김 · 차단 경고 없음 · live 회사면 합성 아님).
- `request_promotion` 은 mlp_approval(pending) 만 만든다. **production 으로 바꾸는 코드는 여기 없다** —
  유일한 경로는 `approval.decide()` 다(G-M09 · gates/check_no_autopromote.py).
- `get(version=None)` = 운영 버전. 없으면 ModelNotReady(503) — 다른 버전으로 대신 답하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .. import audit
from ..db.conn import connect
from ..serve.errors import MissingRequired, NotFound, ServeError
from ..serve.ids import new_id
from .artifacts import ArtifactMismatch, artifact_sha256, resolve_dir, store_path

__all__ = ["ModelRef", "Registry", "ModelNotReady", "ArtifactMismatch", "InvalidTransition"]

PROD = "production"   # 비교 · 조회에만 쓴다. 쓰기는 approval.decide()


class ModelNotReady(ServeError):
    status, code, default_message = 503, "model_not_ready", "운영(production) 모델이 없습니다"


class InvalidTransition(ServeError):
    status, code, default_message = 409, "invalid_transition", "허용되지 않는 상태 전이입니다"


@dataclass(frozen=True)
class ModelRef:
    tenant_id: str
    task_id: str
    version: str
    stage: str
    algo: str
    snapshot_id: str
    run_id: str
    synthetic: bool
    artifact_sha256: str
    trained_at: datetime
    artifact_path: str = ""
    env_lock: dict = field(default_factory=dict)
    beats_baseline: bool = False
    metrics: dict = field(default_factory=dict)
    created_at: datetime | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None


_SELECT = (
    "SELECT mv.*, coalesce(r.finished_at, mv.created_at) AS trained_at "
    "FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id ")


def _ref(row: dict) -> ModelRef:
    return ModelRef(
        tenant_id=row["tenant_id"], task_id=row["task_id"], version=row["version"], stage=row["stage"],
        algo=row["algo"], snapshot_id=row["snapshot_id"], run_id=row["run_id"], synthetic=row["synthetic"],
        artifact_sha256=row["artifact_sha256"], trained_at=row["trained_at"], artifact_path=row["artifact_path"],
        env_lock=row["env_lock"], beats_baseline=row["beats_baseline"], metrics=row["metrics"],
        created_at=row["created_at"], promoted_at=row["promoted_at"], promoted_by=row["promoted_by"])


def _metric(v: Any) -> dict:
    if isinstance(v, dict):
        return {"value": v.get("value"), "baseline": v.get("baseline"), "delta_vs_baseline": v.get("delta_vs_baseline")}
    return {"value": getattr(v, "value", None), "baseline": getattr(v, "baseline", None),
            "delta_vs_baseline": getattr(v, "delta_vs_baseline", None)}


def _blocking(warnings: Any) -> list[dict]:
    """차단 경고 — {severity: "block"} 또는 {block: true} 인 항목 (학습 보고서 warnings)."""
    out = []
    for w in warnings or []:
        if isinstance(w, dict) and (w.get("block") is True or w.get("severity") == "block"):
            out.append(w)
    return out


class Registry:
    """mlp_model_version + 파일 산출물 (D-03). 연결은 요청마다 짧게(db.conn.connect)."""

    # ── 등록 ────────────────────────────────────────────────────────────────
    def register(self, result: Any, *, tenant_id: str, task_id: str) -> ModelRef:
        if getattr(result, "status", None) != "succeeded":
            raise InvalidTransition("학습이 성공하지 않아 등록할 수 없습니다", {"rule": "train_not_succeeded"})
        if not getattr(result, "artifact_dir", None) or not getattr(result, "champion", None):
            raise InvalidTransition("산출물 · 선정 모델이 없어 등록할 수 없습니다", {"rule": "no_artifact"})
        version_dir = resolve_dir(result.artifact_dir)
        digest = artifact_sha256(version_dir)
        claimed = getattr(result, "artifact_sha256", None)
        if claimed and claimed != digest:              # 학습기가 잰 해시와 지금 파일이 다르면 등록하지 않는다
            raise ArtifactMismatch(detail={"rule": "sha256_at_register", "field": None})
        env_lock = json.loads((version_dir / "env.lock").read_text(encoding="utf-8"))
        metrics = {k: _metric(v) for k, v in (getattr(result, "test_metrics", None) or {}).items()}
        with connect() as c:
            run = c.execute("SELECT r.run_id, r.tenant_id, r.task_id, r.snapshot_id, r.code_version, s.synthetic "
                            "FROM mlp_train_run r JOIN mlp_snapshot s ON s.snapshot_id = r.snapshot_id "
                            "WHERE r.run_id = %s", (result.run_id,)).fetchone()
            if not run or run["tenant_id"] != tenant_id or run["task_id"] != task_id:
                raise NotFound("학습 실행을 찾을 수 없습니다")
            # 과제 행을 잠가 버전 일련번호를 직렬화한다
            c.execute("SELECT 1 FROM mlp_task WHERE tenant_id = %s AND task_id = %s FOR UPDATE", (tenant_id, task_id))
            same = c.execute(_SELECT + "WHERE mv.run_id = %s", (result.run_id,)).fetchone()
            if same:                                   # 같은 실행을 두 번 등록하지 않는다(멱등)
                return _ref(same)
            n = c.execute("SELECT coalesce(max(substr(version, 2)::int), 0) + 1 AS n FROM mlp_model_version "
                          "WHERE tenant_id = %s AND task_id = %s", (tenant_id, task_id)).fetchone()["n"]
            version = f"v{n}"
            c.execute(
                "INSERT INTO mlp_model_version (tenant_id, task_id, version, run_id, snapshot_id, algo, metrics, "
                "beats_baseline, stage, artifact_path, artifact_sha256, env_lock, code_version, synthetic) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'candidate',%s,%s,%s::jsonb,%s,%s)",
                (tenant_id, task_id, version, run["run_id"], run["snapshot_id"], result.champion,
                 json.dumps(metrics, default=float), bool(result.beats_baseline), store_path(version_dir), digest,
                 json.dumps(env_lock), run["code_version"], run["synthetic"]))
            audit.write(tenant_id=tenant_id, actor="system", role=None, action="model.register",
                        target=f"{task_id}@{version}", detail={"run_id": run["run_id"], "stage": "candidate"}, conn=c)
            row = c.execute(_SELECT + "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                            (tenant_id, task_id, version)).fetchone()
        return _ref(row)

    # ── candidate → staging ─────────────────────────────────────────────────
    def stage(self, tenant_id: str, task_id: str, version: str, *, actor: str, role: str | None = None,
              request_id: str | None = None) -> ModelRef:
        with connect() as c:
            row = c.execute(
                "SELECT mv.stage, mv.beats_baseline, mv.synthetic, t.mode, r.report FROM mlp_model_version mv "
                "JOIN mlp_tenant t ON t.tenant_id = mv.tenant_id JOIN mlp_train_run r ON r.run_id = mv.run_id "
                "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s FOR UPDATE OF mv",
                (tenant_id, task_id, version)).fetchone()
            if not row:
                raise NotFound("모델 버전을 찾을 수 없습니다")
            if row["stage"] != "candidate":
                raise InvalidTransition("candidate 만 staging 으로 올릴 수 있습니다", {"rule": "from_candidate_only"})
            if not row["beats_baseline"]:
                raise InvalidTransition("기준선을 이기지 못한 모델입니다", {"rule": "baseline"})
            blocks = _blocking((row["report"] or {}).get("warnings"))
            if blocks:
                raise InvalidTransition("차단 경고가 있는 모델입니다", {"rule": "blocking_warning"})
            if row["mode"] == "live" and row["synthetic"]:
                raise InvalidTransition("live 회사에서 합성 스냅숏 모델은 올릴 수 없습니다", {"rule": "live_synthetic"})
            c.execute("UPDATE mlp_model_version SET stage = 'staging', staged_at = now() "
                      "WHERE tenant_id=%s AND task_id=%s AND version=%s AND stage = 'candidate'",
                      (tenant_id, task_id, version))
            audit.write(tenant_id=tenant_id, actor=actor, role=role, action="model.stage",
                        target=f"{task_id}@{version}", detail={"from": "candidate", "to": "staging"},
                        request_id=request_id, conn=c)
            out = c.execute(_SELECT + "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                            (tenant_id, task_id, version)).fetchone()
        return _ref(out)

    # ── 조회 ────────────────────────────────────────────────────────────────
    def get(self, tenant_id: str, task_id: str, version: str | None = None) -> ModelRef:
        with connect() as c:
            if version is None:
                row = c.execute(_SELECT + "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.stage = %s",
                                (tenant_id, task_id, PROD)).fetchone()
            else:
                row = c.execute(_SELECT + "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                                (tenant_id, task_id, version)).fetchone()
        if not row:
            raise ModelNotReady("운영(production) 모델이 없습니다" if version is None else "요청한 모델 버전이 없습니다",
                                {"task": task_id, "version": version})
        return _ref(row)

    def list(self, tenant_id: str, task_id: str) -> list[ModelRef]:
        with connect() as c:
            rows = c.execute(_SELECT + "WHERE mv.tenant_id=%s AND mv.task_id=%s "
                             "ORDER BY substr(mv.version, 2)::int DESC", (tenant_id, task_id)).fetchall()
        return [_ref(r) for r in rows]

    # ── 승인 요청 (production 은 바꾸지 않는다) ──────────────────────────────
    def request_promotion(self, tenant_id: str, task_id: str, version: str, *, actor: str,
                          action: Literal["promote", "rollback"], reason: str | None,
                          role: str | None = None, request_id: str | None = None) -> str:
        if action not in ("promote", "rollback"):
            raise InvalidTransition("알 수 없는 승인 동작입니다", {"rule": "action"})
        if action == "rollback" and not (reason or "").strip():   # 전이 문제가 아니라 입력 누락 (D-54)
            raise MissingRequired("되돌리기는 사유가 필요합니다", {"field": "reason", "rule": "required"})
        with connect() as c:
            row = c.execute("SELECT mv.stage, mv.metrics, mv.synthetic, mv.promoted_at, t.approver_role "
                            "FROM mlp_model_version mv JOIN mlp_task t ON t.tenant_id = mv.tenant_id AND t.task_id = mv.task_id "
                            "WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                            (tenant_id, task_id, version)).fetchone()
            if not row:
                raise NotFound("모델 버전을 찾을 수 없습니다")
            if action == "promote" and row["stage"] != "staging":
                raise InvalidTransition("staging 버전만 승격 요청할 수 있습니다", {"rule": "from_staging_only"})
            if action == "rollback" and (row["stage"] != "archived" or row["promoted_at"] is None):
                raise InvalidTransition("운영 이력이 있는 archived 버전만 되돌릴 수 있습니다", {"rule": "from_archived_only"})
            cur = c.execute("SELECT version, metrics FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s AND stage = %s",
                            (tenant_id, task_id, PROD)).fetchone()
            evidence = {"target": {"version": version, "metrics": row["metrics"], "synthetic": row["synthetic"]},
                        "production": ({"version": cur["version"], "metrics": cur["metrics"]} if cur else None),
                        "shadow": shadow_diff(c, tenant_id, task_id, version, cur["version"] if cur else None)}
            from ..approval import expire_due, ttl_hours     # 지연 import — approval 은 등록부를 import 하지 않는다
            expire_due(tenant_id=tenant_id, conn=c)          # 만료 대기 건을 먼저 닫아야 같은 대상 재요청이 새 승인이 된다(D-130)
            approval_id = new_id("apr")
            got = c.execute(
                "INSERT INTO mlp_approval (approval_id, tenant_id, task_id, kind, ref_id, action, approver_role, state, "
                "requested_by, reason, evidence, expires_at) VALUES (%s,%s,%s,'model',%s,%s,%s,'pending',%s,%s,%s::jsonb, "
                "now() + make_interval(secs => %s)) "
                "ON CONFLICT (tenant_id, kind, ref_id, task_id) WHERE state = 'pending' DO NOTHING RETURNING approval_id",
                (approval_id, tenant_id, task_id, version, action, row["approver_role"], actor, reason,
                 json.dumps(evidence, default=str), ttl_hours("model") * 3600)).fetchone()
            if not got:                                # 같은 대상의 대기 승인이 이미 있다 → 그것을 돌려준다
                return c.execute("SELECT approval_id FROM mlp_approval WHERE tenant_id=%s AND task_id=%s AND kind='model' "
                                 "AND ref_id=%s AND state='pending'", (tenant_id, task_id, version)).fetchone()["approval_id"]
            audit.write(tenant_id=tenant_id, actor=actor, role=role, action=f"approval.request.{action}",
                        target=f"{task_id}@{version}", detail={"approval_id": approval_id}, request_id=request_id, conn=c)
        return approval_id


SHADOW_N = 200


def shadow_diff(c, tenant_id: str, task_id: str, target: str, production: str | None) -> dict | None:
    """그림자 예측 차이 — 최근 운영 입력(mlp_prediction.inputs, 최대 200건)을 대상 버전과 현재 production 으로 같이 채점한
    차이 {n, mean_abs_diff, max_abs_diff, basis}. 시험 구간은 쓰지 않는다(운영 입력만). production · 운영 입력이 없으면 None.
    산출물 불일치 등 실패는 숨기지 않고 {error: code} 로 남긴다(승인자가 본다)."""
    if production is None:
        return None
    rows = c.execute("SELECT inputs FROM mlp_prediction WHERE tenant_id = %s AND task_id = %s AND status <> 'rejected' "
                     "ORDER BY ts DESC LIMIT %s", (tenant_id, task_id, SHADOW_N)).fetchall()
    if not rows:
        return None
    import numpy as np
    import pandas as pd

    from ..serve.validate import impute
    from ..tasks.base import kind_for
    from .artifacts import load_artifacts
    try:
        refs = {v: Registry().get(tenant_id, task_id, v) for v in (target, production)}
        task_type = c.execute("SELECT type FROM mlp_task WHERE tenant_id=%s AND task_id=%s", (tenant_id, task_id)).fetchone()["type"]
        kind = kind_for(task_type)
        vals = {}
        for v, ref in refs.items():
            ld = load_artifacts(ref)
            order = ld.lock["order"]
            feats = {n: {"dtype": (ld.lock["features"][n] or {}).get("dtype", "float"), "label": n, "required": False}
                     for n in order}
            frame = []
            for r in rows:
                filled, _ = impute({k: r["inputs"].get(k) for k in order}, feats, ld.lock, len(order))
                frame.append({n: filled[n] for n in order})
            vals[v] = np.asarray(kind.values(ld, pd.DataFrame(frame, columns=order)), dtype=float)
        d = np.abs(vals[target] - vals[production])
        return {"n": int(len(d)), "mean_abs_diff": round(float(d.mean()), 6), "max_abs_diff": round(float(d.max()), 6),
                "basis": "recent_operating_inputs"}
    except ServeError as e:
        return {"error": e.code, "detail": e.detail}
