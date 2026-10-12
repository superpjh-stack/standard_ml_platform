# progress.md — 검증된 현황의 유일한 진실

## 2차 — 웨이브 P 재진입 (아키텍트, 2026-10-13, 기준 커밋 780e960 · 태그 core-freeze-2 = 5a51d2f) — 다음: 오케스트레이터 `core-freeze-2` 재태그

### 지금 해야 할 것

1. **오케스트레이터:** 이 커밋에 `core-freeze-2` 를 재태그(로컬, 메시지에 `retag` — 사유 decisions D2-70). 그 뒤 G2-C01 이 PASS 로 돌아온다(지금 FAIL = 옛 태그 대비 코어 diff, 정상).
2. 재태그 뒤 `make gate2` 1회로 PASS 39 · BLOCKED 2 확인 → 웨이브 B2(QA 3) 로.
3. 이슈 #24(코어 결함 4건) · #23(D2-02 문구 · 기준선 확인) 닫기 — 이 커밋에서 해결.
4. 사람 확인 대기(그대로): D-27 · D-30 · D-32 · D-33 · D-04 · D-82 · D-130 · D2-07a · D2-16 · D2-17 · D2-60 · 옛 시험 DB `ml_grants_check_db` 삭제(D2-35).

### 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| D2-A2-01 견적 CSV | `to_csv` 과제 `csv` = 품목 열 순서 · 요약(합계 · 구성 금액) 늘 전부 — strict xfail 걷음 → PASS | `tests/test_vertical_slice_2.py::test_kd_quote_csv_has_total` · `tests/test_reentry_p.py` |
| D2-A2-03 견적 입력 | 과제 `input_limits` — kd 수량 0 · 1.5 · 1001 · 시간 단가 0 · 1,000,001 · 외주비 −1 → 422 · ot 수량 0 · 1.5 · 10001 · −3 → 422 · 경계값 201 | `tests/test_kd_quote_flow.py` · `tests/test_ot_quote_flow.py` · `tests/test_reentry_p.py`(로더 모양 11) |
| D2-A2-02 호환 최적화 | `Compat.optimize_fixed` → pc · krs `/api/ml/optimize`(옛 키 · 기본값 · 422 · 예측 행 0 증가 · 표준 best 와 같은 값) | `tests/test_compat.py::test_{pc,krs}_optimize_fixed_only_old_shape` |
| D2-A2-05 호환 기록 | `parse_records` · `records_frame` → krs supplier · q · state · summary · 기본 20 / pc 기본 25 · 검색 30자 | `tests/test_compat.py` krs · pc records |
| D2-A2-04 예시 파일 | `tenants/<code>/samples/` 먼저 → kd sample.dxf · demo(영역 3 · BOM 4 · 650 kg) · ot `/api/data/demo`(20 · 20, 원본 이름 '비공개') · `pending_routes` 4사 전부 `{}` | `tests/test_compat_phase2.py` · `tests/test_compat.py` · `migration/make_tenant_samples.py --check` |
| D2-63 허브 | extract `model.features` · `model.target` · quote `inputs`(변수만) 내보냄 · 모델 extract state | `tests/test_export_hub.py`(13) |
| 정리 | #23 kimchi `time_cv5` 문구 · solder · rollform-quote 기준선 재현 일치(D2-71) · G2-S01 에 ot e2e · bench 프로젝트 고유 접미(D2-72) | `migration/reproduce.py --phase2` · `migration/reproduce_quote.py` |
| pytest | **980 passed · 3 skipped · 0 failed · xfail 0** | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| e2e | **23 passed** | `uv run pytest -q tests/e2e` |
| make gate | **PASS 23 · BLOCKED 1**(G-M08 doctor-live D-13) | `make gate` |
| make gate2 | 41행 **PASS 38 · FAIL 1 · BLOCKED 2** — FAIL = G2-C01(옛 태그 대비 동결 경로 177줄 — 재태그 대기, 정상) · BLOCKED = G-M08 · G2-L01(D-13). C01 밖 FAIL 0 | `make gate2` |


## 2차 — 웨이브 P 마감 · 동결 준비 (아키텍트, 2026-10-13, 기준 커밋 21a39bc) — 다음: 오케스트레이터 `git tag core-freeze-2`

### 지금 해야 할 것

1. **오케스트레이터:** 이 커밋에 `core-freeze-2` 태그(로컬). 그 뒤 `src/mlcore` · `web/src/components` · `std` · `contracts` 0줄(G2-C01).
2. **웨이브 A0-2:** `tests/test_vertical_slice_2.py`(G2-V01) — `kd.quote`(이제 켜짐 · `tests/test_kd_quote_flow.py` 가 업로드 → 견적 초안까지 확인) · `pc.residual_review`.
3. **웨이브 A2:** 팩 `solder` · `rollform-quote` · kimchi `recipe_optimize` · 회사 `krs` · `ot` · task-map 6사 · 이관 보고서 — 코어 장치는 `docs/freeze-readiness.md` 표대로(derived · input_rules · scale · optional · rate_tables · synth.tasks · extractor params/context/replaces · 호환 객체 경로 + `tenants/<code>/compat.py`). 모자라면 고치지 말고 `코어 결함(2차)`.
4. 사람 확인 대기(그대로) + 오케스트레이터 허락 대기: 옛 시험 DB `ml_grants_check_db` 삭제(D2-35).

### 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| D2-31 | G-M01 std 어휘 규칙(과제 이름 = 자기 유형만 면제 · 다른 겹침은 팩 FAIL) → `eto.quote` · `kd.quote` 켬 · G-M01 PASS(코어 116 · 팩 56 파일, std 어휘 과제 이름 1 `quote`) | `uv run python gates/check_core_terms.py` · `tests/test_freeze_readiness.py` |
| 개발자 간 요청 | 추출기 context · 주석 '평창식' 0 · live_perf macro_f1 · doctor learn_view · test_split 항목 version · rule · threshold(일정 작업) · 과제 상세 2차 키 · `live_pairs → from_live`(이미 연결 — 확인) · channel `quote` · `model.target` 확정 · `Purpose queue_scoring` | `tests/test_kd_quote_flow.py` 4 · `test_monitor_extract_live.py` 2 · `test_monitor_review.py` 9 |
| A2 대비 | 모자랐던 코어 기능 8묶음 넣음(D2-45) — 표 `docs/freeze-readiness.md` | `tests/test_optimize_phase2.py` 22 · `test_compat_phase2.py` · `test_freeze_readiness.py` 15 |
| 계약 | api-contract §1 묶음 15 단계 1(B09~B11 11행 합침) · screen-map 7~10 ○ · D2-30 task-schema 표 · D2-33 부분 고유 색인(비파괴, 두 DB) · D2-39 기준선(eto MAE 3.7017 · kimchi MAE 1.5375 · queue_size 3) · F7-5 | `make db-migrate` 2회(멱등) · `gates/check_schema.py` PASS(열 211) |
| 간헐 실패 | 원인 = bench compose 가 호스트 8200 고정(개발 서버 · 남은 `mlpbench-*` 가 쥐면 `up` FAIL → finally 가 치워 다음 PASS). 재현(8200 점유 → FAIL) → 빈 루프백 포트 + 잔여 정리 + 측정 전 build → 8200 점유 상태로 PASS (D2-46) | `gates/bench.py --compose` |
| pytest | **843 passed · 3 skipped · 0 failed** (1 실패 = 팩 baselines 주석의 회사 코드 — 고친 뒤 재실행 통과) | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| e2e | **22 passed** (화면 1~10 · 1024px 가로 스크롤 0) | `uv run pytest -q tests/e2e` |
| make gate | **5회 연속 PASS 23 · BLOCKED 1** (각 137~138 s) | `make gate` ×5 |
| make gate2 | 1차 24행 PASS 23 · BLOCKED 1 · **G2-T01 · G2-R01 · G2-E01 · G2-Q01 · G2-S01 · G2-A01 · G2-I01 · G2-I02 · G2-H01 PASS** · FAIL = G2-C01(태그 전) · G2-V01(A0-2) · G2-P01 · 6사 4행(A2: solder · rollform-quote · krs · ot) · BLOCKED G2-L01(D-13) — 합계 41행 PASS 32 · FAIL 7 · BLOCKED 2 | `make gate2` |


## 2차 — Phase P0 (아키텍트, 2026-10-13, 기준 커밋 40a67c7) — 판정 기준 `goal2.md`, 명령 `make gate2`

### 지금 해야 할 것 (웨이브 P — 코어 확장, 개발 3 병렬 · 끝에 `core-freeze-2`)

1. **웨이브 P 시작.** 판정은 `make gate2`. 1차 게이트는 지금 PASS 23 · BLOCKED 1 — 웨이브 P 내내 유지. 웨이브 P 의 끝 = 1차 게이트 전부 + G2-T01 · G2-R01 · G2-H01 PASS → 오케스트레이터가 `git tag core-freeze-2`(로컬).
2. **개발1 (데이터 · 학습 / 화면 7):** `review_queue` 잔차 계산(guard 경유 — `test_split` 은 `final_eval` 결과만, top_quantile 임계값은 검증 잔차 분위, task-contract §6.1) · `extract` 모델 기반 추출기 학습(층화 · macro-F1 선정 · `majority_class` 기준선 · 라벨 없으면 지표 null) · F13-1(DEF-QA1-006 다른 문법 6종 — check_leakage 는 아키텍트와) · 화면 7 `web/src/screens/Sources.tsx` · 시험 `tests/test_review_queue.py`(G2-R01 — 평창식 전체 재적합 채점 픽스처 거부 포함).
3. **개발2 (추론 · API / 화면 8 · 9 · 10 · 공용 부품):** B09 · B10 · B11 (api-contract §6 — 업로드 상한 · `invalid_document` · `document_too_large` · `quote_locked` · 확정 = 승인 경유 D2-19) · 추출기 인터페이스(task-contract §6.2 → `interfaces.md` 공표) · `quote` 흐름(Decimal 만 · overrides 누적 · 스냅숏 · 금액 문자열 · CSV) · Agent 어댑터 `mlcore/integrations/agent_tools.py` 4 도구(agent-tools.md) · optimize `request_approval` · trace `?view=explain` · 2차 유형 predict 404 `type_route` · 열린 #16 · #19 · #20 항목(F7-4 · F7-11 · F7-12 · F16-8 · F16-9 · F19-3 · F20-1 · F20-2 · F20-5) · 화면 8 · 9 · 10 + `web/src/components/` 문서 뷰어 · 금액 표 · 시험 `tests/test_types_phase2.py` · `test_extract.py` · `test_quote.py` · `test_agent_tools.py`.
4. **개발3 (팩 · 회사 · 감시 · 이관):** 로더가 유형 3 키 검사(`search` 검사는 optimize 만 · `material_aliases`) · 대기열 일정 작업(감시 뒤 `live_residual`) · `make export-hub`(hub-export.md) + `tests/test_export_hub.py` · F7-7 D-123 compose 앱 계정 · F7-8 시험 DB 정리 · F20-4 덮어쓰기 모르는 키 · (A0-2 준비) 팩 `eto` · `kimchi` 최소분.
5. **아키텍트 (웨이브 P 중):** D2-13 열 추가(schema.sql + db-schema §2 + 비파괴 ALTER) · D2-15 std 6건 · 웨이브 P 끝에 api-contract §1 B09~B11 단계 1 · screen-map 7~10 `○` · F7-5 `make image` · F20-3 CONFIRM 명령줄 인자만 · F13-1 check_leakage.
6. 사람 확인 대기(그대로): D-27 · D-30 · D-32 · D-33 · D-04 · D-82 · D-130 + 새 D2-07a(반올림 차이 처리) · D2-16(Agent 팀) · D2-17(허브 팀).

### P0 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 원천 조사 4사 | krs 엔드포인트 7(+SPA) · 화면 3 · 시험 6/6 · 후보 5 · 무작위 5,000 · \|잔차\| ≥ 4 / pc 6(+nginx) · 4 · 4/4 · 3 · 무작위 3,500 · 상위 10% / ot 11(+/) · 4 · 11/26 · 4+3 · Decimal 견적 · 객체 1,600 / kd 11(+/) · 4 · 10/21 · 4 · 영역 3종 + BOM 텍스트 · float `round` 견적 | `migration/source_inventory.md` §7~§13 (파일:줄) |
| 원천 보고 지표 | kd Ridge 시험 MAE 4.1071 · RMSE 5.0456 · R² 0.9956 · 샘플 견적 8,486,493원(58.146 h) / krs · pc · ot **기록 없음**(D2-12) · ot 저장 견적 726,487원 | `KyungDong ML AI/docs/verification.md:23,29` · 원천 SQLite 읽기 전용 |
| task-map 분모 | **6개사 100** = 1차 32(ks 16 · sw 16) + krs 14 · pc 14 · ot 20 · kd 20 | `gates/check_task_cover.py` `units("phase2")` = 100 |
| 계약 | task(§6 유형 3 키 + task-schema 블록) · predict(§8 스키마 3) · api(§6 경로 11 · 오류 8) · screen-map(7~10 소유자 · 필수 요소) · db-schema(§6 — 16 테이블 충분 · 열 추가 요청 D2-13) · tenant(§3 회사 4) · pack(§6 팩 4) · **새** agent-tools · hub-export | `contracts/*.md` · JSON Schema 5 블록 `Draft202012Validator.check_schema` 통과 |
| 게이트 | 새 `check_core_freeze` · `check_decimal` · `check_followups` · `gate2.py` · `check_contract.run_phase2` · `check_migration.run_phase2` · `check_registry/check_tasks/check_task_cover(scope)` · gatelib 등록부 목록 | `make gate2` |
| 1차 잔여 고정 목록 | 33 항목(해결 18 · 열림 15) | `docs/followups.md` ← `gh issue view 7 13 16 19 20` |
| 시험 | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` **459 passed · 3 skipped** (1차와 같음) | 이번 회전 |
| make gate | **PASS 23 · BLOCKED 1** (유지) | `make gate` |

### make gate2 판정표 (P0 — 원문)

```
## 1차 게이트 (gates/gate.py — 1차 기대값)
G-V01   수직 관통             PASS     tests/test_vertical_slice.py: 2 passed, 1 warning in 3.44s
G-S01   스키마               PASS     테이블 16 = spec 16 = 계약 16 = DB(ml_db 16 · ml_test_db 16) · 열 191 일치 · tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부
G-S02   팩·등록부 로드          PASS     팩 3 (_template(2) · press(4) · textile(4)) · 회사 3 로드 · 켜진 과제 8 · 불량 픽스처 5/5 거부(R4=과제 끄기 · 실기동 경로 tests/test_r4_live_path.py, D-27 · D-120)
G-S03   화면                PASS     화면 6/6 /app 200 · _placeholder 0 · e2e(ks·sw, 1024px 화면 2·3 가로 스크롤 0 · 폼=features.yaml) tests/e2e/test_console.py: 8 passed, 1 warning in 13.60s
G-S04   API               PASS     1차 12/12 · 2차 501 3/3 · tests/test_api_contract.py: 38 passed, 1 warning in 1.25s
G-S05   읽기 전용 소스          PASS     어댑터 5/5 · 정적 위반 0 · tests/test_source_contract.py: 18 passed, 1 warning in 1.09s
G-S06   비밀값               PASS     추적 파일 482 · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 9개(값 0)
G-S06   회사 격리             PASS     회사 2 · 회사 파일 10개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0
G-S07   의존성 고정            PASS     uv.lock · package-lock.json 있음 · Python 16개 == 고정 · JS 8개 정확 버전 · Python 3.12 하나
G-M01   코어 순수성            PASS     코어 95파일 · 팩 34파일 위반 0 (금지어 팩 30 · 회사 9 · 테이블 9 · 범주값 10)
G-M02   과제 대응             PASS     대응 32/32 (ks 16 · sw 16) · 미대응 0
G-M03   과제 정의             PASS     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 7/7 거부 · synth · baselines 있음
G-M04   예측 계약             PASS     A 스키마 자체 시험 91/91 · B tests/test_predict_contract.py: 27 passed, 6 warnings in 5.96s · C tests/test_compat.py: 35 passed, 3 skipped, 3 warnings in 7.50s
G-M05   누수 없는 평가          PASS     A 래퍼 자체 시험 20/20 · B 정적 위반 0 · C/D tests/test_split.py: 20 passed, 2 warnings in 3.37s
G-M06   재현·등록부            PASS     A tests/test_determinism.py: 9 passed, 4 warnings in 5.89s · B 기동 경로 학습 코드 0건 · C tests/test_registry.py: 13 passed, 1 warning in 1.86s
G-M07   예측 추적             PASS     tests/test_trace.py: 9 passed, 1 warning in 1.68s
G-M08   소스·doctor         PASS     tests/test_doctor.py: 9 passed in 0.69s
G-M08   doctor-live       BLOCKED  실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)
G-M09   감시·승인             PASS     production 쓰기 경로 1 (decide 안 1 · 밖 0) · decide 호출처 1 (models.py 1) · tests/test_approval.py: 14 passed, 1 warning in 1.98s · tests/test_monitor.py: 15 passed in 2.68s
G-M10   새 회사              PASS     tests/test_new_tenant.py: 3 passed, 3 warnings in 1.75s
G-M11   보안·배포             PASS     docker compose config(MLP_GIT_SHA=40a67c7): 서비스 app·db · DB 포트 0 · 앱 포트 1(8200) · 헬스체크 2/2 · 768MB·CPU 1 · OMP 1 · 태그=SHA 필수 변수 · 비밀 env_file 만 · Dockerfile 3단계 [node:24.18.1-bookworm-slim → ghcr.io/astral-sh/uv:0.12.1 → python:3.12.13-slim-bookworm] · tests/test_auth.py: 18 passed, 1 warning in 1.38s
G-M12   이관 대조             PASS     과제 8 대조 · 행 일치 100%
G-M13   최적화               PASS     tests/test_optimize.py: 11 passed, 2 warnings in 3.54s
G-M14   비기능               PASS     최악값(ks·sw 과제 6) 단건 p95 34.0ms(≤200) · batch500 0.334s(≤3) · 기동 1.725s(≤15) · RSS 249.3MB(≤768) — docker compose 제한 아래(app 768MB · CPU 1 · OMP_NUM_THREADS=1, 이미지 = 커밋 SHA)
소계 24행 — PASS 23 · BLOCKED 1

## 1차 게이트 · 6개사로 넓힌 판정 (goal2 §2 머리말)
G-S02   팩·등록부(6사)         FAIL     2건: 팩 없음 ['eto', 'kimchi', 'rollform-quote', 'solder']; 회사 없음 ['kd', 'krs', 'ot', 'pc']
G-M03   과제 정의(6사)         FAIL     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 7/7 거부 · 위반 1: 팩 없음 ['eto', 'kimchi', 'rollform-quote', 'solder']
G-M02   과제 대응(6사)         FAIL     대응 32/100 · 미대응 68 ['KD-C1', 'KD-E1', 'KD-E10', 'KD-E11', 'KD-E12', 'KD-E2']
G-M12   이관 대조(6사)         FAIL     합성 생성기 없음 ['solder', 'kimchi', 'rollform-quote', 'eto']; 과제 행 없음 12/20 (krs.joint_strength, krs.recipe_optimize, krs.residual_review …)
소계 4행 — FAIL 4

## 2차 게이트 G2-*
G2-C01  코어 동결             FAIL     태그 전 — `core-freeze-2` 없음(HEAD 40a67c7). 판정 대상 없음: 웨이브 P(유형 3 · B09~B11 · 화면 7~10 공용부 · 연동 · 1차 잔여)가 끝나고 1차 게이트 + G2-T01 · G2-R01 · G2-H01 PASS 뒤 오케스트레이터가 찍는다
G2-V01  2차 수직 관통          FAIL     tests/test_vertical_slice_2.py 없음 (대상 미구현)
G2-T01  유형 3 계약           FAIL     std 유형 phase≠1 ['review_queue', 'extract', 'quote']; api-contract §1 의 B09~B11 이 아직 단계 2(501) 7행; tests/test_types_phase2.py 없음 (대상 미구현)
G2-R01  대기열 누수            FAIL     tests/test_review_queue.py 없음 (대상 미구현)
G2-E01  추출                FAIL     tests/test_extract.py 없음 (대상 미구현)
G2-Q01  견적                FAIL     정적 FAIL: 대상 없음 — packs/*/formulas/quote*.py · src/mlcore/**/quote*.py 0개(웨이브 P 개발2 · A2 개발3) · tests/test_quote.py 없음 (대상 미구현)
G2-P01  팩·회사 4            FAIL     2건: 팩 없음 ['eto', 'kimchi', 'rollform-quote', 'solder']; 회사 없음 ['kd', 'krs', 'ot', 'pc']; 팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 7/7 거부 · 위반 1: 팩 없음 ['eto', 'kimchi', 'rollform-quote', 'solder']; baselines 비었음 ['solder', 'kimchi', 'rollform-quote', 'eto']
G2-S01  화면 7~10           FAIL     screen-map 화면 7~10 중 판정 대상(○) 0/4 — 웨이브 P 끝에 아키텍트가 켠다; 화면 파일 없음 ['web/src/screens/Sources.tsx', 'web/src/screens/Review.tsx', 'web/src/screens/Quotes.tsx', 'web/src/screens/Trace.tsx']
G2-A01  API 15            FAIL     계약 §1 단계 1 묶음 12/15 (B09~B11 은 웨이브 P 끝에 단계 1 로)
G2-I01  Agent 도구          FAIL     tests/test_agent_tools.py 없음 (대상 미구현)
G2-I02  허브 내보내기           FAIL     make export-hub 미구현; tests/test_export_hub.py 없음 (대상 미구현)
G2-H01  1차 잔여             FAIL     항목 33 — 해결 18 · 사유 0 · 열림 15 · 열림 ['F13-1', 'F16-8', 'F16-9', 'F19-3', 'F20-1', 'F20-2'] …
G2-L01  실데이터              BLOCKED  키가 없다 — 사람이 .env 에 넣은 뒤 make train-live (D-13)
소계 13행 — FAIL 12 · BLOCKED 1
합계 41행 — PASS 23 · FAIL 16 · BLOCKED 2
```

## 최종 보고 — 1차 종료 (2026-10-13, 기준 커밋 1ec05e6)

goal §4.4 종료 조건 4개를 모두 만족해 루프를 멈춘다.

| 조건 | 판정 | 실측 · 명령 |
|---|---|---|
| 1. G-V01 · G-S01~07 · G-M01~14 전건 PASS (BLOCKED 는 D-13 실연결만) | 충족 | `make gate` = PASS 23 · FAIL 0 · BLOCKED 1(G-M08 doctor-live, D-13) |
| 2. §1 의 1~7 을 `make gate-full` 로 확인 | 충족 | `CONFIRM=1 make gate-full` = PASS 23 · BLOCKED 1 |
| 3. QA 리포트 3종 + 치명 0 | 충족 | `outputs/qa1-*.md` · `qa2-*.md` · `qa3-*.md` (치명 2 · 중대 8 발견) → 웨이브 C 수정 → `outputs/qa-r2-재검증.md` 치명 0 · 중대 0 |
| 4. 연속 2회전 실측 변화 없음 | 충족 | 1ec05e6 이후 코드 변경 0, `make gate` 2회 연속 같은 판정 |

시험: `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` 459 passed · 3 skipped · 0 failed, `uv run pytest -q tests/e2e` 10 passed.

### 과제 8 (합성 시드, 시험 구간 1회)

| 과제 | 유형 | 챔피언 | 시험 지표 (기준선) | 원천 보고값 | 차이 |
|---|---|---|---|---|---|
| ks.remaining_hours | regression | gbr | MAE 5.568 (21.219) · R² 0.9199 | MAE 5.568 · R² 0.9199 | ≤ 0.01% |
| ks.failure_24h | risk | rf_clf | Brier 0.0576 (0.0586) · AUC 0.6444 | Brier 0.0576 · AUC 0.6444 | 0% |
| ks.sensor_ood | anomaly | isolation_forest | flag 0.1389 (밴드 0.04~0.16) | 보고 없음 | — |
| ks.maintenance_timing | optimize | 1차원 격자 | 후보 97 · 충족 89 | 후보 97 | 0% |
| sw.delta_e | regression | extra_trees | MAE 0.557 (1.087) · R² 0.722 | MAE 0.557 · R² 0.722 | ≤ 0.03% |
| sw.defect_risk | risk | gbc | Brier 0.1261 (0.2051) · AUC 0.8686 | Brier 0.127 · AUC 0.868 | ≤ 0.71% (D-52, #3) |
| sw.print_ood | anomaly | isolation_forest | flag 0.1458 | 보고 없음 | — |
| sw.print_setpoint | optimize | 5차원 격자 | 후보 1,080 · 충족 314 | 후보 8,400 | 학습 범위 밖 외삽 제거(D-31, 의도) |

과제 대응 32/32(`docs/task-map.md`). 비기능(compose 768MB · CPU 1): p95 27.9 ms · batch 500 0.306 s · 기동 1.65 s · RSS 248 MB.

### 이관 중 발견한 원천 결함 (요약 — 상세 `docs/migration-report.md` · `migration/source_inventory.md`)
평창식 표본 내 평가(기준선 원칙 위반) · sw 원천 격자의 학습 범위 밖 외삽(S9) · 원천 문서의 공개 IP · 호스트(D-41, 옮기지 않음) · 원천 문서 지표 반올림 불일치(D-52).

### 사람이 정해야 할 것
- D-130 승인 만료(모델 168h · 추천 24h, 가설)
- D-32 · D-33 실데이터(목표 변수 · 원천 열 · Data Platform 뷰 이름) — 이슈 #1
- D-27 · D-30 · D-04 · D-82 · 정본 결함 — 이슈 #2
- D-52 sw 원천 문서값 출처 — 이슈 #3
- D-13 실연결 키(`.env`) — 넣으면 `make doctor` live · `train-live`

### 열린 이슈 (모두 경미 또는 사람 확인)
#1 · #2 · #3(사람) · #7 후속(D-123 compose 앱 계정 · `make image` 재빌드 · D-81 · 시험 DB 정리) · #13 · #16 · #19 · #20 경미 결함.

### 2차 착수 전 확인
goal §10 — 유형 `review_queue` · `extract` · `quote` 를 코어에 먼저 넣고 1차 게이트 재실행, 팩 4 · 회사 4(krs · pc · ot · kd), 화면 7~10, Agent 플랫폼 `ml.*` 도구 · 데이터 허브 연동, 실데이터 1과제 production.

## 지금 해야 할 것 (2026-10-12, 웨이브 C 결함 수정 마감 — 기준 커밋 9d2febc + 작업 트리, 커밋은 오케스트레이터)

1. **make gate 2회 연속 = PASS 23 · FAIL 0 · BLOCKED 1(D-13 만).** 전체 시험 `pytest --ignore=tests/e2e` **459 passed · 3 skipped · 0 failed**, e2e **10 passed**. G-M13 은 게이트 2회 + test_optimize 단독 6회 모두 통과(간헐 실패 재현 0 — 개발2 가 시험 대역을 고친 뒤).
2. 웨이브 C 로 고친 QA 결함: QA1 #8~#12 · QA2 #14~#16 · QA3 #17 · #18 · DEF-QA3-002 · 004 · 005 · 006 등(개발1 D-85~D-88 · 개발2 D-130~D-134 · 개발3 D-120~D-126 · 마무리 결정 decisions.md 끝 표). 이슈 닫기는 오케스트레이터가 QA 재확인 뒤.
3. 남은 일: compose 앱 계정을 `mlp_app` 구성원 LOGIN 역할로(D-123, `docker-compose.yml`) · 커밋 뒤 `make image` · D-130 승인 만료 기간 사람 확인 · D-81(개발2) · QA 재검증(웨이브 B 재실행).
4. `make db-schema` · `db-reset` · `gate-full` 은 이제 `CONFIRM=1` 이 있어야 돈다(D-124). 기존 DB 의 보호 · 권한만 다시 적용은 `make db-grants`(비파괴).
5. 사람 확인 대기(그대로): D-27 · D-30 · D-32 · D-33 · D-04 · D-82 · D-130.

## (지난) 지금 해야 할 것 (2026-10-12, 웨이브 A 아키텍트 회전 직후 — 기준 커밋 be24075 + 작업 트리, 커밋은 오케스트레이터)

1. **make gate = PASS 23 · FAIL 0 · BLOCKED 1(D-13, 허용).** 웨이브 A 게이트 전부 PASS. 다음은 웨이브 B — QA1~3 교차 검증(goal §3.3) · `make gate-full` · 종료 조건 §4.4.
2. 이슈 정리(오케스트레이터): **#5 닫을 수 있음**(D-65). **#6** 4항목 모두 해소(1 B08 · 2 compat.round = be24075, 3 e2e = 이번 회전, 4 호환 인증 = D-59 사람 결정) → 닫을 수 있음. **#4** 의 D-51 · D-53 · D-54 · D-57 은 §4 에서 확정(정본 결함 부분은 #2 로 남김) → 닫을 수 있음. #1 · #2 · #3 은 사람 확인 대기.
3. 남은 가설 · 후속: D-68(개발1 — `test_source_contract` 가 `tests/fixtures/*/source_db.sql` 을 읽게) · D-73(추천 승인 만료) · D-76 구현(개발2 · 개발3 `warn_with`) · D-80 · D-81(개발2) · D-82(사람). `CLAUDE.md` 명령표의 "웨이브 A 에서 채운다" 문구는 사람이 갱신(아키텍트는 고치지 않았다).
4. 사람 확인 대기: D-27 · D-30 · D-32 · D-33(실데이터 차단) · D-04(승인자 명단).
5. **사고 기록(2026-10-12 아키텍트):** 이 파일을 갱신하던 셸 명령의 백틱이 명령으로 실행되어 `make gate-full` 의 앞 단계(`db-reset` = 두 DB mlp 스키마 재생성 + 표준 시드 · `web` 빌드)가 의도치 않게 1회 돌았다. ml_db · ml_test_db 의 기존 행이 지워졌다(지금 ml_db = 회사 2 · 과제 8 시드, 모델 0 · 예측 0). 두 DB 모두 시험 · 루프용(실데이터 없음, D-13)이고 그 뒤 `make gate` 를 다시 돌려 PASS 23 을 확인했다. 개발자가 ml_db 에 손으로 만든 모델이 있었다면 `make train` 으로 다시 만든다.

## 웨이브 A 아키텍트 회전 실측 (2026-10-12)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 전체 시험 | **389 passed · 3 skipped** (55 s, e2e 8 포함) — 전 378 + e2e 8 + 후속 3 | `OMP_NUM_THREADS=1 uv run pytest -q` |
| G-M11 compose | `docker compose config`(MLP_GIT_SHA=be24075) 정규화 결과: 서비스 app · db · DB 포트 0 · 앱 포트 1(127.0.0.1:8200→8200) · 헬스체크 2/2 · app mem 805306368 B · cpus 1 · OMP 1 · `MLP_GIT_SHA` 없으면 config 실패(기본값 0) · environment 에 비밀 이름 0(env_file 만). docker CLI 없을 때 YAML 정적 파싱도 PASS | `make check-deploy` · `PATH=/usr/bin:/bin .venv/bin/python gates/check_deploy.py` |
| 이미지 빌드 1회 | **성공** `mlp-app:be24075`(내용 349 MB, 디스크 1.56 GB) — node 24.18.1-bookworm-slim → uv 0.12.1 → python 3.12.13-slim-bookworm, `uv sync --frozen`. 작업 트리 기준(커밋 전 변경 포함) — 커밋 뒤 `make image` 로 다시 | `make image` |
| 기동 1회 (compose) | `mlpbench-ks` · `mlpbench-sw` 임시 프로젝트 `up --wait` → app · db healthy → 컨테이너 안 학습 · 승인(과제 3, 2.3 s · 2.5 s) → 재시작 → 측정 → `down -v`(남은 컨테이너 · 볼륨 0). 비밀은 임시 폴더 env 파일(저장소 밖, 실행 뒤 삭제) | `make bench-compose` |
| G-M14 (compose 제한 아래) | cgroup memory.max **805306368**(768 MB) · cpu.max **100000 100000**(CPU 1). 최악값: 단건 p95 **27.4 ms**(≤200) · batch 500 **0.306 s**(≤3, anomaly) · 기동 **1.65 s**(≤15, health 1.25 s + 과제 3 첫 예측) · app RSS(VmHWM) **247.8 MB**(≤768). 과제별 p95: ks 21.9 / 23.0 / 27.9 · sw 24.1 / 22.0 / 27.8 ms | `make bench` → `outputs/bench-compose-latest.json` |
| G-M14 (로컬, 참고) | compose 제한 아래 아님: p95 37.5 ms · batch 0.295 s · 기동 1.22 s · RSS 226.5 MB | `make bench-local` → `outputs/bench-latest.json` |
| G-S03 e2e | Playwright **1.63.0**(Python, chromium r1243) · 실제 uvicorn + 시험 DB · 회사 ks · sw 사본: 화면 1~6 HTTP 200 · 제목 일치 · `_placeholder` 0 · 페이지 오류 0 · 1024px 화면 2 · 3 폼 · 결과 후 가로 스크롤 0 · 폼 칸 · 라벨 · 범주 선택지 = features.yaml · 과제 YAML · 등록부 categories · 화면 3 sw 탐색 1,080점 · 충족 314(reproduce 와 같음). 8 passed / 13 s | `make e2e` |
| G-M09 조이기 | `decide(` 호출처(AST, src/mlcore · migration) **1** = api/routers/models.py | `uv run python gates/check_no_autopromote.py` |
| baselines.yaml | press: MAE 5.5683 · Brier 0.0576 · flag 0.1389 · 충족률 0.9175(89/97) / textile: MAE 0.5569 · Brier 0.1261 · flag 0.1458 · 충족률 0.2907(314/1080) / _template: MAE 2.3458 · Brier 0.1352 (전 값 null → 기입) | `OMP_NUM_THREADS=1 uv run python migration/reproduce.py` |
| 결정 | D-W1 12 · D-W2 9 · D-W3 8 → D-59~D-84: 확정 21 · 가설 6(D-68 · D-73 · D-80 · D-81 · D-82 · D-62 경로) · 차단 0. D-59 = 사람 결정(호환 경로 키 요구). D-40 확정 | `decisions.md` §9 |

명령(이번 회전에 연결): `make train TENANT= TASK=` · `make worker` · `make doctor TENANT=` · `make tenant NEW= PACK= [CSV=]` · `make monitor TENANT=` · `make bench`(auto) · `bench-local` · `bench-compose` · `make e2e` · `make image` · `make compose-config` · `make check-deploy`.

## make gate 판정표 (웨이브 A 아키텍트 회전 — 2026-10-12)

```
G-V01   수직 관통             PASS     tests/test_vertical_slice.py: 2 passed, 1 warning in 3.08s
G-S01   스키마               PASS     테이블 16 = spec 16 = 계약 16 = DB(ml_db 16 · ml_test_db 16) · 열 191 일치 · tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부
G-S02   팩·등록부 로드          PASS     팩 3 (_template(2) · press(4) · textile(4)) · 회사 3 로드 · 켜진 과제 8 · 불량 픽스처 5/5 거부(R4=과제 끄기, D-27)
G-S03   화면                PASS     화면 6/6 /app 200 · _placeholder 0 · e2e(ks·sw, 1024px 화면 2·3 가로 스크롤 0 · 폼=features.yaml) tests/e2e/test_console.py: 8 passed, 1 warning in 13.63s
G-S04   API               PASS     1차 12/12 · 2차 501 3/3 · tests/test_api_contract.py: 38 passed, 1 warning in 1.19s
G-S05   읽기 전용 소스          PASS     어댑터 5/5 · 정적 위반 0 · tests/test_source_contract.py: 18 passed, 1 warning in 0.99s
G-S06   비밀값               PASS     추적 파일 256 · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 9개(값 0)
G-S06   회사 격리             PASS     회사 2 · 회사 파일 10개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0
G-S07   의존성 고정            PASS     uv.lock · package-lock.json 있음 · Python 16개 == 고정 · JS 8개 정확 버전 · Python 3.12 하나
G-M01   코어 순수성            PASS     코어 95파일 · 팩 34파일 위반 0 (금지어 팩 30 · 회사 9 · 테이블 9 · 범주값 10)
G-M02   과제 대응             PASS     대응 32/32 (ks 16 · sw 16) · 미대응 0
G-M03   과제 정의             PASS     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 4/4 거부 · synth · baselines 있음
G-M04   예측 계약             PASS     A 스키마 자체 시험 91/91 · B tests/test_predict_contract.py: 27 passed, 6 warnings in 5.25s · C tests/test_compat.py: 35 passed, 3 skipped, 3 warnings in 5.91s
G-M05   누수 없는 평가          PASS     A 래퍼 자체 시험 14/14 · B 정적 위반 0 · C/D tests/test_split.py: 20 passed, 2 warnings in 3.05s
G-M06   재현·등록부            PASS     A tests/test_determinism.py: 9 passed, 4 warnings in 5.43s · B 기동 경로 학습 코드 0건 · C tests/test_registry.py: 13 passed, 1 warning in 1.80s
G-M07   예측 추적             PASS     tests/test_trace.py: 9 passed, 1 warning in 1.54s
G-M08   소스·doctor         PASS     tests/test_doctor.py: 7 passed in 0.58s
G-M08   doctor-live       BLOCKED  실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)
G-M09   감시·승인             PASS     production 쓰기 경로 1 (decide 안 1 · 밖 0) · decide 호출처 1 (models.py 1) · tests/test_approval.py: 14 passed, 1 warning in 1.81s · tests/test_monitor.py: 15 passed in 2.43s
G-M10   새 회사              PASS     tests/test_new_tenant.py: 3 passed, 3 warnings in 1.61s
G-M11   보안·배포             PASS     docker compose config(MLP_GIT_SHA=be24075): 서비스 app·db · DB 포트 0 · 앱 포트 1(8200) · 헬스체크 2/2 · 768MB·CPU 1 · OMP 1 · 태그=SHA 필수 변수 · 비밀 env_file 만 · Dockerfile 3단계 [node:24.18.1-bookworm-slim → ghcr.io/astral-sh/uv:0.12.1 → python:3.12.13-slim-bookworm] · tests/test_auth.py: 18 passed, 1 warning in 1.30s
G-M12   이관 대조             PASS     과제 8 대조 · 행 일치 100%
G-M13   최적화               PASS     tests/test_optimize.py: 11 passed, 2 warnings in 3.18s
G-M14   비기능               PASS     최악값(ks·sw 과제 6) 단건 p95 27.35ms(≤200) · batch500 0.306s(≤3) · 기동 1.647s(≤15) · RSS 247.8MB(≤768) — docker compose 제한 아래(app 768MB · CPU 1 · OMP_NUM_THREADS=1, 이미지 = 커밋 SHA)

합계 24행 — PASS 23 · BLOCKED 1
```

## Phase 0 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| spec 테이블 수 (§10.1) | **16** = contracts/db-schema.md 16 = ml_db 16 = ml_test_db 16 | `grep -cE '^\| \`mlp_[a-z_]+\` \|' spec.md` · `grep -c '^### ' contracts/db-schema.md` · `gates/check_schema.py` |
| spec 과제 유형 (§2.1) | **7** (1차 4) = std/task_types.yaml 7 (phase 1: 4) | `sed -n '/^### 2.1/,/^### 2.2/p' spec.md \| grep -cE '^\| \`[a-z_]+\` \|'` |
| spec 응답 상태 (§2.3) | **6** = std/statuses.yaml 6 = schema CHECK 6 = predict-contract enum 6 | `grep -cE '^\| \`(ok\|watch\|review\|out_of_range\|rejected\|needs_approval)\` \|' spec.md` |
| spec 분할 정책 (§5.3) | **4** = std/split_policies.yaml 4 | `grep -cE '^\| \`(time_60_20_20\|time_cv5\|stratified_60_20_20\|random_60_20_20)\` \|' spec.md` |
| spec API 묶음 (§12.2) | **15** (1차 12 = review · documents · quotes 제외) = contracts/api-contract.md B01~B15 (1차 12) | `grep -cE '^\| \`(GET\|POST\|PATCH) ' spec.md` → 15, `… \| grep -cvE 'review\|documents\|quotes'` → 12 |
| 회사 등록부 (1차) | **2** (ks · sw) + _template | `ls tenants/*.yaml \| grep -v _template \| wc -l` |
| mlp 열 | 191 (spec 주요 열 97 전부 포함) | `gates/check_schema.py` |
| 계약 | 9종 (goal 의 "8종" 표기와 다름 — D-24) | `ls contracts/` |
| 팩 · 과제 | press 4 · textile 4 · _template 2 = 과제 YAML 10, 스키마 위반 0 | `gates/check_tasks.py` |
| 원천 조사 ks | 엔드포인트 /api 6 (+/ 1) · 변수 9 (수치 7 + 범주 2) · 후보 8 · 분할 432/144/144 · 최적화 1 (0.5h 격자) · 화면 5 · 시험 9 함수/20 케이스 · 시험 MAE 5.568 · R² 0.9199 · AUC 0.6444 · Brier 0.0576 | `migration/source_inventory.md` §1 (파일:줄) |
| 원천 조사 sw | 엔드포인트 /api 6 (+/ 1) · 변수 9 (조절 5 + 원단 2 + 범주 2) · 후보 8 · 분할 432/144/144 · 최적화 1 (8,400점 격자) · 화면 5 · 시험 11 함수/24 케이스 · 시험 MAE 0.557 · R² 0.722 · AUC 0.868 · Brier 0.127 | `migration/source_inventory.md` §2 |
| G-M02 분모 | **32** (ks 16 · sw 16) | `migration/source_inventory.md` §0.1 · §5 |
| 원천 대응률 | sw 7/9 (dwell_time · color_tone 없음) · ks 6/9 확정 | `migration/source_inventory.md` §3 · §4 |
| 예측 계약 자체 시험 | 예시 4(유형 4) 통과 · 키 누락/ null 위반 변형 91/91 정확 판정 | `gates/check_contract.py` |
| 누수 래퍼 자체 시험 | 14/14 (금지 목적 6 · 2회 평가 · 평가 전 report · 직접 접근 4 · 표본 내 평가) | `gates/check_leakage.py` |
| 웹 골격 | Vite 8.3.0 · React 19.3.0 · TS 7.0.2 · 화면 1~6 `_placeholder` · `npm run build` 성공 | `cd web && npm run build` |
| API 골격 | `GET /api/v1/health` 200 (과제 8 model_ready=false) · 인증 없으면 401 · 2차 경로 501 | `MLP_TENANT=ks` TestClient |

## make gate 판정표 (Phase 0 종료 — 2026-10-12)

```
G-V01   수직 관통             FAIL     tests/test_vertical_slice.py 없음 (대상 미구현)
G-S01   스키마               PASS     테이블 16 = spec 16 = 계약 16 = DB(ml_db 16 · ml_test_db 16) · 열 191 일치 · tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부
G-S02   팩·등록부 로드          PASS     팩 3 (_template(2) · press(4) · textile(4)) · 회사 3 로드 · 켜진 과제 8 · 불량 픽스처 5/5 거부(R4=과제 끄기, D-27)
G-S03   화면                FAIL     _placeholder 화면 6/6 ([1, 2, 3, 4, 5, 6]); tests/e2e/ 없음(1024px 검사)
G-S04   API               FAIL     1차 묶음 1/12 구현 (없음 B02 B03 B04 B05 B06 B07 B08 B12 B13 B14 B15); tests/test_api_contract.py 없음 (대상 미구현)
G-S05   읽기 전용 소스          FAIL     어댑터 0/5 (없음 ['synthetic', 'csv', 'gateway', 'dataplatform', 'mes']) · 정적 위반 0 · tests/test_source_contract.py 없음 (대상 미구현)
G-S06   비밀값               PASS     추적 파일 130 · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 9개(값 0)
G-S06   회사 격리             PASS     회사 2 · 회사 파일 4개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0
G-S07   의존성 고정            PASS     uv.lock · package-lock.json 있음 · Python 15개 == 고정 · JS 8개 정확 버전 · Python 3.12 하나
G-M01   코어 순수성            PASS     코어 38파일 · 팩 24파일 위반 0 (금지어 팩 30 · 회사 9 · 테이블 9 · 범주값 10)
G-M02   과제 대응             FAIL     docs/task-map.md 없음 — 대응 0/32 (분모 ks 16 · sw 16)
G-M03   과제 정의             FAIL     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 4/4 거부 · 위반 3: press: synth/*.py 없음(합성 생성기 미이관); textile: synth/*.py 없음(합성 생성기 미이관); _template: synth/*.py 없음(합성 생성기 미이관)
G-M04   예측 계약             FAIL     A 스키마 자체 시험 91/91 · B predict 미구현 — 켜진 과제 0/8 검사 · C tests/test_compat.py 없음 (대상 미구현)
G-M05   누수 없는 평가          FAIL     A 래퍼 자체 시험 14/14 · B 정적 위반 0 · C 학습기(mlcore.train.trainer) 없음 — 계측 대상 0/8 · D 표본 내 평가 픽스처 대상 없음
G-M06   재현·등록부            FAIL     A 학습기 없음 — 재학습 대조 0/8 · B 기동 경로 학습 코드 0건 · C tests/test_registry.py 없음 (대상 미구현)
G-M07   예측 추적             FAIL     tests/test_trace.py 없음 (대상 미구현)
G-M08   소스·doctor         FAIL     tests/test_doctor.py 없음 (대상 미구현)
G-M08   doctor-live       BLOCKED  실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)
G-M09   감시·승인             FAIL     production 쓰기 경로 0 (decide 안 0 · 밖 0) · approval.decide() 없음 — 승인 경로 미구현
G-M10   새 회사              FAIL     tests/test_new_tenant.py 없음 (대상 미구현)
G-M11   보안·배포             FAIL     docker-compose.yml 없음 · tests/test_auth.py 없음 (대상 미구현)
G-M12   이관 대조             FAIL     docs/migration-report.md 없음 — 대조 0/8 · 합성 생성기 미이관 ['press', 'textile'] (대조값 4과제 준비됨)
G-M13   최적화               FAIL     tests/test_optimize.py 없음 (대상 미구현)
G-M14   비기능               FAIL     make bench 미구현 (p95 · batch 500 · 기동 · RSS 미측정)
합계 24행 — PASS 6 · FAIL 17 · BLOCKED 1
```

Phase 0 끝 조건 G-S01 · G-S02 · G-S06 · G-S07 · G-M01 = **PASS**. G-V01 FAIL 은 정상(웨이브 A0 목표). 나머지 FAIL 은 대상 미구현 사유를 그대로 표시한다(가짜 PASS 0).
