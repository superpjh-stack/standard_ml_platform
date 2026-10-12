# 계약 — 공개 API `/api/v1` (API Contract)

> **정본.** 출처: `spec.md` §12.2(묶음 15) · §7 · §8.1 · §6.1 · goal §2.3(오류 계약) · goal §6(역할). 검사: `gates/check_routes.py`(G-S04) · `tests/test_api_contract.py`.
> 1차 = 묶음 **12** (B09 review · B10 documents · B11 quotes 제외 — 이 셋은 경로는 두되 **501 `not_implemented`**).
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
| B09 review | 2 | GET | `/api/v1/tenants/{t}/tasks/{task}/review` | viewer | `GET .../review` |
| B09 review | 2 | PATCH | `/api/v1/tenants/{t}/tasks/{task}/review/{item_id}` | approver | `PATCH .../review/{id}` |
| B10 documents | 2 | POST | `/api/v1/tenants/{t}/tasks/{task}/documents` | operator | `POST .../documents` |
| B10 documents | 2 | GET | `/api/v1/tenants/{t}/tasks/{task}/documents/{doc_id}` | operator | `GET .../documents/{id}` |
| B11 quotes | 2 | POST | `/api/v1/tenants/{t}/tasks/{task}/quotes` | operator | `POST .../quotes` |
| B11 quotes | 2 | GET | `/api/v1/tenants/{t}/tasks/{task}/quotes` | operator | `GET .../quotes` |
| B11 quotes | 2 | GET | `/api/v1/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv` | operator | `GET .../quotes/{id}.csv` |
| B12 records | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/records` | viewer | `GET .../records?search=&limit=20&cursor=` |
| B13 approvals | 1 | GET | `/api/v1/tenants/{t}/approvals` | operator(조회) | `GET .../approvals` |
| B13 approvals | 1 | POST | `/api/v1/approvals/{approval_id}/decide` | approver(own_task) | `POST /approvals/{id}/decide` |
| B14 monitor | 1 | GET | `/api/v1/tenants/{t}/tasks/{task}/monitor` | operator(조회) | `GET .../monitor` |
| B14 monitor | 1 | GET | `/api/v1/tenants/{t}/doctor` | operator(조회) | `GET /doctor` (회사 범위로 둔다 — D-28) |
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
| 2차 유형 경로(B09 · B10 · B11) | 501 | `not_implemented` |

## 4. 주요 본문

| 경로 | 요청 | 응답 |
|---|---|---|
| `predict` · `predict:batch` · `optimize` | `contracts/predict-contract.md` §1 | 같은 문서 §5 |
| `actuals` | `{entity_id, value, observed_at}` | `{actual_id, linked_prediction_ids: [...]}` |
| `train` | `{source_role: "demo"\|"eval"\|"train", seed?: int}` | 202 `{run_id, status: "queued"}` · 멱등이면 200 `{run_id, status, reused: true}`. 접수만 한다 — 실행 · candidate 등록은 API 밖 작업자(`interfaces.md` §4.1, D-57). 등록부에 없는 `source_role` 은 503 `source_disconnected` |
| `runs/{id}` | — | `{run_id, status, task, snapshot: {snapshot_id, rows, ts_from, ts_to, sha256}, champion, valid_metrics, test_metrics: {name: {value, baseline, delta_vs_baseline}}, beats_baseline, version, warnings}` |
| `models` | — | `{items: [{version, stage, algo, metrics, beats_baseline, synthetic, snapshot_id, created_at, promoted_at, promoted_by}], next_cursor}` |
| `models/{v}/promote` · `rollback` | promote `{reason?}` · rollback `{reason}`(필수 — 없으면 422 `missing_required`) | 202 `{approval_id, state: "pending"}` — production 은 바뀌지 않는다 |
| `approvals/{id}/decide` | `{decision: "approve"\|"reject", reason}` | 200 `{approval_id, state, production_version}` · 409 `already_decided` |
| `overview` | — | `{task, type, production: {version, algo, trained_at, synthetic} \| null, test_metrics, baseline, predictions_yesterday, monitor: {level, alerts}}` |
| `records` | `?search&limit&cursor` | `{items: [표준 프레임 행], next_cursor, total}` |
| `monitor` | `?days=30` | `{items: [{day, metric, feature, value, level}], next_cursor}` |
| `doctor` | — | `{tenant, sources: [{role, kind, status: "연결"\|"미연결", rows, ts_from, ts_to, coverage, missing_rates, target: "있음"\|"목표 없음", message}]}` |
| `trace` | — | `{prediction: {...}, model: {version, stage, algo, artifact_sha256}, run: {run_id, config_hash, seed, code_version}, snapshot: {snapshot_id, sha256, rows, ts_from, ts_to, synthetic}, sources: [{kind, ref}], actuals: [...]}` |
| `health` | — | `{status: "ok"\|"degraded", db: bool, version, tasks: [{task, model_ready: bool, version \| null}]}` |

## 5. 호환 라우터 (D-18 — `/api/v1` 밖)

`MLP_TENANT` 가 켠 회사의 `tenants/<code>.yaml: compat.routes` 만 붙는다. 옛 키 대응은 `contracts/predict-contract.md` §7. 1차 대상: `/api/maintenance/predict`(ks) · `/api/quality/predict`(sw) · `/api/ml/optimize` · `/api/ml/overview` · `/api/data/records` · `/api/data/records/{lot_id}` · `/api/health`(옛 모양).
