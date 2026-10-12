"""모델 추출기 — 도면 객체 분류(외곽 · 홀 · 슬롯 · 기타) + 기하 검증 나머지 5 사유 (task-contract §6.2 · source_inventory §10.5 X8 · X9).

원천 `api/cad.py:108-128` · `ml_service.py:114-117 classify()` 를 **읽어** 이관했다(실행하지 않는다).
- 입력: 앞 추출기(geometry_objects)까지 합친 결과 `context["previous"]` 의 objects(설명자 6 · 기하 사유 앞 3).
- 모델: 이 extract 과제의 등록부 production 산출물(`model` — 코어가 해시 대조해 넘긴다, 여기서 학습하지 않는다).
  분류 = 확률 최대 클래스 · 점수 = 그 확률(소수 4자리, 보정된 신뢰확률이 아니다 — 원천 경고 문구 그대로).
- 사유(원천 순서): 기하 사유(앞 추출기) → 점수 < score_min → 외곽인데 외곽 아님 → 외곽 아닌데 외곽 → 원 아닌 홀 → 곡선 없는 슬롯.
  사유가 있으면 label other(자동 홀 · 슬롯 수에서 뺀다), 사유 없이 모델이 other 면 "지원 학습 형상 밖".
- 결과는 앞 objects 를 이어 붙이지 않고 바꾼다(`replaces: [objects, counts]`). counts 는 outer · hole · slot · other.
점수 하한은 과제 params(score_min) — 코드 상수 0.
"""

from __future__ import annotations

import pandas as pd

from mlcore.tasks.extract import ExtractError

NAME = "object_classifier"
VERSION = "1.0.0"
KIND = "model"

CLASSES = ("outer", "hole", "slot", "other")
DESCRIPTORS = ("is_circle", "is_closed", "aspect_ratio", "area_ratio", "circularity", "is_curved")
HELPER_KEYS = ("descriptors", "is_outer", "geometry_reason")
DEFAULTS = {"score_min": 0.8}
REASON_SCORE = "분류 점수 {pct}% 미만"
REASON_OUTER_MISMATCH = "외곽 기하와 모델 분류 불일치"
REASON_EXTRA_OUTER = "추가 외곽 후보: 다중 부품 확인 필요"
REASON_HOLE = "원형 홀 기하 확인 필요"
REASON_SLOT = "슬롯 곡선 기하 확인 필요"
REASON_UNSUPPORTED = "지원 학습 형상 밖: 수동 확인 필요"


def _estimator_and_order(model):
    """등록부 산출물(LoadedModel: model · lock) 또는 시험용 (estimator, 설명자 순서)."""
    if model is None:
        raise ExtractError("invalid_document", "model", "객체 분류 모델이 없습니다")
    est = getattr(model, "model", model)
    lock = getattr(model, "lock", None) or {}
    order = list(lock.get("order") or DESCRIPTORS)
    return est, order


def classify(model, rows: list[dict]) -> list[tuple[str, float]]:
    est, order = _estimator_and_order(model)
    if not rows:
        return []
    X = pd.DataFrame([[float(r[k]) for k in order] for r in rows], columns=order)
    proba = est.predict_proba(X)
    classes = [str(c) for c in est.classes_]
    out = []
    for p in proba:
        i = max(range(len(p)), key=lambda j: (p[j], -j))        # numpy argmax 와 같다(동률이면 앞 클래스)
        out.append((classes[i], round(float(p[i]), 4)))
    return out


def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None, context: dict | None = None) -> dict:
    ctx = context or {}
    prm = {**DEFAULTS, **(ctx.get("params") or {})}
    prev = ctx.get("previous") or {}
    objects = [dict(o) for o in (prev.get("objects") or [])]
    if not objects:
        raise ExtractError("invalid_document", "parse", "분류할 도형이 없습니다(기하 추출 결과 없음)")
    if any(not isinstance(o.get("descriptors"), dict) for o in objects):
        raise ExtractError("invalid_document", "parse", "앞 추출기 결과에 기하 설명자가 없습니다")
    score_min = float(prm["score_min"])
    preds = classify(model, [o["descriptors"] for o in objects])
    for o, (label, conf) in zip(objects, preds):
        o.update({"model_label": label, "confidence": conf, "label": label})
        reason = o.get("geometry_reason")
        is_outer = bool(o.get("is_outer"))
        if reason:
            pass
        elif conf < score_min:
            reason = REASON_SCORE.format(pct=f"{score_min * 100:g}")
        elif is_outer and label != "outer":
            reason = REASON_OUTER_MISMATCH
        elif not is_outer and label == "outer":
            reason = REASON_EXTRA_OUTER
        elif label == "hole" and o.get("entity") != "CIRCLE":
            reason = REASON_HOLE
        elif label == "slot" and not o.get("curved"):
            reason = REASON_SLOT
        if reason:
            o["label"] = "other"
        o["review_reason"] = reason or (REASON_UNSUPPORTED if o["label"] == "other" else None)
        for k in HELPER_KEYS:
            o.pop(k, None)
    counts = {c: sum(o["label"] == c for o in objects) for c in CLASSES}
    warnings = [f"검토 대상 {counts['other']}개는 자동 홀·슬롯 수에서 제외했습니다."] if counts["other"] else []
    conf = [o["confidence"] for o in objects if o["confidence"] is not None]
    return {"objects": objects, "counts": counts, "replaces": ["objects", "counts"],
            "confidence": round(sum(conf) / len(conf), 6) if conf else None, "warnings": warnings}
