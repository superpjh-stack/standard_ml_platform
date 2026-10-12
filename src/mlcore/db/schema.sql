-- 표준 ML 플랫폼 — mlp_* 테이블 16 (spec §10.1 · §10.2, contracts/db-schema.md 가 정본)
-- 적용: psql -h /tmp -d ml_db -f src/mlcore/db/schema.sql   (make db-schema CONFIRM=1 — 데이터를 전부 지운다)
-- 기존 DB 의 보호 · 권한만 다시: make db-grants (아래 `-- @grants-begin` 구간만, 비파괴)
-- 불변 규칙
--   1. 모든 테이블에 tenant_id (회사당 배포여도 둔다, D-01)
--   2. mlp_prediction · mlp_audit · mlp_quote 는 추가만 — UPDATE · DELETE · TRUNCATE 트리거(ENABLE ALWAYS) 거부 + mlp_app 권한 회수
--   3. 과제마다 stage='production' 은 하나 — 부분 고유 색인
--   4. mode=live 회사의 synthetic 모델은 staging · production 불가 — 검사 제약(tenant_mode 비정규화 + 동기화 트리거)

SET client_min_messages = warning;

DROP TABLE IF EXISTS mlp_api_key, mlp_audit, mlp_approval, mlp_monitor_daily, mlp_quote, mlp_document,
    mlp_review_item, mlp_recommendation, mlp_actual, mlp_prediction, mlp_model_version, mlp_train_run,
    mlp_snapshot, mlp_source, mlp_task, mlp_tenant CASCADE;

-- 1 회사
CREATE TABLE mlp_tenant (
    tenant_id    text PRIMARY KEY CHECK (tenant_id ~ '^[a-z][a-z0-9]{1,7}$'),
    name         text NOT NULL,
    pack         text NOT NULL,
    mode         text NOT NULL CHECK (mode IN ('demo', 'eval', 'live')),
    hub_company  text,
    config_hash  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- 2 과제(정의 해시)
CREATE TABLE mlp_task (
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,                     -- <tenant>.<task>
    pack_task_id  text NOT NULL,                     -- <pack>.<task>
    type          text NOT NULL CHECK (type IN ('regression', 'risk', 'anomaly', 'optimize', 'review_queue', 'extract', 'quote')),
    def_hash      text NOT NULL,
    enabled       boolean NOT NULL DEFAULT true,
    approver_role text NOT NULL,
    disabled_reason text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, task_id)
);

-- 3 데이터 소스 설정 · 상태
CREATE TABLE mlp_source (
    source_id    bigserial PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id      text,
    role         text NOT NULL CHECK (role IN ('train', 'actuals', 'demo', 'monitor')),
    kind         text NOT NULL CHECK (kind IN ('synthetic', 'csv', 'gateway', 'dataplatform', 'mes')),
    ref          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 뷰 · 테이블 · 파일 · 환경변수 이름(값 아님)
    last_probe   timestamptz,
    status       text NOT NULL DEFAULT 'unknown' CHECK (status IN ('connected', 'disconnected', 'unknown')),
    probe_result jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, role, kind, ref)
);

-- 4 학습 스냅숏
CREATE TABLE mlp_snapshot (
    snapshot_id   text PRIMARY KEY,                    -- snp_<sha256 앞 16>
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    source_id     bigint REFERENCES mlp_source (source_id),
    rows          integer NOT NULL CHECK (rows >= 0),
    ts_from       timestamptz,
    ts_to         timestamptz,
    columns       jsonb NOT NULL,
    missing_rates jsonb NOT NULL DEFAULT '{}'::jsonb,
    ranges        jsonb NOT NULL DEFAULT '{}'::jsonb,  -- 변수별 {p1, p99} — 학습 범위
    sha256        text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    source_ref    jsonb NOT NULL DEFAULT '{}'::jsonb,
    synthetic     boolean NOT NULL,
    path          text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    UNIQUE (tenant_id, task_id, sha256)
);

-- 5 학습 작업
CREATE TABLE mlp_train_run (
    run_id       text PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id      text NOT NULL,
    snapshot_id  text NOT NULL REFERENCES mlp_snapshot (snapshot_id),
    config_hash  text NOT NULL,
    seed         integer NOT NULL,
    code_version text NOT NULL,
    status       text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    started_at   timestamptz,
    finished_at  timestamptz,
    log          text,
    report       jsonb,
    error        jsonb,
    created_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    UNIQUE (tenant_id, task_id, snapshot_id, config_hash)      -- 같은 스냅숏 · 같은 설정 = 멱등
);
-- 회사당 동시 학습 1개 (spec §5.5)
CREATE UNIQUE INDEX mlp_train_run_one_active ON mlp_train_run (tenant_id) WHERE status IN ('queued', 'running');

-- 6 모델 버전
CREATE TABLE mlp_model_version (
    tenant_id       text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id         text NOT NULL,
    version         text NOT NULL CHECK (version ~ '^v[1-9][0-9]*$'),
    run_id          text NOT NULL REFERENCES mlp_train_run (run_id),
    snapshot_id     text NOT NULL REFERENCES mlp_snapshot (snapshot_id),
    algo            text NOT NULL,
    metrics         jsonb NOT NULL,                    -- {name: {value, baseline, delta_vs_baseline}}
    beats_baseline  boolean NOT NULL,
    stage           text NOT NULL DEFAULT 'candidate' CHECK (stage IN ('candidate', 'staging', 'production', 'archived')),
    artifact_path   text NOT NULL,
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    env_lock        jsonb NOT NULL,
    code_version    text NOT NULL,
    synthetic       boolean NOT NULL,
    tenant_mode     text NOT NULL DEFAULT 'demo' CHECK (tenant_mode IN ('demo', 'eval', 'live')),  -- 트리거가 mlp_tenant.mode 로 채운다
    approval_id     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    staged_at       timestamptz,
    promoted_at     timestamptz,
    promoted_by     text,
    PRIMARY KEY (tenant_id, task_id, version),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    -- 기준선을 못 이기면 candidate 까지만 (spec §2.4 · G-M05)
    CONSTRAINT mlp_model_version_baseline_gate CHECK (beats_baseline OR stage IN ('candidate', 'archived')),
    -- live 회사에서 합성 스냅숏 모델은 staging · production 불가 (spec §10.2-4)
    CONSTRAINT mlp_model_version_no_live_synthetic CHECK (NOT (synthetic AND tenant_mode = 'live' AND stage IN ('staging', 'production')))
);
-- 과제마다 production 하나 (spec §10.2-3)
CREATE UNIQUE INDEX mlp_model_version_one_production ON mlp_model_version (tenant_id, task_id) WHERE stage = 'production';

CREATE OR REPLACE FUNCTION mlp_sync_tenant_mode() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    SELECT mode INTO NEW.tenant_mode FROM mlp_tenant WHERE tenant_id = NEW.tenant_id;
    RETURN NEW;
END $$;
CREATE TRIGGER mlp_model_version_tenant_mode BEFORE INSERT OR UPDATE ON mlp_model_version
    FOR EACH ROW EXECUTE FUNCTION mlp_sync_tenant_mode();

-- 회사 mode 가 바뀌면 모델 행에 전파 → live 전환 시 합성 운영 모델이 있으면 검사 제약이 거부한다
CREATE OR REPLACE FUNCTION mlp_propagate_tenant_mode() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.mode IS DISTINCT FROM OLD.mode THEN
        UPDATE mlp_model_version SET tenant_mode = NEW.mode WHERE tenant_id = NEW.tenant_id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlp_tenant_mode_propagate AFTER UPDATE OF mode ON mlp_tenant
    FOR EACH ROW EXECUTE FUNCTION mlp_propagate_tenant_mode();

-- 7 예측 기록 (추가만)
CREATE TABLE mlp_prediction (
    prediction_id text PRIMARY KEY,                  -- prd_<ulid>
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    version       text NOT NULL,
    entity_id     text,
    inputs        jsonb NOT NULL,
    outputs       jsonb NOT NULL,                    -- 표준 응답 전체 (contracts/predict-contract.md)
    status        text NOT NULL CHECK (status IN ('ok', 'watch', 'review', 'out_of_range', 'rejected', 'needs_approval')),
    caller        text NOT NULL,
    channel       text NOT NULL DEFAULT 'api' CHECK (channel IN ('api', 'batch', 'console', 'compat', 'optimize', 'quote')),
    synthetic     boolean NOT NULL,
    ts            timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id, version) REFERENCES mlp_model_version (tenant_id, task_id, version)
);
CREATE INDEX mlp_prediction_entity ON mlp_prediction (tenant_id, task_id, entity_id);
CREATE INDEX mlp_prediction_ts ON mlp_prediction (tenant_id, task_id, ts);

-- 8 실측
CREATE TABLE mlp_actual (
    actual_id     bigserial PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    entity_id     text NOT NULL,
    value         double precision NOT NULL,
    observed_at   timestamptz NOT NULL,
    source        text NOT NULL CHECK (source IN ('api', 'csv', 'mes', 'dataplatform', 'gateway', 'synthetic')),
    created_by    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    UNIQUE (tenant_id, task_id, entity_id, observed_at)
);

-- 9 최적화 추천
CREATE TABLE mlp_recommendation (
    rec_id        text PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    fixed_inputs  jsonb NOT NULL,
    candidates    jsonb NOT NULL,                    -- 상위 5 · 제약별 충족/여유
    uses_versions jsonb NOT NULL,                    -- {"<task>": "v<n>"}
    feasible      boolean NOT NULL,
    status        text NOT NULL DEFAULT 'needs_approval' CHECK (status IN ('needs_approval', 'approved', 'rejected', 'applied', 'dismissed')),
    applied_at    timestamptz,
    applied_by    text,
    created_by    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id)
);

-- 10 검토 대기열 (2차 유형 — 테이블은 1차에 만든다)
CREATE TABLE mlp_review_item (
    item_id       text PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    entity_id     text NOT NULL,
    prediction_id text,
    predicted     double precision,
    actual        double precision,
    residual      double precision NOT NULL,
    reason        text NOT NULL,
    origin        text NOT NULL CHECK (origin IN ('test_split', 'live_residual')),   -- 학습 구간 잔차 금지 (spec §8.2)
    state         text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'confirmed_issue', 'false_alarm')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id)
);

-- 11 추출 원본 · 결과 (2차)
CREATE TABLE mlp_document (
    doc_id            text PRIMARY KEY,
    tenant_id         text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id           text NOT NULL,
    filename          text NOT NULL,
    raw_sha256        text NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    raw_path          text NOT NULL,
    result            jsonb,
    extractor_name    text,
    extractor_version text,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id)
);

-- 12 견적 스냅숏 (2차, 추가만)
CREATE TABLE mlp_quote (
    quote_id      text PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    doc_id        text REFERENCES mlp_document (doc_id),
    lines         jsonb NOT NULL,
    total         numeric(18, 2) NOT NULL,
    overrides     jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_versions jsonb NOT NULL DEFAULT '{}'::jsonb,
    reviewed      boolean NOT NULL DEFAULT false,
    reviewed_by   text,
    review_note   text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    CONSTRAINT mlp_quote_review_note CHECK (NOT reviewed OR (reviewed_by IS NOT NULL AND char_length(review_note) >= 5))
);

-- 13 감시 결과
CREATE TABLE mlp_monitor_daily (
    monitor_id   bigserial PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id      text NOT NULL,
    day          date NOT NULL,
    metric       text NOT NULL CHECK (metric IN ('psi', 'oor_rate', 'missing_rate', 'live_perf', 'volume', 'error_rate', 'source_health')),
    feature      text NOT NULL DEFAULT '',          -- 과제 단위 지표는 ''
    value        double precision,
    level        text NOT NULL CHECK (level IN ('ok', 'warn', 'retrain')),
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    UNIQUE (tenant_id, task_id, day, metric, feature)
);

-- 14 승인 대기열
CREATE TABLE mlp_approval (
    approval_id   text PRIMARY KEY,
    tenant_id     text NOT NULL REFERENCES mlp_tenant (tenant_id),
    task_id       text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('model', 'recommendation', 'quote')),
    ref_id        text NOT NULL,                    -- model: v<n> · recommendation: rec_id · quote: quote_id
    action        text NOT NULL DEFAULT 'promote' CHECK (action IN ('promote', 'rollback', 'apply', 'confirm')),
    approver_role text NOT NULL,
    state         text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'approved', 'rejected', 'expired')),
    requested_by  text NOT NULL,
    requested_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    decided_by    text,
    decided_at    timestamptz,
    reason        text,
    evidence      jsonb NOT NULL DEFAULT '{}'::jsonb, -- 지표 비교 · 그림자 예측 차이
    FOREIGN KEY (tenant_id, task_id) REFERENCES mlp_task (tenant_id, task_id),
    CONSTRAINT mlp_approval_decided CHECK ((state = 'pending') = (decided_at IS NULL)),
    CONSTRAINT mlp_approval_rollback_reason CHECK (action <> 'rollback' OR state = 'pending' OR char_length(coalesce(reason, '')) > 0)
);
-- 같은 대상의 대기 승인은 하나
CREATE UNIQUE INDEX mlp_approval_one_pending ON mlp_approval (tenant_id, kind, ref_id, task_id) WHERE state = 'pending';

-- 15 감사 로그 (추가만)
CREATE TABLE mlp_audit (
    audit_id     bigserial PRIMARY KEY,
    tenant_id    text NOT NULL,                     -- 인증 실패 등 회사 미상은 '-'
    ts           timestamptz NOT NULL DEFAULT now(),
    actor        text NOT NULL,
    role         text,
    action       text NOT NULL,
    target       text,
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_id   text
);
CREATE INDEX mlp_audit_ts ON mlp_audit (tenant_id, ts);

-- 16 API 키(해시) · 역할 · 회사 범위
CREATE TABLE mlp_api_key (
    key_id       bigserial PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES mlp_tenant (tenant_id),
    key_hash     text NOT NULL UNIQUE,              -- pbkdf2_sha256$… 또는 sha256 — 평문 저장 금지
    key_prefix   text NOT NULL,                     -- 식별용 앞 8자
    role         text NOT NULL CHECK (role IN ('viewer', 'operator', 'approver', 'admin')),
    approver_roles jsonb NOT NULL DEFAULT '[]'::jsonb, -- approver 가 맡는 과제 approver_role 목록
    consumer     text NOT NULL,
    active       boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    CONSTRAINT mlp_api_key_no_plain CHECK (key_hash ~ '^(pbkdf2_sha256\$|sha256\$)')
);

-- @migrate-begin ── 2차 열 추가 (decisions.md D2-13 · contracts/db-schema.md §6) ─────────────────────────────────
-- **비파괴 · 멱등**: ADD COLUMN IF NOT EXISTS 만(DROP · TRUNCATE · UPDATE 0). 새 DB 는 위 CREATE 뒤 여기서 같은 열을 얻고,
-- 기존 DB 는 `make db-migrate`(CONFIRM 불필요 · 데이터 삭제 0)가 이 구간만 적용한다. 열 순서 = 계약 §2 표 순서.
-- 기존 행에 값을 지어내지 않는다: 근거가 없는 열은 NULL 허용, 기본값은 사실인 것만(초안 · revision 1 · 빈 jsonb · labels none).
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS version     text;
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS rule        text CHECK (rule IN ('abs_residual_ge', 'top_quantile'));
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS threshold   double precision;
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS decided_by  text;
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS decided_at  timestamptz;
ALTER TABLE mlp_review_item ADD COLUMN IF NOT EXISTS note        text;
ALTER TABLE mlp_document    ADD COLUMN IF NOT EXISTS size_bytes   bigint CHECK (size_bytes >= 0);
ALTER TABLE mlp_document    ADD COLUMN IF NOT EXISTS entity_count integer CHECK (entity_count >= 0);
ALTER TABLE mlp_document    ADD COLUMN IF NOT EXISTS labels       text NOT NULL DEFAULT 'none' CHECK (labels IN ('none', 'synthetic', 'provided'));
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_confirm', 'confirmed'));
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS revision       integer NOT NULL DEFAULT 1 CHECK (revision >= 1);
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS supersedes     text;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS inputs         jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS costs          jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS rates          jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS prediction_ids jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS approval_id    text;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS confirmed_by   text;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS confirmed_at   timestamptz;
ALTER TABLE mlp_quote ADD COLUMN IF NOT EXISTS created_by     text;
-- 웨이브 P 마감(D2-45 · D2-33) — 넓히기 · 색인만(행 변경 0). 채널 CHECK 에 견적이 부른 예측 'quote' 를 더한다(값 집합을 넓히기만).
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mlp_prediction'::regclass
                   AND conname = 'mlp_prediction_channel_check' AND pg_get_constraintdef(oid) LIKE '%quote%') THEN
        ALTER TABLE mlp_prediction DROP CONSTRAINT IF EXISTS mlp_prediction_channel_check;
        ALTER TABLE mlp_prediction ADD CONSTRAINT mlp_prediction_channel_check
            CHECK (channel IN ('api', 'batch', 'console', 'compat', 'optimize', 'quote'));
    END IF;
END $$;
-- 같은 운영 예측은 대기열에 한 번만 — 동시 실행 이중 삽입을 DB 가 막는다 (D2-33). test_split 항목은 prediction_id 가 NULL 이라 대상 밖
CREATE UNIQUE INDEX IF NOT EXISTS mlp_review_item_prediction_once
    ON mlp_review_item (tenant_id, task_id, prediction_id) WHERE prediction_id IS NOT NULL;
-- @migrate-end

-- @grants-begin ── 보호 구간: 추가만 트리거 + 권한 분리 (DEF-QA2-009 · decisions.md D-123) ──────────────────────
-- 이 아래는 **멱등 · 비파괴**다(DROP · TRUNCATE 0). 기존 DB 에는 `make db-grants` 가 이 구간만 다시 적용한다.
-- 앱은 DB 소유자가 아니라 `mlp_app` 의 구성원(LOGIN 역할, 비밀번호는 배포 비밀)으로 붙는다 — 소유자 · 슈퍼유저는
-- 트리거를 DDL 로 끌 수 있으므로 보호의 둘째 겹은 권한이다.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mlp_app') THEN
        CREATE ROLE mlp_app NOLOGIN;
    END IF;
END $$;

-- 추가만 테이블: UPDATE · DELETE · TRUNCATE 거부 (spec §10.2-2)
CREATE OR REPLACE FUNCTION mlp_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append_only: % 은(는) 추가만 할 수 있습니다 (%)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE TRIGGER mlp_prediction_append_only BEFORE UPDATE OR DELETE ON mlp_prediction FOR EACH ROW EXECUTE FUNCTION mlp_append_only();
CREATE OR REPLACE TRIGGER mlp_prediction_no_truncate BEFORE TRUNCATE ON mlp_prediction FOR EACH STATEMENT EXECUTE FUNCTION mlp_append_only();
CREATE OR REPLACE TRIGGER mlp_audit_append_only      BEFORE UPDATE OR DELETE ON mlp_audit      FOR EACH ROW EXECUTE FUNCTION mlp_append_only();
CREATE OR REPLACE TRIGGER mlp_audit_no_truncate      BEFORE TRUNCATE ON mlp_audit      FOR EACH STATEMENT EXECUTE FUNCTION mlp_append_only();
CREATE OR REPLACE TRIGGER mlp_quote_append_only      BEFORE UPDATE OR DELETE ON mlp_quote      FOR EACH ROW EXECUTE FUNCTION mlp_append_only();
CREATE OR REPLACE TRIGGER mlp_quote_no_truncate      BEFORE TRUNCATE ON mlp_quote      FOR EACH STATEMENT EXECUTE FUNCTION mlp_append_only();
-- session_replication_role = replica 에서도 돈다 (QA2 재현: replica 로 UPDATE 성공했다)
ALTER TABLE mlp_prediction ENABLE ALWAYS TRIGGER mlp_prediction_append_only;
ALTER TABLE mlp_prediction ENABLE ALWAYS TRIGGER mlp_prediction_no_truncate;
ALTER TABLE mlp_audit      ENABLE ALWAYS TRIGGER mlp_audit_append_only;
ALTER TABLE mlp_audit      ENABLE ALWAYS TRIGGER mlp_audit_no_truncate;
ALTER TABLE mlp_quote      ENABLE ALWAYS TRIGGER mlp_quote_append_only;
ALTER TABLE mlp_quote      ENABLE ALWAYS TRIGGER mlp_quote_no_truncate;

-- 권한: 먼저 전부 회수한 뒤 필요한 것만 (앱 코드의 DML = SELECT · INSERT · UPDATE · ON CONFLICT DO UPDATE, DELETE 0)
REVOKE ALL ON mlp_tenant, mlp_task, mlp_source, mlp_snapshot, mlp_train_run, mlp_model_version, mlp_prediction,
    mlp_actual, mlp_recommendation, mlp_review_item, mlp_document, mlp_quote, mlp_monitor_daily, mlp_approval,
    mlp_audit, mlp_api_key FROM PUBLIC, mlp_app;
GRANT USAGE ON SCHEMA public TO mlp_app;
GRANT SELECT, INSERT, UPDATE ON mlp_tenant, mlp_task, mlp_source, mlp_snapshot, mlp_train_run, mlp_model_version,
    mlp_actual, mlp_recommendation, mlp_review_item, mlp_document, mlp_monitor_daily, mlp_approval, mlp_api_key TO mlp_app;
GRANT SELECT, INSERT ON mlp_prediction, mlp_audit, mlp_quote TO mlp_app;
REVOKE UPDATE, DELETE, TRUNCATE ON mlp_prediction, mlp_audit, mlp_quote FROM mlp_app;    -- 명시(위 REVOKE ALL 과 같은 뜻)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mlp_app;
