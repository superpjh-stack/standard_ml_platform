"""과제 목록 — 병합된 회사 등록부(registry.tenants.Merged)를 추론이 쓰는 모양으로 (G-M01: 코어는 이름을 모른다)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..data.features import FeatureDef, feature_defs
from .errors import NotFound


@dataclass(frozen=True)
class TaskSpec:
    tenant_id: str
    task: Any                     # registry.tenants.TaskDef (id · pack_id · type · raw · def_hash)
    features: dict[str, dict]     # 과제 변수 이름 → 병합된 변수 정의(values_from: tenant 는 회사 categories 로 채움)
    notice: str
    max_imputed: int
    defs: tuple[FeatureDef, ...] = ()   # 같은 변수의 FeatureDef (계약 interfaces §7 — 검증은 이것으로, D-47)

    def meta(self) -> list[dict]:
        """화면 폼 생성용 변수 메타(과제 변수 순서) — features.yaml 항목 + name."""
        return [{"name": n, **{k: v for k, v in f.items() if k != "values_from"}} for n, f in self.features.items()]


class TaskCatalog:
    def __init__(self, merged: Any):
        self.merged = merged
        self.tenant_id: str = merged.tenant.code
        cats = merged.tenant.config.get("categories") or {}
        default_notice = merged.pack.meta.get("notice") or ""
        self._specs: dict[str, TaskSpec] = {}
        for task_id, td in merged.tasks.items():
            feats: dict[str, dict] = {}
            for name in td.raw.get("features") or []:
                f = dict(merged.pack.features[name])
                if f.get("values_from") == "tenant":
                    f["values"] = list(cats.get(name) or [])
                feats[name] = f
            notice = td.raw.get("notice") or (merged.tenant.config.get("labels") or {}).get("notice") or default_notice
            names = list(feats)
            if td.type == "optimize":   # 최적화는 자기 변수가 없다 — 고정 · 조절 변수(의존 과제 변수)를 쓴다
                names = list(dict.fromkeys(list(td.raw.get("fixed") or []) + list(td.raw.get("controls") or [])))
                for name in names:
                    f = dict(merged.pack.features[name])
                    if f.get("values_from") == "tenant":
                        f["values"] = list(cats.get(name) or [])
                    feats[name] = f
            defs = tuple(feature_defs(merged.pack.features, names, cats))
            self._specs[task_id] = TaskSpec(self.tenant_id, td, feats, notice, int(td.raw.get("max_imputed", 3)), defs)

    def get(self, tenant_id: str, task_id: str) -> TaskSpec:
        spec = self._specs.get(task_id)
        if spec is None or tenant_id != self.tenant_id:
            raise NotFound("과제를 찾을 수 없습니다")
        return spec

    def require_servable(self, tenant_id: str, task_id: str, ref: Any = None) -> None:
        """예측 시점 방어 (D-120a · DEF-QA3-001 #17, 개발3 요청).
        1) 병합에서 꺼진 과제(R4 등) → 503 model_not_ready (404 아님 — 과제는 있으나 운영 모델을 쓸 수 없다).
        2) live 회사인데 production 이 합성 스냅숏 모델 → 503 model_not_ready (기동 뒤 승인된 합성 모델은 기동 병합이 못 본다)."""
        from ..registry.models import ModelNotReady
        if tenant_id == self.tenant_id and task_id in (getattr(self.merged, "disabled", None) or {}):
            raise ModelNotReady("이 과제는 꺼져 있어 운영 모델을 쓸 수 없습니다", {"task": task_id, "rule": "disabled"})
        if ref is not None and self.merged.tenant.config.get("mode") == "live" and getattr(ref, "synthetic", False):
            raise ModelNotReady("live 회사에서 합성 스냅숏 모델로 답하지 않습니다", {"task": task_id, "rule": "live_synthetic"})

    def ids(self) -> list[str]:
        return list(self._specs)


# ── 유형별 모델 상태 (DEF-QA23-002 · #29 · C2 D2-94) ────────────────────────────────────────────────
# 자기 모델이 있는 과제는 학습 유형(regression · risk · anomaly)과 model 추출기를 가진 extract 뿐이다. 규칙 extract 는 모델이
# 필요 없고, optimize · quote · review_queue 는 `uses` 과제의 production 으로 돈다 — health · overview · 화면 1 이 같은 판정을 쓴다.
LEARNED_TYPES = ("regression", "risk", "anomaly")


def model_required(task: Any) -> bool:
    if task.type in LEARNED_TYPES:
        return True
    if task.type == "extract":
        return any((e or {}).get("kind") == "model" for e in task.raw.get("extractors") or [])
    return False


def uses_of(task: Any, tenant_id: str) -> list[str] | None:
    """의존 과제의 회사 과제 ID(`<회사>.<짧은 이름>`). 의존이 없는 유형은 None."""
    uses = task.raw.get("uses") if task.type in ("optimize", "quote", "review_queue") else None
    return [f"{tenant_id}.{str(u).split('.', 1)[-1]}" for u in uses] if uses else None


def serving_ready(task: Any, tenant_id: str, has_production) -> bool:
    """has_production(task_id) → bool. 자기 모델 과제 = 그 production, 의존 과제 = uses 전부 production, 규칙만 = True."""
    if model_required(task):
        return bool(has_production(task.id))
    uses = uses_of(task, tenant_id)
    return all(has_production(u) for u in uses) if uses else True
