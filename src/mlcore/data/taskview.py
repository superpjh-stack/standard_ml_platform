"""학습 관점의 과제 보기 (task-contract §6.2 · D2-15).

`extract` 과제는 학습 키(변수 · 후보 · 분할 · 목표)를 `model:` 블록 안에 둔다. 학습 경로(소스 읽기 · 스냅숏 · 분할 ·
후보 · 학습기)는 1차 유형과 같은 키를 읽으므로, 여기서 `model:` 블록을 위로 올린 TaskDef 보기를 만든다.
과제 ID · 팩 과제 ID · def_hash 는 원본 그대로(run_id · config_hash 가 바뀌지 않는다). 그 밖의 유형은 원본을 돌려준다.
목표 열 이름은 `model.target`(없으면 `label`) — 합성 설명자 생성기의 라벨 열.
"""

from __future__ import annotations

from dataclasses import replace

DEFAULT_LABEL = "label"
CLASS_TARGET_TYPES = ("extract",)      # 목표가 클래스 이름(문자열)인 유형 — 표준 프레임이 수치로 바꾸지 않는다


TRAINABLE = ("regression", "risk", "anomaly", "extract")   # extract = model: 블록이 있는 모델 추출기만 (D2-15)


def has_model(task) -> bool:
    return task.type == "extract" and isinstance(task.raw.get("model"), dict)


def trainable(task) -> bool:
    """자기 모델을 학습하는 과제인가 — 1차 학습 유형 + `model:` 블록이 있는 extract. 대기열 · 규칙 추출 · 견적 · 최적화는
    아니다(uses 과제의 production 모델을 쓴다). 접수(`data.jobs.submit`)와 학습기가 같은 규칙을 쓴다(D2-82)."""
    return task.type in TRAINABLE and (task.type != "extract" or has_model(task))


def learn_view(task):
    if not has_model(task):
        return task
    raw = dict(task.raw)
    m = dict(raw.get("model") or {})
    raw.update({
        "features": list(m.get("features") or []),
        "candidates": list(m.get("candidates") or []),
        "candidate_params": dict(m.get("candidate_params") or {}),
        "split": m.get("split", "stratified_60_20_20"),
        "time_key": None,
        "group_key": m.get("group_key"),
        "target": {"name": m.get("target", DEFAULT_LABEL)},
        "classes": [str(c) for c in (m.get("classes") or [])],
        "selection": m.get("selection", "macro_f1"),
        "_learn_view": "model",
    })
    return replace(task, raw=raw)
