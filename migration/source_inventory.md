# 원천 조사 — 6개사 기존 ML 서비스 인벤토리 (1차 Phase 0: ks · sw / 2차 Phase P0: krs · pc · ot · kd)

> 조사: 아키텍트, 2026-10-12. 방법: 원천 저장소 파일을 **직접 열어** 줄 번호로 셌다. 원천 코드는 실행하지 않았다(읽기 전용).
> 원천: `../KwangSung ML AI`(ks) · `../SongWol ML AI`(sw). MES 열 대응의 보조 근거: `../SongWol AI Platform/src/songwol/db/schema.sql` · `../KwangSung AI Platform/db/schema.sql` · `../Standard Data Hub/companies/{ks,sw}.yaml`.
> 2차 4개사 절은 §7~§12(아키텍트, 2026-10-13 — 원천 HEAD: 고려솔더 `b101cfc` · 평창 `75568aa` · 원터치 `8a2250e` · 경동 `0073ecf`).
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


---

# 2차 — 4개사 (Phase P0, 아키텍트 2026-10-13)

> 방법은 1차와 같다: 원천 파일을 **직접 열어** 줄 번호로 셌다. 원천 코드 · 시험은 실행하지 않았다. 원천 SQLite 견적 이력은 `sqlite3 "file:…?mode=ro"` 읽기 전용으로 행 수 · 금액만 읽었다.
> 원천: `../Koreal Solder ML AI`(krs) · `../PyoungChang ML AI`(pc) · `../OneTouch ML AI`(ot) · `../KyungDong ML AI`(kd). 원천 문서의 포트 · 주소 · 사업자번호 · 고객사명은 옮기지 않았다(D-20).
> 표기 `파일:줄`. 같은 줄 번호가 계속 나오면 앞 표의 파일을 가리킨다.

## 7. 요약 (수) — 4개사

| 항목 | krs | pc | ot | kd | 근거 |
|---|---|---|---|---|---|
| API 엔드포인트 (`/api/*`) | **7** | **6** | **11** | **11** | krs `api/main.py:36,41,47,54,62,67,76` · pc `api/main.py:27,30,36,39,42,49` · ot `api/main.py:47,52,56,69,74,82,94,101,109,114,126` · kd `api/main.py:70,74,78,82,89,100,107,113,129,135,142` |
| 화면 진입 (`/`) | 1 (`/{path:path}` SPA, `main.py:85-92`) | 1 (웹 컨테이너 nginx `web/nginx.conf:15`, API 는 `/api/` 만 `:7`) | 1 (`main.py:146-149`) | 1 (`main.py:154-157`) | |
| 입력 변수 | 8 (수치 7 + 범주 1) | 11 (수치 9 + 범주 2) | 8 (수치 6 + 범주 2) | 7 (수치 5 + 범주 2) | krs `ml_service.py:20-22` · pc `ml_service.py:21-24` · ot `config.py:10-20` · kd `config.py:8-17` |
| `FEATURE_META` dict | 없음 (`FEATURES` 목록 + `LIMITS` `:20-27`) | 없음 (`LIMITS` `:27-31`) | 있음 `config.py:10-17` | 있음 `config.py:8-14` | 표준에서는 0(G-M03) — 팩 `features.yaml` 로 |
| 목표 | `joint_strength_mpa` | `sensory_score` | `minutes`(개당 가공 분) + 객체 라벨 4 | `hours`(대당 제조공수) | krs `:22` · pc `:20` · ot `ml_service.py:53,16` · kd `ml_service.py:24` |
| 학습 모델 묶음 | **1** (회귀) | **1** (회귀) | **2** (회귀 · 객체 분류) | **1** (회귀) | |
| 후보 수 | 5 | 3 | 4 + 3 | 4 | krs `:97-103` · pc `:72-73` · ot `:77-79,90-91` · kd `:48-50` |
| 최적화 | 무작위 5,000 | 무작위 3,500 (수락 표본) | — | — | krs `ml_service.py:125-145` · pc `ml_service.py:90-106` |
| 검토 대기열 | \|잔차\| ≥ 4 MPa | 잔차 상위 10% (표시 8) | — | — | krs `:169-195` · pc `ml_service.py:79` · `main.py:42-47` |
| 추출기 | — | — | 기하 추출 + 객체 분류 + 기하 규칙 검증 | 영역 3종(규칙) · BOM 텍스트(규칙) | ot `api/cad.py:38-137` · kd `api/cad.py:50-123` |
| 견적식 | — | — | `Decimal` · `ROUND_HALF_UP` (구성 금액마다) | Python `round`(짝수 반올림) · float | ot `api/quote.py:6-35` · kd `api/quote.py:5-23` |
| 화면 | **3** | **4** | **4** | **4** | krs `web/src/App.tsx:6,12` · pc `web/src/App.tsx:5,16` · ot `web/src/App.tsx:9` · kd `web/src/App.tsx:9` |
| 시험 함수 / 케이스 | **6 / 6** | **4 / 4** | **11 / 26** | **10 / 21** | krs `tests/test_api.py:9-48` · pc `tests/test_api.py:8-24` · ot `tests/test_api.py:33-169` (parametrize 14 + 3) · kd `tests/test_api.py:30-125` (parametrize 12) · kd `docs/verification.md:8` "21개" |
| 합성 행 · 결측 셀 · 시드 | 720 · 24 (+이상치 5) · 20260917 | 420 · 15 · 42 | 작업 900 · 12 / 객체 1,600 · 0 · 42 | 작업 900 · 12 · 42 | krs `:31-56` · pc `:36-55` · ot `ml_service.py:19-58` · kd `ml_service.py:15-29` |
| 분할 | 무작위 80/20 (`random_state=42`), **선정도 시험 구간** | 무작위 78/22, **선정도 시험 구간** + 전체 재적합 | 작업: 행 순서 540/180/180 · 객체: 층화 960/320/320 | 행 순서 540/180/180 | krs `:96,116-117` · pc `:71,78` · ot `:76,88-89` · kd `:47` |
| 기동 학습 | `@lru_cache train_models()` 첫 호출 | `@lru_cache state()` 첫 호출 | `lifespan` → `ml.state()` | `lifespan` → `ml.state()` | krs `:92` · pc `:69` · ot `main.py:17-20` · kd `main.py:16-19` (표준 금지 — F3) |

## 8. krs — `../Koreal Solder ML AI` (팩 `solder`)

### 8.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 키 |
|---|---|---|---|---|
| KRS-E1 | `GET /api/health` | `api/main.py:36-38` | — | `status` · `model_ready`(상수 true) |
| KRS-E2 | `GET /api/ml/overview` | `:41-44` → `ml_service.py:121` | — | `quality` · `models`(5) · `champion` · `statistics` · `features` · `target` · `data_mode` |
| KRS-E3 | `GET /api/ml/samples` | `:47-51` | `limit`(12, 1~100) · `offset` | `total` · `items` |
| KRS-E4 | `POST /api/ml/optimize` | `:54-59` → `ml_service.py:125-145` | `OptimizeRequest` `{target_strength 30~70 (48), max_cost 0~200 \| null, supplier A\|B\|C}` (`:19-22`) | `feasible` · `model` · `target_strength` · `predicted_strength` · `cost_index` · `composition`(5) · `process` · `notice` (8) · 결과 없음 422 (`:57-58`, 실제로는 도달 불가 — 대체 행이 항상 있다) |
| KRS-E5 | `GET /api/quality/overview` | `:62-64` → `ml_service.py:169-195` | `limit`(12, 1~50) | `model` · `evaluated_lots` · `normal_lots` · `flagged_lots` · `mean_absolute_error` · `review_threshold`(4.0) · `flagged[]` · `notice` |
| KRS-E6 | `POST /api/quality/predict` | `:67-73` → `ml_service.py:148-166` | `QualityPredictRequest` 8 필드 (`:25-33`) · 조성 합 100 ± 0.1 아니면 422 (`:70-72`) | `model` · `predicted_strength` · `status`(주의 · 정상) · `warnings` · `notice` (5) |
| KRS-E7 | `GET /api/data/records` | `:76-82` → `ml_service.py:198-229` | `limit`(20, 1~100) · `offset` · `q`(≤40) · `supplier` · `state`(정상 · 결측 · 이상) | `total` · `offset` · `limit` · `items` · `summary` |
| KRS-E8 | `GET /{path:path}` (+ `/assets`) | `:85-92` | — | `web/dist` SPA (없으면 경로 없음) |

오류: FastAPI 기본 `{"detail": …}` (처리기 없음). 요청 모델에 `extra=forbid` · `allow_inf_nan=False` 가 **없다**(`main.py:19-33`) — 모르는 키를 조용히 버린다(원천 결함 K3).

### 8.2 변수 (`ml_service.py:20-27` · 요청 경계 `main.py:25-33` · 생성 범위 `:33-40`)

| 변수 | 요청 min~max | 데이터 상태 `LIMITS` | 합성 생성 | 결측 주입 | 비고 |
|---|---|---|---|---|---|
| `sn_pct` | 90~100 | 93.0~99.2 | `100 - ag - cu - sb - flux` | — | 조성(합 100) |
| `ag_pct` | 0~6 | 0.3~4.2 | U(0.35, 4.0) | 8 행 | 조성 |
| `cu_pct` | 0~3 | 0.1~1.2 | U(0.15, 1.05) | — | 조성 |
| `sb_pct` | 0~3 | 0.0~2.0 | U(0, 1.7) | — | 조성 |
| `flux_pct` | 0~2 | 0.05~0.8 | U(0.08, 0.72) | — | 조성 |
| `temperature_c` | 150~350 | 225~270 | N(246, 8) clip 226~268 | 8 행 + 이상치 5 (145 · 352, `:55`) | 공정 |
| `mixing_min` | 5~150 | 20~90 | N(53, 14) clip 20~88 | 8 행 | 공정 |
| `supplier` | A · B · C | — | choice p = .45/.35/.2 (`:40`) | — | 범주(공급사 — 팩 중립 값으로, 회사 값은 `categories`) |
| 목표 `joint_strength_mpa` | — | — | `31 + 5.8ag + 2.4cu + 1.25sb − 2(flux−.28)² − .055(T−246)² − .009(m−54)² + 공급사(1.1/.3/−.7) + N(0,1.8)` (`:41-46`) | — | MPa |

합성 생성 순서(`:31-56`): `default_rng(20260917)` → ag · cu · sb · flux `uniform` → sn = 100 − 합 → temp `normal` clip → mixing `normal` clip → supplier `choice(p)` → 목표 `normal` → `lot_id = KS-2024xxxx`(`:48`, **1차 ks 접두와 겹친다** — 표준은 팩 중립 `DEMO-`, 옛 접두는 `compat.entity_prefix`) → 결측(ag · temp · mixing 각 `choice(720, 8)`) → 이상치 temp `choice(720,5)` ← `choice([145,352],5)`. **이 RNG 순서를 바꾸면 G-M12 행 일치가 깨진다.**

### 8.3 전처리 · 후보 · 선정 · 분할

| 항목 | 값 | 줄 |
|---|---|---|
| 이상치 제거 | 수치 7 열 IQR(1.5) — **분할 전 전체 데이터**에서 경계 계산 · 행 제거 | `:59-73`, 호출 `:95` (누수 — D2-03: 표준은 학습 구간에서만) |
| 전처리 | 수치 median → **RobustScaler**, 범주 most_frequent → OneHot(ignore) | `:76-80` |
| 후보 (이름 → 표준) | Decision Tree→`decision_tree`(depth 8 · leaf 5) · SVR→`svr`(C 20 · ε .15) · Random Forest→`random_forest`(180 · depth 10) · Gradient Boosting→`gbr`(180 · depth 3 · lr .04) · Extra Trees→`extra_trees`(180 · depth 12) · `random_state=42` | `:97-103` |
| 분할 | `train_test_split(cleaned, test_size=.2, random_state=42)` — 검증 구간 없음 | `:96` |
| 선정 | **시험 구간 RMSE 최소** (`scores.sort(rmse)`) — 시험으로 선정(누수, 원천 결함 K1) | `:116-117` |
| 재적합 | 없음 (학습 80% 모델 그대로) | `:104-110` |
| 보고 | 5 후보 시험 R² · MAE · RMSE (소수 4 · 3 · 3) | `:111-115` |
| 표준 분할 | `time_key` 없음 → `random_60_20_20`(seeded) · 선정은 검증 RMSE · 시험 1회 | D2-03 · std/split_policies.yaml |

### 8.4 보고 지표

**원천 문서에 기록된 수치 없음** (`README.md:1-34` 에 지표 없음 · `docs/` 없음). 시험은 `rmse` 순서 · 5 모델만 본다(`tests/test_api.py:9-13`). → G-M12 대조값은 **원천 절차 재현값**(원천 코드를 읽어 같은 시드 · 같은 절차를 이관 도구로 다시 계산 — 원천 실행 아님, D2-12). 표준 재측정 값과 나란히 적는다.

### 8.5 최적화 — 배합 무작위 탐색 (`ml_service.py:125-145`)

| 항목 | 값 |
|---|---|
| 결정 변수 | ag · cu · sb · flux ~ U(생성 범위) · sn = 100 − 합(조성 등식 제약) · temp U(232, 260) · mixing U(35, 75) (`:130-131`) |
| 고정 | `supplier` (요청) |
| 표본 | 5,000 (`trials` `:125`) · 시드 `int(target × 100) + ord(supplier)` (`:127`) |
| 의존 예측 | 챔피언 회귀 접합강도 (`:133`) |
| 비용식 | `cost_index = Σ pct × 단가 / 100`, 단가 sn 31 · ag 1220 · cu 14 · sb 22 · flux 85 (`COST :28`, `:134`) |
| 제약 | `predicted ≥ target_strength` · (있으면) `cost ≤ max_cost` (`:135-137`) |
| 정렬 | 충족: 비용 ↑, 강도 ↓ · **미충족: 전체 표본을 같은 정렬**(위반량을 보지 않는다 — 원천 결함 K2, 표준은 `least_violation`) (`:138`) |
| 출력 | 추천 1 (후보 5 아님) |

### 8.6 검토 대기열 (`ml_service.py:169-195` · `main.py:62-64`)

| 항목 | 값 |
|---|---|
| 대상 | `bundle.cleaned` **전체**(학습 80% 포함) 를 학습 모델로 채점 (`:171-172`) — 학습 구간 잔차 사용(원천 결함 K4, 표준 금지 · G2-R01) |
| 규칙 | `|실측 − 예측| ≥ 4` MPa → `주의` (`:173-174`, `review_threshold: 4.0` `:193`) |
| 정렬 · 수 | 절대 오차 ↓ 상위 `limit`(12, ≤ 50) (`:175`) |
| 항목 키 | `lot_id` · `supplier` · `actual_strength` · `predicted_strength` · `absolute_error` · `temperature_c` · `mixing_min` · `status` (`:178-186`) |
| 표준 | `review_queue` 규칙 `abs_residual_ge: 4.0` (D2-11), 대상 = 시험 구간 잔차 + 실측이 붙은 운영 예측 잔차만 |

### 8.7 화면 (`web/src/App.tsx:6,12`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| KRS-S1 | 배합최적화 (지표 · 모델 비교표 포함 `:20,46`) | E2 · E4 | 3 조건 추천 + 4 모델 비교 |
| KRS-S2 | 품질예측 (예측 폼 + 주의 LOT 표 `:29,47`) | E5 · E6 | 2 예측 시험 + 8 검토 대기열 |
| KRS-S3 | 데이터 관리 (검색 · 공급사 · 상태 필터 · CSV `:36`) | E7 | 7 데이터 소스 + B12 records |

### 8.8 시험 (`tests/test_api.py`, 6 함수 · 6 케이스)

`test_overview_has_five_ranked_models` · `test_optimize_composition_is_balanced` · `test_validation_rejects_invalid_target` · `test_quality_dashboard_and_prediction` · `test_quality_prediction_rejects_unbalanced_composition` · `test_data_records_filter_and_paging`.

### 8.9 상수 · 문구

`review_threshold 4.0` (`:193`) · 권장 온도 232~260 · 혼합 35~75 · 내부 검토 기준 35 MPa (`:154-159` — 경고 문구, 팩 `thresholds`) · 상태 "주의"/"정상" (`:163`) · CSV 내보내기에 **수식 주입 방지 없음**(`web/src/App.tsx:36` 단순 `join(',')`, BOM 만 붙임 — 원천 결함 K5).

## 9. pc — `../PyoungChang ML AI` (팩 `kimchi`)

### 9.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 키 |
|---|---|---|---|---|
| PC-E1 | `GET /api/health` | `api/main.py:27-28` | — | `status` · `model_ready` · `data_mode` · `product` |
| PC-E2 | `GET /api/ml/overview` | `:30-34` | — | `data_mode` · `rows` · `missing_cells` · `duplicate_lots` · `features` · `target` · `champion` · `metrics`(3) · `limits` · `warning` (10) |
| PC-E3 | `POST /api/ml/optimize` | `:36-37` → `ml_service.py:90-106` | `OptimizeInput {target_score 65~95, max_material_cost 45~100, cabbage_origin, line}` (`:23-25`) | `feasible` · `prediction_score` · `material_cost_index` · `settings`(9) · `context` · `unmet_constraints` · `model` · `notice` (8) |
| PC-E4 | `POST /api/quality/predict` | `:39-40` → `ml_service.py:82-87` | `ProcessInput` 11 필드 (`:13-17`) · 배합 합 98~102 아니면 422 (`:18-21`) | `prediction_score` · `status`(검토 필요 · 예측 범위 양호) · `warnings` · `model` · `notice` (5) |
| PC-E5 | `GET /api/quality/overview` | `:42-47` | — | `evaluated` · `demo_review_score` · `residual_review_threshold` · `priority_queue`(8) · `notice` (화면이 부르지 않는다 — `web/src/App.tsx` 에 경로 없음) |
| PC-E6 | `GET /api/data/records` | `:49-59` | `limit`(25, 1~100) · `offset` · `line` · `cabbage_origin` · `search`(≤30) | `total` · `limit` · `offset` · `records` |
| PC-E7 | `GET /` (웹 컨테이너) | `web/nginx.conf:15` (API 프록시 `:7`) | — | 정적 콘솔 |

### 9.2 변수 (`ml_service.py:21-31` · 요청 경계 `main.py:14-17`)

| 변수 | 요청 min~max | `LIMITS`(생성 · 탐색) | 결측 주입 | 비고 |
|---|---|---|---|---|
| `cabbage_pct` | 55~85 | 66~76 | — | 배합 |
| `radish_pct` | 0~20 | 5~11 | — | 배합 |
| `seasoning_pct` | 8~35 | 15~23 (= 100 − 나머지, 범위 밖이면 재추출 `:39-43`) | — | 배합 |
| `salt_pct` | 0.5~5 | 1.2~2.6 | — | 배합 |
| `brine_salinity_pct` | 5~18 | 9~13 | 5 행 | 절임 |
| `brining_hours` | 3~24 | 8~16 | — | 절임 |
| `fermentation_temp_c` | −2~15 | 2~8 | 5 행 | 숙성 |
| `fermentation_hours` | 6~120 | 18~72 | — | 숙성 |
| `storage_temp_c` | −5~10 | −1~4 | 5 행 | 저장 |
| `cabbage_origin` | 3값 | choice p .68/.20/.12 (`:46`) | — | 범주(원료 산지 — 회사 값은 `categories`) |
| `line` | 2값 | choice p .58/.42 | — | 범주(라인 — 회사 값) |
| 목표 `sensory_score` | — | `86 − |염도−11.1|·2 − |절임−12|·.65 − |숙성온도−4.8|·1.15 − |숙성시간−42|·.13 − |저장−1|·.8 − |양념−19.5|·.45 + 산지 .8 + 라인 .25 + N(0,1.8)` (`:47-49`) | — | 점 |

합성 순서(`:36-55`): `default_rng(42)` → cabbage · radish · salt `uniform(LIMITS, 420)` → seasoning = 100 − 합 → **범위 밖 행 재추출 루프**(`:41-43`, 같은 RNG) → salinity · brining · ferment_temp · ferment_hours · storage `uniform` → origin `choice(p)` → line `choice(p)` → 목표 `normal` → `lot_id = PC-K-0001…` · `produced_at = 2025-01-02` 부터 **12시간 간격**(`:50`) → 결측(염도 · 숙성온도 · 저장온도 각 `choice(420, 5)`). `produced_at` 이 있으므로 표준은 `time_key` 를 둔다 → `time_60_20_20` 강제(D2-02).

### 9.3 후보 · 선정 · 분할 (`ml_service.py:69-79`)

| 항목 | 값 |
|---|---|
| 전처리 | 수치 median → StandardScaler · 범주 most_frequent → OneHot(ignore) (`:58-61`) |
| 후보 | 릿지 회귀→`ridge`(α 1) · 엑스트라 트리→`extra_trees`(180 · leaf 3) · 그래디언트 부스팅→`gbr`(140 · depth 2) · seed 42 (`:72-73`) |
| 분할 | `train_test_split(test_size=.22, random_state=42)` — 무작위, 검증 없음 (`:71`) |
| 선정 | **시험 구간 MAE 최소** (`:78`) — 원천 결함 P1 |
| 재적합 | 챔피언을 **전체 420 행**으로 재적합(`:78`) → 운영 모델 · 대기열 · 임계값이 모두 이 모델 |
| 평가 | 보고 지표 = 재적합 전 시험 구간 지표(`:77`) — 그러나 대기열 · 임계값은 **전체 재적합 모델로 같은 데이터 채점**(표본 내, `:79`) — 원천 결함 P2 (`std/split_policies.yaml rules.in_sample_evaluation: forbidden`, G2-R01 거부 픽스처의 원형) |

### 9.4 보고 지표

**원천 문서에 기록된 수치 없음**(`README.md:1-24` · docs 없음). 시험은 `len(metrics) == 3` 만 본다(`tests/test_api.py:10`). D2-02: 평창은 표준 절차 재측정 값이 정본, 원천 절차 재현값은 병기만 · ±10% 대조 제외.

### 9.5 최적화 — 배합 · 숙성 무작위 탐색 (`ml_service.py:90-106`)

| 항목 | 값 |
|---|---|
| 결정 변수 | 배합 4(cabbage · radish · salt U(LIMITS), seasoning = 100 − 합 · 범위 안만 수락) + 공정 5 U(LIMITS) (`:93-96`) |
| 고정 | `cabbage_origin` · `line` (`:97`) |
| 표본 | 수락 3,500 (`:92`) · 시드 `42 + int(target×10) + int(max_cost)` (`:91`) |
| 비용식 | `material_cost = Σ pct × 단가` (배추 .55 · 무 .32 · 양념 1.55 · 소금 .12, `COST :32`) |
| 제약 | `prediction ≥ target_score` · `cost ≤ max_material_cost` (`:99`) |
| 위반 | `max(0, target − pred)/3 + max(0, cost − max)/5` (`:98`) — 표준 `least_violation`(정규화 = \|rhs\|)과 가중이 다르다(사유 기록) |
| 정렬 | 충족: 비용 ↑, 예측 ↓ · 미충족: 위반 ↑, 비용 ↑ (`:100`) · 추천 1 |
| 미충족 문구 | "목표 품질점수 N점 미달" · "원재료비 지수 상한 초과" (`:102-103`) — 호환 `optimize_unmet_text` |

### 9.6 검토 대기열 (`ml_service.py:79` · `main.py:42-47`)

임계값 = 전체 재적합 모델의 표본 내 \|잔차\| **0.9 분위**(`:79`). 화면 대기열 = 같은 잔차 내림차순 **상위 8** (`main.py:44`) — 임계값을 쓰지 않는다. 항목 키 `lot_id` · `measured_score` · `predicted_score` · `residual_score` (`:45`). 표준: `review_queue` 규칙 `top_quantile: 0.10`(D2-11), 분위는 **검증 구간 잔차**에서 정하고(시험 구간 · 운영 잔차에 적용) 학습 구간 · 표본 내 잔차는 쓰지 않는다.

### 9.7 화면 (`web/src/App.tsx:5,16`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| PC-S1 | 운영 개요 (지표 · 챔피언 `:24`) | E2 | 1 개요 + 4 모델 비교 |
| PC-S2 | 배합·숙성 최적화 | E3 | 3 조건 추천 |
| PC-S3 | 품질 예측 | E4 | 2 예측 시험 |
| PC-S4 | LOT 데이터 (`:31`) | E6 | 7 데이터 소스 + B12 records |

E5(잔차 우선순위)는 API 만 있고 화면이 없다 → 표준 화면 8 이 대응.

### 9.8 시험 (`tests/test_api.py`, 4 함수 · 4 케이스)

`test_health_and_models` · `test_predict_and_unbalanced_recipe_rejected` · `test_optimization_recipe_is_balanced_and_fallback_labeled` · `test_records_are_bounded_filtered_and_json_safe`.

### 9.9 상수 · 문구

`DEMO_REVIEW_SCORE = 78.0` (`:33` — 예측 < 78 이면 "검토 필요", 팩 `thresholds.review_below`) · 배합 합 경고 99.7~100.3 (`:84`) · 요청 거부 98~102 (`main.py:20`) · 상태 "검토 필요"/"예측 범위 양호" (`:86`).

## 10. ot — `../OneTouch ML AI` (팩 `rollform-quote`)

### 10.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 |
|---|---|---|---|---|
| OT-E1 | `GET /api/health` | `api/main.py:47-49` | — | `status` · `model_ready` · `version` · `mode` |
| OT-E2 | `GET /api/ml/overview` | `:52-53` → `ml_service.py:101-111` | — | `version` · `mode` · `job_rows` · `object_rows` · `missing_cells` · `champion` · `metrics`(4) · `test_metrics` · `recognition_champion` · `recognition_metrics`(3) · `recognition_test{accuracy, macro_f1, confusion_matrix, classes}` · `split` · `trend`(시험 끝 24) · `features` · `materials` · `profiles` · `cost` · `warning` |
| OT-E3 | `GET /api/data/demo` | `:56-66` | — | `manifest` · `cad`(20) · `quotes`(20) — `data/demo/*.json` |
| OT-E4 | `GET /api/cad/sample.dxf` | `:69-71` | — | 합성 DXF(1200×160 · 홀 6 · 슬롯 2, `cad.py:11-23`) |
| OT-E5 | `POST /api/cad/demo` | `:74-79` | — | 도면 분석(저장) |
| OT-E6 | `POST /api/cad/analyze` | `:82-91` | multipart `file` · `unit_override` mm\|inch | 415(.dxf 아님) · 413(> 5 MiB) · 422(파싱 · 규칙) · 200 도면 분석 `{filename, unit, source_unit, objects[], counts, bbox, dimensions, skipped, warnings, entity_count, data_mode, id, created_at}` |
| OT-E7 | `GET /api/cad/{drawing_id}` | `:94-98` | — | 저장된 분석 · 404 |
| OT-E8 | `POST /api/quotes` | `:101-106` → `quote.py:10-35` | `QuoteInput` (`:31-44`, `extra=forbid` · `allow_inf_nan=False`) — `reviewed: Literal[True]` · `review_note` 5~500 | 견적 초안 스냅숏(저장) |
| OT-E9 | `GET /api/quotes` | `:109-111` → `storage.py:48-54` | `search`(≤80) · `offset` · `limit`(10, 1~100) | `total` · `offset` · `limit` · `records` |
| OT-E10 | `GET /api/quotes/{quote_id}` | `:114-118` | — | 견적 · 404 |
| OT-E11 | `GET /api/quotes/{quote_id}/csv` | `:126-139` | — | UTF-8 BOM CSV · 수식 주입 방지 `safe_cell` (`:121-123`: `= + - @ \t \r` 앞 `'`) |
| OT-E12 | `GET /` (+ `/assets`) | `:142-149` | — | 콘솔 · 없으면 503 |

오류: 422 처리기가 `loc` · `msg` · `type` 만(입력값 되풀이 없음, `:26-28`).

### 10.2 변수 (`api/config.py:4-20` `FEATURE_META`)

| 변수 | 라벨 | 단위 | min | max | default | 비고 |
|---|---|---|---|---|---|---|
| `length` | 제품 길이 | mm | 100 | 6000 | 1200 | 도면 외곽에서 초기값(`cad.py:135`) |
| `width` | 전개 폭 | mm | 30 | 600 | 160 | 도면 외곽 · 학습 결측 12 (`ml_service.py:57`, 앞 540 행 안) |
| `thickness` | 소재 두께 | mm | 0.5 | 6 | 2 | 사람 입력 |
| `holes` | 홀 수 | 개/제품 | 0 | 100 | 6 | 도면 `counts.hole` · 정수 |
| `slots` | 슬롯 수 | 개/제품 | 0 | 50 | 2 | 도면 `counts.slot` · 정수 |
| `bends` | 성형 굽힘 수 | 개/단면 | 0 | 12 | 2 | 사람 입력 · 정수 |
| `material` | 재질 | 범주 | — | — | — | 3값 (`MATERIALS :4-8`, 밀도 · kg 단가 포함) |
| `profile` | 제품 형상 | 범주 | — | — | — | 4값 (`PROFILES :9`) |
| 목표 `minutes` | 개당 통합 가공시간 | 분 | — | — | — | `(.3 + L/2200 + W/1400 + 홀·.028 + 슬롯·.095 + 굽힘·.16 + t^1.45·.12 + 형상) × 재질계수 + N(0,.16)` (`ml_service.py:50-54`) · 예측 하한 0.05 (`:122`) |

합성 순서(`ml_service.py:43-58`): `default_rng(42)` → `FEATURE_META` 순서로 `uniform(min,max,900)` → holes · slots · bends 반올림 정수 → material `choice` → profile `choice` → 목표 `normal` → `job_id = OT-SYN-0001…` → 결측 width `choice(540, 12)`.
객체 설명자(`:19-40`): `default_rng(42)` → 클래스 `outer · hole · slot · other` 순서로 각 400 행, 특징 6 `circle · closed · aspect · relative_area · circularity · curved` (`:15`). **합계 1,600** (G2-E01 "1,600 합성 설명자").

### 10.3 후보 · 선정 · 분할 (`ml_service.py:73-111`)

| 묶음 | 분할 | 후보 (→ 표준) | 선정 | 재적합 · 평가 |
|---|---|---|---|---|
| OT-M1 가공시간 회귀 | 행 순서 `iloc[:540]` / `[540:720]` / `[720:]` (`:76`) — 시간순 아님(독립 합성 행) | Ridge→`ridge`(α 1) · Random Forest→`random_forest`(100 · leaf 2) · Extra Trees→`extra_trees`(100 · leaf 2) · Gradient Boosting→`gbr`(180 · depth 3) (`:77-79`) | 검증 MAE 최소, 동률 이름순 (`:84`) | 학습+검증 720 재적합(`:86`) · 시험 1회(`:103`) |
| OT-M2 객체 분류 (4 클래스) | 층화 `test 0.2` → dev 중 `valid 0.25` → 960 / 320 / 320 (`:88-89`) | Logistic Regression→`logreg`(max_iter 2000) · Random Forest→`rf_clf`(100) · Extra Trees→`et_clf`(100) — StandardScaler 공통 (`:90-94`) | 검증 macro-F1 최대, 동률 이름순 (`:97`) | dev 1,280 재적합(`:99`) · 시험 1회 accuracy · macro-F1 · 혼동행렬(`:100-106`) |

표준: OT-M1 → `regression` · `random_60_20_20`(time_key 없음) — 원천 행 순서 분할과 다르므로 차이 사유를 기록. OT-M2 → `extract` 의 모델 기반 추출기 학습, `stratified_60_20_20`(다중 클래스로 확장 — 표준 변경 요청 D2-15). 정답 라벨은 **합성 설명자의 생성 라벨**뿐이다 — 실제 도면 정답이 아니므로 실도면 평가는 `labels: none`.

### 10.4 보고 지표

**원천 문서에 기록된 수치 없음.** `README.md:98` 이 `docs/verification.md` 를 가리키지만 그 파일이 없다(원천 결함 O1). 원천 시험이 확인하는 값: 후보 4 · 3, 분할 합 = 행 수, 혼동행렬 합 320, 결측 12, 시험 끝 첫 id `OT-SYN-0877`(`tests/test_api.py:147-160`). 저장 견적 1건(`data/onetouch.sqlite3` quotes 1행): 수량 100 · 개당 1.3286 분 · 재료비 423,222 · 가공비 119,576 · 가산 86,145 · 부가세 66,044 · **합계 726,487 원** · 모델 Ridge · `ot-cad-demo-2026.09`. → G-M12 대조값은 원천 절차 재현값(D2-12), 견적 대조는 G2-Q01 fixture.

### 10.5 추출 규칙 — 기하 추출 + 객체 분류 (`api/cad.py:38-137`)

| # | 규칙 | 줄 |
|---|---|---|
| X1 | 바이너리 DXF 거부 · UTF-8 → cp949 해독 · ezdxf 읽기 실패 → 오류 | `:39-46` |
| X2 | 단위 `$INSUNITS` 1 inch · 4 mm · 5 cm · 6 m → mm, 0 이면 `unit_override` 필수, 그 밖 단위 거부 | `:47-54` |
| X3 | 모델 공간 요소 **≤ 2,000** (`MAX_ENTITIES` `config.py:25`) — 경동(20,000)과 다르다 | `:55-56` |
| X4 | 지원 요소 LINE · CIRCLE · ARC · LWPOLYLINE, 그 밖은 `skipped` 집계 | `:59-63` |
| X5 | 비평면(extrusion ≠ (0,0,1) · Z ≠ 0) 제외 | `:64-67, :80-82` |
| X6 | 폴리라인 꼭짓점 ≤ 500 · 곡선 평탄화 0.2 mm · 요소당 ≤ 2,000 점 · 전체 ≤ 60,000 점 · 좌표 유한 · \|v\| ≤ 1e7 | `:69-87, :104` |
| X7 | 객체 = 면적 · 둘레 · bbox · 폭 · 높이, 외곽 = 가장 큰 폐합 LWPOLYLINE | `:90-107` |
| X8 | 특징 6 → 분류기 `classify` (확률 최대 · 점수) | `:108-112`, `ml_service.py:114-117` |
| X9 | 기하 검증 8 사유 → `other`(검토 대상): 열린 도형 · 외곽 없음 · 외곽 밖/교차 · 점수 < 0.8 · 외곽 불일치 · 추가 외곽 · 원 아닌 홀 · 곡선 없는 슬롯 | `:113-124` |
| X10 | `counts{outer, hole, slot, other}` · `dimensions{length, width}`(외곽 bbox 긴 변 · 짧은 변) · 경고 문구 | `:127-135` |

### 10.6 견적식 (`api/quote.py:6-35` · `config.py:4-8,21` · `README.md:68-77`)

```
won(x)   = int(Decimal(str(x)).quantize(Decimal("1"), ROUND_HALF_UP))          # :6-7 — 입력 x 는 float 곱의 결과
minutes  = round(predict_time(record), 4)                                       # :13 (Python round, 소수 4)
weight   = length × width × thickness / 1e9 × density                           # :16 (float, 개당 kg)
material = won(weight × price_kg × (1 + scrap 0.08) × q)                        # :17
processing = won(minutes × machine_per_min 900 × q)                             # :18
setup    = won(setup_minutes 35 × 900)                                          # :19 (주문당 1회 = 31,500)
base     = material + processing + setup ; markup = won(base × 0.15)            # :20-21
subtotal = base + markup ; vat = won(subtotal × 0.10) ; total = subtotal + vat  # :22-23, :31
unit_price = round(subtotal / q, 2)                                             # :31 (float — 원천 결함 O2)
```

`overrides`: 도면 인식값(`holes` · `slots` · `length` · `width`)과 확정 입력이 0.001 넘게 다르면 `{field, recognized, confirmed}` (`:24-27`) — 시험 `[{'field':'holes','recognized':6,'confirmed':7}]` (`tests/test_api.py:59`). 단가 · 계수 스냅숏 `assumptions` (`:33`). 원천 시험값: `weight_per_piece 3.0144` · `setup_cost 31500` (`tests/test_api.py:51-52`). **float 곱 → Decimal 반올림**이라 "Decimal 만" 은 아니다 — 표준 이관은 같은 수식을 Decimal 로 계산하고 원천 fixture 와 원 단위 대조(차이 나는 행은 사유, D2-07a). `scripts/generate_sample_data.py:21-22` 의 `won()` 은 `int(round(x))`(짝수 반올림)로 `quote.py` 와 다르다(원천 결함 O3) → `data/demo/quote_candidates_20.json` 은 견적식 대조 fixture 로 쓰지 않는다(쓰면 사유 표기).

### 10.7 화면 (`web/src/App.tsx:9`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| OT-S1 | CAD 객체인식 (업로드 · 미리보기 · 유형 필터 · 객체 목록 `:68-71`) | E4 · E5 · E6 · E7 | 9 도면 추출 |
| OT-S2 | 견적자동화 (인식값 수정 · 검토 메모 · CSV `:37,73`) | E8 · E11 | 9 견적 |
| OT-S3 | 견적 이력 (검색 · 상세 `:74,77`) | E9 · E10 | 9 견적 이력 (B11 목록) |
| OT-S4 | 모델 비교·검증 | E2 | 4 모델 비교 |

### 10.8 시험 (`tests/test_api.py`, 11 함수 · 26 케이스)

`test_demo_geometry_and_storage` · `test_quote_accounting_and_csv` · `test_quote_rejects_invalid_inputs`(14) · `test_nonfinite_input_returns_json_error`(3) · `test_upload_types_size_and_corruption` · `test_unitless_and_inches` · `test_open_outside_and_unsupported_are_reviewed` · `test_planarity_and_entity_budget` · `test_paging_search_and_missing_ids` · `test_models_preprocessing_health_and_real_holdout` · `test_production_entrypoint`.

## 11. kd — `../KyungDong ML AI` (팩 `eto`)

### 11.1 엔드포인트

| ID | 메서드 · 경로 | 파일:줄 | 입력 | 출력 |
|---|---|---|---|---|
| KD-E1 | `GET /api/health` | `api/main.py:70-71` | — | `status` · `model_ready` · `version` · `mode` |
| KD-E2 | `GET /api/ml/overview` | `:74-75` → `ml_service.py:59-67` | — | `version` · `mode` · `job_rows` · `missing_cells` · `duplicates` · `champion` · `metrics`(4) · `test_metrics` · `split` · `seed` · `trend` · `features` · `materials` · `products` · `cost` · `recognition{method, labels(3), measured_accuracy: null, reason}` · `warning` |
| KD-E3 | `GET /api/cad/sample.dxf` | `:78-79` | — | 합성 도면(표제란 · BOM표 · 리비전표 · 장비 외형, `cad.py:16-39`) |
| KD-E4 | `POST /api/cad/demo` | `:82-86` | — | 도면 분석(저장) |
| KD-E5 | `POST /api/cad/analyze` | `:89-97` | multipart `file` · `unit_override` | 415 · 413(> 5 MiB) · 422(`ValueError` · `TypeError` · `OverflowError`) · 200 `{filename, sha256, unit, scale_to_mm, unit_source, mode, bbox, paths, texts, objects[], bom[], counts, unsupported, warnings, entity_count, id, created_at}` |
| KD-E6 | `GET /api/cad/{drawing_id}` | `:100-104` | — | 저장된 분석 · 404 |
| KD-E7 | `POST /api/quotes` | `:107-110` → `quote.py:5-23` | `QuoteInput` (`:47-67`): `bom` 1~100 행(`BomRow :34-44`) · `quantity` 1~1000 · `cut_m` · `weld_m` · `thickness_mm` · `complexity` · `labor_rate` · `outsource_cost` · `reviewed: Literal[True]` · `review_note` 5~500 · 총중량 10~10,000 · 대표 재질 ∈ BOM | 견적 초안 스냅숏(저장) |
| KD-E8 | `GET /api/quotes` | `:113-115` | `search` · `offset` · `limit`(10, 1~100) | `total` · `offset` · `limit` · `records` |
| KD-E9 | `GET /api/quotes/export/csv` | `:129-132` | 같은 검색 · 페이지 | 보이는 페이지 CSV(BOM · `safe_cell`) |
| KD-E10 | `GET /api/quotes/{quote_id}` | `:135-139` | — | 견적 · 404 |
| KD-E11 | `GET /api/quotes/{quote_id}/csv` | `:142-147` | — | 견적 + 품목 행 CSV (`safe_cell` `:118-120`) |
| KD-E12 | `GET /` (+ `/assets`) | `:150-157` | — | 콘솔 · 없으면 503 |

### 11.2 변수 (`api/config.py:4-17` `FEATURE_META`)

| 변수 | 라벨 | 단위 | min | max | default | 비고 |
|---|---|---|---|---|---|---|
| `mass_kg` | BOM 총중량 | kg/대 | 10 | 10000 | 650 | 견적 때 = Σ BOM 개당중량 × 수량 (`quote.py:6-8`) |
| `cut_m` | 확인한 절단 길이 | m/대 | 0 | 500 | 24 | 학습 결측 12 (`ml_service.py:28`) |
| `weld_m` | 확인한 용접 길이 | m/대 | 0 | 300 | 18 | |
| `thickness_mm` | 대표 판재 두께 | mm | 1 | 30 | 6 | |
| `complexity` | 조립 난이도 (데모 척도) | 1–5 | 1 | 5 | 3 | |
| `material` | 대표 재질 | 범주 | — | — | — | 8값 + 별칭 6 (`MATERIALS :5` · `ALIASES :6`, 고객 회신 D-160 ② 재질 통합) |
| `product` | 제품군 | 범주 | — | — | — | 6값 (`PRODUCTS :4`) |
| 목표 `hours` | 대당 통합 제조공수 | h | — | — | — | `8 + mass^.8·.05 + cut·.09 + weld·.8 + t^1.4·.3 + 난이도·5 + 재질 i·3 + 제품 j·5 + N(0,4)` clip ≥ 1 (`ml_service.py:24-26`) · 예측 하한 0.1 (`:71`) |

합성 순서(`ml_service.py:15-29`): `default_rng(42)` → `FEATURE_META` 순서 `uniform(900)` → material `choice` → product `choice` → 목표 `normal` → `job_id = KD-SYN-0001…` → 결측 cut_m `choice(540, 12)`.

### 11.3 후보 · 선정 · 분할 (`ml_service.py:44-67`)

행 순서 540/180/180 (`:47`) · Ridge→`ridge`(α 1) · Random Forest→`random_forest`(100 · leaf 2) · Extra Trees→`extra_trees`(100 · leaf 2) · Gradient Boosting→`gbr`(160 · depth 3) (`:48-50`) · 검증 MAE 최소, 동률 이름순 (`:55`) · 학습+검증 720 재적합 (`:57`) · 시험 1회 (`:58-62`). 표준: `regression` · `random_60_20_20`(time_key 없음, 원천 문서도 "시간순 실적 검증이 아니다" `docs/methodology.md:23`).

### 11.4 보고 지표 (`docs/verification.md:23,29` — 2026-09-19 실측)

| 과제 | 챔피언 | **시험 (G-M12 대조값)** | 그 밖 |
|---|---|---|---|
| 공수 회귀 | Ridge (`ridge`) | **MAE 4.1071 h · RMSE 5.0456 h · R² 0.9956** | 샘플 조건 예측 58.146 h/대 · 샘플 1대 합계 **8,486,493 원** (`:29`) |
| 영역 인식 | 규칙 | **지표 없음** — `measured_accuracy: null`, 사유 "3종 영역 정답 라벨 미확보"(`ml_service.py:65`, `docs/methodology.md:15`) | G2-E01 `labels: none` 의 원형 |

저장 견적(`data/kyungdong.sqlite3` quotes 2행): `kd-cad-demo-2026.09.1` 1대 · 58.146 h · 소재 4,092,120 · 가공 2,616,570 · 외주 0 · 가산 1,006,304 · 부가세 771,499 · 합계 8,486,493 / 이전 버전 `kd-cad-demo-2026.09` 1대 · 1.0275 h · 합계 5,235,023(버전별 금액 보존 — 확정 스냅숏 불변의 원형, `docs/methodology.md:27`).

### 11.5 추출 규칙 — 영역 3종 · BOM 텍스트 (`api/cad.py:11-123`)

**영역 3종(KD-X1, D2-06 = 고객 회신 D-160 ④ `title_block` · `bom_table` · `rev_table`, `data/reference/customer_answers.json:40-49`)**

| # | 규칙 | 줄 |
|---|---|---|
| R1 | 해독 UTF-8-sig → cp949 → cp1252, 바이너리 DXF 거부 | `:42-47` |
| R2 | 모델 공간 요소 **≤ 20,000** (`MAX_ENTITIES` `config.py:20`) · 업로드 ≤ 5 MiB (`config.py:19`, `main.py:93-94`) | `:54` |
| R3 | 단위 `$INSUNITS` 1 · 4 · 5 · 6 → mm 환산, 그 밖 · 0 이면 `override`(mm · inch) 필수, 헤더가 있으면 헤더 우선 | `:55-60` |
| R4 | 좌표 유한 · \|v\| ≤ 1e8 · TEXT/MTEXT 2,000자 자름 · LWPOLYLINE ≤ 4,000 꼭짓점 · bulge 있는 폴리라인은 `unsupported` | `:62-75` |
| R5 | 사각형 후보 = 닫힌 4점 축 정렬 LWPOLYLINE | `:81` |
| R6 | 키워드(대문자 비교): title_block `DRAWING NO` · `DRAWING NUMBER` · `DWG NO` · `도면번호` · `도면명` / bom_table `BILL OF MATERIAL` · `PARTS LIST` · `BOM` · `부품표` · `자재명세` / rev_table `REVISION` · `REV.` · `리비전` · `개정이력` | `:11-13` |
| R7 | 키워드 텍스트 삽입점을 포함하는 **가장 작은** 사각형을 영역으로, 같은 사각형은 한 번만 | `:94-100` |
| R8 | 영역 안 텍스트 전부의 키워드 종류가 하나면 그 라벨, 둘 이상이면 `other` · 상태 `검토 필요` | `:101-104` |
| R9 | 텍스트 · 사각형이 없으면 영역을 만들지 않는다(가짜 후보 0) · INSERT 등은 `unsupported` 로 공개 | `:117-122`, 시험 `tests/test_api.py:83-88` |

**BOM 텍스트(KD-X2)** — `bom_table` 영역의 각 텍스트를 `|` 로 나눠 정확히 4칸 `품명 | 재질 | 수량 | 개당중량kg` (`:108-111`) → 재질 대문자 + 별칭 통합(`:112`) → 재질 ∈ 8종 · 수량 정수 1~1,000 · 중량 유한 0.01~10,000 만 행으로(`:113-116`), 머리 행 · 다른 형식은 버린다. 행 키 `name`(80자) · `material` · `quantity` · `mass_kg` · `source`(영역 id). 샘플 결과: 영역 3(각 1) · BOM 4 행 · Σ 650 kg (`tests/test_api.py:30-35`, `docs/verification.md:9`).

### 11.6 견적식 (`api/quote.py:5-23` · `README.md:65-77`)

```
mass      = Σ mass_kg × quantity                               # :6 → 회귀 입력 mass_kg
hours     = round(predict_hours(features), 4)                  # :9
line.cost = round(mass_kg × qty × price_kg × 1.08 × 대수)       # :11 (Python round = 짝수 반올림, float)
material  = Σ line.cost                                        # :12
labor     = round(hours × labor_rate × 대수)                    # :13
outsource = round(outsource_cost × 대수)                         # :14
markup    = round((material + labor + outsource) × 0.15)        # :15
subtotal  = material + labor + outsource + markup ; vat = round(subtotal × 0.10) ; total = subtotal + vat   # :16-18
```

`README.md:77` "Python `round` 기준". **Decimal · ROUND_HALF_UP 이 아니다** — goal2 G2-Q01(Decimal · HALF_UP) · D2-07("원천 단계별 반올림 순서 그대로")와 맞물려 정확히 .5 인 단계에서 1원 차이가 날 수 있다(정본 결함 D2-07a). `overrides` 는 없다 — 대신 도면 BOM(`source_bom`)과 확정 BOM(`input.bom`) · 원본 `source_sha256` 을 함께 저장(`:19`). 확정 · 잠금 · 승인은 없다(검토 체크는 서명이 아님 `README.md:37`).

### 11.7 화면 (`web/src/App.tsx:9`)

| ID | 화면 | 사용 API | 표준 화면 |
|---|---|---|---|
| KD-S1 | CAD 객체인식 (3종 후보 · 미리보기) | E3 · E4 · E5 · E6 | 9 도면 추출 |
| KD-S2 | BOM · 견적자동화 (BOM 편집 · 검토 메모 · CSV) | E7 · E11 | 9 견적 |
| KD-S3 | 견적 이력 (검색 · 페이지 CSV · 상세) | E8 · E9 · E10 | 9 견적 이력 |
| KD-S4 | 모델 비교·검증 | E2 | 4 모델 비교 |

### 11.8 시험 (`tests/test_api.py`, 10 함수 · 21 케이스 = `docs/verification.md:8`)

`test_sample_has_three_regions_and_traceable_bom` · `test_quote_arithmetic_persistence_and_csv` · `test_invalid_quote_rejected`(12) · `test_bom_mass_limits_and_category` · `test_unit_confirmation_and_known_unit_precedence` · `test_no_text_does_not_invent_regions_and_blocks_disclosed` · `test_malformed_upload_and_size` · `test_pagination_search_export_matches_visible` · `test_models_split_missing_preprocessing_and_finite_json` · `test_production_frontend_is_served`.

## 12. 기능 단위 목록 — 6개사 합계 task-map 분모 (2차 G-M02)

1차 방법 그대로: 엔드포인트(+ `/`) + 학습 모델 묶음 + 최적화 + 화면, 2차 유형용으로 **대기열 규칙 · 추출기 · 견적식** 을 단위로 더한다.

| 회사 | 엔드포인트 | 모델 묶음 | 최적화 | 대기열 | 추출기 | 견적식 | 화면 | 합 |
|---|---|---|---|---|---|---|---|---|
| ks (1차) | 7 | 3 | 1 | — | — | — | 5 | 16 |
| sw (1차) | 7 | 3 | 1 | — | — | — | 5 | 16 |
| krs | 8 | 1 | 1 | 1 | — | — | 3 | **14** |
| pc | 7 | 1 | 1 | 1 | — | — | 4 | **14** |
| ot | 12 | 2 | — | — | 1 | 1 | 4 | **20** |
| kd | 12 | 1 | — | — | 2 | 1 | 4 | **20** |
| **합** | | | | | | | | **100** (1차 32 + 2차 68) |

| ID | 원천 기능 | 표준 대응 (예정) |
|---|---|---|
| KRS-E1~E8 | 위 §8.1 의 8 | B01 · B06/B07 · B12 · B04 `krs.recipe_optimize` · B09 `krs.residual_review` · B03 `krs.joint_strength` · B12 · 콘솔 `/app/*` + 호환 |
| KRS-M1 | 접합강도 회귀 (후보 5) | `krs.joint_strength` regression |
| KRS-O1 | 배합 무작위 5,000 | `krs.recipe_optimize` optimize(random) |
| KRS-Q1 | \|잔차\| ≥ 4 MPa 대기열 | `krs.residual_review` review_queue |
| KRS-S1~S3 | 화면 3 | 화면 3 · 4 / 2 · 8 / 7 |
| PC-E1~E7 | 위 §9.1 의 7 | B01 · B06 · B04 · B03 · B09 · B12 · 콘솔 + 호환 |
| PC-M1 | 관능점수 회귀 (후보 3) | `pc.sensory_score` regression (재측정 — D2-02) |
| PC-O1 | 배합 · 숙성 무작위 3,500 | `pc.recipe_optimize` optimize(random) |
| PC-Q1 | 잔차 상위 10% 대기열 | `pc.residual_review` review_queue |
| PC-S1~S4 | 화면 4 | 화면 1 · 4 / 3 / 2 / 7 |
| OT-E1~E12 | 위 §10.1 의 12 | B01 · B07 · B12 · B10 · B11 · 콘솔 + 호환 |
| OT-M1 | 가공시간 회귀 (후보 4) | `ot.machining_minutes` regression |
| OT-M2 | 객체 분류 (후보 3, 1,600 설명자) | `ot.cad_objects` extract(모델 기반 추출기) |
| OT-X1 | 기하 추출 + 기하 검증 규칙 X1~X10 | `ot.cad_objects` extract(추출기 `extractors/geometry_objects.py`) |
| OT-C1 | Decimal 견적식 + overrides | `ot.quote` quote (`formulas/quote.py`) |
| OT-S1~S4 | 화면 4 | 화면 9 · 9 · 9 · 4 |
| KD-E1~E12 | 위 §11.1 의 12 | B01 · B07 · B10 · B11 · 콘솔 + 호환 |
| KD-M1 | 공수 회귀 (후보 4) | `kd.labor_hours` regression |
| KD-X1 | 영역 3종 규칙 R1~R9 | `kd.drawing_regions` extract(`extractors/cad_regions.py`) |
| KD-X2 | BOM 텍스트 규칙 | `kd.drawing_regions` extract(`extractors/bom_text.py`) |
| KD-C1 | 견적식(공수 · 소재 · 외주 · 가산 · VAT) | `kd.quote` quote (`formulas/quote.py`) |
| KD-S1~S4 | 화면 4 | 화면 9 · 9 · 9 · 4 |

## 13. 원천 결함 · 차이 — 4개사 (이관 보고서 재료, 원천은 고치지 않는다)

| # | 회사 | 내용 | 근거 |
|---|---|---|---|
| K1 | krs | 모델 선정을 시험 구간 RMSE 로 한다(검증 구간 없음) — 시험 구간 재사용 | `ml_service.py:96,116-117` |
| K2 | krs | 최적화 미충족 시 위반량을 보지 않고 전체 표본 중 최저 비용을 고른다 | `:138` |
| K3 | krs | 요청 모델에 `extra=forbid` · `allow_inf_nan` 없음 · 422 기본 모양 | `main.py:19-33` |
| K4 | krs | 검토 대기열이 학습 구간 행까지 채점(표본 내 잔차) | `:171-175` |
| K5 | krs | CSV 수식 주입 방지 없음 | `web/src/App.tsx:36` |
| K6 | krs | IQR 이상치 경계를 분할 전 전체 데이터에서 계산 | `:59-73,95` |
| K7 | krs | `lot_id` 접두 `KS-` 가 1차 ks(광성) 과 겹친다 | `:48` |
| P1 | pc | 모델 선정을 시험 구간 MAE 로 한다 | `ml_service.py:71,78` |
| P2 | pc | 전체 재적합 모델로 같은 데이터를 채점해 임계값 · 대기열을 만든다(표본 내 평가) | `:78-79` · `main.py:44` |
| P3 | pc | 시간 열(`produced_at`)이 있는데 무작위 분할 | `:50,71` |
| P4 | pc | 대기열 임계값(상위 10%)을 계산하고 화면 대기열은 상위 8 고정 | `:79` · `main.py:44-46` |
| O1 | ot | README 가 가리키는 `docs/verification.md` 가 없다 — 보고 수치 없음 | `README.md:98` |
| O2 | ot | `unit_price` 를 float `round(…, 2)` 로 낸다 · 반올림 입력이 float 곱 | `quote.py:7,17-23,31` |
| O3 | ot | 샘플 생성기 `won()` 이 짝수 반올림(`int(round())`) — 견적식과 다르다 | `scripts/generate_sample_data.py:21-22` |
| O4 | ot | 요소 상한 2,000 (kd 20,000 과 다름) — 표준은 팩 기본값으로 두고 spec 상한 20,000 을 넘지 않게 | `config.py:25` |
| D1 | kd | 견적식이 float + Python `round`(짝수 반올림) | `quote.py:11-17` · `README.md:77` |
| D2 | kd | 확정 · 잠금 · 수정 이력(`overrides`) 없음 — 검토 체크만 | `README.md:37` · `quote.py:18-23` |
| D3 | kd | 영역 인식 정답 라벨 0 — 지표를 내지 않는다(올바름, 표준 `labels: none` 원형) | `ml_service.py:65` |
| D4 | kd | 원천 참조 파일에 사업자번호 · 고객사명이 있다 — 표준 저장소로 옮기지 않음 | `data/reference/customer_answers.json:56-66` |
| C1 | ot · kd | 기동 학습 · 코드 안 버전 상수 · SQLite 단일 파일 저장 | ot `main.py:17-20` · `config.py:3` · kd `main.py:16-19` · `config.py:3` |
