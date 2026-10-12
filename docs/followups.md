# 1차 잔여 — 이슈 #7 · #13 · #16 · #19 · #20 항목 목록 (G2-H01 고정 목록)

> 아키텍트 Phase P0(2026-10-13)가 `gh issue view 7 13 16 19 20`(본문 + 댓글, QA-R2 재검증 `1ec05e6` 댓글까지)을 읽어 **항목을 고정**했다. 목록을 줄이거나 바꾸려면 `decisions.md` 에 사유를 남긴다.
> 검사: `gates/check_followups.py` — 아래 표의 ID 집합 = 검사기의 고정 ID 집합, 그리고 행마다
> `해결` = 근거 열에 **있는** 시험 파일(`tests/…py`) · `사유` = 근거 열의 `D-` / `D2-` 번호가 `decisions.md` 에 있음 · `열림` = FAIL.
> 웨이브 P 개발자는 상태 · 근거 열만 고친다(행 추가 · 삭제 · ID 변경 금지).

| ID | 이슈 | 항목 | 담당 (웨이브 P) | 상태 | 근거 |
|---|---|---|---|---|---|
| F7-1 | #7 | D-68 `test_source_contract` 가 `tests/fixtures/*/source_db.sql` 을 읽게 | 개발1 | 해결 | `tests/test_source_contract.py` (D-68 갱신) |
| F7-2 | #7 | D-76 optimize `warn_with` 구현 · task-schema 허용 키 | 개발2 · 개발3 | 해결 | `tests/test_override_rules.py` (D-131 · D-132) |
| F7-3 | #7 | D-73 추천 승인 만료 규칙 · `state=expired` 전이 · 재요청 경로 (DEF-QA3-004) | 개발2 | 해결 | `tests/test_wave_c_dev2.py` (D-130 — 기간은 사람 확인) |
| F7-4 | #7 | D-81 호환 `/api/data/records` 를 B12 행 함수로 전환 | 개발2 | 해결 | `tests/test_followups_dev2.py` (D-81 — B12 `_frame` 호출) |
| F7-5 | #7 | 커밋 뒤 `make image` 재빌드(이미지가 미커밋 작업 트리로 빌드됨) | 아키텍트 | 열림 | — |
| F7-6 | #7 | task-contract §3 · §4 에 `approver_role` · `target` (D-121) | 아키텍트 | 해결 | `tests/test_override_rules.py` (D-121) |
| F7-7 | #7 · #16 | D-123 compose 앱 계정을 `mlp_app` 구성원 LOGIN 역할로 (DEF-QA2-009 잔여) | 개발3 | 해결 | `tests/test_deploy_app_role.py` (`docker/initdb/20-app-login.sh` · D2-34) |
| F7-8 | #7 | 시험 DB `ml_grants_check_db` · `ml_grants_fresh_db` 정리 + `test_schema_grants` teardown | 개발3 | 해결 | `tests/test_schema_grants.py` (임시 DB + teardown · 남은 옛 DB 1개 삭제는 오케스트레이터 — D2-35) |
| F7-9 | #7 | D-85 시간순 · 그룹 경계 충돌 시 학습 거부 확정 | 아키텍트 | 해결 | `tests/test_split.py` (D-85 확정) |
| F7-10 | #7 | interfaces §2.2 스냅숏 해시 v2 · tenant-contract `read_role` 반영 (D-87 · D-88) | 아키텍트 | 해결 | `tests/test_qa1_regressions.py` (D-87 · D-88) |
| F7-11 | #7 | G-M13 이 gate 실행 중 1건 실패 · 단독 통과 — 간헐 실패 재확인 | 개발2 | 해결 | `tests/test_followups_dev2.py` (재현 0 — test_optimize 5회 연속 11 passed · 같은 요청 2회 같은 추천) |
| F7-12 | #7 | 호환 bundle 의 anomaly 를 rejected 일 때 false 대신 null · 옛 records 행 키 순서 대조 | 개발2 | 해결 | `tests/test_followups_dev2.py` (anomaly null · 키 순서 = tests/compat_expected.yaml record_key_order) |
| F13-1 | #13 | DEF-QA1-006 잔여 — guard 우회 다른 문법 6종(문자열 getattr · gc 참조 · slot 서술자 · setdiff1d/내포 여집합 · 변수 키 test_ts) 정적 검사 · ledger 보강 | 개발1 · 아키텍트 | 해결 | `tests/test_guard_bypass_r2.py` (D2-41 — 실행: 클로저 · getattr 기록 · test_ts 를 SplitPlan 밖으로 / 정적: check_leakage 패턴 7) |
| F13-2 | #13 | DEF-QA1-007 스냅숏 해시 행 순서 · 열 종류 | 개발1 | 해결 | `tests/test_qa1_regressions.py` |
| F13-3 | #13 | DEF-QA1-008 같은 시각 행 묶음이 분할 경계에서 갈림 | 개발1 | 해결 | `tests/test_qa1_regressions.py` |
| F13-4 | #13 | DEF-QA1-009 읽기 전용 이중화(어댑터 범위) | 개발1 | 해결 | `tests/test_qa1_regressions.py` |
| F16-1 | #16 | DEF-QA2-003 batch 건별 오류 | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-2 | #16 | DEF-QA2-004 422 `detail.field` 입력 되풀이 (= DEF-QA3-002) | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-3 | #16 | DEF-QA2-005 산출물 해시 대조 · 적재 TOCTOU | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-4 | #16 | DEF-QA2-006 긴 정수 400 → 422 | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-5 | #16 | DEF-QA2-007 `explain` 엄격 bool | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-6 | #16 | DEF-QA2-008 없는 `model_version` 404 | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F16-7 | #16 | DEF-QA2-010 호환 overview 원천 키 · `differs` 사유 | 개발2 | 해결 | `tests/test_compat.py` (D-132) |
| F16-8 | #16 | 관찰: approver 가 남의 과제 승인 목록을 본다(결정은 403) | 개발2 | 해결 | `tests/test_followups_dev2.py` (own_task approver 목록 = 자기 approver_role) |
| F16-9 | #16 | 관찰: 콘솔이 API 키를 localStorage 에 저장 | 개발2 | 해결 | `tests/test_web_followups.py` (키 = sessionStorage, localStorage 는 회사 코드만) |
| F19-1 | #19 | DEF-QA3-005 화면 5 두 탭 409 문구 | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F19-2 | #19 | DEF-QA3-006 optimize `current` 결정 변수 범위 검사 | 개발2 | 해결 | `tests/test_wave_c_dev2.py` |
| F19-3 | #19 | `web/vite.config` 개발 프록시 포트 8200 고정 → 환경변수 | 개발2 | 해결 | `tests/test_web_followups.py` (MLP_API_PORT, 기본 8200) |
| F20-1 | #20 | DEF-QAR2-001 live 회사 기동 후 합성 승인 시 health `model_ready: true` | 개발2 | 해결 | `tests/test_followups_dev2.py` (health · 옛 health = require_servable 판정) |
| F20-2 | #20 | DEF-QAR2-002 꺼진 과제 호환 404 · 표준 503 불일치 | 개발2 | 해결 | `tests/test_followups_dev2.py` (호환 503 `{detail, code: model_not_ready}`) |
| F20-3 | #20 | DEF-QAR2-003 export 된 `CONFIRM=1` 도 받음 → 명령줄 인자만 | 아키텍트 | 해결 | `tests/test_makefile_confirm.py` (Makefile `confirm` = `$(origin)` command line — 개발3 대행, D2-36) |
| F20-4 | #20 | DEF-QAR2-004 과제 덮어쓰기 모르는 키(오타 · `auto_promote`) 무검증 | 개발3 · 아키텍트 | 해결 | `tests/test_registry_phase2.py` (R1 모르는 키 거부 · D2-30) |
| F20-5 | #20 | DEF-QAR2-005 승인 만료 환경변수 `inf` · 과대값 범위 검증 | 개발2 | 해결 | `tests/test_followups_dev2.py` (유한 · 0 < h ≤ 1년만) |

합계 33 항목 — 해결 18 · 열림 15 · 사유 0 (Phase P0 시점).
