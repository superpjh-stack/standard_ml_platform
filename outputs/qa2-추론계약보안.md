# QA2 — 추론 · 계약 · 보안 리포트 (웨이브 B)

- 기준 커밋 `9d2febc` (작업 트리 변경 0 — `git status --short` 빈 출력) · 2026-10-12
- 범위: G-S04 · G-S06 · G-S07 · G-M01 · G-M04 · G-M07 · G-M11 · G-M14 (goal §3.3)
- **고치지 않았다.** src/ · tests/ · packs/ · tenants/ · contracts/ 수정 0. 검증 스크립트는 `outputs/qa2/` 에만.
- DB: 전용 `ml_qa2_db`(createdb → schema.sql → `seed_std --test`) 만 썼다. ml_db · ml_test_db 쓰기 0, `make gate-full` · `db-reset` 미실행. 끝나고 `dropdb ml_qa2_db`.
- 서버: 벤치 uvicorn 만 포트 **8202** 로 띄웠고 측정 뒤 종료(`lsof -iTCP:8202` 빈 출력 확인).
- 원천(`../KwangSung ML AI` · `../SongWol ML AI`)은 **읽기만**(api/main.py · api/ml_service.py).
- 기대값 출처: `contracts/predict-contract.md` §1~§7 · goal §2.3 · §6 · 원천 코드 · `tests/compat_expected.yaml`.

## 0. 판정 요약

```
G-S04   API                 WARN   1차 12/12 · 2차 501 3/3 · 다른 회사 404 13/13 · 역할 25/25 · 경미 결함 4(DEF-QA2-003 · 006 · 007 · 008)
G-S06   비밀값 · 회사 격리   PASS   gate PASS(추적 260 · 키 0 · IP 0 · 호스트 0) · git log -p 전체(9커밋): IPv4 = 127.0.0.1 · 0.0.0.0 뿐 · URL 호스트 = 패키지 출처 · localhost · json-schema.org · .env 이력 = .env.example(값 0)
G-S07   의존성 고정          PASS   pyproject 직접 11 + dev 4 전부 == · package.json 8 정확 버전 · requires-python ==3.12.* · .python-version 3.12 · uv.lock 136 패키지
G-M01   코어 순수성          PASS   gate PASS + 독립 검사(outputs/qa2/scan_terms.py): 팩 단어 40 · 회사 단어 48 × 코어 170파일 · 팩 34파일 위반 0 · 회사명 대소문자 무시 grep 0
G-M04   예측 계약            PASS   과제 8 predict 24/24 · optimize 4/4 · batch 6/6 18키 + JSON Schema(allOf) 통과 · reject 정책 3유형 rejected 모양 3/3 · 모델 없음 503 18/18
G-M04   호환 라우터 옛 키     FAIL   최상위 키 ks · sw 일치, 그러나 optimize 행 키 · unmet_constraints 값이 원천과 다름(DEF-QA2-001 중대) · overview 원천 키 ks 10 · sw 14 누락(DEF-QA2-010)
G-M07   예측 추적            PASS   tests/test_trace.py 9 passed · 앱 경로 UPDATE/DELETE/TRUNCATE 거부 5/5 · rejected 예측도 기록 · trace 3/3 — 단 소유자 계정은 트리거 우회 가능(DEF-QA2-009 경미)
G-M11   보안 · 배포          PASS   키 해시 sha256$<64hex> 5/5 · 평문 INSERT 거부 · 역할 25/25 · 다른 회사 404 13/13(없는 ID 와 같은 본문 3/3) · CORS 3/3 · compose(DB 포트 0 · 앱 포트 1 루프백 · 헬스체크 2 · USER mlp uid 10001 · 비밀 굽기 0)
G-M14   비기능              PASS   재측정(로컬 uvicorn 8202, compose 제한 아래 아님): 단건 p95 26.3ms · batch500 0.298s · 기동 1.004s · RSS 223.2MB
```

감사 · 보안 별도: **DEF-QA2-002(중대)** 호환 경로 POST predict 의 감사 0행. 치명 결함 **0** (다른 회사 예측 노출 0 · 모델 없이 값 나감 0 · 승인 없는 production 교체 0).

## 1. 결함

| ID | 등급 | 요약 | 담당 |
|---|---|---|---|
| DEF-QA2-001 | **중대** | 호환 `/api/ml/optimize` 의 추천 행 키 · `unmet_constraints` · `objective` 가 원천 응답과 다르다 (ks · sw) | 개발2(`serve/compat`) · 개발3(`tenants/*.yaml compat.optimize_rename`) |
| DEF-QA2-002 | **중대**(보안 · 감사) | 호환 경로(`/api/...`) POST predict 가 `mlp_prediction` 3행을 쓰면서 `mlp_audit` 0행 | 개발2(`api/middleware.py` · `api/routers/compat.py`) |
| DEF-QA2-003 | 경미 | `predict:batch` 에서 한 건의 NaN · Infinity(형식 오류)가 배치 전체를 422 로 만든다 — 계약 §5 "한 건의 422 가 다른 건을 막지 않는다" 위반 | 개발2(`serve/contract.py` BatchBody) |
| DEF-QA2-004 | 경미(보안) | pydantic 단계 422 의 `detail.errors[].field` 가 `inputs` 의 **임의 키 문자열**을 그대로 되풀이(D-75 · goal §2.3 우회) | 개발2(`api/main.py` `_validation`) |
| DEF-QA2-005 | 경미(보안) | 산출물 해시 측정 ↔ `joblib.load` 사이 TOCTOU — 그 사이 바뀐 `model.joblib` 이 검증 없이 적재 · 응답된다 | 개발2(`registry/artifacts.py` `load_artifacts`) |
| DEF-QA2-006 | 경미 | 4300자리 넘는 정수 리터럴 → **400 `http_error`**(오류 계약에 없는 코드). 기대 422 `invalid_input` | 개발2(`api/main.py`) |
| DEF-QA2-007 | 경미 | `explain: "yes"` 가 200(문자열 → bool 강제 변환). 계약 §1 은 형이 틀리면 422 | 개발2(`serve/contract.py` `explain: bool`) |
| DEF-QA2-008 | 경미 | `model_version` 이 **없는 버전**이면 503 `model_not_ready`, candidate 버전이면 404 — 같은 "쓸 수 없는 버전"이 두 코드 | 개발2(`serve/predict.py` `_model` · `registry/models.py get`) |
| DEF-QA2-009 | 경미(보안) | 추가만 테이블 보호가 트리거뿐 — 소유자 · 슈퍼유저는 `session_replication_role=replica` 로 UPDATE 가 성공. `mlp_app` 역할은 만들기만 하고 GRANT/REVOKE 없음, compose 앱은 DB 소유자 계정으로 붙는다 | 아키텍트(`db/schema.sql` · compose 계정) |
| DEF-QA2-010 | 경미 | 호환 `/api/ml/overview` 가 원천 키 ks 10개 · sw 14개를 빼고 내며 `compat_expected.yaml differs` 에 사유가 없다 | 개발2 · 아키텍트(사유 기록) |

### DEF-QA2-001 (중대) 호환 optimize 행 키 · 값

- 재현: `outputs/qa2/probe.py` `compat_checks()` — ks · sw 사본에 실제 학습 → 승인 → `POST /api/ml/optimize {record: <compat_expected default_record>, <optimize_params>}` (operator 키), 불가능 조건은 `optimize_infeasible`.
- 실측:
  - ks `recommendation` 행 키 = `[stop_after_hours, remaining_hours, maintenance_cost, violation]`, 불가능 시 `unmet_constraints = ["reserve", "max_cost"]`, `objective = "제약 충족 후보 중 maintenance_cost 최소화, 동률이면 stop_after_hours 최대"`.
  - sw 행 키 = `[set_temp, set_pressure, line_speed, ink_usage, dwell_time, delta_e, defect_risk, process_cost, violation]`, `unmet_constraints = ["max_delta_e", "max_risk", "min_line_speed"]`.
- 기대(원천 코드를 직접 읽음):
  - ks `api/ml_service.py:138-148` — 행 = `{stop_after_hours, cost_index, reserve_hours(= 수명 − t), violation}`, unmet = `["요청한 잔여수명 여유시간 미충족", "정비 비용지수 상한 초과"]`.
  - sw `api/ml_service.py:172-192` — 행 = `CONTROLS + [pred_delta_e, risk_probability, cost_index, violation, anomaly]`, unmet = 한국어 문구 3종.
- 원인: `compat.optimize_rename`(tenant-contract §1, D-71)이 ks · sw 어디에도 없다. ks `reserve_hours`(여유) · sw `anomaly` 는 이름 바꾸기만으로 나오지 않는다. `tests/test_compat.py` 는 최상위 키만 본다.
- 영향: 옛 화면 · MES 연동이 `recommendation.cost_index` 등을 읽으면 `undefined`. G-M04 "옛 키로 돌려준다"가 행 단위에서 깨진다.

### DEF-QA2-002 (중대) 호환 predict 감사 누락

- 재현: 같은 스크립트. `POST /api/maintenance/predict`(ks) · `/api/quality/predict`(sw) 1회 전후로 `mlp_audit`(회사) · `mlp_prediction`(channel=compat) 행 수를 셌다.
- 실측: ks · sw 모두 예측 +3행, 감사 **+0행**. 같은 요청을 `/api/v1/.../predict` 로 보내면 감사 +1행. 호환 optimize 는 optimizer 안에서 +1행(PASS).
- 원인: `AuthAuditMiddleware` 는 `/api/v1/` 만 감시(`guarded = path.startswith("/api/v1/")`)하고, 호환 라우터는 자체 인증만 하고 감사를 쓰지 않는다.
- 덧붙임(WARN): 미들웨어가 다른 회사 키를 404 로 돌려보내는 쓰기 시도(13건)도 감사에 0행이다.
- 기대: 쓰기 요청(POST)은 경로와 상관없이 `mlp_audit` 1행(middleware docstring · spec §17).

### DEF-QA2-003 ~ 010 재현 · 실측

| ID | 재현(스크립트 함수) | 실측 | 기대 |
|---|---|---|---|
| 003 | `contract_suite`: `{"items":[{정상},{"inputs":{x: NaN}}]}` 원문 JSON | 6과제 모두 422(배치 전체), `field: items.1.inputs.<변수>.int` … | 200 + `items[1] = {index:1, error:{invalid_input}}` · `items[0]` 응답 |
| 004 | `weird_inputs`: `inputs` 에 임의 키(`<sentinel><b>키`) + 값 NaN 또는 중첩 객체 | 4과제 × 2 = 8/8 에서 `detail.errors[].field = "inputs.<sentinel><b>키.int"` 처럼 키를 되풀이 | 변수 이름 꼴(`^[a-z][a-z0-9_]{0,63}$`)이 아니면 field 를 null (D-75, `validate_format` 과 같게) |
| 005 | `artifact_attacks (e)`: `artifact_sha256` 직후 `model.joblib` 을 다른 과제 모델로 바꾸는 경합 창을 계측으로 만듦 | 200 · `remaining_hours.prediction.value` 103.09 → **0.0** (검증 안 된 모델이 적재 · 응답). 다음 요청은 503(캐시 키가 바뀜) | 해시를 잰 바이트에서 적재하거나 적재 뒤 재검증 → 503. `joblib.load` 는 임의 코드 실행이므로 경합 창이 곧 검증 우회 |
| 006 | `weird_inputs`: 수치 자리에 5000자리 정수 | 4과제 400 `http_error` | 422 `invalid_input` |
| 007 | `weird_inputs`: `"explain": "yes"` | 4과제 200 | 422 `invalid_input` (StrictBool) |
| 008 | `probe2.py §3`: approver · admin `model_version: "v99"` | 503 `model_not_ready`(candidate v2 는 404 `not_found`) | 같은 404 `not_found` — 대체 모델은 없었다(값 나감 0) |
| 009 | `psql -d ml_qa2_db`: `BEGIN; SET LOCAL session_replication_role = replica; UPDATE mlp_prediction …; ROLLBACK;` | `UPDATE 1` (롤백함). 일반 경로 UPDATE/DELETE/TRUNCATE 는 `InsufficientPrivilege append_only` 거부 5/5 | 앱 계정은 비소유 · 비슈퍼유저 `mlp_app` 이고 두 테이블에 INSERT · SELECT 만 GRANT |
| 010 | `compat_checks`: `GET /api/ml/overview` | 13키. 원천 ks `ml_service.py:160-169` 대비 `missing_cells · duplicate_lots · impossible_cells · machines · products · importance · review_count · evaluated · trend · priority_queue` 누락, sw `:205-215` 대비 14 누락(`equipment · print_types · color_tones · controls · defect_rate · delta_e_review` 등) | 원천 키 전부, 또는 `differs` 에 키별 사유 |

## 2. 통과 · 관찰 항목 (실측 · 명령)

명령(전부 `MLP_TEST_DB_DSN="dbname=ml_qa2_db host=/tmp" OMP_NUM_THREADS=1`):
`uv run python outputs/qa2/probe.py`(318 검사 → `probe-result.json`) · `uv run python outputs/qa2/probe2.py`(33 → `probe2-result.json`) · `uv run python outputs/qa2/scan_terms.py` · `uv run python outputs/qa2/bench_qa2.py`(→ `bench-qa2.json`) · `uv run pytest tests/test_{api_contract,predict_contract,predict_validation,compat,auth,trace,registry}.py` → **157 passed · 3 skipped** · `gates/check_{secrets,tenant_bleed,pins,core_terms,deploy,contract,routes}.py` 전부 PASS.

```
G-M04   predict 18키 · 유형 null 규칙(과제 6 × 4 경우)     PASS  24/24 JSON Schema 오류 0 (sw imputed3 3건은 시험 설계 오류 — set_temp 가 필수라 422, 결함 아님)
G-M04   optimize 18키(ks · sw · 충족/불가능)               PASS  4/4 · needs_approval / review · in_train_range_rate 1.0
G-M04   batch 순서 · 건별 422 · {items, next_cursor}        PASS  6/6 [ok, error, ok, error] · 501건 → 422 6/6
G-M04   reject 정책 rejected 모양(regression · risk · anomaly) PASS  3/3 200 · value/score null · 18키 · 기록 · trace 200
G-M04   모델 없음                                          PASS  과제 8 + batch 6 = 14/14 503 model_not_ready · 값 키 없음 · health ready=false 2/2
G-M04   NaN · ±Infinity · 1e400 → 422 invalid_input        PASS  16/16
G-M04   1e308 · 10**30 · 10**400 → 422 out_of_bounds       PASS  12/12
G-M04   빈 문자열 · "1" · true · 객체 · 배열 · 유니코드 키 · 범주 숫자 · 최상위 모르는 키 · 비 JSON · entity_id 129자 · model_version 형식  PASS  44/44 422 · 값 되풀이 0
G-M04   -0.0                                               PASS  200 정상 채점
G-M04   중복 키(앞 잘못 · 뒤 정상)                           WARN  200 — 마지막 값이 이긴다(파이썬 json). 앞 값 검증 없음
G-M04   범주 값 반사(<sentinel><script>)                    PASS  422 out_of_bounds · 응답에 값 0
G-M04   max_imputed 경계(ks remaining_hours · failure_24h)  PASS  null 3개 200 · 4개 422 missing_required · 키 생략 4개 422 · 필수 범주 null 422
G-M04   max_imputed 경계(sw)                                WARN  보정 가능한 수치가 2개(absorb_rate · fabric_strength)뿐이라 한도 3 에 닿을 수 없다(원천과 같음)
G-M04   범위 경계 p1 · p99 정확히 같은 값                    PASS  48/48 — p1 · p99 = 범위 안(near_range · watch), nextafter 바깥 = out_of_range
G-M04   호환 predict · records · health 키 · 옛 422 · NaN    PASS  ks · sw predict 키 = 원천 ml_service 반환 키(순서까지) · records 720 · 옛 422 값 되풀이 0
G-M11   다른 회사 admin 키 13경로(tasks · models · predict · batch · actuals · trace · runs · approvals · decide · promote · monitor · doctor · records)  PASS  13/13 404 not_found
G-M11   다른 회사 ↔ 없는 ID 응답 동일(trace · runs · decide) PASS  3/3 상태 · 본문 동일
G-M11   경로 꼴 우회(다른 회사 경로 + 과제 접두 · // · 대문자 · %2F) PASS  4/4 404 · prediction_id 0
G-M11   역할 표 goal §6                                    PASS  25/25 (viewer 쓰기 · 승인 · 감시 403, operator 학습 · stage · promote · decide · trace · model_version 403, approver 학습 · stage · trace 403, 다른 과제 approver decide · promote 403, admin trace 200)
G-M11   approver 의 승인 목록                               WARN  다른 과제 담당 approver 도 남의 과제 승인 8건을 본다(결정은 403). goal §6 "자기 과제만" 이 목록에도 적용되는지 확인 필요
G-M11   키 없음 · 틀림 · 폐기 → 401                          PASS  3/3
G-M11   API 키 저장 · 타이밍                                 PASS  sha256$<64hex> 5/5 · 평문 INSERT → CheckViolation(mlp_api_key_no_plain) · 조회는 해시 동등 비교(평문 접두 비교 없음 — 접두 타이밍 단서 없음). key_prefix 8자 = "mlp_"+4자
G-M11   CORS                                               PASS  목록 origin 만 ACAO · 다른 origin 400/무헤더 · "*" 설정은 버림 · 빈 값이면 미부착 · credentials 미허용
G-M11   compose · Dockerfile                               PASS  DB ports 없음 · 앱 127.0.0.1:8200 1개 · 헬스체크 app · db · mem 768m · cpus 1 · USER mlp(uid 10001, 코드 폴더는 root 소유) · .dockerignore .env* · 이미지 태그 SHA 필수
G-M11   산출물 바꿔치기 · env.lock 위조 · lock 범위 위조 · 폴더 삭제  PASS  4/4 503 model_artifact_mismatch · 예측 기록 0
G-M11   제자리 변조(크기 · mtime · inode 같음)               WARN  캐시는 이미 검증한 메모리 모델로 답함(변조본 미사용) · 캐시 비우면 503
G-M07   append-only(앱 경로)                               PASS  mlp_prediction · mlp_audit UPDATE/DELETE/TRUNCATE 5/5 거부
G-M14   bench 재측정(8202, 로컬)                            PASS  ks p95 19.2/21.0/25.8ms · sw 21.7/18.6/26.3ms · batch500 ≤ 0.298s · 기동 ≤ 1.004s(health 0.39s) · RSS ≤ 223.2MB. 참고: 기존 compose 제한 아래 값 p95 27.4ms · RSS 247.8MB(outputs/bench-compose-latest.json)와 같은 크기
```

기타 관찰(WARN, 결함으로 올리지 않음):
- 키 없는 `/api/v1/health` 가 회사 코드 · 과제 이름 · 운영 버전을 낸다(설계상 공개). 산출물이 변조돼 predict 가 503 이어도 health 는 `model_ready: true`(DB 만 본다) — 화면 1 이 정상처럼 보인다.
- `X-Request-Id` 를 길이 · 문자 제한 없이(8000자 확인) 응답 헤더로 되돌리고 감사에 저장한다.
- 콘솔은 API 키를 `localStorage` 에 둔다. `web/src` 에 `innerHTML` · `dangerouslySetInnerHTML` 0건.
- 호환 bundle 의 `anomaly` 는 flag 가 null(rejected)이면 `false` 로 낸다 — 1차 과제 8 은 모두 `predict_with_warning`(D-07)이라 지금은 닿지 않는다.

## 3. GitHub 이슈

중복 확인: `gh issue list --state all` (#1~#13) — 호환 optimize · 감사 관련 열린 이슈 없음.
- DEF-QA2-001 → 이슈 #14
- DEF-QA2-002 → 이슈 #15 (보안 — 본문에 결함 종류 · 영향 · 관련 파일만)

경미 결함(003~010)은 CLAUDE.md 규칙상 등록 대상이지만 이번 지시(치명 · 중대만)에 따라 이 리포트에만 둔다.
