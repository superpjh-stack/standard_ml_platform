# 표준 ML 플랫폼 — 명령 (CLAUDE.md §명령). 검증 스크립트는 gates/, 이관 도구는 migration/.
# 포트: API 8200 · 웹 5190 (D-14). DB: ml_db · ml_test_db (unix socket /tmp). 학습은 OMP_NUM_THREADS=1.
SHELL  := /bin/bash
PSQL   := psql -h /tmp -v ON_ERROR_STOP=1 -q
UV     := uv run
export OMP_NUM_THREADS := 1
TENANT ?=
TASK   ?=
NEW    ?=
DATE   ?=
PACK   ?= _template
CSV    ?=
GIT_SHA = $(shell git rev-parse --short HEAD)
need    = @test -n "$($(1))" || { echo "$(1)= 가 필요하다 — $(2)"; exit 2; }
# DB 를 지우는 대상은 **명령줄** CONFIRM=1 이 있어야 돈다 (#7 · D-124). 셸에 export 된 CONFIRM · make -e 는 받지 않는다
# (DEF-QAR2-003 · F20-3 — $(origin) 이 'command line' 인 것만). 예: make db-reset CONFIRM=1
confirm = @test "$(origin CONFIRM)" = "command line" && test "$(CONFIRM)" = 1 || { echo "$@: ml_db · ml_test_db 의 mlp 데이터를 전부 지운다 — 정말이면 명령줄 인자로 'make $@ CONFIRM=1' (셸 환경변수 CONFIRM 은 받지 않는다)"; exit 2; }
GRANTS  = sed -n '/^-- @grants-begin/,$$p' src/mlcore/db/schema.sql
MIGRATE = sed -n '/^-- @migrate-begin/,/^-- @migrate-end/p' src/mlcore/db/schema.sql

.PHONY: setup db-schema db-grants db-migrate db-seed db-reset run web build test gate gate-full doctor doctor-live train train-live \
        worker tenant monitor bench bench-local bench-compose e2e image compose-config gate2 export-hub \
        check-routes check-schema check-registry check-deploy check-security check-leakage \
        check-core-freeze check-decimal check-followups

setup:            ## DB 생성 · 스키마(없는 DB 만) · 보호 구간 · 표준 시드 · Python/웹 의존성 — 기존 데이터는 지우지 않는다
	@for db in ml_db ml_test_db; do createdb -h /tmp $$db 2>/dev/null || true; done
	uv sync -q
	@for db in ml_db ml_test_db; do \
	  if [ "$$($(PSQL) -d $$db -tAc "SELECT to_regclass('public.mlp_tenant') IS NOT NULL")" = t ]; then \
	    echo "$$db: mlp 스키마 있음 — 지우지 않고 열 추가 · 보호 구간만 적용"; $(MIGRATE) | $(PSQL) -d $$db; $(GRANTS) | $(PSQL) -d $$db; \
	  else $(PSQL) -d $$db -f src/mlcore/db/schema.sql; fi; done
	$(MAKE) db-seed
	cd web && npm ci --no-audit --no-fund --loglevel=error

db-schema:        ## 두 DB 의 mlp 스키마 재생성 — 데이터를 전부 지운다 (CONFIRM=1 필수)
	$(confirm)
	@for db in ml_db ml_test_db; do $(PSQL) -d $$db -f src/mlcore/db/schema.sql; done

db-grants:        ## 기존 두 DB 에 추가만 트리거(ALWAYS) · mlp_app 권한만 다시 적용 — 비파괴 (D-123)
	@for db in ml_db ml_test_db; do $(GRANTS) | $(PSQL) -d $$db && echo "$$db: 보호 구간 적용"; done

db-migrate:       ## 기존 두 DB 에 2차 열 추가(ADD COLUMN IF NOT EXISTS) + 보호 구간 재적용 — 비파괴 · 멱등 · CONFIRM 불필요 (D2-13)
	@for db in ml_db ml_test_db; do $(MIGRATE) | $(PSQL) -d $$db && $(GRANTS) | $(PSQL) -d $$db && echo "$$db: 2차 열 · 보호 구간 적용"; done

db-seed:          ## tenants/*.yaml → mlp_tenant · mlp_task (멱등)
	$(UV) python -m mlcore.db.seed_std && $(UV) python -m mlcore.db.seed_std --test

db-reset:         ## 스키마 재생성 + 시드 — 데이터를 전부 지운다 (CONFIRM=1 필수)
	$(confirm)
	$(MAKE) db-schema db-seed CONFIRM=1

run:              ## API 8200 (+ web/dist 가 있으면 /app/*). 기동 시 학습하지 않는다
	MLP_TENANT=$(TENANT) $(UV) uvicorn mlcore.api.main:app --host 127.0.0.1 --port 8200

web:              ## 콘솔 개발 서버 5190
	cd web && npm run dev

build:
	cd web && npm run build

test:
	$(UV) pytest -q

gate:             ## 판정표 → outputs/gate-latest.md (goal §2)
	$(UV) python gates/gate.py

gate2:            ## 2차 판정표 = 1차 게이트 전부 + 6개사로 넓힌 판정 + G2-* → outputs/gate2-latest.md (goal2 §2). 대상 없는 2차 게이트는 FAIL
	$(UV) python gates/gate2.py

export-hub:       ## G2-I02 — 회사 전부 과제 · 변수 · 소스 · 일 호출 수 → var/export/hub/<date>.json (contracts/hub-export.md). DATE= 기본 어제 KST
	$(UV) python -m mlcore.monitor.hub_export $(if $(DATE),--date $(DATE))

gate-full:        ## 스키마 재생성(데이터 삭제 — CONFIRM=1 필수) + (A) 과제 8 재학습 2회 · 이관 대조 · 새 회사 · 승인 경합 · bench → 판정
	$(confirm)
	$(MAKE) db-reset build CONFIRM=1
	$(UV) python gates/gate.py

doctor:           ## make doctor TENANT=<code> — fixture 소스 점검(연결 · 대응률 · 미연결 · 목표 없음) (D-W3-07)
	$(call need,TENANT,make doctor TENANT=ks)
	$(UV) python -m mlcore.monitor.doctor --tenant $(TENANT)

doctor-live:      ## 실연결 — 사람이 .env 에 MLP_<CODE>_* 를 넣은 뒤 사람만 돌린다
	@echo "BLOCKED (D-13) — 실 Data Platform · MES · Gateway 연결은 루프에서 돌리지 않는다"; exit 2

train:            ## make train TENANT=<code> TASK=<code>.<task> — 접수 → 같은 프로세스에서 run_and_register → candidate (D-57 · D-W1-12)
	$(call need,TENANT,make train TENANT=ks TASK=ks.remaining_hours)
	$(call need,TASK,make train TENANT=ks TASK=ks.remaining_hours)
	$(UV) python -m mlcore.train.jobs --submit $(TENANT) $(TASK)

worker:           ## API 밖 작업자 — queued 학습 실행 전부를 run_and_register (D-57). API 는 학습하지 않는다
	$(UV) python -m mlcore.train.jobs --pending

train-live:
	@echo "BLOCKED (D-13) — 실데이터 학습은 사람이 키를 넣은 뒤 돌린다"; exit 2

tenant:           ## make tenant NEW=<code> PACK=<pack> [CSV=<path>] [CATEGORIES=<yaml>] — 등록부 <code>.yaml 만 만든다(코드 수정 0, D-51 · D-W3-07 · D2-100)
	$(call need,NEW,make tenant NEW=yn PACK=_template CSV=<path>)
	$(UV) python migration/make_tenant.py --new $(NEW) --pack $(PACK) $(if $(CSV),--csv $(CSV)) $(if $(CATEGORIES),--categories $(CATEGORIES))

monitor:          ## make monitor TENANT=<code> — 감시 1회(어제 KST, 후보까지만 — production 은 승인으로만). 상주는 --once 빼고 직접
	$(call need,TENANT,make monitor TENANT=ks)
	$(UV) python -m mlcore.monitor.scheduler --tenant $(TENANT) --once

bench:            ## G-M14 — docker 데몬이 있으면 compose 제한(768MB · CPU 1) 아래, 없으면 로컬(그 사실을 실측란에) → outputs/bench*-latest.json
	$(UV) python gates/bench.py
bench-local:    ; $(UV) python gates/bench.py --local
bench-compose:  ; $(UV) python gates/bench.py --compose

e2e:              ## G-S03 — Playwright(1.63.0) 화면 1~6 · 1024px · features.yaml 폼 (브라우저 없으면: uv run playwright install chromium)
	$(UV) pytest -q tests/e2e

compose-config:   ## G-M11 — docker compose config (이미지 태그 = 커밋 SHA)
	MLP_GIT_SHA=$(GIT_SHA) docker compose config

image:            ## 앱 이미지 빌드(태그 = 커밋 SHA). 작업 트리가 커밋과 다르면 거부(F7-5 — 미커밋 트리에 커밋 SHA 를 붙이지 않는다). push 없음
	@test -z "$$(git status --porcelain)" || { echo "image: 작업 트리에 커밋하지 않은 변경이 있다 — 커밋한 뒤 'make image' (태그 = 커밋 SHA, F7-5)"; exit 2; }
	MLP_GIT_SHA=$(GIT_SHA) docker compose build app

check-routes:   ; $(UV) python gates/check_routes.py
check-schema:   ; $(UV) python gates/check_schema.py
check-registry: ; $(UV) python gates/check_registry.py
check-deploy:   ; $(UV) python gates/check_deploy.py
check-leakage:  ; $(UV) python gates/check_leakage.py
check-security: ; $(UV) python gates/check_secrets.py && $(UV) python gates/check_tenant_bleed.py && $(UV) python gates/check_core_terms.py
check-core-freeze: ; $(UV) python gates/check_core_freeze.py
check-decimal:  ; $(UV) python gates/check_decimal.py
check-followups: ; $(UV) python gates/check_followups.py
