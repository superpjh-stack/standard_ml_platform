# QA-R2 — 웨이브 C 결함 재검증 · 회귀 사냥 · 새 치명 사냥 (QA1 · QA2 · QA3 통합)

- 기준 커밋 `1ec05e6` · 2026-10-13 · **고치지 않았다**. src/ · tests/ · packs/ · tenants/ · contracts/ · web/src 는 수정하지 않았다(`git status` = outputs 만 바뀜).
- 환경: 전용 DB `ml_qar2_db`(createdb → schema.sql → seed_std, 끝나고 **dropdb**) · 서버 포트 **8204**(끝나고 종료, LISTEN 0) · 산출물/스냅숏 = 저장소 밖 임시 폴더 · `OMP_NUM_THREADS=1`. ml_db · ml_test_db 쓰기 0, 원천 저장소 실행 0. `make gate` · `gate-full` · `db-reset` 은 실제로 돌리지 않았다(가짜 psql/uv 를 PATH 에 두고 차단 여부만 확인).
- 임시 LOGIN 역할 `qar2_login IN ROLE mlp_app` 을 만들어 권한을 확인한 뒤 DROP 했다.
- 재현 스크립트: `outputs/qa-r2/`(env.sh · qa1/ · qa2/ · qa3/ · run_qa3_ks.sh · run_r4.sh · run_newtenant.sh). 원 QA 스크립트 사본은 DB · 포트 · 경로만 바꿨다. API 가 바뀐 곳(`with_last_value` 제거 · 분할 거부)은 사본에서만 맞췄다. 결과는 각 폴더의 `*.out` · `r*.txt`, 스크린샷은 `outputs/qa-r2/e2e/`.
- 실행: `export QAR2_SCRATCH=<임시폴더>; source outputs/qa-r2/env.sh; createdb -h /tmp ml_qar2_db && psql -h /tmp -d ml_qar2_db -f src/mlcore/db/schema.sql && uv run python -m mlcore.db.seed_std` 뒤 각 스크립트.

## 1. 이전 결함 재검증

| 결함 | 이슈 | 판정 | 실측(원 재현 절차) |
|---|---|---|---|
| DEF-QA1-001 치명 | #8 | **해결** | 원 lv_flip(무작위 60그룹)은 이제 학습 거부 `split_time_group_conflict`. 분할이 성립하는 블록 그룹 10 · 40에서는 시험 목표를 교란해도 검증 기준선 비교 · 종류 · beats 가 같았다(`lv_flip_r2.out`). leak_probe 15/15 PASS |
| DEF-QA1-002 중대 | #9 | **해결** | 섞인 그룹의 time_60_20_20 · time_cv5 는 거부된다(학습 failed · report.error.code). 그 밖에는 시간순 OK · 그룹 교차 0(`group_probe.out` · `split_regress.out`) |
| DEF-QA1-003 중대 | #10 | **해결** | approver_role 을 다른 역할 · 대소문자 · 목록으로 바꾸면 R1 거부. 같은 값을 다시 적는 것은 통과(`override_probe.out` · `override_r2.out`) |
| DEF-QA1-004 중대 | #11 | **해결** | target 변경(대소문자 · 공백 포함)과 features · fixed 에 목표 열을 넣는 것은 R1 거부(`override_train_probe.out`) |
| DEF-QA1-005 중대 | #12 | **해결** | 소스별로 센다: sw gateway 0.0% · 목표 없음, actuals 77.8%(=7/9, 그 테이블 대응 열을 손으로 셈) · 있음, train null "셀 수 없다". ks actuals 66.7% · 목표 없음 |
| DEF-QA1-006 경미 | #13 | **부분** | 원 5경로 중 vars · copy · pickle · overlaps 2회는 TestLeak 이고, 여집합 · test_ts 는 정적 검사가 잡는다. 같은 효과의 다른 문법 6종(getattr 문자열 조립 · gc.get_referents · slot 서술자 · np.setdiff1d · 리스트 내포 여집합 · 변수 키 test_ts)은 ledger 와 check_leakage 가 둘 다 못 잡는다. src 사용처 0 |
| DEF-QA1-007 경미 | #13 | **해결** | 해시 안정 6/6(중복 키 행 순서 · ROW-n 포함) · 민감 11/11 |
| DEF-QA1-008 경미 | #13 | **해결** | 같은 시각 3행 · 4행 묶음의 경계 교차 0 |
| DEF-QA1-009 경미 | #13 | **해결(어댑터 범위)** | 허용 뷰가 쓰기 함수를 불러도 ReadOnlySqlTransaction 으로 막히고 원천 행 0이다. 쓰기 권한 계정이면 probe 가 경고하고, read_role 실패는 미연결로 나온다. 연결 객체를 직접 쥔 코드의 쓰기는 여전히 되며 계정 권한에 기댄다(D-88 설계 한계) |
| DEF-QA2-001 중대 | #14 | **해결** | 옛 optimize 행 키가 원천과 같다. ks = stop_after_hours · cost_index · reserve_hours · violation, sw = 조절 5 · pred_delta_e · risk_probability · cost_index · violation · anomaly. 미충족 · objective 는 한국어 원문 |
| DEF-QA2-002 중대 | #15 | **해결** | 호환 POST predict 의 감사가 +1 이다(ks · sw). 키 없는 401 쓰기는 '-' · anonymous 로 1행, 다른 회사 404 는 키의 회사로 1행 |
| DEF-QA2-003 · 004 · 006 · 007 · 008 | #16 | **해결** | batch NaN 은 건별로 처리된다(6/6). 422 field 는 계약 필드 · 색인 · `*` 만 내며 되풀이 0(8/8)이고, 정상 위치(explain · entity_id · decision · inputs)는 남는다. 5000자리 수는 422, explain "yes" 는 422, v99 는 404 |
| DEF-QA2-005 경미 | #16 | **해결** | 해시를 잰 바이트를 읽은 직후 디스크를 바꿔치기해도 응답은 검증된 바이트 값이다(103.086277 같음). 다음 요청은 503, health 는 false + error |
| DEF-QA2-009 경미 | #16 | **부분** | mlp_app 실접속: 추가만 3테이블 UPDATE/DELETE/TRUNCATE · replica · 트리거 끄기 · DROP · CREATE 가 거부되고, 정상 경로 12/12 가 통과한다. **compose 앱은 여전히 소유자 계정**(D-123) |
| DEF-QA2-010 경미 | #16 | **해결** | 개요 키를 추가했고, 뺀 키 6종은 compat_expected `differs` 에 사유가 있다 |
| DEF-QA3-001 치명 | #17 | **해결** | A) live + 합성 production 으로 기동하면 3과제가 disabled, predict · batch 가 503(rule disabled)이다. B) 기동 뒤 승인된 합성 모델은 predict · batch · 호환 모두 503(live_synthetic)이다 |
| DEF-QA3-002 중대 | #16 | **해결** | t03 반사 문자열 echo 0 |
| DEF-QA3-003 중대 | #18 | **해결** | `/api/data/records/KS-DEMO-0001` 200 · 9999 404 · sw 도 같다 |
| DEF-QA3-004 경미 | #7 댓글 | **해결** | expires_at 은 모델 168h · 추천 24h 다. 만료되면 state=expired 가 되고 대기열에서 빠진다. 재요청은 새 승인이다. 만료 경계 경합 6회 모두 결정 1회 · 200 ≤ 1 |
| DEF-QA3-005 경미 | #19 | **해결** | 화면 5 늦은 탭에 `already_decided` 문구가 보인다(`qar2-ui-approvals-tabB-409-1024.png`) |
| DEF-QA3-006 경미 | #19 | **해결** | current 1000 · −5 → 422. (#19 의 vite 프록시 8200 고정은 남음) |

QA3 원 스크립트 판정 행: t01 7 · t02 33 · t03 47 · t04 31 · t05 19 · t06 12 · t07 7 · t08 5 · t10 9 · t11 14. FAIL 로 찍힌 행은 모두 결함이 아니다.
- t03 run_id 하드코딩(해시 v2 로 ID 가 바뀜, reused=true 는 정상).
- 화면 3 영문 문자열 검사(배지는 한국어 '승인 필요').
- `GET /` 404(task-map 에 명시).
- yn 동시 학습 409 train_busy(계약). 순차 학습은 succeeded 다.

## 2. 회귀 사냥 (웨이브 C 변경 영역)

| 영역 | 판정 | 실측 |
|---|---|---|
| 분할 거부가 정상 과제를 거부하나 | PASS | group 없음 n=1000/400/120, 같은 시각 묶음, 블록 그룹, 경계 3/4 교차, 설비 2대 정렬, time_cv5, stratified · random 섞인 그룹이 모두 분할된다. 켜진 6과제 leak 15/15 · 결정성 30/30. *관찰*: 설비 2대 LOT 엇갈림 · 모든 경계 1행 교차는 거부된다(D-85 확정대로이나 실데이터에서 잦을 수 있음) |
| 해시 v2 ↔ v1 | PASS | 저장소 var/snapshots(읽기만) 1293개 중 v1 60 · v2 20 표본을 복사해 80/80 적재했다. 표지 제거(하향) · 표지 추가(상향) · 값 변조 · 'v0' 7/7 거부 |
| guard 강화 · 정상 경로 | PASS | check_leakage 래퍼 20/20 · 정적 0 · leak 15/15 |
| 읽기 전용 트랜잭션 | PASS | 위 DEF-QA1-009 |
| 감사 미들웨어 | PASS | GET 5건 감사 0. 감사 쓰기를 예외로 만들어도 응답 200 · 예측 기록이 정상이다. *관찰*: 이때 그 쓰기는 감사 없이 커밋된다(로그만 남음) |
| 422 필드 위치 · batch 건별 | PASS | 위 표 · 7건 혼합 [ok, invalid_input×5, out_of_bounds] · 빈 items · 객체 items 422 |
| TOCTOU · health | PASS | 위 표. 제자리 변조(mtime 유지)는 캐시가 검증된 메모리 모델로 답한다 |
| 승인 만료 · 재요청 | PASS | 위 표 |
| R4 실경로 A · B | PASS | 위 표 |
| R1 덮어쓰기 | PASS(+경미) | 정상 덮어쓰기 6/6 통과 · 우회 7/8 거부. 모르는 키(`auto_promote`)는 조용히 받는다 → DEF-QAR2-004 |
| doctor 소스별 | PASS | 위 표 |
| DB 권한 분리 | PASS(배포 부분) | 위 DEF-QA2-009 |
| CONFIRM 없는 db-reset | PASS(+경미) | db-reset · db-schema · gate-full 이 CONFIRM 없음 · 0 · yes · true · 01 일 때 exit 2(가짜 psql 호출 0). 셸 환경변수 `CONFIRM=1` 은 통과 → DEF-QAR2-003 |
| 호환 optimize 행 키 | PASS | 위 표. sw 행 값 cost_index 60.25 · anomaly false |
| 새 회사 G-M10 | PASS | 빈 등록부 → yn.yaml 1개 → doctor → train(eval) → 승인 → predict 18키. src · packs · tenants 해시 전후 동일 |

## 3. 새 치명 사냥 (goal §3.3 7기준)

| 기준 | 시도 | 결과 |
|---|---|---|
| 시험 구간이 선정 · 보정에 | 블록 그룹 시험 목표 교란 · 15사례 교란 · guard 새 우회 문법 | 선정 · 보정 변화 0. 우회 문법은 src 사용 0(경미, DEF-QA1-006 부분) |
| 승인 없이 production 변경 | 만료 경계 경합 · 감시 드리프트 · 기준선 미달 후보 · mlp_app 직접 SQL · DB 불변식 | production 전부 '승인된 같은 버전 승인 행' · 과제당 ≤1 |
| 같은 승인 두 번 결정 | 두 탭 + expire_due 동시 6회 · 두 탭 화면 | 감사 결정 중복 0 |
| 모델 없이 값 | archived · candidate · 없는 · 형식 이상 model_version(predict · batch) · 산출물 폴더 삭제 뒤 predict · optimize(uses) | 전부 404/422/503, 값 0 |
| 합성 모델 live 운영 | 기동 시 · 기동 뒤 승인 · 호환 경로 · model_version 지정 | 전부 503(값 0). health 불일치는 경미 → DEF-QAR2-001 |
| 다른 회사 예측 노출 | 다른 회사 trace · 같은 entity_id actuals 섞기 · 과제 칸에 전체 id · 승인 목록 · 호환 키 | 전부 404 · 섞임 0 |
| 원천 쓰기 | 쓰기 함수 뷰 · 허용목록 밖 · 다문장 · 주입 · dataplatform 메서드 | 어댑터 API 쓰기 0 · GET 만 |

**치명 0 · 중대 0** (새 결함은 모두 경미라 GitHub 이슈는 새로 만들지 않았다. 부분 판정은 #13 · #16 · #19 · #7 에 댓글을 달았다).

## 4. 새 결함 (DEF-QAR2)

| ID | 등급 | 요약 · 재현 | 기대 | 담당 |
|---|---|---|---|---|
| DEF-QAR2-001 | 경미 | live 회사에서 기동 뒤 합성 모델을 승인하면 predict 는 503(live_synthetic)인데 `/api/v1/health` 는 `model_ready: true` 다 — 화면 1 이 정상처럼 보인다(`run_r4.sh` B) | health 도 같은 require_servable 판정으로 false + error | 개발2(api/routers/v1.py) |
| DEF-QAR2-002 | 경미 | 꺼진(disabled) 과제의 호환 predict 는 404 "켜져 있지 않습니다", 표준은 503 model_not_ready(D-120a)(`run_r4.sh` A) | 호환도 503(값 0 은 같음) | 개발2(serve/compat) |
| DEF-QAR2-003 | 경미 | Makefile `confirm` 이 셸 환경변수 CONFIRM 도 받는다 — `export CONFIRM=1` 이 남은 셸에서 `make db-reset` 이 바로 돈다(가짜 바이너리로 확인) | 명령줄 인자만 인정하거나 대상 DB 이름 입력 요구 | 아키텍트(Makefile) |
| DEF-QAR2-004 | 경미 | 과제 덮어쓰기의 모르는 키(`auto_promote: true`, 오타)를 검증 없이 병합한다(`override_r2.out`). 지금 쓰는 코드는 0 | 덮어쓰기에도 과제 스키마 허용 키 검사 → R1 거부 | 개발3 · 아키텍트 |
| DEF-QAR2-005 | 경미 | `MLP_APPROVAL_TTL_HOURS_*=inf` 를 받으면 expires_at = infinity 라 만료되지 않는다. 1e12 처럼 아주 큰 값은 승인 요청 SQL 에서 interval out of range(500) | 유한 · 상한(예: ≤ 8760h) 검사, 아니면 기동 거부 | 개발2(approval) |

관찰(결함 아님): 감사 쓰기가 실패해도 쓰기는 진행된다(fail-open, 로그만 남음). 설비 병렬 LOT 엇갈림 데이터는 분할 거부. 다른 과제 approver 가 승인 목록을 본다(QA2 WARN 유지).

## 5. 이슈

- **닫아도 됨(해결):** #8 · #9 · #10 · #11 · #12 · #14 · #15 · #17 · #18
- **열어 둠:** #13(DEF-QA1-006 부분) · #16(DEF-QA2-009 compose 계정) · #19(vite 프록시 8200 고정) · #7(QA3-004 는 해결, 다른 항목 남음)
- 남은 미해결: 위 부분 3건 + DEF-QAR2-001~005(경미).
