# 계약 — DB 스키마 (mlp 테이블 16)

> **정본.** `src/mlcore/db/schema.sql` 은 이 문서를 구현한다. 둘이 다르면 `gates/check_schema.py`(G-S01)가 FAIL 을 낸다.
> 출처: `spec.md` §10.1(테이블 · 주요 열) · §10.2(불변 규칙). spec 의 "주요 열" 은 전부 포함하고, 구현에 필요한 열을 더했다.
> 소유: 아키텍트. 열 추가 · 변경은 `decisions.md` 에 `계약 불일치` 또는 결정으로 올린 뒤 이 문서 → schema.sql 순서로 고친다.

## 0. 수와 불변 규칙

| 항목 | 값 | 구현 | 검사 |
|---|---|---|---|
| 테이블 수 | **16** (spec §10.1 행 수와 같다) | `CREATE TABLE mlp_*` 16 | `check_schema`: 계약 표 수 = DB 수 = spec 행 수 |
| 전 테이블 `tenant_id` | 16/16 | 각 표 `tenant_id` 열 | `information_schema.columns` |
| 추가만 3 | `mlp_prediction` · `mlp_audit` · `mlp_quote` | `BEFORE UPDATE OR DELETE` 행 트리거 + `BEFORE TRUNCATE` 문 트리거 `mlp_append_only()` · 역할 `mlp_app` 에 `SELECT, INSERT` 만 | 트리거 존재 + 실제 UPDATE/DELETE 시도(롤백)가 거부되는지 |
| production 하나 | 과제당 1 | 부분 고유 색인 `mlp_model_version_one_production ON (tenant_id, task_id) WHERE stage='production'` | `pg_indexes` |
| live + synthetic 금지 | `mode=live` 회사의 `synthetic=true` 모델은 `staging` · `production` 불가 | 검사 제약 `mlp_model_version_no_live_synthetic` + `tenant_mode` 비정규화 열(트리거 `mlp_sync_tenant_mode` 가 채움) + 회사 mode 변경 전파 트리거 | `pg_constraint` + 실제 위반 INSERT 거부 |
| 기준선 미달 승격 금지 | `beats_baseline=false` 면 `candidate` · `archived` 만 | 검사 제약 `mlp_model_version_baseline_gate` | `pg_constraint` |
| 회사당 동시 학습 1 | `queued` · `running` 하나 | 부분 고유 색인 `mlp_train_run_one_active` | `pg_indexes` |
| 학습 멱등 | 같은 스냅숏 · 같은 설정 → 같은 run | `UNIQUE (tenant_id, task_id, snapshot_id, config_hash)` | — |
| 대기 승인 하나 | 같은 대상 `pending` 하나 | 부분 고유 색인 `mlp_approval_one_pending` | — |
| 키 평문 금지 | `key_hash` 는 `pbkdf2_sha256$` · `sha256$` 접두 | 검사 제약 `mlp_api_key_no_plain` | — |

ID 형식: `snapshot_id = snp_<sha256 앞 16>` · `run_id = run_<sha256(tenant·task·snapshot_id·config_hash) 앞 16>`(결정적 — 같은 스냅숏 · 설정이면 같은 run_id, 멱등 · G-M06, D-49) · `prediction_id = prd_<ulid>` · `rec_id = rec_<ulid>` · `approval_id = apr_<ulid>` · 버전 `v<n>`(과제 안 일련번호).
시각은 전부 `timestamptz`(KST 로 표시). 금액은 `numeric`.

## 1. spec §10.1 주요 열 대응

| spec 표기 | 이 계약 |
|---|---|
| `mlp_snapshot.ts_from/to` | `ts_from` · `ts_to` |
| `mlp_train_run.started/finished_at` | `started_at` · `finished_at` |
| `mlp_approval.kind(model · recommendation · quote)` | `kind` CHECK 3값 |
| 그 밖의 주요 열 | 같은 이름 |

## 2. 테이블과 열

### 1. `mlp_tenant`

| 열 | 형 | NULL |
|---|---|---|
| `tenant_id` | text | N |
| `name` | text | N |
| `pack` | text | N |
| `mode` | text | N |
| `hub_company` | text | Y |
| `config_hash` | text | Y |
| `created_at` | timestamp with time zone | N |
| `updated_at` | timestamp with time zone | N |

### 2. `mlp_task`

| 열 | 형 | NULL |
|---|---|---|
| `tenant_id` | text | N |
| `task_id` | text | N |
| `pack_task_id` | text | N |
| `type` | text | N |
| `def_hash` | text | N |
| `enabled` | boolean | N |
| `approver_role` | text | N |
| `disabled_reason` | text | Y |
| `created_at` | timestamp with time zone | N |
| `updated_at` | timestamp with time zone | N |

### 3. `mlp_source`

| 열 | 형 | NULL |
|---|---|---|
| `source_id` | bigint | N |
| `tenant_id` | text | N |
| `task_id` | text | Y |
| `role` | text | N |
| `kind` | text | N |
| `ref` | jsonb | N |
| `last_probe` | timestamp with time zone | Y |
| `status` | text | N |
| `probe_result` | jsonb | Y |
| `created_at` | timestamp with time zone | N |

### 4. `mlp_snapshot`

| 열 | 형 | NULL |
|---|---|---|
| `snapshot_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `source_id` | bigint | Y |
| `rows` | integer | N |
| `ts_from` | timestamp with time zone | Y |
| `ts_to` | timestamp with time zone | Y |
| `columns` | jsonb | N |
| `missing_rates` | jsonb | N |
| `ranges` | jsonb | N |
| `sha256` | text | N |
| `source_ref` | jsonb | N |
| `synthetic` | boolean | N |
| `path` | text | N |
| `created_at` | timestamp with time zone | N |

### 5. `mlp_train_run`

| 열 | 형 | NULL |
|---|---|---|
| `run_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `snapshot_id` | text | N |
| `config_hash` | text | N |
| `seed` | integer | N |
| `code_version` | text | N |
| `status` | text | N |
| `started_at` | timestamp with time zone | Y |
| `finished_at` | timestamp with time zone | Y |
| `log` | text | Y |
| `report` | jsonb | Y |
| `error` | jsonb | Y |
| `created_by` | text | Y |
| `created_at` | timestamp with time zone | N |

### 6. `mlp_model_version`

| 열 | 형 | NULL |
|---|---|---|
| `tenant_id` | text | N |
| `task_id` | text | N |
| `version` | text | N |
| `run_id` | text | N |
| `snapshot_id` | text | N |
| `algo` | text | N |
| `metrics` | jsonb | N |
| `beats_baseline` | boolean | N |
| `stage` | text | N |
| `artifact_path` | text | N |
| `artifact_sha256` | text | N |
| `env_lock` | jsonb | N |
| `code_version` | text | N |
| `synthetic` | boolean | N |
| `tenant_mode` | text | N |
| `approval_id` | text | Y |
| `created_at` | timestamp with time zone | N |
| `staged_at` | timestamp with time zone | Y |
| `promoted_at` | timestamp with time zone | Y |
| `promoted_by` | text | Y |

### 7. `mlp_prediction`

| 열 | 형 | NULL |
|---|---|---|
| `prediction_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `version` | text | N |
| `entity_id` | text | Y |
| `inputs` | jsonb | N |
| `outputs` | jsonb | N |
| `status` | text | N |
| `caller` | text | N |
| `channel` | text | N |
| `synthetic` | boolean | N |
| `ts` | timestamp with time zone | N |

### 8. `mlp_actual`

| 열 | 형 | NULL |
|---|---|---|
| `actual_id` | bigint | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `entity_id` | text | N |
| `value` | double precision | N |
| `observed_at` | timestamp with time zone | N |
| `source` | text | N |
| `created_by` | text | Y |
| `created_at` | timestamp with time zone | N |

### 9. `mlp_recommendation`

| 열 | 형 | NULL |
|---|---|---|
| `rec_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `fixed_inputs` | jsonb | N |
| `candidates` | jsonb | N |
| `uses_versions` | jsonb | N |
| `feasible` | boolean | N |
| `status` | text | N |
| `applied_at` | timestamp with time zone | Y |
| `applied_by` | text | Y |
| `created_by` | text | Y |
| `created_at` | timestamp with time zone | N |

### 10. `mlp_review_item`

| 열 | 형 | NULL |
|---|---|---|
| `item_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `entity_id` | text | N |
| `prediction_id` | text | Y |
| `predicted` | double precision | Y |
| `actual` | double precision | Y |
| `residual` | double precision | N |
| `reason` | text | N |
| `origin` | text | N |
| `state` | text | N |
| `created_at` | timestamp with time zone | N |
| `updated_at` | timestamp with time zone | N |

### 11. `mlp_document`

| 열 | 형 | NULL |
|---|---|---|
| `doc_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `filename` | text | N |
| `raw_sha256` | text | N |
| `raw_path` | text | N |
| `result` | jsonb | Y |
| `extractor_name` | text | Y |
| `extractor_version` | text | Y |
| `created_by` | text | Y |
| `created_at` | timestamp with time zone | N |

### 12. `mlp_quote`

| 열 | 형 | NULL |
|---|---|---|
| `quote_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `doc_id` | text | Y |
| `lines` | jsonb | N |
| `total` | numeric | N |
| `overrides` | jsonb | N |
| `model_versions` | jsonb | N |
| `reviewed` | boolean | N |
| `reviewed_by` | text | Y |
| `review_note` | text | Y |
| `created_at` | timestamp with time zone | N |

### 13. `mlp_monitor_daily`

| 열 | 형 | NULL |
|---|---|---|
| `monitor_id` | bigint | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `day` | date | N |
| `metric` | text | N |
| `feature` | text | N |
| `value` | double precision | Y |
| `level` | text | N |
| `detail` | jsonb | N |
| `created_at` | timestamp with time zone | N |

### 14. `mlp_approval`

| 열 | 형 | NULL |
|---|---|---|
| `approval_id` | text | N |
| `tenant_id` | text | N |
| `task_id` | text | N |
| `kind` | text | N |
| `ref_id` | text | N |
| `action` | text | N |
| `approver_role` | text | N |
| `state` | text | N |
| `requested_by` | text | N |
| `requested_at` | timestamp with time zone | N |
| `expires_at` | timestamp with time zone | Y |
| `decided_by` | text | Y |
| `decided_at` | timestamp with time zone | Y |
| `reason` | text | Y |
| `evidence` | jsonb | N |

### 15. `mlp_audit`

| 열 | 형 | NULL |
|---|---|---|
| `audit_id` | bigint | N |
| `tenant_id` | text | N |
| `ts` | timestamp with time zone | N |
| `actor` | text | N |
| `role` | text | Y |
| `action` | text | N |
| `target` | text | Y |
| `detail` | jsonb | N |
| `request_id` | text | Y |

### 16. `mlp_api_key`

| 열 | 형 | NULL |
|---|---|---|
| `key_id` | bigint | N |
| `tenant_id` | text | N |
| `key_hash` | text | N |
| `key_prefix` | text | N |
| `role` | text | N |
| `approver_roles` | jsonb | N |
| `consumer` | text | N |
| `active` | boolean | N |
| `created_at` | timestamp with time zone | N |
| `revoked_at` | timestamp with time zone | Y |

## 3. 상태 열의 값 (CHECK)

| 테이블.열 | 값 |
|---|---|
| `mlp_tenant.mode` | demo · eval · live |
| `mlp_task.type` | regression · risk · anomaly · optimize · review_queue · extract · quote (`std/task_types.yaml`) |
| `mlp_source.kind` | synthetic · csv · gateway · dataplatform · mes |
| `mlp_source.role` | train · actuals · demo · monitor |
| `mlp_source.status` | connected · disconnected · unknown |
| `mlp_train_run.status` | queued · running · succeeded · failed |
| `mlp_model_version.stage` | candidate · staging · production · archived |
| `mlp_prediction.status` | ok · watch · review · out_of_range · rejected · needs_approval (`std/statuses.yaml`) |
| `mlp_prediction.channel` | api · batch · console · compat · optimize |
| `mlp_actual.source` | api · csv · mes · dataplatform · gateway · synthetic |
| `mlp_recommendation.status` | needs_approval · approved · rejected · applied · dismissed |
| `mlp_review_item.state` | open · confirmed_issue · false_alarm |
| `mlp_review_item.origin` | test_split · live_residual (학습 구간 잔차 금지) |
| `mlp_monitor_daily.metric` | psi · oor_rate · missing_rate · live_perf · volume · error_rate · source_health |
| `mlp_monitor_daily.level` | ok · warn · retrain |
| `mlp_approval.kind` | model · recommendation · quote |
| `mlp_approval.action` | promote · rollback · apply · confirm |
| `mlp_approval.state` | pending · approved · rejected · expired |
| `mlp_api_key.role` | viewer · operator · approver · admin (`std/roles.yaml`) |

## 4. 쓰기 경로 (누가 어떤 열을 바꾸는가)

| 열 | 유일한 쓰기 경로 |
|---|---|
| `mlp_model_version.stage → production` | `approval.decide()` (같은 트랜잭션: 조건부 UPDATE `mlp_approval WHERE state='pending'` → 기존 production `archived` → 새 버전 `production` → `mlp_audit` INSERT). `gates/check_no_autopromote.py` |
| `mlp_model_version.stage → staging` | 등록부 `stage()` (admin, 기준선 이김 · 차단 경고 없음) |
| `mlp_prediction` | `serve.record` INSERT 만 |
| `mlp_audit` | `audit.write` INSERT 만 |
| `mlp_recommendation.status → applied/dismissed` | 소비자 기록 API. 설비 쓰기 없음 |

## 5. 보존 (D-10)

예측 · 감사 1년 · 감시 집계 영구 · production 이었던 버전의 산출물 영구 · 나머지 스냅숏 · 산출물 90일. 추가만 테이블의 1년 경과 삭제는 별도 보존 작업(소유자 권한, 트리거를 우회하지 않고 파티션 분리 방식으로 — 2차 설계).
