"""`extract` 유형 — 추출기 플러그인 프로토콜 · 로더 · 결과 합침 (task-contract §6.2 · progress-dev2 2차 §1.1). 소유 개발2.

코어는 도면의 뜻을 모른다: 영역 · 객체 · BOM 을 만드는 것은 팩 `extractors/<name>.py` 다. 코어는
(1) 과제 `document` 상한을 spec 상한 아래로 정하고 (2) 플러그인을 과제 정의 순서대로 부르고 (3) 결과를 계약 키로 합친다.
`model` 추출기는 그 extract 과제의 등록부 production 산출물만 받는다(호출자가 넘긴다 — 여기서 학습하지 않는다).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Literal, Protocol

from .dxf import DocumentError

__all__ = ["Extractor", "ExtractError", "limits_for", "load_extractor", "merge_results", "SPEC_LIMITS", "OUTPUT_KEYS"]

SPEC_LIMITS = {"max_bytes": 5 * 1024 * 1024, "max_entities": 20000}       # spec §8.3 — 팩 · 회사는 낮추기만
OUTPUT_KEYS = ("regions", "objects", "bom_rows")
REPLACEABLE = OUTPUT_KEYS + ("counts", "dimensions")     # 결과 `replaces` 로 앞 결과를 바꿀 수 있는 키


class ExtractError(DocumentError):
    """추출기가 올리는 문서 오류 — code invalid_document(422) | document_too_large(413), rule 은 api-contract §6.1."""


class Extractor(Protocol):
    NAME: str
    VERSION: str
    KIND: Literal["rule", "model"]

    def extract(self, raw: bytes, filename: str, *, unit: str, limits: dict, model: Any = None,
                context: dict | None = None) -> dict: ...
    # context(선택 인자 — 받는 추출기에만 넘긴다): {categories, material_aliases, params, previous}
    #   params   = 과제 extractors[].params (팩 YAML 값 — 임계값 · 허용차 · 팩 고유 상한, 코드 상수 금지)
    #   previous = 앞 추출기까지 합친 결과(None = 첫 추출기). 규칙 추출기가 찾은 객체를 모델 추출기가 분류할 때 쓴다.
    # 결과 키 `replaces: ["objects", …]` 가 있으면 합칠 때 그 배열을 이어 붙이지 않고 이 결과로 바꾼다(앞 결과를 다듬은 경우).


def limits_for(task_raw: dict) -> dict:
    """과제 document 상한(낮추기만) → {max_bytes, max_entities, unit_override}."""
    doc = task_raw.get("document") or {}
    out = {}
    for k, cap in SPEC_LIMITS.items():
        v = doc.get(k)
        out[k] = min(int(v), cap) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else cap
    out["unit_override"] = [u for u in (doc.get("unit_override") or ["mm", "inch"]) if u in ("mm", "inch")]
    out["formats"] = list(doc.get("formats") or ["dxf"])
    return out


_CACHE: dict[tuple[str, str], Any] = {}


def load_extractor(pack_path: Path, spec: dict) -> Any:
    """`extractors/<name>.py` → 모듈(NAME · VERSION · KIND · extract). 같은 파일 · 같은 내용이면 한 번만 import."""
    path = (Path(pack_path) / str(spec["module"])).resolve()
    if not path.is_file() or Path(pack_path).resolve() not in path.parents:
        raise FileNotFoundError(f"추출기 모듈 없음: {spec.get('module')}")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    key = (str(path), sha)
    if key not in _CACHE:
        name = f"mlp_extractor_{sha[:16]}_{path.stem}"
        mod_spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(mod_spec)
        sys.modules[name] = mod
        mod_spec.loader.exec_module(mod)
        for attr in ("NAME", "VERSION", "KIND", "extract"):
            if not hasattr(mod, attr):
                raise TypeError(f"추출기 {path.stem} 에 {attr} 가 없습니다")
        if mod.KIND not in ("rule", "model"):
            raise TypeError(f"추출기 {path.stem} KIND {mod.KIND!r}")
        _CACHE[key] = mod
    return _CACHE[key]


def merge_results(parts: list[tuple[Any, dict]]) -> dict:
    """[(추출기 모듈, 결과)] → 합친 결과. 배열 이어 붙임(결과 `replaces` 에 든 배열은 바꿈) · counts 키별 합 · dimensions 처음 non-null ·
    confidence = model 추출기 값 평균(규칙만이면 None) · warnings 이어 붙임."""
    out: dict[str, Any] = {k: [] for k in OUTPUT_KEYS}
    out.update(counts={}, dimensions=None, confidence=None, warnings=[])
    scores: list[float] = []
    for mod, res in parts:
        if not isinstance(res, dict):
            raise TypeError(f"추출기 {getattr(mod, 'NAME', '?')} 결과가 dict 가 아닙니다")
        replaces = res.get("replaces") or []
        if not isinstance(replaces, list) or any(k not in REPLACEABLE for k in replaces):
            raise TypeError(f"추출기 {getattr(mod, 'NAME', '?')} 의 replaces 는 {list(REPLACEABLE)} 중 이름 목록입니다")
        if "counts" in replaces:
            out["counts"] = {}
        if "dimensions" in replaces:
            out["dimensions"] = None
        for k in OUTPUT_KEYS:
            vals = res.get(k) or []
            if not isinstance(vals, list):
                raise TypeError(f"추출기 {mod.NAME} 의 {k} 가 배열이 아닙니다")
            if k in replaces:
                out[k] = list(vals)
            else:
                out[k].extend(vals)
        for k, v in (res.get("counts") or {}).items():
            out["counts"][str(k)] = int(out["counts"].get(str(k), 0)) + int(v)
        if out["dimensions"] is None and res.get("dimensions") is not None:
            out["dimensions"] = dict(res["dimensions"])
        if mod.KIND == "model" and res.get("confidence") is not None:
            scores.append(float(res["confidence"]))
        out["warnings"].extend(str(w) for w in (res.get("warnings") or []))
    if scores:
        out["confidence"] = round(sum(scores) / len(scores), 6)
    return out
