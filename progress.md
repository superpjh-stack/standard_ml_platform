# progress.md — 검증된 현황의 유일한 진실

## 지금 해야 할 것 (2026-10-12, Phase 0 종료 직후)

1. **웨이브 A0 — G-V01 하나만.** `ks.remaining_hours` × `sw.delta_e` 를 같은 코어로 fixture 스냅숏 → 학습 → candidate(기준선) → 승인 → production → predict → `mlp_prediction` → actuals → trace. 화면 · 최적화 · 감시 · 호환 라우터는 하지 않는다(goal §3.2).
   - 개발1: `DataSource` · `Snapshot` · `TrainResult` 를 `progress-dev1.md` §1 에 먼저 공표 → synthetic · csv 어댑터 · 스냅숏 · `time_60_20_20` · 후보 2 · 기준선. 누수 래퍼는 `src/mlcore/train/guard.py`(이미 있음)를 쓴다.
   - 개발2: `Predictor.predict()` · 응답 모델(`contracts/predict-contract.md` 18키)을 `progress-dev2.md` §1 에 먼저 공표 → 등록부 · 산출물 해시 · predict · 기록 · trace · `approval.decide()`.
   - 개발3: `packs/{press,textile}/synth/*.py` 이관(원천 `demo_data()` 행 일치) · `tests/fixtures/{ks,sw}/` 생성(README 계획대로) · `registry/{packs,tenants}.py` 인수(D-44).
2. 사람 확인 대기: D-27(R4 판정) · D-30(spec 예시 대 원천 값) · D-32 · D-33(실데이터 차단) · D-04(승인자 명단).

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
