"""추론 — Predictor.predict() (contracts/interfaces.md §7 · predict-contract.md). 소유 개발2.

모델은 등록부(Registry.get)와 해시 대조 산출물(load_artifacts)에서만 온다. 운영 모델이 없으면 503 model_not_ready —
기본값 · 대체 모델로 답하지 않는다. 학습 범위 밖이면 200 + out_of_range(정책 reject 면 rejected, 값 null).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any, Sequence

import pandas as pd

from ..registry.artifacts import ArtifactMismatch, load_artifacts
from ..registry.models import ModelNotReady, ModelRef, Registry
from ..tasks.base import kind_for, warn
from .catalog import TaskCatalog, TaskSpec
from .contract import to_contract
from ..db.conn import connect
from .errors import InvalidInput, NotFound, ServeError
from .ids import new_id
from .record import record
from .validate import check_missing, impute, range_check, validate_bounds, validate_format

KST = timezone(timedelta(hours=9))
EXPLAIN_TOP = 5
BATCH_MAX = 500
IMPUTE_TEXT = {"median": "학습 중앙값으로 보정했습니다", "most_frequent": "학습 최빈값으로 보정했습니다"}


@dataclass(frozen=True)
class PredictRequest:
    inputs: dict[str, Any]
    entity_id: str | None = None
    explain: bool = False
    model_version: str | None = None


@dataclass(frozen=True)
class BatchItemError:
    """배치 한 건이 요청 모양 단계(라우터의 pydantic 검증)에서 이미 422 인 자리 — 다른 건은 그대로 채점한다."""
    index: int
    error: ServeError


def _iso(ts) -> str:
    return ts.astimezone(KST).isoformat(timespec="seconds")


class Predictor:
    def __init__(self, catalog: TaskCatalog, registry: Registry | None = None):
        self.catalog = catalog
        self.registry = registry or Registry()

    # ── 모델 ────────────────────────────────────────────────────────────────
    def _model(self, spec: TaskSpec, version: str | None) -> tuple[ModelRef, Any]:
        try:
            ref = self.registry.get(spec.tenant_id, spec.task.id, version)  # production 없음 → ModelNotReady(503)
        except ModelNotReady:
            if version is None:
                raise
            ref = None                     # 지정한 버전이 없다 = 쓸 수 없는 버전 → candidate 와 같은 404 (DEF-QA2-008)
        if version is not None and (ref is None or ref.stage not in ("production", "staging")):
            raise NotFound("예측에 쓸 수 있는 모델 버전이 아닙니다")
        self.catalog.require_servable(spec.tenant_id, spec.task.id, ref)
        loaded = load_artifacts(ref)                                        # 해시 · env.lock 불일치 → ArtifactMismatch
        order = list(loaded.lock.get("order") or [])
        if sorted(order) != sorted(spec.features):
            raise ArtifactMismatch(detail={"rule": "features_lock", "field": None})
        return ref, loaded

    def _explain(self, kind, loaded, frame: pd.DataFrame, base: float) -> dict:
        """permutation_local — 변수 하나를 학습 보정값으로 바꿨을 때의 변화량(기여 = 원래 − 바꾼 값)."""
        lf = loaded.lock.get("features") or {}
        names = [n for n in frame.columns if (lf.get(n) or {}).get("fill") is not None]
        if not names:
            return {"method": "permutation_local", "top": []}
        rows = pd.concat([frame] * len(names), ignore_index=True)
        for n in names:                                # 정수 열에 실수 보정값을 넣을 수 있게
            if not isinstance(lf[n]["fill"], str):
                rows[n] = rows[n].astype(float)
        for i, n in enumerate(names):
            rows.at[i, n] = lf[n]["fill"]
        vals = kind.values(loaded, rows)
        contrib = [(n, float(base - v)) for n, v in zip(names, vals)]
        contrib.sort(key=lambda x: (-abs(x[1]), x[0]))
        return {"method": "permutation_local",
                "top": [{"field": n, "contribution": round(c, 6)} for n, c in contrib[:EXPLAIN_TOP]]}

    # ── 예측 ────────────────────────────────────────────────────────────────
    def _check(self, spec: TaskSpec, req: PredictRequest) -> None:
        """입력 검증 3단 중 모델 없이 판정하는 것 — 형식 → min/max → 필수 · 보정 한도 (순서 고정)."""
        feats = spec.defs                                                    # Sequence[FeatureDef] (D-47)
        validate_format(req.inputs, feats)                                   # 1단 형식
        validate_bounds(req.inputs, feats)                                   # 2단 min/max
        check_missing(req.inputs, feats, spec.max_imputed)                   # 필수 · 보정 한도

    def _answer(self, spec: TaskSpec, ref: ModelRef, loaded: Any, reqs: Sequence[PredictRequest]) -> list[dict]:
        """검증을 통과한 요청들을 한 번에 채점 → 계약 응답 dict 목록(prediction_id 포함, 기록 전)."""
        task, feats = spec.task, spec.defs
        kind = kind_for(task.type)
        by_name = {f.name: f for f in feats}
        order = loaded.lock["order"]
        prepared = []
        for req in reqs:
            filled, imputed = impute(req.inputs, feats, loaded.lock, spec.max_imputed)
            oor, near = range_check(filled, loaded.lock, skip=imputed)           # 3단 학습 범위
            reject = bool(oor) and task.raw.get("out_of_range") == "reject"
            prepared.append((req, filled, imputed, oor, near, reject))
        live = [p for p in prepared if not p[5]]
        frame = pd.DataFrame([{n: p[1][n] for n in order} for p in live], columns=order)
        pieces = iter(kind.score(loaded, frame, task)) if len(frame) else iter(())
        raw_vals = iter(kind.values(loaded, frame)) if len(frame) and any(p[0].explain for p in live) else None
        out = []
        for req, filled, imputed, oor, near, reject in prepared:
            if reject:
                piece = kind.rejected(loaded, task)
                _, ws = kind.status(piece, task, oor, near)
                status = "rejected"
                base = None
            else:
                piece = next(pieces)
                status, ws = kind.status(piece, task, oor, near)
                base = next(raw_vals) if raw_vals is not None else None
            warnings = [warn("imputed", n, IMPUTE_TEXT.get(by_name[n].impute, "학습 값으로 보정했습니다"))
                        for n in imputed] + ws
            if ref.synthetic:
                warnings.append(warn("synthetic_model", None, "합성 데이터로 학습한 모델입니다"))
            explain = None
            if req.explain and not reject:
                one = pd.DataFrame([{n: filled[n] for n in order}], columns=order)
                explain = self._explain(kind, loaded, one, float(base))
            out.append(to_contract({
                "task": task.id, "type": task.type, "tenant": spec.tenant_id, "entity_id": req.entity_id,
                **piece, "recommendation": None,
                "status": status,
                "warnings": warnings, "imputed_fields": imputed, "out_of_range_fields": oor,
                "explain": explain,
                "model": {"name": ref.algo, "version": ref.version, "trained_at": _iso(ref.trained_at),
                          "snapshot_id": ref.snapshot_id, "synthetic": ref.synthetic},
                "uses": None, "prediction_id": new_id("prd"), "synthetic": ref.synthetic, "notice": spec.notice,
            }))
        return out

    def _record(self, spec: TaskSpec, ref: ModelRef, reqs, outs, *, caller: str, channel: str, conn=None) -> None:
        for req, out in zip(reqs, outs):
            record(prediction_id=out["prediction_id"], tenant_id=spec.tenant_id, task_id=spec.task.id,
                   version=ref.version, entity_id=req.entity_id, inputs=dict(req.inputs), outputs=out,
                   status=out["status"], caller=caller, channel=channel, synthetic=ref.synthetic, conn=conn)

    def predict(self, tenant_id: str, task_id: str, req: PredictRequest, *, caller: str, channel: str = "api") -> dict:
        self.catalog.require_servable(tenant_id, task_id)                    # 꺼진 과제 → 503 (D-120a)
        spec = self.catalog.get(tenant_id, task_id)                          # 없는 과제 → 404
        if spec.task.type == "optimize":
            raise NotFound("최적화 과제는 predict 가 아니라 optimize 로 부릅니다")
        kind_for(spec.task.type)                                             # 2차 유형 → 501
        self._check(spec, req)
        ref, loaded = self._model(spec, req.model_version)
        out = self._answer(spec, ref, loaded, [req])[0]
        self._record(spec, ref, [req], [out], caller=caller, channel=channel)
        return out

    def predict_batch(self, tenant_id: str, task_id: str, reqs: Sequence[PredictRequest], *, caller: str,
                      channel: str = "api") -> dict:
        """1~500건. 한 건의 422 가 다른 건을 막지 않는다(그 자리에 {index, error}). 모델 · 산출물 오류(503)는 전체 실패.
        순서 = 요청 순서. 같은 model_version 끼리 한 번에 채점하고, 기록은 한 트랜잭션."""
        if not 1 <= len(reqs) <= BATCH_MAX:
            raise InvalidInput(f"한 번에 1~{BATCH_MAX}건입니다", {"field": "items", "rule": "batch_size"})
        self.catalog.require_servable(tenant_id, task_id)
        spec = self.catalog.get(tenant_id, task_id)
        if spec.task.type == "optimize":
            raise NotFound("최적화 과제는 predict 가 아니라 optimize 로 부릅니다")
        kind_for(spec.task.type)
        items: list[dict | None] = [None] * len(reqs)
        groups: dict[str | None, list[int]] = {}
        for i, req in enumerate(reqs):
            if isinstance(req, BatchItemError):
                items[i] = {"index": i, "error": req.error.body()["error"]}
                continue
            try:
                self._check(spec, req)
            except ServeError as e:
                if e.status != 422:
                    raise
                items[i] = {"index": i, "error": e.body()["error"]}
                continue
            groups.setdefault(req.model_version, []).append(i)
        done: list[tuple[ModelRef, list[int], list[dict]]] = []
        for version, idx in groups.items():
            ref, loaded = self._model(spec, version)
            ok_idx, outs = self._answer_each(spec, ref, loaded, reqs, idx, items)   # 모델을 본 뒤의 422 도 그 건만
            done.append((ref, ok_idx, outs))
        with connect() as c:
            for ref, idx, outs in done:
                self._record(spec, ref, [reqs[i] for i in idx], outs, caller=caller, channel=channel, conn=c)
                for i, out in zip(idx, outs):
                    items[i] = out
        return {"items": items, "next_cursor": None}

    def _answer_each(self, spec, ref, loaded, reqs, idx, items):
        """한 번에 채점하되, 보정값 없음(422) 같은 건별 오류는 그 건만 뺀다."""
        good = []
        for i in idx:
            try:
                impute(reqs[i].inputs, spec.defs, loaded.lock, spec.max_imputed)
                good.append(i)
            except ServeError as e:
                if e.status != 422:
                    raise
                items[i] = {"index": i, "error": e.body()["error"]}
        outs = self._answer(spec, ref, loaded, [reqs[i] for i in good]) if good else []
        return good, outs
