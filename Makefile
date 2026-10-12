# 표준 ML 플랫폼 — 명령 (CLAUDE.md §명령). 검증 스크립트는 gates/, 이관 도구는 migration/.
# 포트: API 8200 · 웹 5190 (D-14). DB: ml_db · ml_test_db (unix socket /tmp). 학습은 OMP_NUM_THREADS=1.
SHELL  := /bin/bash
PSQL   := psql -h /tmp -v ON_ERROR_STOP=1 -q
UV     := uv run
export OMP_NUM_THREADS := 1
TENANT ?=
TASK   ?=
NEW    ?=
PACK   ?= _template
NOTYET  = @echo "미구현 — $@ (웨이브 A0/A, goal.md §3.2)"; exit 1

.PHONY: setup db-schema db-seed db-reset run web build test gate gate-full doctor doctor-live train train-live \
        tenant bench check-routes check-schema check-registry check-security check-leakage

setup:            ## DB 생성 · 스키마 · 표준 시드 · Python/웹 의존성
	@for db in ml_db ml_test_db; do createdb -h /tmp $$db 2>/dev/null || true; done
	uv sync -q
	$(MAKE) db-schema db-seed
	cd web && npm ci --no-audit --no-fund --loglevel=error

db-schema:        ## 두 DB 의 mlp 스키마 재생성 — 데이터를 전부 지운다
	@for db in ml_db ml_test_db; do $(PSQL) -d $$db -f src/mlcore/db/schema.sql; done

db-seed:          ## tenants/*.yaml → mlp_tenant · mlp_task (멱등)
	$(UV) python -m mlcore.db.seed_std && $(UV) python -m mlcore.db.seed_std --test

db-reset: db-schema db-seed

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

gate-full: db-reset build   ## 스키마 재생성 + (A) 과제 8 재학습 2회 · 이관 대조 · 새 회사 · 승인 경합 · bench → 판정
	$(UV) python gates/gate.py

doctor:           ## make doctor TENANT=<code> — fixture 소스 점검 (개발3)
	$(NOTYET)

doctor-live:      ## 실연결 — 사람이 .env 에 MLP_<CODE>_* 를 넣은 뒤 사람만 돌린다
	@echo "BLOCKED (D-13) — 실 Data Platform · MES · Gateway 연결은 루프에서 돌리지 않는다"; exit 2

train:            ## make train TENANT=<code> TASK=<code>.<task> (개발1)
	$(NOTYET)

train-live:
	@echo "BLOCKED (D-13) — 실데이터 학습은 사람이 키를 넣은 뒤 돌린다"; exit 2

tenant:           ## make tenant NEW=<code> PACK=<pack> — tenants/<code>.yaml 만 만든다 (개발3)
	$(NOTYET)

bench:            ## G-M14 — 768MB · CPU 1 아래 p95 · batch · 기동 · RSS
	$(NOTYET)

check-routes:   ; $(UV) python gates/check_routes.py
check-schema:   ; $(UV) python gates/check_schema.py
check-registry: ; $(UV) python gates/check_registry.py
check-leakage:  ; $(UV) python gates/check_leakage.py
check-security: ; $(UV) python gates/check_secrets.py && $(UV) python gates/check_tenant_bleed.py && $(UV) python gates/check_core_terms.py
