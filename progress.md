# progress.md — 검증된 현황의 유일한 진실

## 지금 해야 할 것 (2026-10-12, 웨이브 C 결함 수정 마감 — 기준 커밋 9d2febc + 작업 트리, 커밋은 오케스트레이터)

1. **make gate 2회 연속 = PASS 23 · FAIL 0 · BLOCKED 1(D-13 만).** 전체 시험 `pytest --ignore=tests/e2e` **459 passed · 3 skipped · 0 failed**, e2e **10 passed**. G-M13 은 게이트 2회 + test_optimize 단독 6회 모두 통과(간헐 실패 재현 0 — 개발2 가 시험 대역을 고친 뒤).
2. 웨이브 C 로 고친 QA 결함: QA1 #8~#12 · QA2 #14~#16 · QA3 #17 · #18 · DEF-QA3-002 · 004 · 005 · 006 등(개발1 D-85~D-88 · 개발2 D-130~D-134 · 개발3 D-120~D-126 · 마무리 결정 decisions.md 끝 표). 이슈 닫기는 오케스트레이터가 QA 재확인 뒤.
3. 남은 일: compose 앱 계정을 `mlp_app` 구성원 LOGIN 역할로(D-123, `docker-compose.yml`) · 커밋 뒤 `make image` · D-130 승인 만료 기간 사람 확인 · D-81(개발2) · QA 재검증(웨이브 B 재실행).
4. `make db-schema` · `db-reset` · `gate-full` 은 이제 `CONFIRM=1` 이 있어야 돈다(D-124). 기존 DB 의 보호 · 권한만 다시 적용은 `make db-grants`(비파괴).
5. 사람 확인 대기(그대로): D-27 · D-30 · D-32 · D-33 · D-04 · D-82 · D-130.

## (지난) 지금 해야 할 것 (2026-10-12, 웨이브 A 아키텍트 회전 직후 — 기준 커밋 be24075 + 작업 트리, 커밋은 오케스트레이터)

1. **make gate = PASS 23 · FAIL 0 · BLOCKED 1(D-13, 허용).** 웨이브 A 게이트 전부 PASS. 다음은 웨이브 B — QA1~3 교차 검증(goal §3.3) · `make gate-full` · 종료 조건 §4.4.
2. 이슈 정리(오케스트레이터): **#5 닫을 수 있음**(D-65). **#6** 4항목 모두 해소(1 B08 · 2 compat.round = be24075, 3 e2e = 이번 회전, 4 호환 인증 = D-59 사람 결정) → 닫을 수 있음. **#4** 의 D-51 · D-53 · D-54 · D-57 은 §4 에서 확정(정본 결함 부분은 #2 로 남김) → 닫을 수 있음. #1 · #2 · #3 은 사람 확인 대기.
3. 남은 가설 · 후속: D-68(개발1 — `test_source_contract` 가 `tests/fixtures/*/source_db.sql` 을 읽게) · D-73(추천 승인 만료) · D-76 구현(개발2 · 개발3 `warn_with`) · D-80 · D-81(개발2) · D-82(사람). `CLAUDE.md` 명령표의 "웨이브 A 에서 채운다" 문구는 사람이 갱신(아키텍트는 고치지 않았다).
4. 사람 확인 대기: D-27 · D-30 · D-32 · D-33(실데이터 차단) · D-04(승인자 명단).
5. **사고 기록(2026-10-12 아키텍트):** 이 파일을 갱신하던 셸 명령의 백틱이 명령으로 실행되어 `make gate-full` 의 앞 단계(`db-reset` = 두 DB mlp 스키마 재생성 + 표준 시드 · `web` 빌드)가 의도치 않게 1회 돌았다. ml_db · ml_test_db 의 기존 행이 지워졌다(지금 ml_db = 회사 2 · 과제 8 시드, 모델 0 · 예측 0). 두 DB 모두 시험 · 루프용(실데이터 없음, D-13)이고 그 뒤 `make gate` 를 다시 돌려 PASS 23 을 확인했다. 개발자가 ml_db 에 손으로 만든 모델이 있었다면 `make train` 으로 다시 만든다.

## 웨이브 A 아키텍트 회전 실측 (2026-10-12)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 전체 시험 | **389 passed · 3 skipped** (55 s, e2e 8 포함) — 전 378 + e2e 8 + 후속 3 | `OMP_NUM_THREADS=1 uv run pytest -q` |
| G-M11 compose | `docker compose config`(MLP_GIT_SHA=be24075) 정규화 결과: 서비스 app · db · DB 포트 0 · 앱 포트 1(127.0.0.1:8200→8200) · 헬스체크 2/2 · app mem 805306368 B · cpus 1 · OMP 1 · `MLP_GIT_SHA` 없으면 config 실패(기본값 0) · environment 에 비밀 이름 0(env_file 만). docker CLI 없을 때 YAML 정적 파싱도 PASS | `make check-deploy` · `PATH=/usr/bin:/bin .venv/bin/python gates/check_deploy.py` |
| 이미지 빌드 1회 | **성공** `mlp-app:be24075`(내용 349 MB, 디스크 1.56 GB) — node 24.18.1-bookworm-slim → uv 0.12.1 → python 3.12.13-slim-bookworm, `uv sync --frozen`. 작업 트리 기준(커밋 전 변경 포함) — 커밋 뒤 `make image` 로 다시 | `make image` |
| 기동 1회 (compose) | `mlpbench-ks` · `mlpbench-sw` 임시 프로젝트 `up --wait` → app · db healthy → 컨테이너 안 학습 · 승인(과제 3, 2.3 s · 2.5 s) → 재시작 → 측정 → `down -v`(남은 컨테이너 · 볼륨 0). 비밀은 임시 폴더 env 파일(저장소 밖, 실행 뒤 삭제) | `make bench-compose` |
| G-M14 (compose 제한 아래) | cgroup memory.max **805306368**(768 MB) · cpu.max **100000 100000**(CPU 1). 최악값: 단건 p95 **27.4 ms**(≤200) · batch 500 **0.306 s**(≤3, anomaly) · 기동 **1.65 s**(≤15, health 1.25 s + 과제 3 첫 예측) · app RSS(VmHWM) **247.8 MB**(≤768). 과제별 p95: ks 21.9 / 23.0 / 27.9 · sw 24.1 / 22.0 / 27.8 ms | `make bench` → `outputs/bench-compose-latest.json` |
| G-M14 (로컬, 참고) | compose 제한 아래 아님: p95 37.5 ms · batch 0.295 s · 기동 1.22 s · RSS 226.5 MB | `make bench-local` → `outputs/bench-latest.json` |
| G-S03 e2e | Playwright **1.63.0**(Python, chromium r1243) · 실제 uvicorn + 시험 DB · 회사 ks · sw 사본: 화면 1~6 HTTP 200 · 제목 일치 · `_placeholder` 0 · 페이지 오류 0 · 1024px 화면 2 · 3 폼 · 결과 후 가로 스크롤 0 · 폼 칸 · 라벨 · 범주 선택지 = features.yaml · 과제 YAML · 등록부 categories · 화면 3 sw 탐색 1,080점 · 충족 314(reproduce 와 같음). 8 passed / 13 s | `make e2e` |
| G-M09 조이기 | `decide(` 호출처(AST, src/mlcore · migration) **1** = api/routers/models.py | `uv run python gates/check_no_autopromote.py` |
| baselines.yaml | press: MAE 5.5683 · Brier 0.0576 · flag 0.1389 · 충족률 0.9175(89/97) / textile: MAE 0.5569 · Brier 0.1261 · flag 0.1458 · 충족률 0.2907(314/1080) / _template: MAE 2.3458 · Brier 0.1352 (전 값 null → 기입) | `OMP_NUM_THREADS=1 uv run python migration/reproduce.py` |
| 결정 | D-W1 12 · D-W2 9 · D-W3 8 → D-59~D-84: 확정 21 · 가설 6(D-68 · D-73 · D-80 · D-81 · D-82 · D-62 경로) · 차단 0. D-59 = 사람 결정(호환 경로 키 요구). D-40 확정 | `decisions.md` §9 |

명령(이번 회전에 연결): `make train TENANT= TASK=` · `make worker` · `make doctor TENANT=` · `make tenant NEW= PACK= [CSV=]` · `make monitor TENANT=` · `make bench`(auto) · `bench-local` · `bench-compose` · `make e2e` · `make image` · `make compose-config` · `make check-deploy`.

## make gate 판정표 (웨이브 A 아키텍트 회전 — 2026-10-12)

```
G-V01   수직 관통             PASS     tests/test_vertical_slice.py: 2 passed, 1 warning in 3.08s
G-S01   스키마               PASS     테이블 16 = spec 16 = 계약 16 = DB(ml_db 16 · ml_test_db 16) · 열 191 일치 · tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부
G-S02   팩·등록부 로드          PASS     팩 3 (_template(2) · press(4) · textile(4)) · 회사 3 로드 · 켜진 과제 8 · 불량 픽스처 5/5 거부(R4=과제 끄기, D-27)
G-S03   화면                PASS     화면 6/6 /app 200 · _placeholder 0 · e2e(ks·sw, 1024px 화면 2·3 가로 스크롤 0 · 폼=features.yaml) tests/e2e/test_console.py: 8 passed, 1 warning in 13.63s
G-S04   API               PASS     1차 12/12 · 2차 501 3/3 · tests/test_api_contract.py: 38 passed, 1 warning in 1.19s
G-S05   읽기 전용 소스          PASS     어댑터 5/5 · 정적 위반 0 · tests/test_source_contract.py: 18 passed, 1 warning in 0.99s
G-S06   비밀값               PASS     추적 파일 256 · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 9개(값 0)
G-S06   회사 격리             PASS     회사 2 · 회사 파일 10개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0
G-S07   의존성 고정            PASS     uv.lock · package-lock.json 있음 · Python 16개 == 고정 · JS 8개 정확 버전 · Python 3.12 하나
G-M01   코어 순수성            PASS     코어 95파일 · 팩 34파일 위반 0 (금지어 팩 30 · 회사 9 · 테이블 9 · 범주값 10)
G-M02   과제 대응             PASS     대응 32/32 (ks 16 · sw 16) · 미대응 0
G-M03   과제 정의             PASS     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 4/4 거부 · synth · baselines 있음
G-M04   예측 계약             PASS     A 스키마 자체 시험 91/91 · B tests/test_predict_contract.py: 27 passed, 6 warnings in 5.25s · C tests/test_compat.py: 35 passed, 3 skipped, 3 warnings in 5.91s
G-M05   누수 없는 평가          PASS     A 래퍼 자체 시험 14/14 · B 정적 위반 0 · C/D tests/test_split.py: 20 passed, 2 warnings in 3.05s
G-M06   재현·등록부            PASS     A tests/test_determinism.py: 9 passed, 4 warnings in 5.43s · B 기동 경로 학습 코드 0건 · C tests/test_registry.py: 13 passed, 1 warning in 1.80s
G-M07   예측 추적             PASS     tests/test_trace.py: 9 passed, 1 warning in 1.54s
G-M08   소스·doctor         PASS     tests/test_doctor.py: 7 passed in 0.58s
G-M08   doctor-live       BLOCKED  실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)
G-M09   감시·승인             PASS     production 쓰기 경로 1 (decide 안 1 · 밖 0) · decide 호출처 1 (models.py 1) · tests/test_approval.py: 14 passed, 1 warning in 1.81s · tests/test_monitor.py: 15 passed in 2.43s
G-M10   새 회사              PASS     tests/test_new_tenant.py: 3 passed, 3 warnings in 1.61s
G-M11   보안·배포             PASS     docker compose config(MLP_GIT_SHA=be24075): 서비스 app·db · DB 포트 0 · 앱 포트 1(8200) · 헬스체크 2/2 · 768MB·CPU 1 · OMP 1 · 태그=SHA 필수 변수 · 비밀 env_file 만 · Dockerfile 3단계 [node:24.18.1-bookworm-slim → ghcr.io/astral-sh/uv:0.12.1 → python:3.12.13-slim-bookworm] · tests/test_auth.py: 18 passed, 1 warning in 1.30s
G-M12   이관 대조             PASS     과제 8 대조 · 행 일치 100%
G-M13   최적화               PASS     tests/test_optimize.py: 11 passed, 2 warnings in 3.18s
G-M14   비기능               PASS     최악값(ks·sw 과제 6) 단건 p95 27.35ms(≤200) · batch500 0.306s(≤3) · 기동 1.647s(≤15) · RSS 247.8MB(≤768) — docker compose 제한 아래(app 768MB · CPU 1 · OMP_NUM_THREADS=1, 이미지 = 커밋 SHA)

합계 24행 — PASS 23 · BLOCKED 1
```

## Phase 0 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| spec 테이블 수 (§10.1) | **16** = contracts/db-schema.md 16 = ml_db 16 = ml_test_db 16 | `grep -cE '^\| \`mlp_[a-z_]+\` \|' spec.md` · `grep -c '^### ' contracts/db-schema.md` · `gates/check_schema.py` |
| spec 과제 유형 (§2.1) | **7** (1차 4) = std/task_types.yaml 7 (phase 1: 4) | `sed -n '/^### 2.1/,/^### 2.2/p' spec.md \| grep -cE '^\| \`[a-z_]+\` \|'` |
| spec 응답 상태 (§2.3) | **6** = std/statuses.yaml 6 = schema CHECK 6 = predict-contract enum 6 | `grep -cE '^\| \`(ok\|watch\|review\|out_of_range\|rejected\|needs_approval)\` \|' spec.md` |
| spec 분할 정책 (§5.3) | **4** = std/split_policies.yaml 4 | `grep -cE '^\| \`(time_60_20_20\|time_cv5\|stratified_60_20_20\|random_60_20_20)\` \|' spec.md` |
| spec API 묶음 (§12.2) | **15** (1차 12 = review · documents · quotes 제외) = contracts/api-contract.md B01~B15 (1차 12) | `grep -cE '^\| \`(GET\|POST\|PATCH) ' spec.md` → 15, `… \| grep -cvE 'review\|documents\|quotes'` → 12 |
| 회사 등록부 (1차) | **2** (ks · sw) + _template | `ls tenants/*.yaml \| grep -v _template \| wc -l` |
| mlp 열 | 191 (spec 주요 열 97 전부 포함) | `gates/check_schema.py` |
| 계약 | 9종 (goal 의 "8종" 표기와 다름 — D-24) | `ls contracts/` |
| 팩 · 과제 | press 4 · textile 4 · _template 2 = 과제 YAML 10, 스키마 위반 0 | `gates/check_tasks.py` |
| 원천 조사 ks | 엔드포인트 /api 6 (+/ 1) · 변수 9 (수치 7 + 범주 2) · 후보 8 · 분할 432/144/144 · 최적화 1 (0.5h 격자) · 화면 5 · 시험 9 함수/20 케이스 · 시험 MAE 5.568 · R² 0.9199 · AUC 0.6444 · Brier 0.0576 | `migration/source_inventory.md` §1 (파일:줄) |
| 원천 조사 sw | 엔드포인트 /api 6 (+/ 1) · 변수 9 (조절 5 + 원단 2 + 범주 2) · 후보 8 · 분할 432/144/144 · 최적화 1 (8,400점 격자) · 화면 5 · 시험 11 함수/24 케이스 · 시험 MAE 0.557 · R² 0.722 · AUC 0.868 · Brier 0.127 | `migration/source_inventory.md` §2 |
| G-M02 분모 | **32** (ks 16 · sw 16) | `migration/source_inventory.md` §0.1 · §5 |
| 원천 대응률 | sw 7/9 (dwell_time · color_tone 없음) · ks 6/9 확정 | `migration/source_inventory.md` §3 · §4 |
| 예측 계약 자체 시험 | 예시 4(유형 4) 통과 · 키 누락/ null 위반 변형 91/91 정확 판정 | `gates/check_contract.py` |
| 누수 래퍼 자체 시험 | 14/14 (금지 목적 6 · 2회 평가 · 평가 전 report · 직접 접근 4 · 표본 내 평가) | `gates/check_leakage.py` |
| 웹 골격 | Vite 8.3.0 · React 19.3.0 · TS 7.0.2 · 화면 1~6 `_placeholder` · `npm run build` 성공 | `cd web && npm run build` |
| API 골격 | `GET /api/v1/health` 200 (과제 8 model_ready=false) · 인증 없으면 401 · 2차 경로 501 | `MLP_TENANT=ks` TestClient |

## make gate 판정표 (Phase 0 종료 — 2026-10-12)

```
G-V01   수직 관통             FAIL     tests/test_vertical_slice.py 없음 (대상 미구현)
G-S01   스키마               PASS     테이블 16 = spec 16 = 계약 16 = DB(ml_db 16 · ml_test_db 16) · 열 191 일치 · tenant_id 16/16 · production 부분 고유 · 추가만 3 UPDATE/DELETE/TRUNCATE 거부 · live+synthetic 거부 · 평문 키 거부
G-S02   팩·등록부 로드          PASS     팩 3 (_template(2) · press(4) · textile(4)) · 회사 3 로드 · 켜진 과제 8 · 불량 픽스처 5/5 거부(R4=과제 끄기, D-27)
G-S03   화면                FAIL     _placeholder 화면 6/6 ([1, 2, 3, 4, 5, 6]); tests/e2e/ 없음(1024px 검사)
G-S04   API               FAIL     1차 묶음 1/12 구현 (없음 B02 B03 B04 B05 B06 B07 B08 B12 B13 B14 B15); tests/test_api_contract.py 없음 (대상 미구현)
G-S05   읽기 전용 소스          FAIL     어댑터 0/5 (없음 ['synthetic', 'csv', 'gateway', 'dataplatform', 'mes']) · 정적 위반 0 · tests/test_source_contract.py 없음 (대상 미구현)
G-S06   비밀값               PASS     추적 파일 130 · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 9개(값 0)
G-S06   회사 격리             PASS     회사 2 · 회사 파일 4개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0
G-S07   의존성 고정            PASS     uv.lock · package-lock.json 있음 · Python 15개 == 고정 · JS 8개 정확 버전 · Python 3.12 하나
G-M01   코어 순수성            PASS     코어 38파일 · 팩 24파일 위반 0 (금지어 팩 30 · 회사 9 · 테이블 9 · 범주값 10)
G-M02   과제 대응             FAIL     docs/task-map.md 없음 — 대응 0/32 (분모 ks 16 · sw 16)
G-M03   과제 정의             FAIL     팩 3 · 과제 YAML 10 스키마 통과 · 덮어쓰기 불변 4/4 거부 · 위반 3: press: synth/*.py 없음(합성 생성기 미이관); textile: synth/*.py 없음(합성 생성기 미이관); _template: synth/*.py 없음(합성 생성기 미이관)
G-M04   예측 계약             FAIL     A 스키마 자체 시험 91/91 · B predict 미구현 — 켜진 과제 0/8 검사 · C tests/test_compat.py 없음 (대상 미구현)
G-M05   누수 없는 평가          FAIL     A 래퍼 자체 시험 14/14 · B 정적 위반 0 · C 학습기(mlcore.train.trainer) 없음 — 계측 대상 0/8 · D 표본 내 평가 픽스처 대상 없음
G-M06   재현·등록부            FAIL     A 학습기 없음 — 재학습 대조 0/8 · B 기동 경로 학습 코드 0건 · C tests/test_registry.py 없음 (대상 미구현)
G-M07   예측 추적             FAIL     tests/test_trace.py 없음 (대상 미구현)
G-M08   소스·doctor         FAIL     tests/test_doctor.py 없음 (대상 미구현)
G-M08   doctor-live       BLOCKED  실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)
G-M09   감시·승인             FAIL     production 쓰기 경로 0 (decide 안 0 · 밖 0) · approval.decide() 없음 — 승인 경로 미구현
G-M10   새 회사              FAIL     tests/test_new_tenant.py 없음 (대상 미구현)
G-M11   보안·배포             FAIL     docker-compose.yml 없음 · tests/test_auth.py 없음 (대상 미구현)
G-M12   이관 대조             FAIL     docs/migration-report.md 없음 — 대조 0/8 · 합성 생성기 미이관 ['press', 'textile'] (대조값 4과제 준비됨)
G-M13   최적화               FAIL     tests/test_optimize.py 없음 (대상 미구현)
G-M14   비기능               FAIL     make bench 미구현 (p95 · batch 500 · 기동 · RSS 미측정)
합계 24행 — PASS 6 · FAIL 17 · BLOCKED 1
```

Phase 0 끝 조건 G-S01 · G-S02 · G-S06 · G-S07 · G-M01 = **PASS**. G-V01 FAIL 은 정상(웨이브 A0 목표). 나머지 FAIL 은 대상 미구현 사유를 그대로 표시한다(가짜 PASS 0).
