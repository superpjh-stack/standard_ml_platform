# 원천 조사 — ks · sw 기존 ML 서비스 인벤토리 (Phase 0)

> 조사: 아키텍트, 2026-10-12. 방법: 원천 저장소 파일을 **직접 열어** 줄 번호로 셌다. 원천 코드는 실행하지 않았다(읽기 전용).
> 원천: `../KwangSung ML AI`(ks) · `../SongWol ML AI`(sw). MES 열 대응의 보조 근거: `../SongWol AI Platform/src/songwol/db/schema.sql` · `../KwangSung AI Platform/db/schema.sql` · `../Standard Data Hub/companies/{ks,sw}.yaml`.
> **이 표가 G-M02 의 분모, G-M12 의 대조값이다.** 표기 `파일:줄`. 원천의 배포 문서에 있는 주소 · 호스트명은 공개 저장소 위생(D-20)에 따라 옮기지 않았다.

## 0. 요약 (수)

| 항목 | ks | sw | 근거 |
|---|---|---|---|
| API 엔드포인트 (`/api/*`) | **6** | **6** | ks `api/main.py:71,76,81,86,91,102` · sw `api/main.py:71,76,81,86,91,102` |
| 화면 진입 경로 (`/` + `/assets`) | 1 (+정적) | 1 (+정적) | `api/main.py:111-118` (둘 다) |
| 입력 변수 (`FEATURE_META` 수치 + 범주) | **9** (수치 7 + 범주 2) | **9** (수치 7 = 조절 5 + 원단 2, 범주 2) | ks `api/config.py:6-16` · sw `api/config.py:9-23` |
| 목표 | 2 (`remaining_hours` · `failure_24h`) | 2 (`delta_e` · `defect`) | ks `config.py:18` · `ml_service.py:33` · sw `config.py:25-26` |
| 학습 모델 묶음 (회귀 · 분류 · 이상) | **3** | **3** | ks `ml_service.py:77-96` · sw `ml_service.py:96-115` |
| 후보 모델 수 (회귀 + 분류 + 이상) | **8** (4 + 3 + 1) | **8** (4 + 3 + 1) | 같은 줄 |
| 최적화 | **1** (1차원 시간 격자) | **1** (5차원 전수 격자 8,400점) | ks `ml_service.py:132-148` · sw `ml_service.py:159-192` |
| 화면 | **5** | **5** | ks `web/src/App.tsx:5-11` · sw `web/src/App.tsx:5-11` |
| 시험 함수 / 시험 케이스 | **9 / 20** | **11 / 24** | ks `tests/test_api.py` · `docs/verification.md:8` · sw `tests/test_api.py` · `docs/verification.md:8` |
| 합성 행 · 결측 셀 · 시드 | 720 · 24 · 42 | 720 · 24 · 42 | ks `ml_service.py:20-38` · sw `ml_service.py:39-57` · 둘 다 `config.py:2` |
| 분할 | 시간순 432 / 144 / 144 | 시간순 432 / 144 / 144 | ks `ml_service.py:76` · sw `ml_service.py:95` |

### 0.1 G-M02 분모 — 대응해야 할 기능 단위 **32** (ks 16 · sw 16)

| 회사 | 엔드포인트 | 모델 묶음 | 최적화 | 화면 | 합 |
|---|---|---|---|---|---|
| ks | 7 (`/api/*` 6 + `/`) | 3 | 1 | 5 | **16** |
| sw | 7 | 3 | 1 | 5 | **16** |

목록은 §5 에 ID(`KS-E1` …)로 적었다. `docs/task-map.md` 는 이 ID 전부를 표준 과제 · 경로 · 화면에 대응시켜야 한다(G-M02 = 32/32).

## 1. ks — `../KwangSung ML AI`

### 1.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 키 |
|---|---|---|---|---|
| KS-E1 | `GET /api/health` | `api/main.py:71-73` | — | `status` · `model_ready` · `data_mode` · `version` |
| KS-E2 | `GET /api/ml/overview` | `api/main.py:76-78` → `ml_service.py:151-169` | — | `data_mode` · `version` · `rows` · `missing_cells` · `duplicate_lots` · `impossible_cells` · `champion` · `risk_champion` · `metrics` · `risk_metrics` · `test_metrics` · `risk_test_metrics` · `features` · `machines` · `products` · `split` · `importance` · `review_count` · `evaluated` · `risk_threshold` · `trend` · `priority_queue` · `warning` (23) |
| KS-E3 | `POST /api/maintenance/predict` | `api/main.py:81-83` → `ml_service.py:115-129` | `ProcessInput` (`main.py:38-60`) 9 필드, `extra=forbid` · `allow_inf_nan=False` | `remaining_hours` · `risk_probability` · `anomaly` · `status` · `warnings` · `imputed_fields` · `model` · `risk_model` · `version` · `notice` (10) |
| KS-E4 | `POST /api/ml/optimize` | `api/main.py:86-88` → `ml_service.py:132-148` | `{record, reserve_hours, max_delay_hours, max_cost_index}` (`main.py:63-68`) | `feasible` · `prediction` · `candidate_count` · `feasible_count` · `recommendation` · `alternatives` · `unmet_constraints` · `objective` · `notice` (9) |
| KS-E5 | `GET /api/data/records` | `api/main.py:91-99` | `limit`(15, 1~100) · `offset` · `machine` · `product` · `search`(≤60) | `total` · `limit` · `offset` · `records` |
| KS-E6 | `GET /api/data/records/{lot_id}` | `api/main.py:102-107` | — | `record` · `source` · 404 |
| KS-E7 | `GET /` (+ `/assets`) | `api/main.py:110-118` | — | `web/dist/index.html` · 없으면 503 |

오류 처리: 422 처리기가 입력값을 되풀이하지 않는다 `api/main.py:25-31`. 기동 학습: `lifespan` 이 `ml.state()` 를 부른다 `api/main.py:16-19`, `@lru_cache state()` `ml_service.py:73-108` (표준에서는 금지 — F3).

### 1.2 변수 (`api/config.py:6-16` — `FEATURE_META` 7 + 범주 2)

| 변수 | 라벨 | 단위 | min | max | default | 결측 주입(`ml_service.py:36-37`) | 비고 |
|---|---|---|---|---|---|---|---|
| `press_force` | 프레스 하중 | ton | 180 | 320 | 245 | — | |
| `vibration` | 진동 | mm/s | 0.4 | 8 | 2.1 | 8 행 | |
| `motor_current` | 모터 전류 | A | 30 | 85 | 48 | 8 행 | |
| `equip_temp` | 설비 온도 | °C | 30 | 85 | 47 | — | |
| `mold_temp` | 금형 온도 | °C | 25 | 70 | 39 | 8 행 | |
| `cycle_time` | 사이클 타임 | s | 6 | 15 | 9.5 | — | |
| `shot_count` | 금형 누적 샷 | 회 | 5000 | 180000 | 65000 | — | 정수만 (`main.py:58-59`, `ml_service.py:23`) |
| `machine` | 설비 | 범주 | — | — | `PRS-01` | — | 4값 `PRS-01~04` (`config.py:4`) — 회사 설비 코드 |
| `product` | 품목 | 범주 | — | — | `FRONT SHELL` | — | 3값 (`config.py:5`) |

검증: 수치 결측 최대 3개(`main.py:56-57`) → 표준 `max_imputed: 3`. 범위 밖 · 미지 범주 · 소수 샷 · NaN/Inf → 422 (`main.py:50-60`).
합성 생성 순서(`ml_service.py:20-38`): `default_rng(42)` → 변수 7 `uniform(min,max,720)`(위 표 순서) → `shot_count` 반올림 정수 → `machine` `choice` → `product` `choice` → 마모식 → `remaining_hours = clip(155 - wear + normal(0,5), 1, 180)` → `failure_24h = binomial(1, sigmoid(-(rh-40)/13))` → `lot_id = KS-DEMO-0001…` → `recorded_at = 2026-08-01T00:00+09:00` 부터 1시간 간격 → 결측 주입(`vibration` · `motor_current` · `mold_temp` 각 8, `choice(720, 8, replace=False)`). **이 RNG 호출 순서를 바꾸면 G-M12 행 일치가 깨진다.**

### 1.3 후보 · 선정 · 분할 (`ml_service.py:73-108`)

| 과제 | 후보 (이름 → 표준 이름) | 하이퍼파라미터 | 선정 |
|---|---|---|---|
| 잔여수명 회귀 | Ridge→`ridge` · Random Forest→`random_forest` · Extra Trees→`extra_trees` · Gradient Boosting→`gbr` | Ridge α=3 · RF 100/leaf 3 · ET 100/leaf 3 · GBR 120/depth 2 · `random_state=42` (`:77-79`) | 검증 MAE 최소, 동률 이름순 (`:90`) |
| 24h 고장 분류 | Logistic Regression→`logreg` · Random Forest→`rf_clf` · Gradient Boosting→`gbc` | LogReg max_iter 500 · RFC 100/leaf 5 · GBC 80/depth 2 (`:80-82`) | 검증 Brier 최소 (`:91`) |
| 이상 탐지 | IsolationForest→`isolation_forest` | 100 · contamination 0.08 (`:96`) | — (학습+검증 576행으로 적합) |

분할: `iloc[:432]` 학습 · `[432:576]` 검증 · `[576:]` 시험 (`:76`) — 시간순(`recorded_at` 1시간 간격). 재적합: 학습+검증 576 (`:93-95`). 시험 1회 (`:97-100`). 전처리: 수치 median → StandardScaler, 범주 OneHot(ignore) (`:41-46`, 트리에도 스케일러 적용). 중요도: **검증 구간** 순열 중요도, 학습 구간 적합 모델, n_repeats 3 (`:101-106`) — spec §5.4 는 시험 구간(차이 → D-29).
그룹 경계: 없음(설비 4대가 전 구간에 섞임). 우선 점검 큐: 시험 구간만 (`:168`).

### 1.4 보고 지표 (`docs/verification.md:28-34`, 2026-09-18 실측)

| 과제 | 챔피언 | 검증 | **시험 (G-M12 대조값)** |
|---|---|---|---|
| 잔여수명 | Gradient Boosting (`gbr`) | MAE 5.213 h · RMSE 6.544 · R² 0.9143 | **MAE 5.568 h · RMSE 6.979 · R² 0.9199** |
| 24h 고장 | Random Forest (`rf_clf`) | — | **ROC AUC 0.6444 · AP 0.1426 · Brier 0.0576** |
| 이상 탐지 | IsolationForest | — | 보고 없음 (오염률 0.08 설정만) |

goal 표기 "MAE 5.57h · R² 0.92 · AUC 0.64" 는 위 값의 반올림이다. 기준선(학습 평균 · 양성률) 비교는 원천에 없다 → 표준에서 새로 낸다.

### 1.5 최적화 — 정비 시점 (`ml_service.py:132-148` · `README.md:49-61` · `config.py:21`)

| 항목 | 값 |
|---|---|
| 결정 변수 | 대기 시간 `t` (`stop_after_hours`) — **모델 입력이 아니다**(센서값은 고정, `:134`) |
| 공간 | `t ∈ [0, max_delay_hours]`, 간격 0.5 h (`:135`). `max_delay_hours=48` → 97점 (`tests/test_api.py:93`) |
| 의존 예측 | 잔여수명 `L = predict(record).remaining_hours` (`:133-136`) |
| 비용식 | `cost = 60 + max(0, 24 - t) × 4 + max(0, t - 0.6 L) × 6` (`:137`, `PLAN_COST` `config.py:21`) |
| 제약 | `L - t ≥ reserve_hours` · `cost ≤ max_cost_index` (`:139`) |
| 요청 범위 | `reserve_hours` 1~150 · `max_delay_hours` 0~72 · `max_cost_index` 1~500 (`main.py:66-68`) |
| 위반 | `max(0, reserve - (L-t)) / max(reserve,1) + max(0, cost - maxcost) / max(maxcost,1)` (`:139`) |
| 정렬 | 충족: 비용 ↑, `t` ↓ · 미충족: 위반 ↑, 비용 ↑, `t` ↓ (`:141`) · 상위 5 (`:147`) |

### 1.6 화면 (`web/src/App.tsx:5-11`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| KS-S1 | 운영 개요 | E2 · E6 | 1 개요 |
| KS-S2 | 모델 비교·검증 | E2 | 4 모델 비교 |
| KS-S3 | 프레스 예지보전 | E3 | 2 예측 시험 |
| KS-S4 | 정비 시점 탐색 | E4 | 3 조건 추천 |
| KS-S5 | LOT 데이터 | E5 · E6 · CSV(`web/src/api.ts:10-17`, 수식 주입 방지 · BOM) | 1 개요 + B12 records (화면 7 은 2차) |

### 1.7 시험 (`tests/test_api.py`, 9 함수 · 20 케이스 = `docs/verification.md:8` "20 passed")

`test_readiness_metrics_and_time_separation`(1) · `test_invalid_measurements_rejected`(5) · `test_missing_and_finite_values`(1) · `test_predictions_reproducible`(1) · `test_bad_paging_and_filters`(6) · `test_records_filters_stable_paging_and_detail`(1) · `test_feasible_and_infeasible_schedules`(1) · `test_invalid_constraints`(3) · `test_production_entrypoint_and_no_unknown_api_fallback`(1).

### 1.8 상수 · 문구 (표준에서 YAML 로 옮길 것)

`MODEL_VERSION = "ks-demo-2026.09.18"` (`config.py:3`, 코드 안 버전 상수 — F3) · `RISK_THRESHOLD = 0.5` (`:19`) · 상태 문구 "점검 검토" / "추가 징후 없음" (`ml_service.py:128`) · `NOTICE` (`config.py:20`) · 배포 768MB · CPU 1 · OMP 1 (`deploy/hostinger.compose.yaml:11-16`).

## 2. sw — `../SongWol ML AI`

### 2.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 키 |
|---|---|---|---|---|
| SW-E1 | `GET /api/health` | `api/main.py:71-73` | — | `status` · `model_ready` · `data_mode` · `version` |
| SW-E2 | `GET /api/ml/overview` | `api/main.py:76-78` → `ml_service.py:195-218` | — | ks 23키 중 `machines`·`products` 대신 `controls`·`print_types`·`color_tones`·`equipment` + `defect_rate`·`delta_e_review` (27) |
| SW-E3 | `POST /api/quality/predict` | `api/main.py:81-83` → `ml_service.py:140-151` | `PrintInput` (`main.py:38-60`) 9 필드 | `delta_e` · `risk_probability` · `anomaly` · `status` · `warnings` · `imputed_fields` · `equipment` · `model` · `risk_model` · `version` · `notice` (11) |
| SW-E4 | `POST /api/ml/optimize` | `api/main.py:86-88` → `ml_service.py:164-192` | `{record, max_delta_e, max_risk, min_line_speed}` (`main.py:63-68`) | `feasible` · `current` · `current_cost_index` · `candidate_count` · `feasible_count` · `recommendation` · `alternatives` · `unmet_constraints` · `warnings` · `objective` · `notice` (11) |
| SW-E5 | `GET /api/data/records` | `api/main.py:91-99` | `limit` · `offset` · `print_type` · `color_tone` · `search` | `total` · `limit` · `offset` · `records` |
| SW-E6 | `GET /api/data/records/{lot_id}` | `api/main.py:102-107` | — | `record` · `source` · 404 |
| SW-E7 | `GET /` (+ `/assets`) | `api/main.py:110-118` | — | index.html |

### 2.2 변수 (`api/config.py:9-23`)

| 변수 | 라벨 | 단위 | min | max | default | step(탐색) | 조절 | 결측 주입(`ml_service.py:52-53`) |
|---|---|---|---|---|---|---|---|---|
| `set_temp` | 설정 온도 | ℃ | 140 | 210 | 175 | 10 | ○ | — |
| `set_pressure` | 설정 압력 | bar | 2 | 6 | 4 | 1 | ○ | — |
| `line_speed` | 라인속도 | m/min | 6 | 24 | 14 | 3 | ○ | — |
| `ink_usage` | 잉크 사용량 | g/m² | 10 | 30 | 18 | 4 | ○ | 8 행 (학습 데이터만; API 는 필수) |
| `dwell_time` | 가열 유지시간 | s | 20 | 80 | 50 | 15 | ○ | — |
| `absorb_rate` | 원단 흡수율 | % | 60 | 98 | 82 | — | ✕ (고정) | 8 행 |
| `fabric_strength` | 원단 강도 | N | 220 | 480 | 340 | — | ✕ (고정) | 8 행 |
| `print_type` | 인쇄 방식 | 범주 | — | — | 나염 | — | ✕ | 3값 나염 · 승화 · DTF (`config.py:5`), 확률 .45/.35/.2 (`ml_service.py:42`) |
| `color_tone` | 색상 계열 | 범주 | — | — | 진한 색상 | — | ✕ | 3값 연한 · 중간 · 진한 색상 (`config.py:8`) |

검증: 조절 변수 5 는 필수, 원단 2 만 결측 허용(`main.py:56-59`). spec §3.1 예시(`set_temp` 150~210 step 1 · `set_pressure` 2.0~5.0 …)는 **원천과 다르다** → 팩은 원천 값을 쓴다(D-30).
합성 생성 순서(`ml_service.py:39-57`): `default_rng(42)` → 변수 7 `uniform` (위 표 순서) → `print_type` `choice(p=[.45,.35,.2])` → `color_tone` `choice` → `delta_e = clip(true_delta_e + normal(0,.35), .2, 12)` (`true_delta_e` `:29-36`, 방식별 최적값 `:23-25`) → `defect = binomial(1, sigmoid((ΔE-3.8)/.45))` → `equip_code` ← 방식 대응 → `lot_id = SW-DEMO-0001…` → `recorded_at = 2026-08-01T08:00+09:00` 부터 1시간 → 결측(`absorb_rate` · `fabric_strength` · `ink_usage` 각 8) → 수치 소수 2 · ΔE 소수 3 반올림.

### 2.3 후보 · 선정 · 분할 (`ml_service.py:92-126`)

ks 와 같은 구조. 차이: GBR 200 / depth 3 / lr 0.05 (`:98`) · LogReg max_iter 1000 (`:99`). 분할 432/144/144 (`:95`) · 재적합 576 (`:112-114`) · IF 0.08 (`:115`) · 중요도 검증 구간 (`:121-124`). 그룹 경계 없음.

### 2.4 보고 지표 (`docs/verification.md:21-24`, 2026-09-19 실측)

| 과제 | 챔피언 | 검증 | **시험 (G-M12 대조값)** |
|---|---|---|---|
| ΔE | Extra Trees (`extra_trees`) | MAE 0.520 · R² 0.752 | **MAE 0.557 · RMSE 0.709 · R² 0.722** |
| 불량 | Gradient Boosting (`gbc`) | — | **ROC AUC 0.868 · AP 0.781 · Brier 0.127** (합성 불량률 31.5%) |
| 이상 | IsolationForest | — | 보고 없음 |

### 2.5 최적화 — 인쇄 조건 격자 (`ml_service.py:154-192` · `README.md:46-55` · `config.py:31`)

| 항목 | 값 |
|---|---|
| 조절 변수 | `set_temp` · `set_pressure` · `line_speed` · `ink_usage` · `dwell_time` |
| 공간 | 각 `[min, max]` 를 step 간격 전수 (`:159-161`): 8 × 5 × 7 × 6 × 5 = **8,400** (`tests/test_api.py:107`) — 학습 범위와 교차하지 않는다(표준 G-M13 은 교차 → 점 수가 줄어든다, D-31) |
| 고정 | `absorb_rate` · `fabric_strength` · `print_type` · `color_tone` (`:168-169`) |
| 의존 예측 | ΔE 회귀 · 불량 확률 · 이상 플래그 (`score` `:133-137`) |
| 비용식 | `ink × 2.0 + 360 / line_speed + max(0, temp - 140) × 0.25 + dwell × 0.15` (`:154-156`, `PROCESS_COST` `config.py:31`) |
| 제약 | `ΔE ≤ max_delta_e` (0.5~8) · `risk ≤ max_risk` (0.01~0.9) · `line_speed ≥ min_line_speed` (6~24) (`:172-173`, `main.py:66-68`) |
| 위반 | 각 초과량 / 상한(또는 하한) 합 (`:172-173`) |
| 정렬 | 충족: 비용 ↑, ΔE ↑ · 미충족: 위반 ↑, 비용 ↑, ΔE ↑ (`:175-176`) · 상위 5 |
| 경고 | 추천 조건이 이상 탐지에 걸리면 시험 인쇄 경고 (`:182`) |
| 실측 (verification.md:15-16) | ΔE ≤ 2.5 · 위험 ≤ 20% · 속도 ≥ 12 → 8,400 중 1,054 충족 / ΔE ≤ 0.5 · 1% · 24 → 0 충족 |

### 2.6 화면 (`web/src/App.tsx:5-11`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| SW-S1 | 운영 개요 | E2 · E6 | 1 |
| SW-S2 | 모델 비교·검증 | E2 | 4 |
| SW-S3 | 색상 품질 예측 | E3 | 2 |
| SW-S4 | 인쇄조건 탐색 | E4 | 3 |
| SW-S5 | 인쇄 LOT 데이터 | E5 · E6 · CSV | 1 + B12 |

### 2.7 시험 (`tests/test_api.py`, 11 함수 · 24 케이스)

`test_readiness_metrics_and_time_separation`(1) · `test_invalid_conditions_rejected`(6) · `test_extra_fields_and_infinity_rejected`(1) · `test_missing_fabric_values_are_imputed_not_zeroed`(1) · `test_predictions_reproducible`(1) · `test_bad_paging_and_filters`(6) · `test_records_filters_stable_paging_and_detail`(1) · `test_feasible_recommendation_respects_constraints_and_ranges`(1) · `test_infeasible_fallback_ranks_by_violation_then_cost`(1) · `test_invalid_constraints`(4) · `test_production_entrypoint_and_no_unknown_api_fallback`(1).

### 2.8 상수 · 문구

`MODEL_VERSION = "sw-demo-2026.09.19"` (`config.py:3`) · `DELTA_E_REVIEW = 3.5` (`:27`, spec §3.2 예시는 2.0 — D-30) · `RISK_THRESHOLD = 0.5` (`:28`) · 상태 "품질 검토" / "추가 징후 없음" (`ml_service.py:150`) · 설비 대응 `EQUIPMENT` (`config.py:6`: 방식 → 설비 코드 · 이름 — 회사 값이므로 `tenants/sw.yaml: compat`).

## 3. sw MES 테이블 대응 — `feature_map` 재료

근거: `SongWol ML AI/docs/methodology.md:7` · `README.md:76-77`(테이블 이름) + `SongWol AI Platform/src/songwol/db/schema.sql`(열, 줄 번호).

| 팩 변수 / 목표 | 원천 테이블.열 | schema.sql 줄 | 대응 |
|---|---|---|---|
| `set_temp` | `PRT_PRINT_CONDS.SET_TEMP` | 608 | ○ |
| `set_pressure` | `PRT_PRINT_CONDS.SET_PRESSURE` | 609 | ○ |
| `line_speed` | `PRT_PRINT_CONDS.LINE_SPEED` | 610 | ○ |
| `ink_usage` | `PRT_PRINT_CONDS.INK_USAGE` | 611 | ○ |
| `print_type` | `PRT_PRINT_CONDS.PRINT_TYPE` | 607 | ○ |
| `dwell_time` | — | — | **✕ 원천 열 없음** |
| `absorb_rate` | `RCV_MATERIAL_LOTS.ABSORB_RATE` | 421 | ○ |
| `fabric_strength` | `RCV_MATERIAL_LOTS.STRENGTH_VALUE` | 422 | ○ (이름 다름) |
| `color_tone` | — (색상 코드 미수집 `config.py:7`) | — | **✕** |
| 목표 `delta_e` | `PRT_QUALITY_HISTORY.DELTA_E` (+ `MEASURE_DT`) | 702-703 | ○ (현행 보유량 0 — `README.md:5`) |
| 목표 `defect` | `PRT_QUALITY_HISTORY.JUDGE_RESULT` 또는 `PRT_PRINT_RESULTS.DEFECT_QTY` | 704 · 669 | △ 정의 미확정 |
| 결합 키 | `PRT_PRINT_RESULTS.LOT_ID → RCV_MATERIAL_LOTS` · `.PRINT_COND_ID → PRT_PRINT_CONDS` · `.EQUIP_ID → BAS_EQUIPMENTS` · `PRT_QUALITY_HISTORY.PRINT_RESULT_ID` | 664-666 · 700 | entity = 인쇄 실적(LOT) |
| 기준 | `BAS_QUALITY_STD_ITEMS.UPPER_LIMIT` (ΔE 상한, 값 미확정) | 151 | 임계값 원천(`차단`) |
| 기존 예측 테이블(호환 뷰, D-11) | `PRT_COLOR_PREDICTIONS.PRED_DELTA_E` · `PRT_QUALITY_PREDICTIONS.DEFECT_PROB` | 780 · 807 | `db/compat/sw.sql` 뷰 정의만 |

변수 대응률 **7/9 = 77.8%**(필수 `dwell_time` · `color_tone` 원천 없음) → `live` 로는 병합 규칙 R2 에 걸린다. 1차는 `demo`/`eval`(합성 소스로 100%) — D-32 `차단`.

## 4. ks 원천 대응 (참고 — 광성 MES · Gateway)

근거: `KwangSung AI Platform/db/schema.sql` · `Standard Data Hub/companies/ks.yaml`. ks ML 저장소 자체에는 원천 대응 문서가 없다(`README.md:79-85` 는 전환 계획만).

| 팩 변수 / 목표 | 원천 | 줄 | 대응 |
|---|---|---|---|
| `press_force` | `PRS_PROCESS_DATA.PRESS_FORCE_TON` (`COLLECT_DT` · `EQUIP_ID` · `PRODUCT_LOT_NO`) | 556 | ○ |
| `mold_temp` | `PRS_PROCESS_DATA.MOLD_TEMP_C` | 557 | ○ |
| `vibration` | `PRS_PROCESS_DATA.VIBRATION_MMS` | 560 | ○ |
| `cycle_time` | `PRS_PROCESS_DATA.CYCLE_TIME_SEC` | 561 | ○ |
| `motor_current` · `equip_temp` | `PRC_SENSOR_DATA.MEASURE_ITEM` / `MEASURE_VALUE` (세로형 — `KwangSung ML AI/docs/methodology.md:7` "전류/설비온도는 별도 센서 테이블") · 항목 코드값 미확인 | 990-1001 | △ 항목 코드 대응 필요 |
| `shot_count` | `PRS_MOLD_SHOTS.ACC_SHOT_CNT` | 803 | ○ (일 단위) |
| `machine_code` (원천 `machine`) | `BAS_EQUIPMENTS.EQUIP_CODE` (`EQUIP_ID` 결합) | 135 | ○ |
| `product_type` (원천 `product`) | 미확인 (`PRODUCT_LOT_NO` → 품목 결합 경로 미확인) | — | ✕ |

변수 대응률 **6/9 = 66.7%** 확정 + 2 항목 코드 미확인(`motor_current` · `equip_temp`) · 1 미확인(`product`).
| Gateway 착륙 | `EIF_PLC_RAW` (허브 등록부) | — | 창 집계 필요 |
| 목표 `remaining_hours` · `failure_24h` | 정비 · 고장 이력 테이블 **미발견** | — | **✕ 목표 없음** — D-33 `차단` |

## 5. 기능 단위 목록 (G-M02 분모 32 — `docs/task-map.md` 가 전부 대응해야 한다)

| ID | 원천 기능 | 표준 대응 (예정) |
|---|---|---|
| KS-E1 | `GET /api/health` | B01 `GET /api/v1/health` + 호환 |
| KS-E2 | `GET /api/ml/overview` | B06 overview(과제 3) + 호환 `/api/ml/overview` |
| KS-E3 | `POST /api/maintenance/predict` | B03 `ks.remaining_hours` · `ks.failure_24h` · `ks.sensor_ood` + 호환 |
| KS-E4 | `POST /api/ml/optimize` | B04 `ks.maintenance_timing` + 호환 |
| KS-E5 | `GET /api/data/records` | B12 records + 호환 |
| KS-E6 | `GET /api/data/records/{lot_id}` | B12 records(`search=`) + 호환 |
| KS-E7 | `GET /` | 콘솔 `/app/*` |
| KS-M1 | 잔여수명 회귀 (후보 4) | `ks.remaining_hours` regression |
| KS-M2 | 24h 고장 분류 (후보 3) | `ks.failure_24h` risk |
| KS-M3 | IsolationForest 이상 | `ks.sensor_ood` anomaly |
| KS-O1 | 정비 시점 1차원 격자 | `ks.maintenance_timing` optimize |
| KS-S1~S5 | 화면 5 | 화면 1 · 4 · 2 · 3 · 1 |
| SW-E1~E7 | 위와 같은 7 | 같은 대응 (`sw.*`) |
| SW-M1 | ΔE 회귀 | `sw.delta_e` |
| SW-M2 | 불량 분류 | `sw.defect_risk` |
| SW-M3 | 이상 | `sw.print_ood` |
| SW-O1 | 인쇄 조건 5차원 격자 | `sw.print_setpoint` |
| SW-S1~S5 | 화면 5 | 화면 1 · 4 · 2 · 3 · 1 |

## 6. 원천 결함 · 차이 (이관 보고서 재료 — 원천은 고치지 않는다)

| # | 회사 | 내용 | 근거 |
|---|---|---|---|
| S1 | ks · sw | 기동 시 메모리 학습 · 코드 안 버전 상수 | `main.py:16-19` · `config.py:3` |
| S2 | ks · sw | 순열 중요도를 검증 구간 · 학습 구간 모델로 계산(spec 은 시험 구간) | ks `ml_service.py:103-104` · sw `:121-122` |
| S3 | ks · sw | 트리 모델에도 StandardScaler 적용(spec §5.1 은 생략) — 결과 영향 없음, 결정성 대조 시 동일 파이프라인 필요 | ks `:41-46` |
| S4 | ks · sw | 기준선 비교 없음 · 예측 구간 없음 · 확률 보정 없음 | 전 파일 |
| S5 | sw | `ink_usage` 는 API 필수인데 학습 데이터에는 결측 8 | `main.py:56` · `ml_service.py:52` |
| S6 | ks | 비용식은 검증 안 된 데모 가정 | `README.md:61` |
| S7 | ks | 배포 문서에 공인 주소 · 호스트명이 평문 — 표준 저장소로 옮기지 않음 | `docs/deployment.md:5,13-15` |
| S8 | ks · sw | 오류 응답이 FastAPI 기본 `{"detail": [...]}` — 표준 봉투와 다름(호환 라우터가 재현) | `main.py:25-31` |
| S9 | sw | 최적화 격자가 학습 범위와 교차하지 않아 끝단 외삽 — 원천도 경고로만 처리 | `docs/methodology.md:40` |
| S10 | ks · sw | 목록 페이징 `offset` · 키 `records` · 기본 15 (표준 `cursor` · `items` · 20) | `main.py:91-99` |
