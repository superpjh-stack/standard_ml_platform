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
from ..registry.models import ModelRef, Registry
from ..tasks.base import kind_for, warn
from .catalog import TaskCatalog, TaskSpec
from .contract import to_contract
from .errors import NotFound
from .ids import new_id
from .record import record
from .validate import check_missing, impute, range_check, validate_bounds, validate_format

KST = timezone(timedelta(hours=9))
EXPLAIN_TOP = 5
IMPUTE_TEXT = {"median": "학습 중앙값으로 보정했습니다", "most_frequent": "학습 최빈값으로 보정했습니다"}


@dataclass(frozen=True)
class PredictRequest:
    inputs: dict[str, Any]
    entity_id: str | None = None
    explain: bool = False
    model_version: str | None = None


def _iso(ts) -> str:
    return ts.astimezone(KST).isoformat(timespec="seconds")


class Predictor:
    def __init__(self, catalog: TaskCatalog, registry: Registry | None = None):
        self.catalog = catalog
        self.registry = registry or Registry()

    # ── 모델 ────────────────────────────────────────────────────────────────
    def _model(self, spec: TaskSpec, version: str | None) -> tuple[ModelRef, Any]:
        ref = self.registry.get(spec.tenant_id, spec.task.id, version)      # 없으면 ModelNotReady
        if version is not None and ref.stage not in ("production", "staging"):
            raise NotFound("예측에 쓸 수 있는 모델 버전이 아닙니다")
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
        for i, n in enumerate(names):
            rows.at[i, n] = lf[n]["fill"]
        vals = kind.values(loaded, rows)
        contrib = [(n, float(base - v)) for n, v in zip(names, vals)]
        contrib.sort(key=lambda x: (-abs(x[1]), x[0]))
        return {"method": "permutation_local",
                "top": [{"field": n, "contribution": round(c, 6)} for n, c in contrib[:EXPLAIN_TOP]]}

    # ── 예측 ────────────────────────────────────────────────────────────────
    def predict(self, tenant_id: str, task_id: str, req: PredictRequest, *, caller: str, channel: str = "api") -> dict:
        spec = self.catalog.get(tenant_id, task_id)                          # 없는 과제 → 404
        task, feats = spec.task, spec.features
        validate_format(req.inputs, feats)                                   # 1단 형식
        validate_bounds(req.inputs, feats)                                   # 2단 min/max
        check_missing(req.inputs, feats, spec.max_imputed)                   # 필수 · 보정 한도 (모델 없이 판정)
        kind = kind_for(task.type)
        ref, loaded = self._model(spec, req.model_version)
        filled, imputed = impute(req.inputs, feats, loaded.lock, spec.max_imputed)
        oor, near = range_check(filled, loaded.lock, skip=imputed)           # 3단 학습 범위
        frame = pd.DataFrame([{n: filled[n] for n in loaded.lock["order"]}], columns=loaded.lock["order"])

        reject = bool(oor) and task.raw.get("out_of_range") == "reject"
        if reject:
            piece = kind.rejected(loaded, task)
            _, ws = kind.status(piece, task, oor, near)
            status = "rejected"
        else:
            piece = kind.score(loaded, frame, task)[0]
            status, ws = kind.status(piece, task, oor, near)
        warnings = [warn("imputed", n, IMPUTE_TEXT.get(feats[n].get("impute", "median"), "학습 값으로 보정했습니다"))
                    for n in imputed] + ws
        if ref.synthetic:
            warnings.append(warn("synthetic_model", None, "합성 데이터로 학습한 모델입니다"))
        explain = None
        if req.explain and not reject:
            explain = self._explain(kind, loaded, frame, float(kind.values(loaded, frame)[0]))

        prediction_id = new_id("prd")
        out = to_contract({
            "task": task.id, "type": task.type, "tenant": tenant_id, "entity_id": req.entity_id,
            **piece, "recommendation": None,
            "status": status,
            "warnings": warnings, "imputed_fields": imputed, "out_of_range_fields": oor,
            "explain": explain,
            "model": {"name": ref.algo, "version": ref.version, "trained_at": _iso(ref.trained_at),
                      "snapshot_id": ref.snapshot_id, "synthetic": ref.synthetic},
            "uses": None, "prediction_id": prediction_id, "synthetic": ref.synthetic, "notice": spec.notice,
        })
        record(prediction_id=prediction_id, tenant_id=tenant_id, task_id=task.id, version=ref.version,
               entity_id=req.entity_id, inputs=dict(req.inputs), outputs=out, status=out["status"],
               caller=caller, channel=channel, synthetic=ref.synthetic)
        return out

    def predict_batch(self, tenant_id: str, task_id: str, reqs: Sequence[PredictRequest], *, caller: str) -> dict:
        raise NotImplementedError("predict:batch 는 웨이브 A")   # pragma: no cover
