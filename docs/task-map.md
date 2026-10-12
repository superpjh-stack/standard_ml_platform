# 과제 대응표 — 6개사 기존 기능 → 표준 과제 · 경로 · 화면 (G-M02)

> 이관 도구 M1~M2 산출물(개발3). 분모는 `migration/source_inventory.md` §5 · §12 의 기능 단위 **100**(1차 ks 16 · sw 16 = 32, D-38 · 2차 krs 14 · pc 14 · ot 20 · kd 20 = 68). 검사 `gates/check_task_cover.py`(1차 `phase1` 32 · gate2 `phase2` 100).
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

## 3. krs — 기능 14 (팩 `solder` · 원천 `../Koreal Solder ML AI`, source_inventory §8)

> 회사 등록부 `tenants/krs.yaml` — demo(합성) + eval(CSV), **live 불가**(D2-01). 공급사 값은 `공급사A · 공급사B · 공급사C`(원천 A · B · C — G-M01 금지어 충돌, D2-61).
> 호환 경로 · 옛 모양은 `tenants/krs/compat.py`(개발2, 웨이브 A2).

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| KRS-E1 | `GET /api/health` (`api/main.py:36-38`) | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` | 원천 `model_ready` 상수 true(K3 계열) — 표준은 과제별 production 유무 |
| KRS-E2 | `GET /api/ml/overview` (모델 5 · 챔피언 · 통계) | `krs.joint_strength` | `/api/v1/tenants/{t}/tasks/{task}/overview` (B06) · `/api/v1/tenants/{t}/tasks/{task}/models` (B07) | 화면 1 · 화면 4 | `/api/ml/overview` | 원천 챔피언 = 시험 RMSE 최소(K1) — 표준은 검증 선정 · 시험 1회 |
| KRS-E3 | `GET /api/ml/samples` (limit 12 · offset) | `krs.joint_strength` | `/api/v1/tenants/{t}/tasks/{task}/records` (B12) | 화면 7 | `/api/ml/samples` | 표준 cursor · items (S10) |
| KRS-E4 | `POST /api/ml/optimize` (목표 강도 · 최대 비용 · 공급사) | `krs.recipe_optimize` | `/api/v1/tenants/{t}/tasks/{task}/optimize` (B04) | 화면 3 | `/api/ml/optimize` | 추천 1 → 상위 5 · least_violation(K2) · 시드 고정 |
| KRS-E5 | `GET /api/quality/overview` (\|잔차\| ≥ 4 주의 LOT) | `krs.residual_review` | `/api/v1/tenants/{t}/tasks/{task}/review` (B09) | 화면 8 | `/api/quality/overview` | 시험 · 운영 잔차만(원천 표본 내 K4, G2-R01) |
| KRS-E6 | `POST /api/quality/predict` (조성 합 100 ± 0.1) | `krs.joint_strength` | `/api/v1/tenants/{t}/tasks/{task}/predict` (B03) | 화면 2 | `/api/quality/predict` | 조성 합 = 과제 `input_rules` 422 · 35 MPa 주의 = `thresholds.review_below` |
| KRS-E7 | `GET /api/data/records` (검색 · 공급사 · 상태) | `krs.joint_strength` | `/api/v1/tenants/{t}/tasks/{task}/records` (B12) | 화면 7 | `/api/data/records` | 상태(정상 · 결측 · 이상) 필터 · summary · 옛 공급사 표기 · 기본 20 은 호환 훅(parse_records · records_frame, D2-A2-05) |
| KRS-E8 | `GET /{path}` SPA 콘솔 | 회사 전체 | `/app/*` | 화면 1 ~ 화면 10 | — | 회사 화면 코드 0 |
| KRS-M1 | 접합강도 회귀 (후보 5 · IQR · RobustScaler) | `krs.joint_strength` (regression) | `/api/v1/tenants/{t}/tasks/{task}/train` (B08) · `GET /api/v1/runs/{run_id}` | 화면 4 | — | IQR 학습 구간만(D2-03) · 표준 전처리 · random_60_20_20 (이관 보고서 K1 · K6) |
| KRS-O1 | 배합 무작위 5,000 (sn = 100 − 합) | `krs.recipe_optimize` (optimize) | `/api/v1/tenants/{t}/tasks/{task}/optimize` (B04) | 화면 3 | `/api/ml/optimize` | `derived` · 수락 표집 · `max_cost` optional (D2-45) |
| KRS-Q1 | \|잔차\| ≥ 4 MPa 검토 | `krs.residual_review` (review_queue) | `/api/v1/tenants/{t}/tasks/{task}/review` · `PATCH /api/v1/tenants/{t}/tasks/{task}/review/{item_id}` (B09) | 화면 8 | `/api/quality/overview` | 규칙 `abs_residual_ge: 4.0` (D2-11) · 검토 결과 기록(원천 없음) |
| KRS-S1 | 화면 배합최적화 (지표 · 모델 비교표) | `krs.recipe_optimize` · `krs.joint_strength` | B04 · B07 | 화면 3 · 화면 4 | — | |
| KRS-S2 | 화면 품질예측 (예측 폼 + 주의 LOT) | `krs.joint_strength` · `krs.residual_review` | B03 · B09 | 화면 2 · 화면 8 | — | |
| KRS-S3 | 화면 데이터 관리 (검색 · 필터 · CSV) | `krs.joint_strength` | B12 · 소스 | 화면 7 | — | CSV 수식 주입 방지(원천 K5 없음) |

## 4. pc — 기능 14 (팩 `kimchi` · 원천 `../PyoungChang ML AI`, source_inventory §9)

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| PC-E1 | `GET /api/health` | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` | |
| PC-E2 | `GET /api/ml/overview` (지표 3 · 챔피언 · limits) | `pc.sensory_score` | `/api/v1/tenants/{t}/tasks/{task}/overview` (B06) · B07 | 화면 1 · 화면 4 | `/api/ml/overview` | 원천 지표는 시험 선정 · 표본 내(P1 · P2) — 표준 재측정(D2-02) |
| PC-E3 | `POST /api/ml/optimize` (목표 점수 · 최대 원가 · 산지 · 라인) | `pc.recipe_optimize` | `/api/v1/tenants/{t}/tasks/{task}/optimize` (B04) | 화면 3 | `/api/ml/optimize` | 수락 3,500 · seasoning = 100 − 합 · scale 3 · 5 |
| PC-E4 | `POST /api/quality/predict` (배합 합 98~102) | `pc.sensory_score` | `/api/v1/tenants/{t}/tasks/{task}/predict` (B03) | 화면 2 | `/api/quality/predict` | `input_rules` 422 · 경고 문구는 호환 |
| PC-E5 | `GET /api/quality/overview` (잔차 상위 10% · 8) | `pc.residual_review` | `/api/v1/tenants/{t}/tasks/{task}/review` (B09) | 화면 8 | `/api/quality/overview` | 임계값 = 검증 잔차 분위(D2-11) |
| PC-E6 | `GET /api/data/records` (라인 · 산지 · 검색) | `pc.sensory_score` | `/api/v1/tenants/{t}/tasks/{task}/records` (B12) | 화면 7 | `/api/data/records` | S10 |
| PC-E7 | `GET /` (웹 nginx) | 회사 전체 | `/app/*` | 화면 1 ~ 화면 10 | — | |
| PC-M1 | 관능점수 회귀 (후보 3) | `pc.sensory_score` (regression) | B08 train | 화면 4 | — | 표준 재측정(time_cv5 — 행 420 < 500) · 원천 값 병기 |
| PC-O1 | 배합 · 숙성 무작위 3,500 | `pc.recipe_optimize` (optimize) | B04 | 화면 3 | `/api/ml/optimize` | 미충족 문구 2 = 호환 |
| PC-Q1 | 잔차 상위 10% 검토 | `pc.residual_review` (review_queue) | `/api/v1/tenants/{t}/tasks/{task}/review` · `PATCH /api/v1/tenants/{t}/tasks/{task}/review/{item_id}` (B09) | 화면 8 | `/api/quality/overview` | 원천 표본 내 분위(P2) 금지 |
| PC-S1 | 화면 운영 개요 | `pc.sensory_score` | B06 · B07 | 화면 1 · 화면 4 | — | |
| PC-S2 | 화면 배합·숙성 최적화 | `pc.recipe_optimize` | B04 | 화면 3 | — | |
| PC-S3 | 화면 품질 예측 | `pc.sensory_score` | B03 | 화면 2 | — | |
| PC-S4 | 화면 LOT 데이터 | `pc.sensory_score` | B12 | 화면 7 | — | |

## 5. ot — 기능 20 (팩 `rollform-quote` · 원천 `../OneTouch ML AI`, source_inventory §10)

> 회사 등록부 `tenants/ot.yaml` + 단가표 `tenants/ot/tasks/quote.yaml`(재질별 밀도 · kg 단가). 호환 경로 · 옛 모양은 `tenants/ot/compat.py`(개발2).
> 변수 이름(원천 → 팩): length → part_length_mm · width → blank_width_mm · thickness → sheet_thickness_mm · holes → hole_count · slots → slot_count · bends → bend_count · material → steel_grade · profile → section_profile (`compat.input_rename`).

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| OT-E1 | `GET /api/health` (`api/main.py:47-49`) | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` | 원천 버전 상수(C1) — 표준은 등록부 |
| OT-E2 | `GET /api/ml/overview` (회귀 4 · 분류 3 · 혼동행렬 · 추세) | `ot.machining_minutes` · `ot.cad_objects` | `/api/v1/tenants/{t}/tasks/{task}/overview` (B06) · `/api/v1/tenants/{t}/tasks/{task}/models` (B07) · B08 runs | 화면 1 · 화면 4 | `/api/ml/overview` | 혼동행렬 = run 보고서 `extract_metrics` |
| OT-E3 | `GET /api/data/demo` (manifest · 후보 20 · 견적 20) | `ot.quote` | `/api/v1/tenants/{t}/tasks/{task}/quotes` (B11) · `/api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/data/demo` (pack_file — `tenants/ot/samples/demo.json`) | 원천 샘플 20행의 **가린 사본**(원본 도면 이름 · 제품명 · 모델 코드 '비공개', D2-65 · D2-70) — 짝수 반올림(O3)이라 대조 fixture 아님(D2-07a). 표준 자리는 등록된 견적 · 문서 목록 |
| OT-E4 | `GET /api/cad/sample.dxf` | `ot.cad_objects` | 팩 파일 `packs/rollform-quote/samples/sample.dxf` | 화면 9 | `/api/cad/sample.dxf` (pack_file) | `synth/sample_dxf.py` 로 생성(원천 sample_bytes 같은 도형) |
| OT-E5 | `POST /api/cad/demo` | `ot.cad_objects` | `POST /api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/cad/demo` (document_demo) | 샘플 도면을 표준 업로드로 |
| OT-E6 | `POST /api/cad/analyze` (415 · 413 · 422) | `ot.cad_objects` (extract) | `POST /api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/cad/analyze` | 표준 422 invalid_document · 413 document_too_large(요소 2,000 · 꼭짓점 · 점) · 415 는 호환만 |
| OT-E7 | `GET /api/cad/{drawing_id}` | `ot.cad_objects` | `GET /api/v1/tenants/{t}/tasks/{task}/documents/{doc_id}` (B10) | 화면 9 | `/api/cad/{drawing_id}` | |
| OT-E8 | `POST /api/quotes` (reviewed · 메모 5~500) | `ot.quote` (quote) | `POST /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) | 화면 9 | `/api/quotes` (draft) | 확정은 `confirm` → 승인(D2-19) · overrides 누적 · 스냅숏 |
| OT-E9 | `GET /api/quotes` (search · offset · limit 10) | `ot.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) | 화면 9 | `/api/quotes` | cursor · items |
| OT-E10 | `GET /api/quotes/{quote_id}` | `ot.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}` (B11) | 화면 9 | `/api/quotes/{quote_id}` | 최신 revision |
| OT-E11 | `GET /api/quotes/{quote_id}/csv` (safe_cell · BOM) | `ot.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv` (B11) | 화면 9 | `/api/quotes/{quote_id}/csv` | 수식 주입 방지 · UTF-8 BOM 은 코어 |
| OT-E12 | `GET /` 콘솔 | 회사 전체 | `/app/*` | 화면 1 ~ 화면 10 | — | |
| OT-M1 | 가공시간 회귀 (후보 4 · 하한 0.05) | `ot.machining_minutes` (regression) | B08 train | 화면 4 | — | random_60_20_20(D2-21) · `clip.min 0.05` |
| OT-M2 | 객체 분류 (후보 3 · 설명자 1,600 · 층화) | `ot.cad_objects` (extract — 모델 추출기 `object_classifier`) | B08 train · B10 | 화면 4 · 화면 9 | — | stratified_60_20_20 · macro-F1 · majority_class 기준선 · labels synthetic |
| OT-X1 | 기하 추출 + 기하 검증 X1~X10 (8 사유) | `ot.cad_objects` (extract — 규칙 추출기 `geometry_objects` → 모델 추출기) | `POST /api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/cad/analyze` | 상한 · 허용차 = 과제 params · 결과 replaces [objects, counts] |
| OT-C1 | Decimal 견적식 + overrides (0.001) | `ot.quote` (`formulas/quote.py` · rate_tables density · price_kg) | `POST /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) | 화면 9 | `/api/quotes` | 표준 = 원천 현행 식 원 단위(저장 견적 726,487 ↔ 726,484 사유 D2-60) · unit_price Decimal(O2) |
| OT-S1 | 화면 CAD 객체인식 | `ot.cad_objects` | B10 | 화면 9 | — | |
| OT-S2 | 화면 견적자동화 (인식값 수정 · 메모 · CSV) | `ot.quote` | B11 | 화면 9 | — | |
| OT-S3 | 화면 견적 이력 | `ot.quote` | B11 목록 | 화면 9 | — | |
| OT-S4 | 화면 모델 비교·검증 | `ot.machining_minutes` · `ot.cad_objects` | B07 · B08 | 화면 4 | — | |

## 6. kd — 기능 20 (팩 `eto` · 원천 `../KyungDong ML AI`, source_inventory §11)

| ID | 원천 기능 | 표준 과제 | 표준 경로 (묶음) | 화면 | 호환 경로 | 차이 · 비고 |
|---|---|---|---|---|---|---|
| KD-E1 | `GET /api/health` | 회사 전체 | `GET /api/v1/health` (B01) | — | `/api/health` | |
| KD-E2 | `GET /api/ml/overview` (지표 · recognition measured_accuracy null) | `kd.labor_hours` · `kd.drawing_regions` | B06 · B07 | 화면 1 · 화면 4 | `/api/ml/overview` | labels none — 지표 없음(D-160) |
| KD-E3 | `GET /api/cad/sample.dxf` | `kd.drawing_regions` | 회사 파일 `tenants/kd/samples/KD-demo-reactor.dxf`(팩 생성기 + 회사 재질 · 도면 번호 — `migration/make_tenant_samples.py`) | 화면 9 | `/api/cad/sample.dxf` (pack_file) | 회사 값이 든 샘플은 회사 폴더(D2-A2-04 · D2-70) |
| KD-E4 | `POST /api/cad/demo` | `kd.drawing_regions` | `POST /api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/cad/demo` (document_demo) | 회사 샘플을 표준 업로드로 — 영역 3 · BOM 4 · 650 kg (원천 tests/test_api.py:30-35) |
| KD-E5 | `POST /api/cad/analyze` | `kd.drawing_regions` (extract) | `POST /api/v1/tenants/{t}/tasks/{task}/documents` (B10) | 화면 9 | `/api/cad/analyze` | 요소 20,000 · 꼭짓점 4,000 = 413 vertices (원천 422) |
| KD-E6 | `GET /api/cad/{drawing_id}` | `kd.drawing_regions` | `GET /api/v1/tenants/{t}/tasks/{task}/documents/{doc_id}` (B10) | 화면 9 | `/api/cad/{drawing_id}` | |
| KD-E7 | `POST /api/quotes` (BOM 1~100 · 검토) | `kd.quote` (quote) | `POST /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) | 화면 9 | `/api/quotes` (draft) | 확정 · 잠금 · overrides(원천 D2 없음) |
| KD-E8 | `GET /api/quotes` | `kd.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) | 화면 9 | `/api/quotes` | |
| KD-E9 | `GET /api/quotes/export/csv` | `kd.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes` (B11) · `.csv` | 화면 9 | `/api/quotes/export/csv` | 페이지 CSV 는 호환 모양 |
| KD-E10 | `GET /api/quotes/{quote_id}` | `kd.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}` (B11) | 화면 9 | `/api/quotes/{quote_id}` | |
| KD-E11 | `GET /api/quotes/{quote_id}/csv` | `kd.quote` | `GET /api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv` (B11) | 화면 9 | `/api/quotes/{quote_id}/csv` | |
| KD-E12 | `GET /` 콘솔 | 회사 전체 | `/app/*` | 화면 1 ~ 화면 10 | — | |
| KD-M1 | 공수 회귀 (후보 4) | `kd.labor_hours` (regression) | B08 train | 화면 4 | — | 원천 MAE 4.1071 ↔ 표준 3.7017 (−9.87%, D2-21) |
| KD-X1 | 영역 3종 규칙 R1~R9 | `kd.drawing_regions` (extract — `cad_regions`) | B10 | 화면 9 | `/api/cad/analyze` | labels none |
| KD-X2 | BOM 텍스트 규칙 | `kd.drawing_regions` (extract — `bom_text`) | B10 | 화면 9 | `/api/cad/analyze` | 재질 별칭 = 회사 `material_aliases` |
| KD-C1 | 견적식 (공수 · 소재 · 외주 · 가산 · VAT) | `kd.quote` (`formulas/quote.py`) | B11 | 화면 9 | `/api/quotes` | float 짝수 반올림(D1) → Decimal HALF_UP · 저장 견적 2건 원 단위 일치 |
| KD-S1 | 화면 CAD 객체인식 | `kd.drawing_regions` | B10 | 화면 9 | — | |
| KD-S2 | 화면 BOM · 견적자동화 | `kd.quote` | B11 | 화면 9 | — | |
| KD-S3 | 화면 견적 이력 | `kd.quote` | B11 목록 | 화면 9 | — | |
| KD-S4 | 화면 모델 비교·검증 | `kd.labor_hours` | B07 · B08 | 화면 4 | — | |

## 7. 집계

| 회사 | 단위 | 대응 | 미대응 |
|---|---|---|---|
| ks | 16 | 16 | 0 |
| sw | 16 | 16 | 0 |
| krs | 14 | 14 | 0 |
| pc | 14 | 14 | 0 |
| ot | 20 | 20 | 0 |
| kd | 20 | 20 | 0 |
| 합 | **100** | **100** | **0** |

표준에 새로 생긴 것(원천에 없음): B05 actuals · B07 models(승인 요청) · B13 approvals · B14 monitor · doctor · B15 trace · 화면 5 · 화면 6 · 화면 10 · 견적 확정(승인 경유) · 검토 대기열 결과 기록. 원천에만 있고 옮기지 않은 것: 기동 학습 · 코드 안 버전 상수(S1 · C1 — 금지 규칙), 검증 구간 순열 중요도(S2 → 시험 구간, D-29), 표본 내 지표 · 대기열(K4 · P2), ot 데모 20행의 실도면 출처 이름.
