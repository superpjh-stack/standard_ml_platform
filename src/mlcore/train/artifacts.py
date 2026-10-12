"""학습 산출물 쓰기 — model.joblib · features.lock.json · env.lock · report.json + SHA-256 (spec §6.2).

파일 모양 · 해시 규칙 · env.lock 은 등록부 쪽 `registry.artifacts`(개발2 progress-dev2.md §1.3-1.4)를 그대로 쓴다 —
적재 대조가 같은 함수로 돌아야 하기 때문이다. 버전 번호는 등록부가 붙이므로 학습기는 run 단위 폴더
(`var/artifacts/<tenant>/<task>/<run_id>/`)에 쓴다(D-48). 내용 해시라 폴더를 옮겨도 그대로다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


def clean(obj):
    """JSON(jsonb) 에 넣을 수 있게 NaN · Inf → None, numpy 스칼라 → 파이썬, 튜플 → 목록."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, AttributeError, TypeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def dumps(obj) -> str:
    return json.dumps(clean(obj), ensure_ascii=False, sort_keys=True, default=str)


def write(dir_: Path, *, model, features_lock: dict, report: dict) -> str:
    """4개 파일 → 산출물 해시(registry.artifacts.artifact_sha256 규칙)."""
    from ..registry.artifacts import save_artifacts

    return save_artifacts(Path(dir_), model, clean(report), clean(features_lock))


def lock(order, feats, *, ranges: dict, fills: dict, baseline, interval: dict | None, extra: dict) -> dict:
    from ..registry.artifacts import features_lock

    base = features_lock(order, {f.name: {"dtype": f.dtype} for f in feats}, ranges=ranges, fills=fills,
                         baseline=baseline, interval=interval)
    return clean({**base, **extra})
