# 계약 — 공개 API `/api/v1` (API Contract)

> **정본.** 출처: `spec.md` §12.2(묶음 15) · §7 · §8.1 · §6.1 · goal §2.3(오류 계약) · goal §6(역할). 검사: `gates/check_routes.py`(G-S04) · `tests/test_api_contract.py`.
> 묶음 **15** 전부 단계 1(구현). 1차 12 + 2차 B09 review · B10 documents · B11 quotes — 웨이브 P 마감(아키텍트, `core-freeze-2` 전)에 §6 의 행을 §1 로 합쳤다. 2차 오류 · 업로드 규칙 · 호환 라우터는 §6.
> 인증: 헤더 `X-API-Key`. 키는 `mlp_api_key.key_hash` 로만 저장된다(평문 0). `GET /api/v1/health` 만 인증 없음. 키의 `tenant_id` 와 경로 `{t}` 가 다르면 **404 `not_found`**(존재 숨김).

## 1. 묶음 15 (기계 판독 — `check_routes.py` 가 이 표를 읽는다)

| 묶음 | 단계 | 메서드 | 경로 | 최소 역할 | spec §12.2 |
|---|---|---|---|---|---|
| B01 health | 1 | GET | `/api/v1/health` | 없음 | `GET /health` |
| B02 tasks | 1 | GET | `/api/v1/tenants/{t}/tasks` | viewer | `GET /tenants/{t}/tasks` |
| B02 tasks | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}` | viewer | `GET .../tasks/{task}` |
| B03 predict | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/predict` | operator | `POST .../predict` |
| B03 predict | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/predict:batch` | operator | `predict:batch` |
| B04 optimize | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/optimize` | operator | `POST .../optimize` |
| B05 actuals | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/actuals` | operator | `POST .../actuals` |
| B06 overview | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/overview` | viewer | `GET .../overview` |
| B07 models | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/models` | approver(조회) | `GET .../models` |
| B07 models | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/models/{v}/stage` | admin | (보강 D-28: candidate→staging) |
| B07 models | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/models/{v}/promote` | approver | `POST .../promote` — **승인 요청만 만든다** |
| B07 models | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/models/{v}/rollback` | approver | `rollback` — 승인 요청(사유 필수) |
| B08 train | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/train` | admin | `POST .../train` |
| B08 train | 1 | GET | `/api/v1/runs/{run_id}` | approver(조회) | `GET /runs/{id}` |
| B09 review | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/review` | operator(조회) | `GET .../review` — `?state=&cursor=&limit=` → `{items: [ReviewItem], next_cursor, total, can_decide}` (viewer ✕ — goal2 §6 · `can_decide` = 이 키가 이 과제 PATCH 판정을 할 수 있는가 — 화면 8 결정 버튼 표시, C2 D2-93) |
| B09 review | 1 | PATCH | `/api/v1/tenants/{t}/tasks/{task}/review/{item_id}` | approver(own_task) | `PATCH .../review/{id}` — `{state: confirmed_issue\|false_alarm, note}` → 200 ReviewItem · 닫힘 409 `already_decided` |
| B10 documents | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/documents` | operator | `POST .../documents` — multipart `file` · `unit_override?` → 201 DocumentExtraction |
| B10 documents | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/documents` | operator | 목록 `?search=&cursor=&limit=` → `{items: [DocumentExtraction 요약], next_cursor, total}` (화면 9) |
| B10 documents | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/documents/{doc_id}` | operator | `GET .../documents/{id}` → DocumentExtraction · 다른 회사 · 없음 404 |
| B11 quotes | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/quotes` | operator | `POST .../quotes` — `{doc_id?, inputs, lines?, reviewed, review_note}` → 201 Quote(`draft`) · `lines` 는 과제 `line_limits` + 코어 기본(task-contract §6.3) — 밖이면 422 `invalid_input`(field `lines.<i>.<키>`), 음수 금액 422 (C2 D2-90) |
| B11 quotes | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/quotes` | operator | `GET .../quotes` — `?search=&cursor=&limit=` → `{items: [Quote], next_cursor, total}` |
| B11 quotes | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}` | operator | → Quote(최신 revision) |
| B11 quotes | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}/revisions` | operator | Quote 와 같은 본문 → 201 Quote(revision+1, `draft`) · 확정 견적 409 `quote_locked` |
| B11 quotes | 1 | POST | `/api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}/confirm` | operator(요청) | `{reviewed: true, review_note}` → 202 `{approval_id, state: pending}` · 검토 없음 422 `missing_required` · 이미 확정 409 `quote_locked`. **확정 결정은 B13 decide(approver 이상 — D2-04 · D2-19)** |
| B11 quotes | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv` | operator | `GET .../quotes/{id}.csv` — UTF-8 BOM · 수식 주입 방지 · 금액 문자열 그대로 |
| B12 records | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/records` | viewer | `GET .../records?search=&limit=20&cursor=` |
| B13 approvals | 1 | GET | `/api/v1/tenants/{t}/approvals` | operator(조회) | `GET .../approvals` |
| B13 approvals | 1 | POST | `/api/v1/approvals/{approval_id}/decide` | approver(own_task) | `POST /approvals/{id}/decide` |
| B14 monitor | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/monitor` | operator(조회) | `GET .../monitor` |
| B14 monitor | 1 | GET | `/api/v1/tenants/{t}/doctor` | approver(조회) | `GET /doctor` (회사 범위로 둔다 — D-28). 권한은 화면 7 `sources`(goal2 §6 operator ✕ 정본 — D2-103) |
| B15 trace | 1 | GET | `/api/v1/predictions/{prediction_id}/trace` | admin | `GET /predictions/{id}/trace` |

## 2. 공통 규칙

- **오류 봉투:** `{"error": {"code": <std/statuses.yaml error_codes>, "message": <한국어>, "detail": {...}}}`. `detail` 에 입력값을 되풀이하지 않는다(`field` · `rule` 만). FastAPI 기본 `{"detail": …}` 422 는 쓰지 않는다(호환 라우터만 예외).
- **목록:** `{"items": [...], "next_cursor": <불투명 문자열 | null>, "total": <int, 선택>}`. 인자 `search` · `limit`(기본 20, 1~100) · `cursor`. `q` · `offset` · `records` 키 없음(F2 통일).
- **시각:** ISO-8601 + `+09:00`. **멱등:** `POST .../train` 같은 스냅숏 · 설정 → 200 + 기존 `run_id`(새 학습 없음).
- **응답 헤더:** `X-Request-Id`(감사 로그 `request_id` 와 같다).

## 3. 오류 계약 (goal §2.3 — QA 시험 케이스)

| 상황 | HTTP | code |
|---|---|---|
| 모르는 키 · NaN · Infinity · 형 불일치 · batch > 500 | 422 | `invalid_input` |
| 필수 변수 누락 · `max_imputed` 초과 | 422 | `missing_required` |
| `min/max` 밖 · 범주 값이 `values`(또는 회사 `categories`) 밖 (D-55) | 422 | `out_of_bounds` (detail.rule = `min` · `max` · `values`) |
| 되돌리기 요청에 `reason` 없음 (D-54) | 422 | `missing_required` (detail.field = `reason`) |
| 학습 범위 밖 | 200 | 응답 `status: out_of_range` (`reject` 정책이면 `rejected`) |
| production 없음 | 503 | `model_not_ready` (대체 · 기본값 응답 없음) |
| 산출물 해시 · 패키지 버전 불일치 | 503 | `model_artifact_mismatch` |
| 소스 실패(train) | 503 | `source_disconnected` (doctor 는 200 + 소스별 `미연결`) |
| 학습할 목표 열 없음(train, 지도학습) | 503 | `source_disconnected` (detail.rule = `no_target`, 문구 `목표 없음`) |
| 키 없음 · 틀림 | 401 | `auth_required` |
| 역할 밖 | 403 | `forbidden` |
| 다른 회사 · 없는 과제 · 없는 예측 ID | 404 | `not_found` |
| 이미 결정 · 만료된 승인 | 409 | `already_decided` |
| 등록부 전이 규칙 위반 — candidate 아닌 것을 stage · 기준선 미달 · 차단 경고 · live 회사의 합성 모델 · staging 아닌 것을 promote · archived 아닌 것을 rollback (D-54) | 409 | `invalid_transition` (detail.rule = `from_candidate_only` · `baseline` · `blocking_warning` · `live_synthetic` · `from_staging_only` · `from_archived_only`) |
| 회사당 동시 학습 1개 초과 — queued · running 이 이미 있음 (spec §5.5, D-54) | 409 | `train_busy` (detail.rule = `tenant_concurrency`) |
| 2차 유형 경로(B09 · B10 · B11)를 그 유형이 아닌 과제로 | 404 | `not_found` (detail.rule = `type_route` — §6.1, D2-20). 501 경로는 없다(G2-T01) |

## 4. 주요 본문

| 경로 | 요청 | 응답 |
|---|---|---|
| `predict` · `predict:batch` · `optimize` | `contracts/predict-contract.md` §1 | 같은 문서 §5 |
| `actuals` | `{entity_id, value, observed_at}` | `{actual_id, linked_prediction_ids: [...]}` |
| `train` | `{source_role: "demo"\|"eval"\|"train", seed?: int}` | 202 `{run_id, status: "queued"}` · 멱등이면 200 `{run_id, status, reused: true}` — 단 같은 run_id 의 **failed** 실행 재접수는 새 실행(학습기가 queued 로 되돌림 · 감사 `train.retry`)이라 202 (D-64). 접수만 한다 — 실행 · candidate 등록은 API 밖 작업자(`interfaces.md` §4.1, D-57). 등록부에 없는 `source_role` 은 503 `source_disconnected` |
| `runs/{id}` | — | `{run_id, status, task, snapshot: {snapshot_id, rows, ts_from, ts_to, sha256}, champion, valid_metrics, test_metrics: {name: {value, baseline, delta_vs_baseline}}, beats_baseline, version, warnings}` + 덧붙임(D-63): `stage · seed · code_version · config_hash · created_at · started_at · finished_at · error · report{선정 사유 · 기준선 종류 · 구간 · 보정 · 임계값 · 중요도 · 잔차 · 보정 곡선 …}`. 다른 회사 · 없음 → 404 |
| `models` | — | `{items: [{version, run_id, stage, algo, metrics, beats_baseline, synthetic, snapshot_id, created_at, promoted_at, promoted_by}], next_cursor}` |
| `models/{v}/promote` · `rollback` | promote `{reason?}` · rollback `{reason}`(필수 — 없으면 422 `missing_required`) | 202 `{approval_id, state: "pending"}` — production 은 바뀌지 않는다 |
| `approvals/{id}/decide` | `{decision: "approve"\|"reject", reason}` | 200 `{approval_id, state, production_version}` · 409 `already_decided` |
| `overview` | — | `{task, type, production: {version, algo, trained_at, synthetic} \| null, test_metrics, baseline, predictions_yesterday, monitor: {level, alerts}}` |
| `records` | `?search&limit&cursor` | `{items: [표준 프레임 행], next_cursor, total}` |
| `monitor` | `?days=30` | `{items: [{day, metric, feature, value, level}], next_cursor}` |
| `doctor` | — | `{tenant, sources: [{role, kind, status: "연결"\|"미연결", rows, ts_from, ts_to, coverage, missing_rates, target: "있음"\|"목표 없음", message}]}` |
| `trace` | — | `{prediction: {...}, model: {version, stage, algo, artifact_sha256}, run: {run_id, config_hash, seed, code_version}, snapshot: {snapshot_id, sha256, rows, ts_from, ts_to, synthetic}, sources: [{kind, ref}], actuals: [...]}` |
| `health` | — | `{status: "ok"\|"degraded", db: bool, version, tasks: [{task, type, model_ready: bool, model_required: bool, version \| null, uses: [{task, version \| null}] \| null}]}` — `model_required` false = 자기 모델이 없는 과제(규칙 extract · quote · optimize · review_queue). 그때 `model_ready` = 규칙 추출만이면 true, `uses` 가 있으면 그 과제 production 이 전부 있을 때 true (C2 D2-94) |

**덧붙인 키(D-78).** 위 표의 키는 전부 필수다(빼거나 선택으로 바꾸지 않는다). 아래 키는 화면이 쓰는 **덧붙임**으로 계약에 올린다 — 이름 · 뜻을 바꾸려면 계약 절차.
- `doctor`: 응답 `mode` · `warnings`, `sources[]` 에 `targets`(과제별 목표 판정) · `unmapped`(정적 대응 밖 변수).
- `monitor`: `total` · `last_day` · `retrain_candidates`(화면 6 재학습 후보 링크) · 요청 `?metric=`(psi · oor_rate · missing_rate · live_perf · volume · error_rate · source_health).
- `tasks` 목록: 응답 `tenant` · `disabled`, 항목 `production` · `uses`.
- `overview`: 항목 `title` · `model_ready` · `model_required` · `uses` · `pending_approvals`, `monitor.day` · `monitor.note`. `uses` 는 optimize · quote · review_queue 의 의존 과제 `[{task, version, synthetic}]`(그 밖 null) — `model_ready` 판정은 health 와 같다(C2 D2-94).

## 5. 호환 라우터 (D-18 — `/api/v1` 밖)

`MLP_TENANT` 가 켠 회사의 `tenants/<code>.yaml: compat.routes` 만 붙는다. 옛 키 대응은 `contracts/predict-contract.md` §7. 1차 대상: `/api/maintenance/predict`(ks) · `/api/quality/predict`(sw) · `/api/ml/optimize` · `/api/ml/overview` · `/api/data/records` · `/api/data/records/{lot_id}` · `/api/health`(옛 모양).

**인증(D-59 확정 — 사람 결정 2026-10-12).** 옛 health 꼴(`/api/health`)만 키 없이 연다. 나머지 호환 경로는 표준과 같이 `X-API-Key` + `std/roles.yaml` 역할 판정 · 다른 회사 키 404. 키 없는 옛 클라이언트는 401(옛 오류 모양 `{"detail": …}`) — 열어 두지 않는다. 회사 고유 값: `tenants/<code>.yaml compat.round`(옛 응답 반올림 자리, 없으면 반올림 안 함 · 위험 확률만 기본 4) · `compat.optimize_rename`(선택, D-71).

**2차 객체 경로(웨이브 P 마감 — `core-freeze-2` 전 장치, D2-45).** `compat.routes` 항목은 문자열(1차 — 접미사 추론) 또는 객체 `{path, method?, action, task?, shape?, params?}`. `path` 는 `/api/` 아래(`/api/v1` 제외), 경로 인자는 한 마디 전체 `{이름}`. 여러 객체가 맞으면 경로 인자가 적은 것이 먼저, 같으면 적힌 순서. 동작(method · 권한 영역 · 과제 유형): `health`(GET, 키 없음) · `overview` · `records` · `record` · `predict` · `optimize`(1차 그대로) · `predict_one`(POST predict, regression\|risk\|anomaly 한 과제) · `samples`(GET overview, `limit/offset`, 기본 `params.limit` 12) · `review_list`(GET review, `limit/state`, 결과에 과제 `rule`) · `document_upload`(POST quotes, multipart `params.file_field`=file — 확장자가 아니면 **415**(원천 모양), 크기 · 엔티티 413, 그 밖 422) · `document_demo`(POST, 회사 · 팩 `samples/<params.file>` 을 업로드 흐름으로) · `document_get` · `pack_file`(GET overview, 회사 `tenants/<code>/samples/` → 팩 `samples/` 순서의 파일만 — `.json` 은 JSON, 그 밖은 원본 바이트, 경로 탈출 404 · D2-A2-04) · `quote_create`(POST quotes — **draft 만**, 확정은 표준 경로 · 승인) · `quote_list`(옛 `search/offset/limit` → `{total, offset, limit, records}`) · `quote_get` · `quote_csv` · `quote_export_csv`(`params.columns`, BOM · 수식 주입 방지). 오류: 표준 422 → 옛 `{"detail":[{loc,msg,type}]}`, 그 밖 → `{"detail", "code"[, "rule"]}`. 설정 결함 503 `compat_config_error`, 플러그인 결함 503 `compat_plugin_error`(숨기지 않는다 — 표준 결과로 대신하지 않는다). 응답 기본 200(`params.status` 로 바꾼다). 등록부 로더가 기동 때 같은 표(`serve/compat_routes.py`)로 객체 항목을 검사한다 — 틀리면 T0 거부. 회사 모양 플러그인은 `predict-contract.md` §7.

## 6. 2차 — B09 review · B10 documents · B11 quotes 상세 (Phase P0 아키텍트 → 웨이브 P 마감에 §1 로 합침)

> 경로 · 역할 · 요청 → 응답은 **§1 표(기계 판독)** 가 정본이다 — 웨이브 P 마감(아키텍트)에 이 절의 표를 §1 로 옮기고 단계를 `1` 로 바꿨다.
> 그래서 `test_contract_counts` 는 단계 1 묶음 15 · 단계 2 묶음 0, G-S04 는 15/15 를 본다. 응답 모양은 `predict-contract.md` §8, 키는 `task-contract.md` §6, 역할은 goal2 §6(→ `std/roles.yaml`).

### 6.1 오류 계약 추가 (goal2 §2.1 — `std/statuses.yaml error_codes` 에 웨이브 P 가 추가)

| 상황 | HTTP | code |
|---|---|---|
| DXF 아님(확장자 · 바이너리 DXF · 파싱 실패 · 단위 미지정인데 `unit_override` 없음 · NUL 문자 — 원본 또는 추출 결과) | 422 | `invalid_document` (detail.rule = `format` · `binary` · `parse` · `unit` · `nul` — C2 D2-92) — 원천 415 는 호환 라우터만 |
| 5 MiB · 20,000 엔티티(또는 과제 `document` 상한) 초과 · 좌표 · 꼭짓점 상한 초과 · 영역 안 텍스트 합계 상한(추출기 params `max_region_texts`) 초과 · 추출 시간 · 결과 상한 초과(task-contract §6.2 `document` — 코어) | 413 | `document_too_large` (detail.rule = `bytes` · `entities` · `vertices` · `points` · `region_texts` — D2-101 · `time` · `items` · `result_bytes` · `resources` — C2 D2-91) |
| 학습 대상이 아닌 과제(review_queue · 규칙 extract · quote · optimize)에 `train` | 422 | `invalid_input` (detail.rule = `not_trainable`, detail.type — 전용 코드 두지 않음, D2-82 · D2-107) |
| 정답 라벨 없음(평가 요청) | 200 | `labels: "none"` · `metrics: null` |
| 검토 없는 견적 확정 | 422 | `missing_required` (detail.field = `reviewed` · `review_note`) |
| 확정된 견적 수정 · 재확정 | 409 | `quote_locked` |
| 대기열 항목 재검토(닫힘) | 409 | `already_decided` |
| 2차 유형 과제에 `predict` · `optimize` | 404 | `not_found` (detail.rule = `type_route`) |
| 견적의 `uses` 과제 production 없음 | 503 | `model_not_ready` (견적 초안을 만들지 않는다 — 대체 금액 0) |

업로드는 스트림으로 `max_bytes + 1` 까지만 읽는다(원천 kd `main.py:93`). 파일 이름은 경로를 떼고 150자(원천 `:91`). 원본은 `var/documents/<tenant>/<sha256>.dxf`(커밋 금지, D2-05).

### 6.2 Agent 도구 · 허브 내보내기

Agent `ml.*` 도구는 위 공개 API 위의 얇은 어댑터다 — 정본 `contracts/agent-tools.md`. 허브 내보내기 파일 형식은 `contracts/hub-export.md`. 둘 다 새 HTTP 경로를 만들지 않는다(묶음 15 그대로).

### 6.3 호환 라우터 (2차 4개사 — D-18, `tenants/<code>.yaml compat.routes`)

| 회사 | 옛 경로 (원천 `api/main.py`) |
|---|---|
| krs | `/api/health` · `/api/ml/overview` · `/api/ml/samples` · `/api/ml/optimize` · `/api/quality/overview` · `/api/quality/predict` · `/api/data/records` |
| pc | `/api/health` · `/api/ml/overview` · `/api/ml/optimize` · `/api/quality/predict` · `/api/quality/overview` · `/api/data/records` |
| ot | `/api/health` · `/api/ml/overview` · `/api/data/demo` · `/api/cad/sample.dxf` · `/api/cad/demo` · `/api/cad/analyze` · `/api/cad/{id}` · `/api/quotes` · `/api/quotes/{id}` · `/api/quotes/{id}/csv` |
| kd | `/api/health` · `/api/ml/overview` · `/api/cad/sample.dxf` · `/api/cad/demo` · `/api/cad/analyze` · `/api/cad/{id}` · `/api/quotes` · `/api/quotes/export/csv` · `/api/quotes/{id}` · `/api/quotes/{id}/csv` |

호환 인증 규칙은 §5(D-59) 그대로 — 옛 health 만 키 없이. 옛 견적 경로는 원천에 확정이 없으므로 `draft` 만 만들고, 확정은 표준 경로 · 승인으로만.
