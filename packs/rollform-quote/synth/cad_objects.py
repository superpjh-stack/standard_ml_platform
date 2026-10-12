"""과제 cad_objects 의 합성 생성기 — 도면 객체 기하 설명자 (spec §4.2 `synth/<task>.py` · pack-contract §6 `synth/geometry.py`).

원천 `api/ml_service.py:19-40 geometry_training_data()` 이관 (migration/source_inventory.md §10.2). 실제 고객 도면 · 라벨이 아니라
**합성 기하 설명자와 그 생성 라벨**이다(과제 labels: synthetic — 실도면 평가 지표가 아니다).
같은 시드에서 원천과 행 일치 100%: 클래스 순서 outer · hole · slot · other, 클래스마다 `rows / 4` 행(원천 400 × 4 = 1,600),
행마다 원천과 같은 순서로 난수를 부른다(hole 1회 · slot 2회 · outer 2회 · other 4회).

이름 대응(원천 GEOMETRY_FEATURES → 팩 변수): circle → is_circle · closed → is_closed · aspect → aspect_ratio ·
relative_area → area_ratio · circularity → circularity · curved → is_curved. 라벨 열 = `label`(과제 model.target, 변수 아님).
행 수는 `pack.yaml synth.tasks.cad_objects`(1,600 · 시드 42 — 작업 900 행과 다른 생성기, D2-45 ⑤).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_ROWS = 1600
DEFAULT_SEED = 42
CLASSES = ("outer", "hole", "slot", "other")
DESCRIPTORS = ("is_circle", "is_closed", "aspect_ratio", "area_ratio", "circularity", "is_curved")
LABEL = "label"
TARGETS = (LABEL,)


def _row(label: str, rng: np.random.Generator) -> list[float]:
    if label == "hole":
        return [1, 1, 1, rng.uniform(.00001, .08), 1, 1]
    if label == "slot":
        aspect = rng.uniform(1.6, 8)
        area = 4 * (aspect - 1) + np.pi            # 반지름 1 캡슐의 면적 · 둘레 (원천 주석 그대로)
        perimeter = 4 * (aspect - 1) + 2 * np.pi
        return [0, 1, aspect, rng.uniform(.0001, .12), 4 * np.pi * area / perimeter ** 2, 1]
    if label == "outer":
        aspect = rng.uniform(1, 30)
        return [0, 1, aspect, 1, np.pi * aspect / (aspect + 1) ** 2, rng.choice([0, 1])]
    return [0, rng.choice([0, 1]), rng.uniform(1, 30), rng.uniform(.001, .4), rng.uniform(0, .65), 0]


def generate(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED, *,
             categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """표준 프레임 조각: entity_id · ts(NaT) · 설명자 6 · label. categories 는 쓰지 않는다(범주 변수 없음)."""
    if rows % len(CLASSES):
        raise ValueError(f"행 수는 클래스 {len(CLASSES)}의 배수(클래스마다 같은 수 — 원천 400 × 4)")
    per = rows // len(CLASSES)
    rng = np.random.default_rng(seed)
    records, labels = [], []
    for label in CLASSES:
        for _ in range(per):
            records.append(_row(label, rng))
            labels.append(label)
    frame = pd.DataFrame(np.array(records, dtype=float), columns=list(DESCRIPTORS))
    frame[LABEL] = labels
    frame.insert(0, "entity_id", [f"DEMO-OBJ-{i + 1:04d}" for i in range(rows)])
    frame.insert(1, "ts", pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, Asia/Seoul]"))
    return frame
