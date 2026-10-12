# 결정 대장 (decisions.md)

> 상태: `확정` · `가설`(사람이 답하기 전 기본값) · `차단`(사람 확인 없이는 진행 불가 — 우회 중) · `표준 변경 요청` · `계약 불일치`.
> 정본(`intro.md` · `problem.md` · `spec.md` · `goal.md`)은 고치지 않는다. 정본의 결함 · 모순은 여기 `정본 결함` 표지로 적고 최종 보고에 올린다.
> 아키텍트가 Phase 0(2026-10-12)에 goal §7 의 D-01~D-20 을 옮기고, D-21 부터 새로 올렸다.

## 1. 열린 결정 — problem.md §8 Q1~Q12 (goal §7.1)

| # | 확인 필요 | 기본값 | 한 곳 | 상태 |
|---|---|---|---|---|
| D-01 | 배포 단위 (Q1) | 회사당 한 벌. 전 테이블에 `tenant_id` | `docker-compose.yml` | 가설 |
| D-02 | 부스팅 라이브러리 (Q2) | `hist_gb` 기본, `lightgbm` 선택 의존성 · 기본 꺼짐 | `std/candidates.yaml` | 가설 |
| D-03 | 등록부 구현 (Q3) | `mlp_*` + 파일 산출물. MLflow 없음 | `registry/models.py` 인터페이스 | 가설 |
| D-04 | 승인자 (Q4) | 과제 `approver_role` 1인. ks · sw 의 실제 승인자 명단은 미확인(`tenants/*.yaml: approvers` 빈 목록) | `tasks/*.yaml` · `approval/` | 가설 |
| D-05 | 시계열 분할 (Q5) | `time_60_20_20`, 행 < 500 이면 `time_cv5` | `std/split_policies.yaml` | 가설 |
| D-06 | 드리프트 기준 (Q6) | PSI 0.2 / 0.3 · 범위 밖 5% · 결측 +10%p · 성능 25% 악화 | `pack.yaml: monitor` | 가설 |
| D-07 | 범위 밖 처리 (Q7) | `predict_with_warning`. 1차 과제 8개 모두 이 값 | `tasks/*.yaml: out_of_range` | 가설 |
| D-08 | 목표 실측 원천 (Q8) | 1차는 fixture CSV · `actuals` API. 실 MES 매핑은 `차단` 가능(D-32 · D-33) | `tenants/*.yaml: sources.actuals` | 가설 |
| D-09 | 도면 라벨 (Q9) | 2차 | — | 가설 |
| D-10 | 보존 (Q10) | 예측 · 감사 1년 · 집계 영구 · 산출물(운영 이력 있는 것) 영구 · 나머지 90일 | `monitor/retention.py` | 가설 (D-35 와 모순) |
| D-11 | MES 예측 테이블 (Q11) | `mlp_prediction` 정본. `db/compat/sw.sql` 은 뷰 정의만(실행 안 함) | `db/compat/` | 가설 |
| D-12 | 고려솔더 (Q12) | 2차, `demo` + CSV | — | 가설 |

## 2. 운영 결정 (goal §7.2)

| # | 결정 | 값 | 한 곳 | 상태 |
|---|---|---|---|---|
| D-13 | 실 원천 | 루프는 fixture · 합성만 쓴다. `doctor-live` · `train-live` 는 사람이 `.env` 에 `MLP_KS_DP_KEY` 등을 넣은 뒤 사람이 돌린다. 그 전까지 `BLOCKED (D-13)` | `Makefile` | 확정 |
| D-14 | 포트 · DB | API 8200 · 웹 5190 · `ml_db` / `ml_test_db` (다른 표준 플랫폼 8100/5180 과 겹치지 않게) | `.env.example` · `Makefile` · `web/vite.config.ts` | 확정 |
| D-15 | 환경변수 접두 | `MLP_` | `.env.example` | 확정 |
| D-16 | 1차 범위 | 팩 `press` · `textile`, 회사 `ks` · `sw`. 같은 방법론(시간순 · 재적합 · 결측 보정)이라 G-M12 대조가 의미 있다 | `goal.md` | 확정 |
| D-17 | 이관 허용폭 | 같은 합성 시드 기준 기존 보고 지표 ±10%. 벗어나면 행마다 사유. 넓힐 수 없다 | `gates/check_migration.py` (`TOLERANCE = 0.10`) | 확정 |
| D-18 | 호환 라우터 수명 | 1차에 ks · sw 옛 경로 제공, 2차 종료 6개월 뒤 제거 | `serve/compat/` | 확정 |
| D-19 | 결정성 범위 | 같은 머신 · 같은 `env.lock` · `OMP_NUM_THREADS=1` 에서 예측 차이 0. 다른 머신은 1e-9 허용 | `gates/check_determinism.py` | 확정 |
| D-20 | 공개 저장소 위생 | IP · 호스트명 · 회사 실데이터 커밋 금지. fixture 는 합성 또는 익명화 사본만 | `gates/check_secrets.py` | 확정 |

## 3. Phase 0 에서 새로 올린 것 (아키텍트)

| # | 구분 | 내용 | 결정 · 우회 | 한 곳 | 상태 |
|---|---|---|---|---|---|
| D-21 | 설계 | 수치 스택 버전 | numpy 1.26.4 · pandas 2.3.3 · scikit-learn 1.6.1 은 원천 ks · sw 가 검증한 버전과 같게 고정(G-M12 행 일치 · 지표 대조 재현성). pyarrow 는 numpy 1.x 를 지원하는 21.0.0. 최신(numpy 2.5 · sklearn 1.9)으로 올리려면 G-M12 를 다시 잰다 | `pyproject.toml` · `uv.lock` | 확정 |
| D-22 | 계약 해석 | 오류 형식 — spec §7.3 "`{code, message, detail}`" | 표준 데이터 허브와 같은 봉투 `{"error": {code, message, detail}}` 로 둔다. 호환 라우터만 옛 `{"detail": [...]}` | `contracts/api-contract.md` §2 · `api/errors.py` | 확정 |
| D-23 | 정본 결함 | spec §7.2 응답이 regression 예시 하나뿐 — optimize 응답 모양 · risk 등급/기준선 자리 · 합성 여부 최상위 표시가 없다 | 계약을 18키로 보강: `tenant` · `recommendation` · `uses` · `synthetic` 추가, `prediction` 5키(`value · unit · interval · grade · baseline`), 유형별 null 규칙을 JSON Schema `allOf` 로 강제 | `contracts/predict-contract.md` | 확정 |
| D-24 | 정본 결함 | goal §3.1-4 가 "`contracts/` 8종" 이라 쓰고 이름은 9개(db-schema · interfaces · task · feature · predict · pack · tenant · api · screen-map)를 나열 | 9개 모두 만들었다 | `contracts/` | 확정 |
| D-25 | 정본 결함 | spec §8.1 탐색 공간은 "조절 변수(모델 입력)" 만 다룬다. ks 정비 시점은 모델 입력이 아닌 결정 변수 `t` 와 요청 상한(`max_delay_hours`) · 요청 제약값(`reserve_hours` · `max_cost_index`)이 필요하고, sw 도 제약값을 요청으로 받는다 | 과제 규격에 `decision_vars` · `params` 를 보강. 결정 변수는 학습 범위가 없으므로 `[min, max]` 만 쓴다 | `contracts/task-contract.md` §2 | 확정 |
| D-26 | 설계 | live + synthetic 금지(spec §10.2-4)는 테이블 간 조건이라 단순 CHECK 로 못 쓴다 | `mlp_model_version.tenant_mode` 비정규화 열 + 동기화 트리거 + 회사 mode 변경 전파 트리거 + 검사 제약. 기준선 미달 승격 금지도 검사 제약(`beats_baseline OR stage IN (candidate, archived)`) | `src/mlcore/db/schema.sql` | 확정 |
| D-27 | 정본 모순 | goal G-S02 "불량 픽스처 5종은 **전부 기동 거부**" ↔ spec §11.3-4 R4 "live 인데 production 이 합성이면 **그 과제만 끄고** `model_not_ready`" | spec 을 따른다: R4 픽스처는 기동하되 그 과제 `disabled`. `check_registry` 가 R1 · R2 · R3 · R5 거부 + R4 과제 끄기를 5/5 로 센다 | `gates/check_registry.py` · `contracts/tenant-contract.md` §2.1 | 확정 (사람 확인 권장) |
| D-28 | 정본 결함 | spec §12.2 의 `...` 경로가 모호하고, candidate→staging 경로가 없으며, `POST .../promote` 가 승인 없이 승격하는 것처럼 읽힌다 | 계약에서 확정: `POST .../models/{v}/stage`(admin) 추가, `promote` · `rollback` 은 **승인 요청만** 만든다(production 은 `approval.decide()` 만), `records` · `monitor` 는 과제 범위, `doctor` 는 `/tenants/{t}/doctor`, `runs/{id}` 는 실행의 회사로 범위 검사 | `contracts/api-contract.md` §1 | 확정 |
| D-29 | 원천 차이 | 원천 ks · sw 는 순열 중요도를 **검증 구간**(학습 구간 모델)으로 계산, spec §5.4 는 **시험 구간** | 표준은 spec 대로 시험 구간(`report` 목적, final_eval 뒤). 이관 보고서에 차이 사유로 적는다 | `train/report.py` · `docs/migration-report.md` | 확정 |
| D-30 | 정본 결함 | spec 예시 값이 원천과 다르다: §3.1 `set_temp` 150~210 step 1 · `set_pressure` 2.0~5.0 (원천 140~210 step 10 · 2~6 step 1), `color_tone` 값 `진함`(원천 `진한 색상`) · §3.2 `review_above: 2.0`(원천 ΔE 3.5) · `group_key: fabric_lot`(원천 합성 데이터에 원단 LOT 열 없음) · 목적 `minimize: delta_e`(원천은 비용지수 최소, 동률 ΔE) · §11.2 sw demo 시드 20260917(원천 42) · goal §1 "시드 42 · 20260917"(ks · sw 는 42 만) | 팩은 **원천 값**을 쓴다(G-M12 대조가 목적). spec 예시는 모양 설명으로 읽는다 | `packs/textile/*` · `tenants/sw.yaml` | 확정 (사람 확인 권장) |
| D-31 | 정본 사이 긴장 | G-M13 · spec §8.1 "탐색점 = 학습 범위(p1~p99) ∩ min/max" → sw 원천 전수 격자 8,400점(학습 범위 무시)과 점 수 · 끝점이 달라진다(예: `set_temp` 140 · 210 끝점 제외 가능) | 표준 규칙을 따른다. 호환 라우터의 `candidate_count` 차이는 `docs/migration-report.md` 에 사유로 적는다. 8,400 을 재현하려고 학습 범위 규칙을 끄지 않는다 | `tasks/optimize.py` · 이관 보고서 | 가설 |
| D-32 | **차단** | sw 실데이터: `dwell_time` · `color_tone` 원천 열 없음(대응률 7/9), 불량 라벨 정의(`JUDGE_RESULT` 대 `DEFECT_QTY`) 미확정, 현행 ΔE 보유량 0, ΔE 기준(`BAS_QUALITY_STD_ITEMS`) 값 미확정, Data Platform 뷰 이름 미확인 | 1차는 `demo`/`eval`(합성 · fixture)로 진행. `live` 전환 시 병합 규칙 R2 가 거부한다(정상). 사람 확인 필요 | `tenants/sw.yaml` | 차단 |
| D-33 | **차단** | ks 실데이터: 목표(잔여수명 · 24h 고장) 실측 원천(정비 · 고장 이력 테이블) 미발견, `motor_current` · `equip_temp` 의 `PRC_SENSOR_DATA.MEASURE_ITEM` 코드 미확인, `product_type` 결합 경로 미확인, Data Platform 뷰 이름 미확인 | 1차는 `demo`/`eval`. `doctor` 는 `목표 없음` 을 내야 한다 | `tenants/ks.yaml` | 차단 |
| D-34 | 설계 | 원천 ks 범주 변수 이름 `machine` · `product` 가 일반어라 코어 금지어 검사(G-M01)에서 `itertools.product` 등과 충돌하고, 값(`PRS-01~04` · 품목명)은 회사 고유값이다 | 팩 변수 이름을 `machine_code` · `product_type` 으로, 값은 `values_from: tenant`(→ `tenants/ks.yaml: categories`). 호환 라우터가 `compat.input_rename` 으로 옛 키를 바꾼다. 합성 생성기는 회사 범주값을 인자로 받아 원천과 같은 행을 낸다 | `packs/press/features.yaml` · `contracts/feature-contract.md` | 확정 |
| D-35 | 정본 모순 | spec §10.2-2 "`mlp_prediction` · `mlp_audit` 는 UPDATE · DELETE 권한 없음" ↔ §17 · D-10 "예측 · 감사 1년 보존"(1년 뒤 삭제) | 1차는 삭제하지 않는다(트리거로 막힘). 보존 작업은 2차에 월 파티션 분리 · 분리 파티션 보관 방식으로 설계(트리거를 우회하는 DELETE 를 만들지 않는다) | `db/schema.sql` · `monitor/retention.py` | 가설 |
| D-36 | 설계 | API 키 해시 방식 | 키는 32바이트 무작위(`mlp_` + urlsafe)라 무염 SHA-256(`sha256$<hex>`)으로 저장 · 조회. 평문 저장은 DB 검사 제약이 막는다. QA2 가 검토 | `auth/__init__.py` · `mlp_api_key_no_plain` | 가설 |
| D-37 | 게이트 해석 | G-M01 금지어 사전의 범위 | 팩 변수 · 과제 · 목표 · 비용식 · 결정 변수 이름 + 회사 코드 · 이름 · 별칭(`aliases`) + 원천 테이블 이름(`feature_map` · `target_map` · `sources`) + 회사 범주값 · 설비 코드. `_template` 팩 이름(x1 · c1 …)은 업종어가 아닌 자리표시라 뺀다 | `gates/check_core_terms.py` | 확정 |
| D-38 | 확정 | G-M02 분모 | ks 16 · sw 16 = **32** (엔드포인트 7 + 모델 묶음 3 + 최적화 1 + 화면 5, 회사당). 목록은 `migration/source_inventory.md` §5 | `gates/check_task_cover.py` | 확정 |
| D-39 | 설계 · 보류 | 감사 미들웨어는 쓰기 요청 응답 뒤 `mlp_audit` INSERT, 실패하면 로그만 남긴다(요청은 이미 처리됨) | 승인 · 되돌리기는 `approval.decide()` 안에서 같은 트랜잭션으로 감사 INSERT(실패 시 전체 롤백)를 강제한다. 일반 쓰기의 감사 실패 정책(요청 실패로 볼지)은 개발2 가 정한다 | `api/middleware.py` | 가설 |
| D-40 | 보류 | spec §1.2 · G-S03 의 콘솔 e2e(Playwright · 1024px)는 의존성이 아직 없다 | QA3 · 개발2 가 `@playwright/test` 를 정확한 버전으로 `web/package.json` devDependencies 에 넣는다(G-S07 유지) | `web/package.json` · `tests/e2e/` | 가설 |
| D-41 | 원천 결함 | `../KwangSung ML AI/docs/deployment.md:5,13-15` 에 공인 주소 · 호스트명이 평문 | 표준 저장소로 옮기지 않았다(D-20). 원천은 고치지 않는다. 이관 보고서 S7 | `migration/source_inventory.md` §6 | 확정 |
| D-42 | 게이트 해석 | G-S06 "IP · 호스트명 0" 의 판정 | 커밋될 파일 전부에서 키 패턴 · IPv4(127.0.0.1 · 0.0.0.0 제외) · URL 호스트(localhost · json-schema.org 만 허용, 잠금 파일은 패키지 출처 호스트 허용) · 호스팅 호스트명 꼴 0 | `gates/check_secrets.py` | 확정 |
| D-43 | 계약 | `rejected` 응답 모양 | 200 + 같은 18키. regression · risk 는 `prediction` 객체를 두되 `value · interval = null`, anomaly 는 `anomaly` 객체의 `score · flag = null`. 숫자를 지어내지 않는다 | `contracts/predict-contract.md` §4 | 확정 |
| D-44 | 소유권 | Phase 0 에서 아키텍트가 초안을 만든 파일 — `registry/{packs,tenants}.py`(→ 개발3) · `train/guard.py`(→ 개발1, check_leakage 와 공유) · `auth/` · `audit/` · `api/{main,middleware,errors}.py` · `api/routers/v1.py`(→ 개발2 · 개발3 각 경로) · `packs/*/formulas/*.py`(→ 개발3) · `tests/fixtures/bad_registry/`(→ 개발3) | 웨이브 A0 부터 표의 담당이 소유한다. 시그니처를 바꾸면 `contracts/interfaces.md` 와 `계약 불일치` 절차 | goal §3.2 | 확정 |
| D-45 | 보류 | fixture 데이터(합성 스냅숏 · 드리프트 · CSV · 원천 DB 사본)는 아직 없다(README · 생성 계획만) | 개발3 이 A0 에서 `migration/make_fixtures.py` 로 만든다. 그 전까지 G-V01 · G-S05 · G-M08 · G-M09 FAIL 이 정상 | `tests/fixtures/*/README.md` | 가설 |
| D-46 | 정본 결함 | spec §16.2 `make gate TENANT=<code>` 는 회사별 게이트를 말하지만 goal §2 게이트는 전 회사 판정이다 | 1차 `make gate` 는 전 회사(ks · sw)를 한 번에 판정한다. `TENANT=` 는 `run` · `doctor` · `train` 에만 쓴다 | `Makefile` | 가설 |
