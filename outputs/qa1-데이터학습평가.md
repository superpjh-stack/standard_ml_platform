# QA1 — 데이터 · 학습 · 평가 (웨이브 B)

> 기준 커밋 9d2febc · 2026-10-12 · QA1. **고치지 않았다**(src · tests · packs · tenants · contracts 수정 0).
> 범위: G-V01 · G-S05 · G-M03 · G-M05 · G-M06 · G-M08 · G-M12 + 누수 사냥 · 결정성 · 스냅숏 해시 · 소스 읽기 전용 · doctor 정직성 · 이관 지표 독립 재계산.
> 환경: 전용 DB `ml_qa1_db`(끝나고 dropdb) · `MLP_DB_DSN` = `MLP_TEST_DB_DSN` = ml_qa1_db · 산출물 · 스냅숏은 `outputs/qa1/var`(삭제) · `OMP_NUM_THREADS=1`. ml_db · ml_test_db 쓰기 0, `make gate-full` · `db-reset` 실행 0, 원천 저장소 실행 0.
> 재현: `createdb -h /tmp ml_qa1_db && psql -h /tmp -d ml_qa1_db -f src/mlcore/db/schema.sql && source outputs/qa1/env.sh && uv run python -m mlcore.db.seed_std` 뒤 `uv run python outputs/qa1/<스크립트>.py`. 각 스크립트 출력은 `outputs/qa1/*.out`.

## 1. 결함

| ID | 등급 | 요약 | 담당 | 이슈 |
|---|---|---|---|---|
| DEF-QA1-001 | **치명 (조건부)** | group_key + 시계열 회귀에서 `last_value` 기준선이 시험 구간 목표를 본다 → 시험 값만 바꿔 기준선 선택 · `beats_baseline` 이 뒤집힌다. 지금 켜진 과제 8 은 group_key null 이라 발현 0 | 개발1 | #8 |
| DEF-QA1-002 | 중대 | group_key 가 시간상 섞이면 시계열 분할이 시간순을 잃는다(학습 585/600 행이 시험 시작보다 늦다). 경고만 내고 진행 | 아키텍트 → 개발1 | #9 |
| DEF-QA1-003 | 중대 | 회사 덮어쓰기로 `approver_role` 을 다른 역할로 바꿀 수 있다(지우기만 거부) — G-M03 · tenant-contract R1 위반 | 아키텍트 → 개발3 | #10 |
| DEF-QA1-004 | 중대 | 덮어쓰기로 `target` 을 입력 변수(`shot_count`)로 바꿔도 등록부 · 학습 통과, 기준선 이김(목표 누수 검사 없음) | 아키텍트 → 개발3 | #11 |
| DEF-QA1-005 | 중대 | doctor 의 미연결 소스 대응률 · 목표가 소스별이 아니라 회사 전체 대응표 하나로 계산된다(sw gateway 77.8% · 목표=있음, 그 테이블 대응 0) | 개발3 | #12 |
| DEF-QA1-006 | 경미 | guard 우회 경로 5가지(여집합 · `vars()` · `overlaps()` 질의 · `boundaries.test_ts` · `copy.copy` 로 final_eval 2회)가 ledger 에 기록되지 않는다. 정적 검사는 `_GuardedTest__idx` 문자열만 본다. src 사용처 0 | 개발1 · 아키텍트(check_leakage) | — |
| DEF-QA1-007 | 경미 | 스냅숏 해시: 같은 (ts, entity_id) 중복 행의 순서만 달라도 해시가 다르다 · entity_id 없는 원천은 행 순서대로 ROW-n 이 붙어 같은 내용이 다른 해시 · 수치 열과 같은 값의 문자열 열이 같은 해시 | 개발1 | — |
| DEF-QA1-008 | 경미 | 같은 시각 행 묶음이 분할 경계 양쪽에 갈린다(3행/시각: 학습∩검증 1 시각 · 검증∩시험 1 시각) | 개발1 | — |
| DEF-QA1-009 | 경미 | DB 어댑터의 읽기 전용은 세션 설정 하나 — 연결 객체를 쥔 코드가 끄면 INSERT 가 된다(어댑터 API 로는 불가). 실 원천은 계정 권한에 기대는데 doctor · 등록부에 SELECT 전용 계정 확인 항목이 없다 | 아키텍트 · 개발1 | — |

### DEF-QA1-001 (치명 · 조건부) — 시험 목표가 기준선 선택에 샌다
- 재현: `uv run python outputs/qa1/lv_flip.py` (팩 중립 임시 과제 · group_key=lot · 60그룹 무작위 · 1000행). 확인: `group_probe.py` · `group_probe2.py`.
- 실측: 원본은 검증 MAE train_mean 13.456 · last_value 1.196 → 기준선 last_value · beats **False**. 시험 목표 44행만 바꾸니 검증 last_value MAE **212.50** → 기준선 train_mean · beats **True**. 같은 배치에서 직전(시각순) 행이 시험 구간인 검증 행이 44개.
- 기대: 시험 구간 값을 바꿔도 `baselines_compared.valid` · 기준선 종류(D-61)는 그대로.
- 원인: `train/trainer.py:53-57` `with_last_value` 가 분할 **전** 전체 프레임 시각순으로 직전 목표를 붙인다(:260). split 이 그룹 블록으로 다시 줄 세우면(`split.py:80-95`) 검증 행의 시각순 직전 행이 시험 구간일 수 있다. GuardedTest 를 거치지 않는 파생 열이라 ledger 에 안 남는다.
- 등급 근거: goal §3.3 "시험 구간이 선정에 쓰였다". 1차 과제 8 은 group_key 가 모두 null 이라 지금 운영 경로에서는 발현 0. 그래도 group_key 를 쓰는 과제가 생기면 그대로 발현한다.

### DEF-QA1-002 (중대)
- 재현 `group_probe.py`. 시험 최초 시각보다 늦은 학습 · 검증 행: time_60_20_20 완전 섞임 585/600 · 195/200, 무작위 60그룹 520/593 · 194/208, time_cv5 완전 섞임 255/272 · 45/48. 그룹 교차는 0(4 정책 × 3 배치 모두).
- 기대: goal G-M05 는 시간순과 그룹 경계를 둘 다 요구한다. 둘을 함께 못 지킬 때 분할을 거부할지, 계약에 예외를 적을지 아키텍트가 정해야 한다. 지금은 `group_regrouped` 경고만 낸다(`trainer.py:265`).

### DEF-QA1-003 · 004 (중대) — 덮어쓰기 규칙
- 재현 `override_probe.py` · `override_train_probe.py`. 임시 등록부 루트를 쓰고, 저장소 tenants/ 는 읽기만 했다.
- 실측: type · split · time_key(null) · group_key · interval 변경과 approver_role 지우기는 거부(PASS). **approver_role → line_lead 는 그대로 적용**. `target: {name: shot_count}` 도 적용되어 학습 succeeded, 시험 MAE 149.9 대 기준선 41,673. seed 덮어쓰기도 적용된다(WARN — "시드 골라 쓰기" 여지).
- 원인: `registry/tenants.py:138-147` 은 `not_removable_on_override` 를 빈 값으로만 검사한다. `contracts/task-contract.md:79` 의 immutable 목록에는 approver_role · target · seed 가 없다. tenant-contract R1 과도 어긋난다.

### DEF-QA1-005 (중대) — doctor 정직성
- 재현 `uv run python -m mlcore.monitor.doctor --tenant sw` (ks 도 같다).
- 실측: sw train(dataplatform · view null) · gateway(PRC_MONITOR_DATA) · actuals(mes) 셋이 모두 대응률 77.8% · 목표=있음이다. 그런데 feature_map · target_map 에 PRC_MONITOR_DATA 열은 하나도 없다. ks gateway(EIF_PLC_RAW)도 66.7%.
- 기대: 소스별로 그 소스가 채우는 열만 센다. 셀 수 없으면 null 이나 `미확인` 으로 둔다. 원인은 `monitor/doctor.py:85-103` `_static_live` 가 role · cfg 를 쓰지 않는 데 있다.
- 정직한 부분(PASS): ks 실연결 3소스는 `목표 없음`(D-33)으로 나오고, 상태는 모두 `미연결` · D-13 이다. CSV 가 없으면 `미연결`, 목표 열이 없는 CSV 는 `목표 없음` 이다.

### DEF-QA1-006~009 (경미)
- 006 `guard_bypass_probe.py`: 시험 인덱스는 여집합 · `vars(test)` · `overlaps([i])` 질의 · `boundaries["test_ts"]` 로 복원된다(ledger 0건). `copy.copy(test)` 로는 final_eval 2회가 허용된다(위반 기록 0). src/mlcore 의 사용처는 정당한 3곳(split.py:105 경계 기록 · guard.py:110 · tenants.py:149)뿐이다. 다만 DEF-001 처럼 **분할 전 전체 프레임 파생 열**은 어떤 검사도 못 잡는다.
- 007 `snapshot_hash_probe.py`: 안정 5/6 · 민감 9/10. 실패는 위 표의 3건이다.
- 008 `group_probe2.py`: `TIE sizes 601 201 200 · train∩valid ts 1 · valid∩test ts 1`.
- 009 `source_probe.py`: `SET default_transaction_read_only = off` 뒤 INSERT 가 성공했다(어댑터 API 밖에서 연결 객체를 직접 쓴 경우). 어댑터 API 경로는 전부 막힌다(아래 §2).

## 2. 판정표

```
G-V01  수직 관통                 PASS  tests/test_vertical_slice.py 2 passed (ks.remaining_hours · sw.delta_e train→candidate→승인→predict→기록→actuals→trace)
G-S05  읽기 전용 소스             PASS  gates/check_sources.py 어댑터 5/5 · 정적 위반 0 · test_source_contract 18 · test_fixture_source_db 4 · test_data_sources 17 passed
G-S05  우회 시도(어댑터 API)       PASS  허용목록 밖 · pg_catalog · 다문장 · 인용부호 탈출 · ts_column 주입 · ts_from 값 주입 · 연결로 INSERT 전부 거부 · dataplatform 요청 GET · 본문 None (source_probe.py)
G-S05  읽기 전용 심층 방어         WARN  세션 read_only 를 끄면 쓰기 가능 (DEF-QA1-009)
G-M03  과제 정의                 PASS  gates/check_tasks.py 팩 3 · 과제 YAML 10 · 불변 4/4 거부
G-M03  덮어쓰기 불변 규칙          FAIL  approver_role 변경 · target 변경 통과 (DEF-QA1-003 · 004)
G-M05  누수 게이트               PASS  gates/check_leakage.py A 14/14 · B 0 · test_split 20 passed
G-M05  시험값 교란 불변(15 사례)   PASS  과제 6 + 임시 9(time_60_20_20 · time_cv5 · random · stratified, iqr · 무작위 탐색 · isotonic · sigmoid · anomaly): 선정 · 검증 지표 · 기준선 · 구간 q · 임계값 · 보정 · 탐색 결과 · lock 범위/결측값 변화 0, 시험 지표만 변화 (leak_probe.py)
G-M05  group 경계 4 정책          PASS  교차 그룹 0 · time_cv5 폴드 교차 0 (12 조합)
G-M05  group + 시계열 기준선       FAIL  DEF-QA1-001 (시험 목표 → 기준선 선택)
G-M05  group + 시간순             WARN  DEF-QA1-002
G-M06  재현 · 등록부              PASS  gates/check_determinism.py · test_determinism 9 · test_registry 13 passed
G-M06  결정성 흔들기              PASS  과제 6 × 5 변형(재실행 · HASHSEED 0/12345/7 · OMP/OPENBLAS/MKL=4 · 행 섞기+열 역순): 스냅숏 ID · 시험 예측 해시 · 챔피언 · 산출물 SHA-256 · 중요도 30/30 같음 (determinism_probe.py)
G-M06  스냅숏 해시               WARN  안정 5/6 · 민감 9/10 (DEF-QA1-007)
G-M08  doctor                   WARN  test_doctor 7 passed · ks 목표 없음 정직 · 미연결 정직 / 실연결 소스 대응률 · 목표가 소스별 아님 (DEF-QA1-005)
G-M08  doctor-live              BLOCKED  D-13 (허용)
G-M12  이관 대조                 PASS  gates/check_migration.py 과제 8 · 행 일치 100%
G-M12  QA 독립 재계산             PASS  원천 코드를 읽고 다시 쓴 스크립트: 행 셀 7,200/7,200 × 2사 일치 · 12지표 보고서 표준값과 Δ ≤ 0.03% · 원천 문서값과 Δ ≤ 0.75% · 챔피언 4/4 같음 (migration_recompute.py)
```

## 3. 통과 항목 세부 (실측 · 명령)

- **보정 · 구간 · 임계값 · 기준선 · 이상치 · 탐색**(코드 읽기 + 교란 시험): 다음은 모두 학습 · 검증 구간에서만 정한다(`trainer.py:297-420`).
  - conformal q · baseline_q 는 검증 잔차로 잡는다.
  - risk 보정기는 검증 확률로 맞춘다.
  - anomaly 임계값은 학습 구간 모델의 검증 점수 1-c 분위다(D-50).
  - 회귀 기준선은 재적합 구간 평균이고, 위험 기준선은 재적합 구간 양성률이다.
  - iqr 은 폴드 학습 구간과 재적합 구간(학습+검증)에서만 경계를 잰다.
  - 무작위 탐색은 검증 지표로 고른다.
  - 학습 범위 p1/p99와 결측 보정값은 재적합 구간에서 잰다.

  재적합 구간은 `sp.fit_idx` 로 시험을 뺀다. `final_evaluation` 이 시험 구간과의 겹침을 거부한다. ledger 는 `[final_eval, report]` 만 남긴다(과제 6). 교란 시험 15/15 PASS.
- **분할 4 정책 · 그룹**: time_60_20_20 · time_cv5(폴드 경계 포함) · stratified · random 모두 그룹 교차 0(D-66 고침을 확인했다). 그룹 없는 같은 시각 4행 묶음은 경계에서 갈라지지 않았다(PASS). 3행 묶음은 갈라졌다(DEF-008).
- **결정성**: 위 판정표대로 30/30. 산출물 SHA-256 은 스레드 4에서도 같다.
- **스냅숏 해시**: 열 순서 · 행 순서 · UTC/KST 표기 · 정수/실수 dtype · Parquet 왕복에 흔들리지 않는다. 다음 변경에는 해시가 바뀐다: 1e-12 값 변경, 결측, 열 추가 · 이름 변경, 행 삭제, 목표, 범주 문자열, `_source_ref`.
- **이관 대조(G-M12)**: 원천 `KwangSung ML AI/api/ml_service.py:20-38 · 74-108`, `SongWol ML AI/api/ml_service.py:29-57 · 93-126` 을 읽고 다시 썼다(원천은 실행하지 않았다).
  - ks: MAE 5.5683 · RMSE 6.9793 · R² 0.9199 · AUC 0.6444 · AP 0.1426 · Brier 0.0576
  - sw: MAE 0.5569 · RMSE 0.7088 · R² 0.7222 · AUC 0.8686 · AP 0.7823 · Brier 0.1261

  이 값들은 `docs/migration-report.md` §1 과 같다. sw 불량은 원천 코드를 시험 확률 4자리 반올림(:117)까지 재현해도 0.8686 · 0.7823 · 0.1261 이 나온다. 그러니 문서값(0.868 · 0.781 · 0.127)과의 차이는 문서 쪽이고, D-52 판단과 맞다. 이 근거를 이슈 #3 에 댓글로 남겼다. 원천 규칙(표본 내 contamination)의 이상 탐지 시험 flag 는 ks 0.1597 · sw 0.1667 로, 보고서 §4 의 0.160 · 0.167 과 같다.
- **관찰(결함 아님)**: 감시의 PSI 기준 분포 · 결측 기준은 스냅숏 전체(시험 포함)에서 잡는다(`monitor/daily.py:79-83`). 실측 성능 하락은 시험 지표와 비교한다. 둘 다 선정 · 보정이 아니라 감시 기준이라 누수로 보지 않았다. 아키텍트가 확인할 것을 권장한다.

## 4. 이슈
신규 #8(DEF-001) · #9(002) · #10(003) · #11(004) · #12(005), 모두 `ai-found`. 중복 검색 결과 0건이었다. 기존 #3 에는 QA1 재계산 근거를 댓글로 달았다.
