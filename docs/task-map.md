# 과제 대응표 — ks · sw 기존 기능 → 표준 과제 · 경로 · 화면 (G-M02)

> 이관 도구 M1~M2 산출물(개발3). 분모는 `migration/source_inventory.md` §5 의 기능 단위 **32**(ks 16 · sw 16, D-38). 검사 `gates/check_task_cover.py`.
> 표기: 표준 과제 `<회사>.<과제>` · 표준 API `/api/v1/...`(묶음 B01~B15, `contracts/api-contract.md`) · 호환 경로(옛 키, D-18 — `tenants/<code>.yaml: compat.routes`, 개발2 `serve/compat/`) · 화면 번호(`contracts/screen-map.md`).
> 원천 근거 `파일:줄` 은 인벤토리 표를 따른다. 원천 코드는 실행하지 않았다(읽기 전용).

## 1. ks — 기능 16

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| KS-E1 | `GET /api/health` (`api/main.py:71-73`) | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` (옛 4키) | `model_ready` 는 과제별 production 유무. 원천은 기동 학습 성공 여부(S1) |
| KS-E2 | `GET /api/ml/overview` (23키) | `ks.remaining_hours` · `ks.failure_24h` · `ks.sensor_ood` | `GET /api/v1/tenants/{t}/tasks/{task}/overview` (B06) × 3 + `GET /api/v1/tenants/{t}/tasks` (B02) | 화면 1 · 화면 4 | `/api/ml/overview` | 후보 표 · 지표 · 중요도는 화면 4(B07 models · B08 runs). 우선 점검 큐 · 추세는 B12 records + mlp_prediction |
| KS-E3 | `POST /api/maintenance/predict` (잔여수명 · 고장 위험 · 이상 한 번에) | `ks.remaining_hours` · `ks.failure_24h` · `ks.sensor_ood` | `POST /api/v1/tenants/{t}/tasks/{task}/predict` (B03) × 3 | 화면 2 | `/api/maintenance/predict` (옛 10키, `compat.input_rename` machine → machine_code) | 표준 응답은 과제마다 18키 한 모양(predict-contract). 호환 라우터가 세 과제를 묶어 옛 키로 |
| KS-E4 | `POST /api/ml/optimize` (정비 시점) | `ks.maintenance_timing` | `POST /api/v1/tenants/{t}/tasks/{task}/optimize` (B04) | 화면 3 | `/api/ml/optimize` (옛 9키) | 추천은 `mlp_recommendation` needs_approval(원천은 기록 없음) |
| KS-E5 | `GET /api/data/records` (offset · machine · product · search) | `ks.remaining_hours` (LOT 표준 프레임) | `GET /api/v1/tenants/{t}/tasks/{task}/records` (B12) | 화면 1 | `/api/data/records` (옛 `total · limit · offset · records`) | 표준은 `cursor` · `items` · 기본 20 (S10) |
| KS-E6 | `GET /api/data/records/{lot_id}` | `ks.remaining_hours` | `GET /api/v1/tenants/{t}/tasks/{task}/records?search=<entity_id>` (B12) | 화면 1 | `/api/data/records/{lot_id}` | 없으면 빈 목록(표준) · 호환 경로는 404 재현 |
| KS-E7 | `GET /` (+ `/assets`) 콘솔 | 회사 전체 | `/app/*` (빌드된 `web/dist`) | 화면 1 ~ 화면 6 | — | 회사 화면 코드 0 — 폼은 features.yaml 에서 |
| KS-M1 | 잔여수명 회귀 (후보 4, `ml_service.py:77-90`) | `ks.remaining_hours` (regression) | `POST /api/v1/tenants/{t}/tasks/{task}/train` (B08) · `GET /api/v1/runs/{run_id}` | 화면 4 | — | 후보 · 하이퍼파라미터 원천 그대로(`packs/press/tasks/remaining_hours.yaml`). 기준선 · 구간 추가(S4) |
| KS-M2 | 24h 고장 분류 (후보 3) | `ks.failure_24h` (risk) | B08 train | 화면 4 | — | Brier 선정 그대로 |
| KS-M3 | IsolationForest 이상 (c 0.08) | `ks.sensor_ood` (anomaly) | B08 train · B03 predict | 화면 4 · 화면 6 | — | 임계값 = 검증 구간 점수 분위(D-50). 원천은 라이브러리 기본 임계 |
| KS-O1 | 정비 시점 1차원 격자 (0.5h · 제약 2 · 비용식) | `ks.maintenance_timing` (optimize) | `POST /api/v1/tenants/{t}/tasks/{task}/optimize` (B04) | 화면 3 | `/api/ml/optimize` | 결정 변수 `stop_after_hours`(D-25) · 비용식 `packs/press/formulas/maintenance_cost.py` |
| KS-S1 | 화면 운영 개요 | `ks.*` 4과제 | B02 · B06 · B01 | 화면 1 | — | 경고 배지 · 합성 배지 · 어제 예측 수 |
| KS-S2 | 화면 모델 비교·검증 | `ks.remaining_hours` · `ks.failure_24h` · `ks.sensor_ood` | B07 models · B08 runs | 화면 4 | — | 시험 지표 대 기준선 · 선정 사유 |
| KS-S3 | 화면 프레스 예지보전 | `ks.remaining_hours` · `ks.failure_24h` · `ks.sensor_ood` | B02 · B03 | 화면 2 | — | 과제 선택 → features.yaml 폼 |
| KS-S4 | 화면 정비 시점 탐색 | `ks.maintenance_timing` | B02 · B04 | 화면 3 | — | 후보 5 · 제약 충족표 |
| KS-S5 | 화면 LOT 데이터 (필터 · 상세 · CSV) | `ks.remaining_hours` | B12 records | 화면 1 | `/api/data/records` | 화면 7(데이터 소스)은 2차. CSV 내보내기(BOM · 수식 주입 방지)는 화면 1 표 |

## 2. sw — 기능 16

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| SW-E1 | `GET /api/health` | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` | KS-E1 과 같다 |
| SW-E2 | `GET /api/ml/overview` (27키) | `sw.delta_e` · `sw.defect_risk` · `sw.print_ood` | B06 overview × 3 + B02 | 화면 1 · 화면 4 | `/api/ml/overview` | `equipment`(방식 → 설비)는 `tenants/sw.yaml: compat.equipment_by_print_type` |
| SW-E3 | `POST /api/quality/predict` (ΔE · 불량 · 이상) | `sw.delta_e` · `sw.defect_risk` · `sw.print_ood` | B03 predict × 3 | 화면 2 | `/api/quality/predict` (옛 11키) | ΔE 검토 기준 3.5(`thresholds.review_above`, D-30) |
| SW-E4 | `POST /api/ml/optimize` (인쇄 조건 격자) | `sw.print_setpoint` | B04 optimize | 화면 3 | `/api/ml/optimize` (옛 11키) | 탐색점 = 학습 범위 ∩ min/max → 8,400 보다 적다(D-31). 이상 탐지 경고는 D-W3-01 |
| SW-E5 | `GET /api/data/records` (print_type · color_tone · search) | `sw.delta_e` | B12 records | 화면 1 | `/api/data/records` | S10 |
| SW-E6 | `GET /api/data/records/{lot_id}` | `sw.delta_e` | B12 records `?search=` | 화면 1 | `/api/data/records/{lot_id}` | |
| SW-E7 | `GET /` 콘솔 | 회사 전체 | `/app/*` | 화면 1 ~ 화면 6 | — | |
| SW-M1 | ΔE 회귀 (후보 4) | `sw.delta_e` (regression) | B08 train | 화면 4 | — | `packs/textile/tasks/delta_e.yaml` |
| SW-M2 | 불량 분류 (후보 3) | `sw.defect_risk` (risk) | B08 train | 화면 4 | — | 불량 라벨 실데이터 정의 미확정(D-32) |
| SW-M3 | IsolationForest 이상 | `sw.print_ood` (anomaly) | B08 train · B03 | 화면 4 · 화면 6 | — | D-50 |
| SW-O1 | 인쇄 조건 5차원 격자 (제약 3 · 비용식) | `sw.print_setpoint` (optimize) | B04 optimize | 화면 3 | `/api/ml/optimize` | 비용식 `packs/textile/formulas/process_cost.py` |
| SW-S1 | 화면 운영 개요 | `sw.*` 4과제 | B02 · B06 · B01 | 화면 1 | — | |
| SW-S2 | 화면 모델 비교·검증 | `sw.delta_e` · `sw.defect_risk` · `sw.print_ood` | B07 · B08 | 화면 4 | — | |
| SW-S3 | 화면 색상 품질 예측 | `sw.delta_e` · `sw.defect_risk` · `sw.print_ood` | B02 · B03 | 화면 2 | — | |
| SW-S4 | 화면 인쇄조건 탐색 | `sw.print_setpoint` | B02 · B04 | 화면 3 | — | 현재 조건 비용 대 추천 비교는 화면 3 |
| SW-S5 | 화면 인쇄 LOT 데이터 | `sw.delta_e` | B12 records | 화면 1 | `/api/data/records` | |

## 3. 집계

| 회사 | 단위 | 대응 | 미대응 |
|---|---|---|---|
| ks | 16 | 16 | 0 |
| sw | 16 | 16 | 0 |
| 합 | **32** | **32** | **0** |

표준에 새로 생긴 것(원천에 없음): B05 actuals · B07 models(승인 요청) · B13 approvals · B14 monitor · doctor · B15 trace · 화면 5 · 화면 6. 원천에만 있고 옮기지 않은 것: 기동 학습 · 코드 안 버전 상수(S1 — 금지 규칙), 검증 구간 순열 중요도(S2 → 시험 구간, D-29).
