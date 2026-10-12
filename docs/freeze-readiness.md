# 코어 동결 준비 점검 — 웨이브 A2 를 코어 수정 없이 붙일 수 있는가 (2차 웨이브 P 마감, 아키텍트 2026-10-13)

> 대상: 웨이브 A2 의 팩 `solder` · `rollform-quote` · `kimchi` 나머지(`recipe_optimize`) · 회사 `krs` · `ot`.
> 근거: `migration/source_inventory.md` §8(krs) · §9.5(pc 최적화) · §10(ot), `contracts/task-contract.md` §1 · §2 · §6, 이번 회전 코드 · 시험.
> 판정: **가능** = 지금 코어로 팩 YAML · 플러그인 · 회사 등록부만으로 된다 · **넣음** = 모자라서 이번 회전에 코어에 넣었다(시험 경로 표기) ·
> **차이 기록** = 코어로 원천과 똑같이 하지 않고 표준 절차로 한다(이관 보고서에 사유 — 코어 변경 불필요).
> 동결 뒤(`core-freeze-2`) 이 표 밖의 코어 기능이 필요해지면 `decisions.md` 에 `코어 결함(2차)` 으로 올린다(goal2 §3.2).

## 1. 팩 `solder` · 회사 `krs` (source_inventory §8)

| 원천 기능 | 원천 근거 | 코어 장치 | 판정 | 시험 · 위치 |
|---|---|---|---|---|
| 접합강도 회귀 · 후보 5(decision_tree · svr · random_forest · gbr · extra_trees) | §8.3 `ml_service.py:97-103` | `std/candidates.yaml` 5 후보 · `candidate_params`(SVR C 20 · ε .15 …) | 가능 | `tests/test_train*.py` |
| IQR(1.5) 이상치 제거 | §8.3 `:59-73` | 과제 `outlier: {method: iqr, k: 1.5, columns: [...]}` — **학습 구간에서만** 경계(D2-03) | 가능 (원천은 분할 전 전체 — 차이 기록) | `train/trainer.py::iqr_filter` |
| RobustScaler 전처리 | §8.3 `:76-80` | 표준 전처리(median → StandardScaler) | 차이 기록 — 원천 절차 재현은 `migration/reproduce.py`(코어 밖) | — |
| 무작위 80/20 · 시험 RMSE 선정 | §8.3 `:96,116` | `random_60_20_20` · 검증 RMSE/MAE 선정 · 시험 1회 | 차이 기록(D2-21 · 원천 결함 K1) | `tests/test_split.py` |
| 배합 무작위 탐색 5,000 | §8.5 `:125` | `search: {strategy: random, max_points: 5000}` — **수락 점 수 = max_points** | **넣음** (수락 표집 · `max_draws`) | `tests/test_optimize_phase2.py` |
| sn = 100 − (ag + cu + sb + flux) (조성 등식) | §8.5 `:130-131` | 과제 `derived: {sn_pct: "100 - ag_pct - cu_pct - sb_pct - flux_pct"}` — 탐색점마다 모델 입력 계산, [min,max] ∩ 학습 범위 밖 점 버림 | **넣음** | `tests/test_optimize_phase2.py` |
| 비용지수 Σ pct × 단가 / 100 | §8.5 `:134` | `formulas/<m>.py::cost(row, params)` (derived 값 포함) | 가능 | `tasks/optimize.py::_evaluate` |
| `max_cost` 선택(null 허용) | §8.1 E4 `:19-22` | params `{default: null, optional: true}` — 없으면 그 제약을 평가하지 않음 | **넣음** | `tests/test_optimize_phase2.py` |
| 시드 = int(target×100)+ord(supplier) | §8.5 `:127` | 과제 `seed` 고정(요청에 따라 바뀌지 않음 — 재현) | 차이 기록 | — |
| 추천 1 · 미충족 정렬(위반 무시) | §8.5 `:138` | 상위 5 · `least_violation`(원천 결함 K2) — 옛 모양 1행은 호환 플러그인이 고른다 | 차이 기록 | — |
| 조성 합 100 ± 0.1 아니면 422 | §8.1 E6 `main.py:70-72` | 과제 `input_rules: [{name, expr: "sn_pct + ag_pct + …", between: [99.9, 100.1]}]` → 422 `invalid_input`(rule `input_rule`) — predict · batch · optimize · 견적 · 호환 공통 | **넣음** | `tests/test_optimize_phase2.py` |
| 내부 기준 35 MPa 미만 '주의' | §8.9 `:154-163` | 회귀 `thresholds.review_below` | 가능 | `tasks/regression.py` |
| \|잔차\| ≥ 4 MPa 대기열 | §8.6 | `review_queue` `rule: {abs_residual_ge: 4.0}` · origins test_split · live_residual | 가능 + **넣음**(test_split 항목을 실제로 DB 에 넣는 경로 — 일정 작업이 production run 보고서로 1회) | `tests/test_monitor_review.py::test_test_split_items_from_run_report_once_per_version` |
| 옛 경로 7(`/api/quality/overview` · `/api/quality/predict` · `/api/ml/samples` …) | §8.1 · api-contract §6.3 | 호환 객체 경로 `review_list` · `predict_one` · `samples` + 회사 플러그인 `tenants/krs/compat.py` | **넣음** | `tests/test_compat_phase2.py` |
| 소스 demo + CSV(live 불가) | D2-01 | `sources.demo: synthetic` · `eval: csv` — CSV 는 등록부 파일 경로(업로드 API 는 계약 15 묶음 밖, 화면 7 은 등록된 csv 소스를 보인다) | 가능 | `tests/e2e/test_console_sources.py` |

## 2. 팩 `rollform-quote` · 회사 `ot` (source_inventory §10)

| 원천 기능 | 원천 근거 | 코어 장치 | 판정 | 시험 · 위치 |
|---|---|---|---|---|
| 가공 분 회귀 · 후보 4 · 하한 0.05 | §10.3 OT-M1 · `:122` | regression · `clip.min: 0.05` · `random_60_20_20` | 가능 (행 순서 분할은 차이 기록 D2-21) | — |
| 객체 분류 합성 설명자 **1,600**(클래스 4 × 400) · 작업 900 행과 다른 생성기 | §10.2 · `ml_service.py:19-40` | `pack.yaml synth.tasks: {cad_objects: {rows: 1600, seed: 42}}` + `synth/cad_objects.py` — 과제별 행 수 · 시드(회사 소스 `tasks.<과제>` 로도) | **넣음** | `tests/test_freeze_readiness.py::test_per_task_synth_rows_and_seed` |
| 층화 960/320/320 · 검증 macro-F1 · 시험 1회 · 혼동행렬 | §10.3 OT-M2 | extract `model:` 블록(`stratified_60_20_20` · logreg · rf_clf · et_clf · `majority_class` 기준선) · 라벨 열 `model.target`(D2-44 확정) | 가능 (`model.target` 등록부 검사 넣음) | `tests/test_extract_model.py` |
| 요소 상한 **2,000**(경동 20,000 과 다름) | §10.5 X3 · D2-22 | 과제 `document.max_entities: 2000`(팩) · 회사 덮어쓰기로 더 낮추기만 — 코어 DXF 읽개가 413 `entities` | 가능 | `tasks/extract.py::limits_for` · `registry/tenants.py::_phase2_override` |
| 꼭짓점 500 · 평탄화 0.2 mm · 요소당 2,000 점 · 전체 60,000 점 · 점수 < 0.8 | §10.5 X6 · X9 | 추출기 `params`(과제 YAML `extractors[].params` → `context["params"]`) — 코드 상수 0, 넘치면 `ExtractError("document_too_large", "vertices"\|"points")` | **넣음** | `tests/test_freeze_readiness.py` (params 검사 · context 전달) |
| 기하 검증 **8 사유** → `other`(검토 대상) | §10.5 X9 | 규칙 추출기가 객체 · `review_reason` 을 내고, 모델 추출기가 `context["previous"]` 의 같은 객체를 분류해 `replaces: ["objects", "counts"]` 로 다시 낸다(이어 붙이기 아님) | **넣음** | `tests/test_freeze_readiness.py::test_merge_replaces_previous_objects_and_counts` |
| 비평면 제외 · 지원 요소 4종 · 좌표 유한 | §10.5 X4 · X5 | 코어 `tasks.dxf.read` 의 그룹 코드(10/20/30 · 210~230) — 판정은 추출기 | 가능 | `tests/test_extract.py` |
| 확장자 아님 415 · 크기 413 · 깨짐 422 | §10.1 E6 | 표준 422 `invalid_document`(rule format) · 호환 `document_upload` 는 옛 415 | 가능 + **넣음**(호환) | `tests/test_compat_phase2.py` |
| 견적 `won(x) = Decimal(str(x)).quantize(1, HALF_UP)` · 재질별 밀도 · kg 단가 | §10.6 `quote.py:6-23` · `config.py:4-8` | 팩 견적식(Decimal · HALF_UP) + **단가표** `rate_tables: {density: material, price_kg: material}` — 팩은 빈 표, 회사가 범주 값마다 칸을 채운다(없음 · 남음 R2) | **넣음** (D2-07a 차이는 행별 사유) | `tests/test_freeze_readiness.py::test_rate_table_*` |
| 인식값(holes · slots · length · width) 0.001 넘게 다르면 overrides | §10.6 `:24-27` | `recognized: {holes: counts.hole, …, tolerance: "0.001"}` | 가능 | `tests/test_quote.py` |
| `unit_price = round(subtotal/q, 2)` (float — 원천 결함 O2) | §10.6 `:31` | 견적식이 품목 행에 Decimal 로(금액 칸은 원 단위 정수만) | 가능 | `serve/quotes.py::compute` |
| 옛 경로 10(`/api/cad/*` · `/api/quotes*` · `/api/data/demo`) | §10.1 · api-contract §6.3 | 호환 객체 경로 `document_upload` · `document_demo` · `document_get` · `pack_file` · `quote_create`(draft 만) · `quote_list` · `quote_get` · `quote_csv` + `tenants/ot/compat.py` | **넣음** (기동 때 T0 검사) | `tests/test_compat_phase2.py` |

## 3. 팩 `kimchi` 나머지 — `recipe_optimize` (source_inventory §9.5)

| 원천 기능 | 원천 근거 | 코어 장치 | 판정 | 시험 · 위치 |
|---|---|---|---|---|
| 무작위 **수락 3,500** · seasoning = 100 − 합 · 범위 안만 수락 | §9.5 `:92-96` | `derived: {seasoning_pct: "100 - cabbage_pct - radish_pct - salt_pct"}` + 수락(범위 ∩ 학습 범위) · `max_points: 3500` | **넣음** | `tests/test_optimize_phase2.py` |
| 위반 = max(0, target − pred)/3 + max(0, cost − max)/5 · 위반 순위 | §9.5 `:98-100` | 제약 `scale: 3` · `scale: 5`(위반 분모) · `least_violation` | **넣음** | `tests/test_optimize_phase2.py` (손 계산) |
| 고정 cabbage_origin · prod_line | §9.5 `:97` | `fixed` | 가능 | — |
| 배합 합 98~102 거부 · 99.7~100.3 경고 | §9.9 · `main.py:20` | `input_rules`(거부). 경고는 회귀 thresholds 범위가 아니라 — 호환 플러그인 문구(원천 문구 그대로) | **넣음**(거부) · 가능(문구) | — |
| 미충족 문구 2 | §9.5 `:102-103` | `compat.optimize_unmet_text` | 가능 | `tests/test_compat.py` |
| 시드 = 42 + int(target×10) + int(max_cost) | §9.5 `:91` | 과제 seed 고정 | 차이 기록 | — |

## 4. 공통 · 감시 · 등록부

| 항목 | 코어 장치 | 판정 | 시험 |
|---|---|---|---|
| 과제 이름 `quote` = 유형 코드(G-M01 충돌) | std 어휘는 코어의 말 — 과제 이름 = 자기 유형 코드만 금지어에서 뺀다, 다른 겹침은 팩 위반(D2-31) | **넣음** | `tests/test_freeze_readiness.py` ① |
| 추출기에 회사 재질 목록 · 별칭 | `context={categories, material_aliases, params, previous}` (받는 추출기만) | **넣음** | `tests/test_kd_quote_flow.py` · `test_freeze_readiness.py` |
| 견적이 부른 예측의 채널 | `mlp_prediction.channel` 에 `quote`(비파괴 CHECK 넓히기) | **넣음** | `tests/test_kd_quote_flow.py` |
| 과제 상세 API 의 2차 키 | quote `inputs · recognized · rates · rate_tables …` · extract `document · extractors · labels · model` · review `rule · origins …` | **넣음** | `tests/test_kd_quote_flow.py::test_task_detail_exposes_quote_and_extract_keys` |
| 모델 추출기 감시(실측 성능 macro_f1) · doctor 학습 보기 | `monitor.daily` 가 extract(model) 를 `learn_view` 로 · `live_performance` macro_f1 · doctor `_learned` = `learn_view` | **넣음** | `tests/test_monitor_extract_live.py` |
| 대기열 중복 삽입 | 부분 고유 색인 `mlp_review_item_prediction_once`(D2-33) · test_split 은 (과제 · 버전 · entity) 1회 | **넣음** | `tests/test_monitor_review.py` |
| 덮어쓰기 허용 키 · 2차 규칙 표 | task-schema 블록 `overridable_on_override` · `review_rules` … (로더가 먼저 읽음 — D2-30) | **넣음**(계약) | `gates/check_tasks.py` |
| 측정 이미지 태그 · 포트 | bench 는 빈 루프백 포트 · 미커밋 트리면 `<sha>-wt<해시>` · `make image` 는 깨끗한 트리만(F7-5) | **넣음** | `tests/test_makefile_image.py` |

## 5. 모자랐던 코어 기능 (이번 회전에 넣은 것 — 요약)

1. 최적화 `derived` + 수락 표집(시도 상한 `max_draws`) · 제약 `scale` · params `optional` — solder · kimchi `recipe_optimize`.
2. 입력 규칙 `input_rules`(조성 합) — predict · batch · optimize · 견적 · 호환 공통 422.
3. 추출기 `context`(회사 범주 · 별칭 · `params` · `previous`) · 결과 `replaces` — ot 기하 검증 8 사유 + 객체 분류 연결, eto 재질 검사.
4. 견적 단가표 `rate_tables` — ot 재질별 밀도 · kg 단가(팩에 회사 범주 값 0).
5. 과제별 합성 행 수 · 시드(`synth.tasks`) — ot 객체 설명자 1,600.
6. 호환 라우터 객체 경로 + 회사 모양 플러그인(`tenants/<code>/compat.py`) · 기동 검사 — krs · pc · ot · kd 옛 경로(goal2 §3.2 가 A2 에 둔 일을 동결 전 장치로).
7. test_split 대기열 항목을 실제로 만드는 경로(일정 작업, run 보고서 증거 확인) · 부분 고유 색인.
8. 견적 예측 채널 `quote` · 과제 상세 2차 키 · 모델 추출기 감시 · G-M01 std 어휘 규칙.

남는 차이(코어 변경 없이 이관 보고서 사유): 요청 의존 시드 · 연속 균등 표집(표준은 격자 step 위 표집 — 팩이 step 을 잘게) · 추천 1 vs 상위 5 · RobustScaler · 분할 정책(D2-21) · 원천 짝수 반올림(D2-07a).
