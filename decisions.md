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
| D-40 | 보류 → 확정 | spec §1.2 · G-S03 의 콘솔 e2e(Playwright · 1024px) | 확정(2026-10-12 아키텍트): Python `playwright==1.63.0`(dev 그룹, uv.lock 고정 — G-S07 유지)로 `tests/e2e/`. 실제 uvicorn + 시험 DB + 실제 학습 · 승인 모델, chromium r1243(Playwright 캐시). `@playwright/test`(Node)는 쓰지 않는다 — 시험 DB · 학습 도우미(`tests/_dev2.py`)를 같은 pytest 세션에서 쓰기 위해 | `pyproject.toml` · `tests/e2e/` | 확정 |
| D-41 | 원천 결함 | `../KwangSung ML AI/docs/deployment.md:5,13-15` 에 공인 주소 · 호스트명이 평문 | 표준 저장소로 옮기지 않았다(D-20). 원천은 고치지 않는다. 이관 보고서 S7 | `migration/source_inventory.md` §6 | 확정 |
| D-42 | 게이트 해석 | G-S06 "IP · 호스트명 0" 의 판정 | 커밋될 파일 전부에서 키 패턴 · IPv4(127.0.0.1 · 0.0.0.0 제외) · URL 호스트(localhost · json-schema.org 만 허용, 잠금 파일은 패키지 출처 호스트 허용) · 호스팅 호스트명 꼴 0 | `gates/check_secrets.py` | 확정 |
| D-43 | 계약 | `rejected` 응답 모양 | 200 + 같은 18키. regression · risk 는 `prediction` 객체를 두되 `value · interval = null`, anomaly 는 `anomaly` 객체의 `score · flag = null`. 숫자를 지어내지 않는다 | `contracts/predict-contract.md` §4 | 확정 |
| D-44 | 소유권 | Phase 0 에서 아키텍트가 초안을 만든 파일 — `registry/{packs,tenants}.py`(→ 개발3) · `train/guard.py`(→ 개발1, check_leakage 와 공유) · `auth/` · `audit/` · `api/{main,middleware,errors}.py` · `api/routers/v1.py`(→ 개발2 · 개발3 각 경로) · `packs/*/formulas/*.py`(→ 개발3) · `tests/fixtures/bad_registry/`(→ 개발3) | 웨이브 A0 부터 표의 담당이 소유한다. 시그니처를 바꾸면 `contracts/interfaces.md` 와 `계약 불일치` 절차 | goal §3.2 | 확정 |
| D-45 | 보류 | fixture 데이터(합성 스냅숏 · 드리프트 · CSV · 원천 DB 사본)는 아직 없다(README · 생성 계획만) | 개발3 이 A0 에서 `migration/make_fixtures.py` 로 만든다. 그 전까지 G-V01 · G-S05 · G-M08 · G-M09 FAIL 이 정상 | `tests/fixtures/*/README.md` | 가설 |
| D-46 | 정본 결함 | spec §16.2 `make gate TENANT=<code>` 는 회사별 게이트를 말하지만 goal §2 게이트는 전 회사 판정이다 | 1차 `make gate` 는 전 회사(ks · sw)를 한 번에 판정한다. `TENANT=` 는 `run` · `doctor` · `train` 에만 쓴다 | `Makefile` | 가설 |

## 4. 웨이브 A0 — 개발1 · 2 · 3 이 올린 계약 불일치 (D-47 ~ D-58, 아키텍트 확정 2026-10-12)

> 번호 정리: D-47~D-50 개발1(먼저 잡음), D-51~D-53 개발3, D-54~D-58 개발2. 겹침 · 빠짐 없음(12건). 전에는 개발2 의 D-54~D-58 이 "개발3" 절에 섞여 있었고 개발1 절이 뒤에 있었다 — 번호순 한 표로 모았다.
> 방향: **계약←코드** = 코드가 맞고 계약을 고쳤다 · **코드←계약** = 계약대로 코드를 고친다(§5 후속) · **둘 다** = 계약 보강 + 코드 일부 수정. 정본 결함은 `정본 결함` 표지 + GitHub 이슈 번호.

| # | 올린 이 | 내용 (요지) | 결정 · 근거 | 방향 | 고친 계약 | 상태 |
|---|---|---|---|---|---|---|
| D-47 | 개발1 | interfaces §1 `mlcore/types.py` 가 없고 주인이 없다 | `types.py` 를 만들지 않는다. 타입은 만드는 담당의 모듈에 둔다: `FeatureDef` → `data/features.py`(개발1) · `TaskDef` → `registry/tenants.py`(개발3) · `SourceKind` 등 → `data/sources/base.py` · `Status` → `serve/contract.py` · `Stage`·`ModelRef` → `registry/models.py`. 근거: "한 파일은 한 사람만"(goal §3.2) — 주인 없는 공용 파일은 소유권 규칙과 충돌. 모양은 계약 그대로라 코드 변경 0. 단 개발2 `serve/validate.py` 가 `FeatureDef` 대신 YAML dict 를 받는 것은 계약(§7 `Sequence[FeatureDef]`)대로 바꾼다 | 계약←코드 (+개발2 소폭) | `interfaces.md` §1 · §7 | 확정 |
| D-48 | 개발1 | `TrainResult` 에 해시 · 합성 여부 없음, 산출물 `<version>/` 은 학습 시점에 모름 | 3필드(`artifact_sha256` · `synthetic` · `test_predictions`, 기본값 있음) 채택. 산출물 폴더 = `var/artifacts/<tenant>/<task>/<run_id>/`, 버전 ↔ 폴더는 `mlp_model_version.artifact_path` 가 정본. 근거: 버전은 `register()` 가 붙인다 · 한 run = 한 버전(`register` 멱등 확인) · 폴더 이름은 해시에 안 들어가 옮길 필요 없음 · 등록부가 해시를 다시 재므로 위조 불가. 합성 여부 정본은 `mlp_snapshot.synthetic`(TrainResult 값은 보조). **정본 결함**: spec §6.2 `<version>/` 표기 — 이슈 #2 에 덧붙일 것 | 계약←코드 | `interfaces.md` §4 | 확정 |
| D-49 | 개발1 | `submit()` 이 `train/` 이면 G-M06 B(api→`mlcore.train` import 금지)와 충돌 · `source_role` · `seed` 가 시그니처에 없음 | `mlcore/data/jobs.py::submit(tenant_id, task_id, *, actor, source_role=None, seed=None, test=False)` 가 정본. `mlcore.train.trainer.submit` 은 다시 내보낸 이름. 근거: 게이트(기동 경로 학습 0)가 위치보다 우선 · 접수는 학습이 아니라 데이터 고정이다. 오류 대응 확정: `SourceDisconnected`·`NoTarget` → 503 `source_disconnected`(`no_target`) · `TrainBusy` → 409 `train_busy` · 꺼진 과제 → 404. run_id 는 결정적(`run_<sha256 16>`) — db-schema 의 `run_<ulid>` 표기를 고쳤다(G-M06 "run_id 동일" 근거). API 본문 `source_role` 은 필수 그대로(함수 기본값은 `make train` · 감시용) | 계약←코드 | `interfaces.md` §4.1 · `db-schema.md` ID 형식 · `api-contract.md` §3 · §4 | 확정 |
| D-50 | 개발1 | anomaly 기준선 판정 규칙이 정본에 없음 · sw.print_ood 0.167 로 미달 | (1) 판정 규칙: 시험 `flag_rate` ∈ c × [0.5, 2.0] — 값은 코드 상수가 아니라 `std/metrics.yaml flag_rate.beats_band`. 밴드는 개발1 가설 그대로이고 **넓히지 않았다**. (2) 임계값: 계약 문구 "학습+검증 점수 분위"는 재적합 모델의 **표본 내** 점수라 IsolationForest 에서 임계값이 낮게 잡힌다(시험 flag 2배) — 계약 쪽 잘못. spec §5.3 "검증 구간으로 보정 · 임계값" 대로 **학습 구간 모델의 검증 구간 점수 `1-c` 분위**로 바꾸고 재적합 모델에 그대로 쓴다(회귀 구간 q 와 같은 방식, 시험 구간 미사용 → 누수 없음). 아키텍트 재현(scratchpad, src 수정 없음, 시드 42): 현행 ks 0.160 · sw 0.167 → 새 규칙 ks **0.139** · sw **0.146** (c 0.08, 둘 다 밴드 안). 시험 flag 가 여전히 c 의 1.7~1.8배인 것은 시험 구간 분포 이동으로 보이며 보고서 경고로 남긴다. **정본 결함**: spec §2.4 · §5 에 라벨 없는 유형의 "기준선 이김" 정의가 없다 — 이슈 #2 | 코드←계약 | `task-contract.md` §2 · `std/metrics.yaml` | 확정 |
| D-51 | 개발3 | `_template` CSV fixture 를 커밋하면 G-S06 FAIL | 커밋하지 않는다 — 개발3 우회가 정답. 근거: spec §17-9 는 새 회사 데이터를 "CSV 업로드"(외부 입력)로 본다 · G-M10 "생성 파일은 `tenants/yn*` 뿐" · "빈 폴더에서 처음부터"(QA3)를 되풀이하려면 `yn` 을 커밋하면 안 된다. 시험이 `make_fixtures.py --kind template_csv` 로 tmp 에 만들고 임시 등록부의 `sources.eval.path` 가 가리킨다. 이전 우회의 "A 에서 `tests/fixtures/yn/` 커밋" 은 **취소**. 게이트 G-S06 은 바꾸지 않는다 | 계약 보강 | `tenant-contract.md` §2 T4 | 확정 |
| D-52 | 개발3 | sw 불량 지표 재현값 ↔ 원천 문서 차이 ≤ 0.0013 | 행 일치 인정(같은 프레임의 회귀 지표 · 불량률 · 필터 건수 완전 일치). 시험 대조는 ±0.0015 절대(더 엄격) + G-M12 ±10%(D-17) 그대로 — 허용폭을 넓힌 것이 아니다. `baselines.yaml` 에는 표준 실측(0.8686 · 0.7823 · 0.1261)을 `value`, 문서값을 `source_reported` 로 적는다(M5 이후 아키텍트). 원천 실행 금지라 원인 확인은 사람 몫 — 이슈 #3 유지 | 판정만 | — | 확정 |
| D-53 | 개발3 | pack-contract §4 생성기 시그니처에 `categories` 없음 · 위치 이중화 | 개발3 공표 그대로 계약에 넣었다: `generate(rows, seed, *, categories=None)` · 반환 열에 목표 열(과제 `target.name`) · 표준 메타 열은 어댑터가 · 과제 진입점 `synth/<task>.py` 우선, 없으면 `pack.yaml synth.module`, 해석은 `registry.packs.synth_spec` 한 곳. 근거: D-34(회사 범주값은 인자로) · spec §4.2(`synth/<task>.py`)와 계약(팩 하나) 둘 다 만족. **정본 결함(경미)**: spec §4.2 · §15 가 생성기 위치를 다르게 적음 — 이슈 #4 | 계약←코드 | `pack-contract.md` §1 · §4 | 확정 |
| D-54 | 개발2 | 전이 규칙 위반 · 동시 학습 초과의 오류 코드 없음 | `std/statuses.yaml error_codes` 에 409 `invalid_transition`(detail.rule 6종) · 409 `train_busy`(detail.rule `tenant_concurrency`) 추가. 단 **사유 없는 rollback 은 전이 문제가 아니라 입력 누락**이므로 422 `missing_required`(detail.field `reason`) — 개발2 수정. 근거: goal §2.3 이 같은 상황(필수 입력 누락)을 이미 422 로 정함. **정본 결함**: goal §2.3 · spec §7.3 오류 표에 전이 · 동시성 행 없음 — 이슈 #2 · #4 | 둘 다 | `std/statuses.yaml` · `api-contract.md` §3 · §4 · `interfaces.md` §5 | 확정 |
| D-55 | 개발2 | 범주 값이 허용 목록 밖이면 무엇인가 | 422 `out_of_bounds`(detail.rule `values`) — 개발2 구현이 맞다. `feature-contract.md` §4 의 "422 `invalid_input`" 문구가 틀렸다: goal §2.3 `invalid_input` = 형식(모르는 키 · NaN · 형), `out_of_bounds` = 있을 수 없는 값. 없는 설비 코드는 후자. 목록 안이지만 학습에 안 나온 값은 200 + `out_of_range` | 계약←코드 | `feature-contract.md` §4 · `api-contract.md` §3 · `interfaces.md` §7 | 확정 |
| D-56 | 개발2 | `decide()` 에 own_task 판정 · `request_id` 자리 없음 | 개발2 안 채택: 회사 범위(404) · own_task(403)는 API 가 decide 전에, decide 는 역할만 다시 확인(심층 방어), 선택 키워드 `request_id=None` → `mlp_audit.request_id`. `decide` 호출처는 API 승인 경로 하나(현재 실측 1곳). 근거: 담당 목록은 인증 계층 지식 · 기존 호출 호환. 호출처 1곳을 게이트로 묶는 것은 아키텍트 후속(§5) | 계약←코드 | `interfaces.md` §6 | 확정 |
| D-57 | 개발2 | 202 queued 를 누가 실행 · 등록하나 | **API 밖 작업자 프로세스.** `python -m mlcore.train.jobs --pending \| <run_id>` 가 run 마다 `serve.training.run_and_register(run_id)` 를 부른다(execute → succeeded 면 `Registry.register` → candidate). `make train` 도 같은 함수. API 안 배경 작업은 두지 않는다. 근거: G-M06(API 프로세스 학습 0) · G-M14(app RSS ≤ 768MB) · spec §5.5 회사당 1개. 등록 호출처를 하나로 묶어 "학습은 됐는데 candidate 가 없는" 길을 없앤다. 시험은 `run_and_register` 직접 호출(현 우회 그대로). **정본 결함**: spec §5.5 가 작업 실행 주체를 정하지 않음 — 이슈 #4 | 둘 다 | `interfaces.md` §4.1 · `api-contract.md` §4 | 확정 |
| D-58 | 개발2 | 산출물 경로 · 해시 규칙 | 개발2 안 채택: `artifact_path` = 저장소 상대 경로, 해시 = 4파일 `"<이름>\0<sha256>\n"` 이름순 SHA-256, 적재 시 해시 · env.lock 파일 · 등록부 env_lock · 현재 패키지(numpy · pandas · scikit-learn · scipy · joblib · python major.minor) 대조, 등록 때 해시 재측정. 근거: 결정성(D-19) · G-M06 `model_artifact_mismatch` · 경로가 머신마다 달라도 같은 해시 | 계약←코드 | `interfaces.md` §5 | 확정 |

## 5. 후속 작업 (위 확정에서 나온 코드 수정 — 담당이 한다, 아키텍트는 src · tests 를 고치지 않았다)

| 담당 | 근거 | 할 일 | 시기 |
|---|---|---|---|
| 개발1 | D-50 | `train/trainer.py`: anomaly 임계값을 **학습 구간 모델의 검증 구간 점수 `1-c` 분위**로(`time_cv5` 는 폴드 검증 점수 이어 붙임) 계산해 재적합 모델에 적용. 재적합 표본 내 분위 코드(`anomaly_thr = quantile(predict(model, X_all.iloc[fit_idx]))`) 삭제. 밴드 0.5 · 2.0 상수 → `std/metrics.yaml flag_rate.beats_band` 읽기. `selection_reason` 문구 고치기. 시험: sw.print_ood `beats_baseline=True`(재현 0.146) · ks 0.139 · 시험 구간을 바꿔도 임계값 불변 | A0 (G-V01 과 무관 — 개발2 시험과 겹치지 않음) |
| 개발1 | D-57 | `train/jobs.py` `__main__`(`--pending` · `<run_id>`)이 `execute` 대신 `mlcore.serve.training.run_and_register` 를 부르게. `make train` 진입점도 같은 함수(Makefile 은 아키텍트가 연결) | A |
| 개발1 | D-49 | 결정적 run_id 라서 같은 스냅숏 · 설정의 **failed** 실행을 다시 접수할 길이 없다 — 재시도 정책(예: failed 면 상태를 queued 로 되돌림 · 감사 기록)을 정해 `progress-dev1.md` 에 공표, 필요하면 `계약 불일치` 로 | A |
| 개발2 | D-54 | `registry/models.py`: 사유 없는 rollback → 422 `missing_required`(detail.field `reason`, `serve.errors.MissingRequired`). `serve/training.py`: `TrainBusy` detail `{rule: tenant_concurrency}`, 주석 "(오류 코드 미정)" 삭제 | `test_vertical_slice.py` 끝낸 뒤 |
| 개발2 | D-47 | `serve/validate.py` 4함수가 계약대로 `Sequence[FeatureDef]`(`mlcore.data.features`)를 받게 — 지금은 features.yaml dict. `progress-dev2.md` §1.1 문구 갱신 | A |
| 개발3 | D-51 | `tests/fixtures/README.md` `yn/` 행에서 "회사 등록은 A" → "커밋하지 않음(T4)". `make tenant` 가 CSV 경로를 받아 `sources.eval.path` 에 적게(`tests/test_new_tenant.py` 는 임시 등록부 폴더에서) | A |
| 개발3 | D-52 | `docs/migration-report.md` 에 sw 불량 3지표 차이와 추정 원인(문서값 = 원천 코드 다른 시점) 행 | A (G-M12) |
| 아키텍트 | D-57 · D-56 | `Makefile` `train` · `worker` 대상 연결. `gates/check_no_autopromote.py` 에 `approval.decide(` 호출처 = `api/routers/models.py` 만(시험 제외) 검사 추가(조이기만) |A — **완료 2026-10-12** (D-70 · decide 호출처 1곳 AST 검사) |
| 아키텍트 | D-52 | M5 이관 대조 후 `packs/*/baselines.yaml` 값 기입 |A — **완료 2026-10-12** (press · textile · _template 시험 구간 실측, 전 값 null → 기입이라 하향 없음) |
| 사람 | D-48 · D-50 · D-53 · D-54 · D-57 | 정본 결함 — spec §6.2 경로 · §2.4 비지도 기준선 · §4.2/§15 생성기 위치 · goal §2.3 오류 표 · §5.5 실행 주체. 이슈 #2 · #4 에 덧붙여 사람 확정 | — |

## 6. 웨이브 A — 개발1 이 올린 것 (임시 번호 `D-W1-nn` — 다른 개발자와 번호가 겹치지 않게. 아키텍트가 D-번호로 정리)

| # | 구분 | 내용 | 개발1 처리 · 요청 | 한 곳 | 상태 |
|---|---|---|---|---|---|
| D-W1-01 | 계약 보강 요청 | 과제 YAML 새 선택 키 2개가 `task-contract.md` §1 에 없다: `outlier: iqr \| {method: iqr, k: 1.5, columns: [...]}`(spec §5.1) · `candidate_search: {<후보>: {<파라미터>: [값, ...]}}`(spec §5.2 "후보당 최대 20회 무작위 탐색"). `std/candidates.yaml` 에는 탐색 횟수(20)만 있고 탐색 공간이 없다 | 둘 다 **기본 꺼짐**(키 없으면 동작 그대로 — G-M12 이관 대조 보존). 탐색은 과제가 격자를 줄 때만, 시드 = 과제 seed, 첫 시도 = 팩 기본값, 비지도(선정 지표 없음)는 탐색 안 함 + 경고. 이상치 경계는 **그 학습 구간에서만** 재고 그 구간에서만 뺀다(검증 · 시험 행 그대로). 아키텍트: 계약 §1 · task-schema 에 두 키 추가 여부 결정 | `train/trainer.py` | → D-60 확정 |
| D-W1-02 | 계약 보강 요청 | `std/metrics.yaml baselines.last_value` 는 있으나 regression 시계열에서 `train_mean` 과 어느 쪽을 기준선으로 쓸지 규칙이 없다 | **검증 구간에서 선정 지표가 더 나은 쪽**(동률 train_mean)을 기준선으로 쓴다 — 더 강한 기준선 · 시험 구간 미사용. 두 기준선의 검증 · 시험 지표는 `report.baselines_compared` 에 남긴다. 실측: ks · sw 과제는 둘 다 train_mean 이 선택돼 지표 변화 0. `features.lock` 의 `baseline` 은 재적합 평균 그대로 + `baseline_kind` | `train/trainer.py` | → D-61 확정 |
| D-W1-03 | 계약 보강 요청 | 어댑터 등록부 키가 `tenant-contract.md` 에 없다: gateway `ts_column · entity_column · pivot{key,value} · window · agg · agg_by · schema`, mes `join_on · ts_column · entity_column · schema`, dataplatform `path · params · page_size · ts_column · entity_column`. dataplatform 기본 경로 `/v1/readings`(회사 Data Platform 클라이언트 `get_readings` 를 따른 **가설**), 뷰 이름 null 이면 `source_disconnected` | 코드에 넣고 progress-dev1 §1.2 에 공표. 원천 열 · 결합 키는 미확인(D-32 · D-33)이라 ks · sw 등록부에는 아직 안 적었다(개발3 소유) | `data/sources/*` | → D-62 확정(키) · 기본 경로 가설 |
| D-W1-04 | 계약 보강 요청 | `GET /runs/{id}` 응답(api-contract §4)이 화면 4 에 필요한 것(선정 사유 · 기준선 종류 · 구간 · 보정 · 중요도 · 잔차 · 보정 곡선)을 담지 않고, B07 `models` 항목에 `run_id` 가 없어 화면 4 가 버전 → 학습 실행으로 갈 수 없다 | `mlcore.data.jobs.run_view(run_id, tenant_id=)` 가 계약 키 전부 + 덧붙임(`stage · seed · code_version · config_hash · 시각 · error · report{…}`)을 낸다(DB 만 읽음 — 학습 코드 import 0). 화면 4 는 `run_id` 가 없으면 입력칸으로 받는다. **요청 개발2**: `api/routers/train.py` 에 `GET /api/v1/runs/{run_id}` = `auth.require(p, "train", write=False)` → `run_view(run_id, tenant_id=p.tenant)` → None 이면 404 `not_found` (G-S04 B08 · tests/test_api_contract.py 실패 1건이 이것). **요청 개발2 · 아키텍트**: `models` 항목에 `run_id` 추가(계약 §4) | `data/jobs.py` · 화면 4 | → D-63 확정 |
| D-W1-05 | 공표 (D-49 후속) | 결정적 run_id 의 failed 실행 재시도 | 같은 스냅숏 · 설정 요청이 다시 오면 **failed 행을 queued 로 되돌린다**(started/finished/report/error 비움, 이전 오류는 `log` 에 덧붙임, `created_by` = 새 요청자) + 같은 트랜잭션에서 `mlp_audit action=train.retry`(detail.previous_error). succeeded · queued · running 은 그대로 돌려준다. 회사에 다른 queued · running 이 있으면 `TrainBusy`(409). **요청 개발2**: `serve.training.submit` 이 "run_id 가 전에 있었다" 로 `reused: true`(200)를 내는데, 재접수는 새 실행이므로 202 `{run_id, status: queued}` 가 맞다 — 이전 상태가 failed 였는지로 가른다 | `data/jobs.py::submit` | → D-64 확정 |
| D-W1-06 | **결함 (담당 밖, 고치지 않음)** | 환경변수 `MLP_TENANTS_DIR` 해석이 둘이다: 개발1 `data.jobs.tenants_base_for` = **`os.pathsep` 목록 · 회사 파일이 있는 첫 폴더 · 없으면 기본 tenants/**, 개발3 `registry.tenants.tenants_dir()` = **값 전체를 경로 하나로**. 개발2 `tests/_dev2.py::use_tenants_dir` 는 목록으로 앞에 붙이고 `os.environ` 에 **영구히** 남긴다 → 같은 pytest 세션의 뒤 시험이 `load_and_merge("ks")` 를 부르면 `'<dirA>:<dirB>/ks.yaml'` FileNotFoundError. 실측: 전체 `pytest -q` 31 failed · 7 errors 중 21건이 이것(파일 단위 실행은 통과) | **요청 개발3**: `tenants_dir()` · `load_tenant(code)` 를 회사 단위 검색(목록 · 기본 폴더 대체)으로 — `mlcore.data.jobs.tenants_base_for` 와 같은 규칙(또는 그 함수를 쓰기). **요청 개발2**: `use_tenants_dir` 를 `monkeypatch.setenv` 처럼 시험 뒤 되돌리게. 개발1 쪽은 여러 폴더 값이면 기본 폴더를 명시해 넘겨 로더가 목록을 경로로 읽지 않게 했다. 이슈 등록 | `registry/tenants.py` · `tests/_dev2.py` | → D-65 확정 (이슈 #5 닫을 수 있음) |
| D-W1-07 | 결함 (고침) | `time_cv5` 의 **폴드 경계**가 `group_key` 를 넘었다(시험 경계만 그룹을 지켰다) — 같은 그룹이 폴드 학습 · 검증 양쪽에 | 폴드 경계도 `_group_cut` 으로 자른다. 그룹이 적어 폴드 5개가 안 되면 실패를 보인다. 시험 `test_time_cv5_group_boundary_and_expanding_folds` | `train/split.py` | → D-66 확정 |
| D-W1-08 | 결함 (고침) | `random_60_20_20` · `stratified_60_20_20` 가 `group_key` 를 무시했다 | 그룹 단위로 섞어 행 비율 60/20/20 에 가깝게 자른다(층화는 그룹 다수 라벨별 비율 정렬). `boundaries.group_key` 기록 | `train/split.py` | → D-66 확정 |
| D-W1-09 | 판단 기록 | 층화 분할은 목표값으로 층을 나누는 것이 정의라서, 시험 구간 **라벨**을 바꾸면 분할 자체가 달라진다(누수 시험의 "시험 구간 값을 바꿔도 불변" 이 라벨에는 성립하지 않음) | 누수가 아니라 층화의 성질로 본다(어느 행이 시험인지가 라벨에 달림 — 시험 구간 값이 선정에 들어가는 길은 없다). 층화의 누수 시험은 **변수 값**만 바꾼다. 다른 정책 3개는 라벨 · 변수 둘 다 바꿔도 불변 | `tests/test_train_wave_a.py` | → D-67 확정 (QA3 재확인 권장) |
| D-W1-10 | 요청 개발3 | `tests/fixtures/<회사>/` 에 원천 DB 사본(G-S05 "fixture 원천 DB 행 수 diff 0")이 없다 | `tests/test_source_contract.py` 가 ml_test_db 임시 스키마에 회사 fixture CSV 를 **등록부 `feature_map` · `target_map` 의 테이블 · 열 모양**으로 옮겨 사본을 만든다(이름은 등록부에서 읽음 — 시험 코드에 원천 이름 0). 결합 키(`FX_KEY`) · 시각 열(`FX_AT`)은 사본 정의다(원천 미확인). **요청 개발3**: `migration/make_fixtures.py` 에 익명화 원천 사본(`--kind source_db`, 회사 폴더 안) 생성 — 생기면 시험이 그것을 읽게 바꾼다 | `tests/test_source_contract.py` | → D-68 가설 (우회 중) |
| D-W1-11 | 설계 | 보정된 risk 모델은 `CalibratedModel`(재적합 분류기 + 검증 구간 보정기)로 model.joblib 에 저장된다. 그 클래스를 `mlcore.train` 에 두면 API 가 산출물을 읽을 때 학습 패키지를 import 하게 된다 | `mlcore/data/calibration.py` 에 둔다(`FeatureCoercer` 가 `data/features.py` 에 있는 것과 같은 이유 — G-M06 B). 학습 코드 · fit 호출 없음 | `data/calibration.py` | → D-69 확정 |
| D-W1-12 | 요청 아키텍트 | D-57 의 Makefile 연결 | `worker: ; $(UV) python -m mlcore.train.jobs --pending` · `train: ; $(UV) python -m mlcore.train.jobs --submit $(TENANT) $(TASK)` (접수 → 같은 프로세스에서 run_and_register). CLI 는 실패가 있으면 종료 코드 1, `--test` 는 시험 DB | `Makefile` | → D-70 확정 |

## 7. 웨이브 A — 개발2 가 올린 것 (D-W2-01 ~, 2026-10-12)

| # | 구분 | 내용 | 결정 · 우회 | 한 곳 | 상태 |
|---|---|---|---|---|---|
| D-W2-01 | 설계 (가설) | 호환 라우터(옛 `/api/maintenance/predict` · `/api/quality/predict` · `/api/ml/*` · `/api/data/*`)의 인증 — 원천 6벌은 키 없이 열려 있었다 | 옛 health 꼴만 키 없이, 나머지는 `X-API-Key` + 표준 역할(std/roles.yaml) · 다른 회사 키 404. 오류 모양은 옛 `{"detail": …}`. 키 없는 옛 클라이언트는 401 이 된다 — 열어 두려면 사람이 정한다 | `serve/compat` · `api/routers/compat.py` | → D-59 확정 (사람 결정 2026-10-12) |
| D-W2-02 | 요청 개발3 | 옛 응답 반올림 자리는 회사 값이다(ks 잔여수명 2자리 · sw ΔE 3자리 — 원천 `ml_service.py:127` · `:149`). 코어 상수로 두지 않는다 | `tenants/{ks,sw}.yaml: compat.round: {<옛 키>: <자리>}` 추가 요청 — ks `{remaining_hours: 2, risk_probability: 4}` · sw `{delta_e: 3, risk_probability: 4}`. 없으면 반올림하지 않는다(위험 확률만 기본 4). **이것 하나로 `tests/test_compat.py` 2건 FAIL → G-M04 FAIL**. 선택: `compat.optimize_rename`(표준 예측 · 비용식 이름 → 옛 행 키, 예 ks `{maintenance_cost: cost_index}` · sw `{delta_e: pred_delta_e, defect_risk: risk_probability, process_cost: cost_index}`) | `tenants/*.yaml` | → D-71 확정 |
| D-W2-03 | 계약 불일치 (경미) | 등록부 루트 주입 `MLP_TENANTS_DIR` 해석이 둘이다 — 개발1 `data.jobs.tenants_base_for` 는 `os.pathsep` 목록 중 `<code>.yaml` 이 있는 폴더, 개발3 `registry.tenants.tenants_dir()` 는 값 하나를 그대로 루트로 | 계약(interfaces §10)에 한 규칙으로 적어 달라(아키텍트). 개발2 는 시험에서 with 블록 안에서만 한 폴더를 붙인다(`tests/_dev2.use_tenants_dir`) — 프로세스 전체에 남겼더니 개발3 시험 24건이 FileNotFound 로 깨졌다(고침) | `contracts/interfaces.md` §10 | → D-65 확정 |
| D-W2-04 | 계약 해석 | optimize 의 허용 상태는 `needs_approval` · `review` 뿐이라, 고정 입력이 학습 범위 밖이면 `out_of_range` 를 낼 수 없다 | 경고 `out_of_range`(field = 고정 변수) + `out_of_range_fields` + status `review`(사람 검토). 숨기지 않는다 | `tasks/optimize.py` | → D-72 확정 |
| D-W2-05 | 설계 | 추천의 승인 경로 — 계약은 "mlp_recommendation 에 needs_approval" 까지만 적었다 | optimize 1회 = `mlp_recommendation`(needs_approval) + `mlp_approval`(kind=recommendation, action=apply, pending) 한 트랜잭션. `approval.decide()` 가 추천 승인 · 반려 시 `mlp_recommendation.status` 만 바꾼다(approved · rejected) — 설비 · MES 쓰기 0, production 불변. 만료(expires_at)는 두지 않았다(미정) | `tasks/optimize.py` · `approval/__init__.py` | → D-73 가설 |
| D-W2-06 | 설계 | 승인 카드의 "그림자 예측 차이"(screen-map 5) 근거 데이터 | `request_promotion` 이 최근 운영 입력(`mlp_prediction.inputs`, 최대 200건, rejected 제외)을 대상 버전 · 현재 production 으로 같이 채점한 `{n, mean_abs_diff, max_abs_diff, basis}` 를 `evidence.shadow` 에 둔다. 시험 구간 미사용. 운영 입력 · production 이 없으면 null, 산출물 오류는 `{error}` 로 보인다 | `registry/models.py` | → D-74 확정 |
| D-W2-07 | 설계 | 모르는 입력 키의 `detail.field` — 키 이름도 요청자가 보낸 문자열이다 | 변수 이름 꼴(`^[a-z][a-z0-9_]{0,63}$`)이면 field 로 알려 주고, 아니면 null(임의 문자열 반사 0) | `serve/validate.py` | → D-75 확정 |
| D-W2-08 | 보류 | 화면 2 · 3 의 1024px 가로 스크롤 0 은 CSS(줄바꿈 · auto-fit 격자)로만 맞췄고 `tests/e2e/`(Playwright) 는 없다 — D-40 의존성 미설치 | G-S03 은 `tests/e2e/ 없음` 으로 FAIL 그대로. QA3 · 개발2 가 `@playwright/test` 정확한 버전을 넣는 것은 다음 회전 | `web/` · `tests/e2e/` | → D-40 확정 (e2e 있음) |
| D-W2-09 | 보류 | 호환 `/api/data/records` 는 운영(regression) 모델 스냅숏 + risk 스냅숏 목표를 entity_id 로 붙여 옛 행을 만든다(개발3 B12 records 와 다른 경로) | B12(`api/routers/ops.py`)가 생겼으니 다음 회전에 B12 의 행 함수를 쓰도록 바꾼다. 행 수 · 정렬 · 페이지는 원천과 같다(시험) | `serve/compat` | → D-81 가설 (개발2 후속) |

## 8. 웨이브 A — 개발3 이 올린 것 (임시 번호 `D-W3-nn` — 아키텍트가 D-번호로 정리)

| # | 구분 | 내용 | 개발3 처리 · 요청 | 한 곳 | 상태 |
|---|---|---|---|---|---|
| D-W3-01 | 계약 보강 요청 | 원천 sw 최적화는 추천 조건이 이상 탐지에 걸리면 "시험 인쇄로 먼저 확인" 경고를 붙였다(`SongWol ML AI/api/ml_service.py` optimize). 계약 `task-contract.md` §2 optimize `uses` 는 regression(예측값) · risk(확률)만 정의하고 anomaly 과제 값을 정의하지 않아 옮기지 못했다 | 지금은 미이관(이관 보고서 §4 · task-map SW-E4 에 적음). 제안: optimize 선택 키 `warn_with: [<pack>.<anomaly 과제>]` — 후보마다 그 과제 production 모델의 flag 를 `warnings` 에 넣는다(제약 · 목적에는 안 씀). 정하면 개발2 `tasks/optimize.py` · 개발3 `print_setpoint.yaml` | `task-contract.md` §2 | → D-76 확정 (계약) · 구현 후속 |
| D-W3-02 | 계약 불일치 | interfaces §9 "재학습 후보 → `registry.request_promotion`" 인데 `request_promotion` 은 staging 버전만 받는다(등록부 전이 규칙 `from_staging_only`). 감시가 만든 candidate 를 바로 승인 요청할 길이 없다 | 개발3 `monitor/retrain.py::request_approvals` 가 **기준선을 이긴 후보만** `Registry.stage(actor="monitor")`(감사 기록) → `request_promotion(action=promote, actor="monitor")`. 기준선 미달은 candidate 로 둔다. production 은 사람이 `approval.decide()` 로만(G-M09 시험 · check_no_autopromote 1/0). 아키텍트 확인: 감시의 staging 허용(계약 문구) 또는 `request_promotion` 이 candidate 를 받게 할지 | `interfaces.md` §9 · `monitor/retrain.py` | → D-77 확정 |
| D-W3-03 | 계약 보강 요청 | 등록부 루트 덮어쓰기 `MLP_TENANTS_DIR` 가 계약에 없다(개발1 D-W1-06 과 같은 변수) | 규칙 하나로 맞췄다: `os.pathsep` 목록 · 회사 파일이 있는 첫 폴더, 없으면 저장소 `tenants/`(`registry.tenants.tenant_base` = `data.jobs.tenants_base_for`). 새 회사 생성 · 회사 목록(`all_codes`, seed)은 목록의 **첫 폴더**(없으면 `tenants/`). D-W1-06 의 개발3 몫은 고쳤다(개발2 `_dev2.use_tenants_dir` 되돌리기는 개발2 몫). `tenant-contract.md` 에 한 줄 필요 | `registry/tenants.py` · `tenant-contract.md` | → D-65 확정 |
| D-W3-04 | 계약 보강 요청 | API 응답의 덧붙인 키 — `doctor.sources[]` 에 `targets`(과제별) · `unmapped`(정적 대응 밖 변수), 응답에 `mode` · `warnings` / `monitor` 에 `total` · `last_day` · `retrain_candidates`(화면 6 "재학습 후보 링크") · `?metric=` 거르기 / `tasks` 목록에 `tenant` · `disabled` · 항목 `production` · `uses` / `overview` 에 `title` · `model_ready` · `uses` · `pending_approvals` · `monitor.day` · `monitor.note` | 계약 키는 전부 그대로 두고 덧붙이기만 했다. api-contract §4 에 적어 주거나 빼라고 정해 주면 따른다 | `api/routers/ops.py` | → D-78 확정 |
| D-W3-05 | 설계 | PSI 세부 규칙(interfaces §9 는 "10분위 · 0 빈도 1e-6 바닥" 만): 경계 = 기대 분포 10분위(numpy 선형 보간, 결측 제외, 중복 경계 제거) · 구간 (a, b] (값 = 경계면 아래) · 비율 바닥 1e-6 후 **재정규화하지 않음** · 결측은 PSI 에서 빼고 결측률(기대 대비 %p)로 따로 · 운영 값이 0건이면 nan(0 으로 꾸미지 않음). 기대 분포 = production 모델의 학습 스냅숏 전체, 범위 밖 판정 = 산출물 `features.lock.json` p1/p99(serve 와 같은 학습 범위) | `monitor/stats.py` 머리말 · `psi_hand.json` 이 같은 규칙의 순수 파이썬 손 계산 | `monitor/stats.py` | → D-79 확정 |
| D-W3-06 | 설계 | 감시 재학습의 소스: 같은 소스(같은 스냅숏)로 다시 접수하면 학습이 멱등이라 새 후보가 없다 | `run_daily(retrain_source=)` · 스케줄러 `--retrain-source` 로 재학습 소스 역할을 고른다(기본 = 회사 mode). 같은 스냅숏이면 run_id 가 재사용되고 새 candidate 가 없다 — 지어내지 않는다. 회사별 기본 재학습 소스를 등록부 키로 둘지(`monitor.retrain_source`)는 아키텍트 | `monitor/daily.py` | → D-80 가설 |
| D-W3-07 | 요청 아키텍트 | Makefile 연결(개발3 대상) | `doctor: ; $(UV) python -m mlcore.monitor.doctor --tenant $(TENANT)` · `tenant: ; $(UV) python migration/make_tenant.py --new $(NEW) --pack $(PACK) $(if $(CSV),--csv $(CSV))` · (선택) `monitor: ; $(UV) python -m mlcore.monitor.scheduler --tenant $(TENANT)` | `Makefile` | → D-70 확정 |
| D-W3-08 | 판단 기록 | G-M12 "6벌 demo_data() 와 팩 synth/ 행 일치 100%" — 원천 실행 금지라 원천 행을 직접 만들어 비교할 수 없다 | 간접 판정: RNG 호출 순서 줄 단위 이관 + 원천 문서 통계(행 · 결측 · 중복 · 범위 밖 · 불량률 · 필터 건수) + 같은 시드 학습 지표 자리수 일치(ks 11값 · sw 5값, sw 불량 3값 ≤ 0.0013 — D-52). `docs/migration-report.md` §3. 사람이 원천을 돌려 직접 대조하면 더 강하다 | `docs/migration-report.md` | → D-82 가설 (사람 확인 권장) |

## 9. 웨이브 A 결정 정리 — D-W1 · D-W2 · D-W3 → D-59 ~ D-84 (아키텍트, 2026-10-12, 기준 커밋 be24075)

> 임시 번호를 D-번호로 옮겼다(D-59 는 개발2 코드 주석이 이미 쓰던 번호라 D-W2-01 에 그대로 준다). 계약 반영 = 고친 계약 파일.
> **개발자 소유 파일을 고친 기록(goal §3.2):** `api/routers/models.py`(개발2) `models` 항목에 `run_id` 1키 추가 — D-63 · `serve/training.py`(개발2) failed 재접수를 `reused` 로 보지 않음 — D-64. 새 파일 `tests/e2e/*`(D-40 은 QA3 · 개발2 몫이었으나 이번 회전 아키텍트가 만듦) · `tests/test_architect_followups.py`(D-63 · D-64 시험). 그 밖의 개발자 파일은 고치지 않았다.

| # | 원래 | 결정 | 계약 반영 | 상태 |
|---|---|---|---|---|
| D-59 | D-W2-01 | 호환 경로도 API 키 요구(옛 health 만 키 없이) · 다른 회사 404 · 옛 오류 모양. **사람 결정(2026-10-12, 오케스트레이터 전달)** — 현재 코드 동작 그대로, 코드 변경 0. 이슈 #6 의 4번 항목 해소 | `api-contract.md` §5 | 확정 |
| D-60 | D-W1-01 | 과제 선택 키 `outlier` · `candidate_search` 채택. 둘 다 기본 꺼짐(G-M12 보존), 이상치 경계는 학습 구간에서만, 탐색은 검증 지표만 · 시드 = 과제 seed | `task-contract.md` §1 | 확정 |
| D-61 | D-W1-02 | 시계열 regression 기준선 = 검증 구간에서 더 나은 쪽(train_mean · last_value, 동률 train_mean) — 더 강한 기준선 · 시험 구간 미사용 | `task-contract.md` §2 | 확정 |
| D-62 | D-W1-03 | 어댑터 등록부 키(gateway · mes · dataplatform)는 `progress-dev1.md` §1.2 공표대로 받는다. 값(원천 열 · 결합 키 · 뷰)은 D-32 · D-33 확인 전까지 등록부에 적지 않는다. dataplatform 기본 경로 `/v1/readings` 는 가설 | `progress-dev1.md` §1.2 (tenant-contract 는 실연결 때) | 확정 (경로 가설) |
| D-63 | D-W1-04 | `GET /runs/{id}` 덧붙임 키 · `models` 항목 `run_id` — 화면 4 가 버전 → 실행으로 간다. B08 은 be24075 에서 붙었다 | `api-contract.md` §4 | 확정 |
| D-64 | D-W1-05 | failed 재접수 = queued 로 되돌림 + 감사 `train.retry`(개발1). API 는 그때 202(재사용 아님) — `serve/training.py` 1줄 수정 · 시험 `tests/test_architect_followups.py` | `api-contract.md` §4 | 확정 |
| D-65 | D-W1-06 · D-W2-03 · D-W3-03 | `MLP_TENANTS_DIR` 한 규칙: `os.pathsep` 목록 · 회사 파일이 있는 첫 폴더 · 없으면 `tenants/`, 생성 · 목록은 첫 폴더. 실측: `registry.tenants.tenant_base` = `data.jobs.tenants_base_for` 같은 규칙, `tests/_dev2.use_tenants_dir` 는 `__exit__` 에서 이전 값 복원(없으면 pop) — 전체 pytest 한 세션 통과. **이슈 #5 닫을 수 있음** | `interfaces.md` §10 · `tenant-contract.md` T5 | 확정 |
| D-66 | D-W1-07 · 08 | 분할 결함 2건(폴드 경계 · 무작위/층화의 group_key) 고침 확인 | — | 확정 |
| D-67 | D-W1-09 | 층화 분할은 정의상 라벨에 따라 시험 행이 바뀐다 — 선정에 시험 값이 들어가는 길이 없으므로 누수 아님. 층화 누수 시험은 변수 값만 바꾼다 | — | 확정 (QA3 재확인 권장) |
| D-68 | D-W1-10 | 원천 DB 사본: 개발3 이 `tests/fixtures/{ks,sw}/source_db.sql` 제공. `test_source_contract.py` 는 아직 자체 사본(등록부 모양) — 개발1 이 그 파일을 읽게 바꾸면 확정 | — | 가설 (우회 중) |
| D-69 | D-W1-11 | `CalibratedModel` 은 `data/calibration.py`(API 가 학습 패키지를 import 하지 않게) | — | 확정 |
| D-70 | D-W1-12 · D-W3-07 | Makefile `train`(`--submit`) · `worker`(`--pending`) · `doctor` · `tenant`(`CSV=`) · `monitor`(`--once`) · `bench` · `e2e` · `image` · `compose-config` 연결 | `Makefile` | 확정 |
| D-71 | D-W2-02 | 옛 응답 반올림은 회사 값 `compat.round`(+ 선택 `compat.optimize_rename`). be24075 에서 ks · sw 기입 | `tenant-contract.md` §1 · `api-contract.md` §5 | 확정 |
| D-72 | D-W2-04 | optimize 고정 입력 범위 밖 → 경고 `out_of_range` + `out_of_range_fields` + status `review` | `task-contract.md` §2 | 확정 |
| D-73 | D-W2-05 | 추천 승인: optimize 1회 = `mlp_recommendation`(needs_approval) + `mlp_approval`(kind=recommendation) 한 트랜잭션, decide 는 추천 상태만 바꾼다(설비 · MES · production 0). **만료(expires_at) 규칙 미정** | — | 가설 |
| D-74 | D-W2-06 | 승인 카드 그림자 예측 차이 = 최근 운영 입력(≤ 200, rejected 제외)을 대상 · 현 production 으로 함께 채점. 시험 구간 미사용 | — | 확정 |
| D-75 | D-W2-07 | 모르는 입력 키 `detail.field` 는 변수 이름 꼴일 때만 | — | 확정 |
| D-76 | D-W3-01 | optimize 선택 키 `warn_with: [<pack>.<anomaly 과제>]` — 후보별 anomaly flag 를 경고로만(목적 · 제약 · 순위 불사용). **구현 후속:** 개발2 `tasks/optimize.py` · 개발3 `print_setpoint.yaml` · task-schema 허용 키 | `task-contract.md` §2 | 확정 (계약) |
| D-77 | D-W3-02 | 감시의 stage 행위자 허용: 기준선을 이긴 candidate 만 `stage(actor="monitor", role="system")` → `request_promotion(actor="monitor")`. `request_promotion` 은 계속 staging 만 받는다(규칙을 넓히지 않음). production 은 decide 만 — `check_no_autopromote` 에 decide 호출처 1곳 검사 추가 | `interfaces.md` §9 | 확정 |
| D-78 | D-W3-04 | API 응답 덧붙임 키(doctor · monitor · tasks · overview) 를 계약에 올린다. 계약 키는 전부 필수 그대로 | `api-contract.md` §4 | 확정 |
| D-79 | D-W3-05 | PSI 세부 규칙(10분위 · (a,b] · 1e-6 바닥 · 재정규화 안 함 · 결측 따로 · 0건 nan) — 손 계산 fixture 와 일치 | `interfaces.md` §9 | 확정 |
| D-80 | D-W3-06 | 감시 재학습 소스 기본 = 회사 mode, `--retrain-source` 로 바꿈. 등록부 키 `monitor.retrain_source` 는 만들지 않는다(실연결 전) | `interfaces.md` §9 | 가설 |
| D-81 | D-W2-09 | 호환 `/api/data/records` 를 B12 행 함수로 바꾸기 — 개발2 다음 회전 | — | 가설 |
| D-82 | D-W3-08 | G-M12 행 일치는 간접 판정(RNG 순서 · 원천 문서 통계 · 지표 자리수) — 원천 실행 금지 | — | 가설 (사람 확인 권장) |
| D-83 | 아키텍트 (G-M11) | 배포: `docker-compose.yml`(app + db) · `docker/Dockerfile`(node 24.18.1 → uv 0.12.1 → python 3.12.13-slim, `uv sync --frozen`). DB 포트 없음 · 앱 포트 `127.0.0.1:8200` 하나(밖은 HTTPS 프록시 — spec §17) · 헬스체크 app · db · app 768m · cpus 1 · OMP 1 · 이미지 `mlp-app:${MLP_GIT_SHA:?}`(기본값 없음 — 없으면 config 실패) · 비밀은 `.env.deploy`(커밋 금지 · 틀 `docker/deploy.env.example`, 로컬 `.env` 와 분리 — 설정 로더가 `.env` 를 읽기 때문) 참조만 · 스키마는 db initdb, 시드는 사람이 1회. 이미지 빌드 1회 성공(`mlp-app:be24075`, 작업 트리 기준 — 커밋 전 변경 포함). `check_deploy` = `docker compose config` 정규화 결과 검사, docker CLI 없으면 YAML 정적 파싱(실측란에 표시) | `docker-compose.yml` · `docker/Dockerfile` · `gates/check_deploy.py` | 확정 |
| D-84 | 아키텍트 (G-M14) | `make bench` = `gates/bench.py`: docker 데몬이 있으면 **같은 compose 파일의 제한 아래**(cgroup memory.max 805306368 = 768MB · cpu.max 100000/100000 = CPU 1 실측 확인) 임시 프로젝트 `mlpbench-<회사>` 로 띄워 컨테이너 안에서 학습 · 승인 → 호스트에서 잰다. 데몬이 없으면 로컬 uvicorn 1 프로세스로 재고 실측란에 **"compose 제한 아래 측정 아님"** 을 적는다 — 판정 기준(200ms · 3s · 15s · 768MB)은 같고 WARN 으로 낮추지 않는다. 기동 = 프로세스 시작 → health 200 · model_ready → 과제 전부 첫 예측(적재 · 해시 대조)까지(더 엄격). 필수 결측 행은 422 가 정상이라 지연 표본에서 뺀다 | `gates/bench.py` · `gates/gate.py` | 확정 |
