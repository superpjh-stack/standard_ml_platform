# 팩 `kimchi` — 김치 · 발효 식품

| 과제 | 유형 | 핵심 |
|---|---|---|
| `sensory_score` | regression | 변수 11 · `time_60_20_20`(시각 열 — D2-02, 행 420 < 500 이라 실제 `time_cv5`) · 후보 ridge · extra_trees · gbr · 구간 split conformal |
| `recipe_optimize` | optimize | uses sensory_score · 무작위 수락 3,500 · `derived` 양념 = 100 − 나머지 · 제약 `scale` 3 · 5 · `least_violation` · 비용식 `formulas/material_cost.py` |
| `residual_review` | review_queue | uses sensory_score · `top_quantile: 0.10`(검증 구간 잔차 분위 — D2-11) · 시험 구간 · 운영 잔차만 |

합성 생성기 `synth/kimchi_lots.py` — 원천 생성기 이관(시드 42 · 420 행 · 결측 15 셀, 재추출 루프 포함). 범주 값은 회사 등록부 `categories`.
