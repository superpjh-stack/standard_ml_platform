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

    def ids(self) -> list[str]:
        return list(self._specs)
