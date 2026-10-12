# 팩 `kimchi` — 김치 · 발효 식품

| 과제 | 유형 | 핵심 |
|---|---|---|
| `sensory_score` | regression | 변수 11 · `time_60_20_20`(시각 열 — D2-02) · 후보 ridge · extra_trees · gbr · 구간 split conformal |
| `residual_review` | review_queue | uses sensory_score · `top_quantile: 0.10`(검증 구간 잔차 분위 — D2-11) · 시험 구간 · 운영 잔차만 |

합성 생성기 `synth/kimchi_lots.py` — 원천 생성기 이관(시드 42 · 420 행 · 결측 15 셀, 재추출 루프 포함). 범주 값은 회사 등록부 `categories`.
`recipe_optimize`(배합 · 숙성 무작위 탐색)는 웨이브 A2 에서 더한다.
