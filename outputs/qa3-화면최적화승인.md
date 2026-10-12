# QA3 — 화면 · 최적화 · 승인 · 새 회사 (웨이브 B)

- 기준: 커밋 9d2febc · 2026-10-12 · goal §2 · §2.3 · §3.3 · §6 · contracts/ · decisions.md
- 범위: G-S02 · G-S03 · G-M02 · G-M09 · G-M10 · G-M13 (+ goal §2.3 오류 계약 전수)
- 환경: 전용 DB `ml_qa3_db`(끝난 뒤 dropdb) · 산출물/스냅숏은 scratchpad 임시 폴더 · 실제 uvicorn 포트 8203(MLP_TENANT=ks → sw → yn → 불량 등록부 순으로 재기동) · 화면은 API 가 제공하는 빌드 `/app/*` 를 Playwright chromium(1.63.0)으로 1024 · 390 폭에서 조작(웹 개발 서버 5193 은 띄우지 않았다 — vite 설정이 8200 프록시 고정이라 web/ 를 고치지 않고는 쓸 수 없음). `make tenant` 는 빈 tmp 등록부 루트(`MLP_TENANTS_DIR`)에서. ml_db · ml_test_db 쓰기 0, `tenants/ · packs/ · src/` 파일 해시 전후 diff 0.
- 검증 스크립트: `outputs/qa3/`(t01~t11 · shots.py · promote.py · env.sh). 판정 행 전체: `outputs/qa3/all_rows.txt`(189행). 스크린샷 40장: `outputs/e2e/qa3-*.png`.
- **고치지 않았다.** QA 는 결함만 기록한다.

## 1. 결함

| ID | 등급 | 요약 | 담당 | 이슈 |
|---|---|---|---|---|
| DEF-QA3-001 | **치명** | live 회사가 합성 스냅숏 production 모델로 예측한다 — 병합 규칙 R4 가 실기동 경로에 연결되지 않음 | 개발3 · 개발1 · 개발2 · 아키텍트(게이트) | #17 |
| DEF-QA3-002 | 중대 | 422 `invalid_input` 이 요청의 임의 키 문자열을 길이 제한 없이 `detail.errors[].field` 로 되돌림(§2.3 · D-75 위반) | 개발2 | #16 댓글(DEF-QA2-004 중복) |
| DEF-QA3-003 | 중대 | 호환 `/api/data/records` lot_id 가 원천 형식이 아님 → 원천 LOT 번호 상세 조회 404 (KS-E6 · SW-E6) | 개발2 | #18 |
| DEF-QA3-004 | 경미 | 만료 승인이 `pending` 으로 남고 같은 버전 재요청이 만료된 승인 ID 를 돌려줘 그 버전을 영영 승격 못 함. expires_at 을 넣는 코드 0(D-73) | 개발2 · 아키텍트 | #7 댓글 |
| DEF-QA3-005 | 경미 | 화면 5 두 탭: 뒤늦은 탭의 409 오류 문구가 목록 재조회로 카드와 함께 즉시 사라져 사용자에게 안내 0 | 개발2 | — |
| DEF-QA3-006 | 경미 | optimize `current` 의 결정 변수(stop_after_hours)를 범위 검사하지 않음 — 1000 · -5 를 받아 개선량 계산 | 개발2 | — |

### DEF-QA3-001 (치명) live + 합성 production 운영
- 재현: `outputs/qa3/t09_r4_real.py <tmp>` — tmp 등록부 `qz4`(textile, mode demo, 합성 demo 소스)로 `qz4.delta_e` 학습 → stage → 승인 → production v1(synthetic=true). YAML 만 `mode: live` 로 바꾸고(합성 소스 제거) `MLP_TENANT=qz4 MLP_TENANTS_DIR=<tmp> uvicorn …` 기동 → health `model_ready: true`, `POST /tenants/qz4/tasks/delta_e/predict` **200 · status ok · 값 1.8368 · model v1 synthetic=true**, tasks `disabled: []`.
- 기대: spec §11.3-4 · tenant-contract §2.1 · D-27 — 그 과제 끄기 + 503 `model_not_ready`. goal §3.3 "합성 모델이 live 에서 운영됐다".
- 원인: `registry/tenants.py:205` R4 는 `production_synthetic` 콜백이 있을 때만 판정. 실기동(`api/main.py:33-41` → `data/jobs.py:44-51 load_merged` → `load_and_merge(code)`)은 콜백을 넘기지 않는다. `gates/check_registry.py:40` 은 `lambda tid: True` 로 5/5 를 세므로 실경로를 보지 않는다. DB 트리거(mlp_propagate_tenant_mode)는 mlp_tenant.mode UPDATE 를 거부하지만(실측: 검사 제약 위반) API 는 YAML mode 만 본다 — seed 를 다시 돌리지 않으면 그대로 운영된다.

### DEF-QA3-002 (중대) 422 입력 되풀이
- 재현: `POST /tenants/ks/tasks/remaining_hours/predict` 본문 `{"inputs":{…}, "<script>alert(1)</script>":1}` → `detail.errors[0].field = "<script>alert(1)</script>"`. `inputs` 안에 `{"SECRET-VALUE-x y":[1,2]}` → `field="inputs.SECRET-VALUE-x y.int"`. 3,000자 키 → 응답 3,132자. optimize · decide 도 같다.
- 기대: goal §2.3 "입력값을 메시지에 되풀이하지 않는다" · D-75(변수 이름 꼴일 때만). 위치 `api/main.py:76-78`(pydantic loc 를 그대로 씀). `inputs` 안 모르는 **수치** 키는 SAFE_NAME 으로 걸러짐(PASS).

### DEF-QA3-003 (중대) 호환 lot_id
- 재현: ks/sw 서버 `GET /api/data/records?limit=2` → `lot_id: "DEMO-0720"`; `GET /api/data/records/KS-DEMO-0001` → 404(sw `SW-DEMO-0001` 도 404), `DEMO-0720` 은 200.
- 기대: 원천 `../KwangSung ML AI/api/ml_service.py:34` `KS-DEMO-{i:04d}` · `../SongWol ML AI/api/ml_service.py:50` `SW-DEMO-…`. `tenants/{ks,sw}.yaml:35 compat.entity_prefix` 를 src 가 읽지 않는다(grep 0건).

### DEF-QA3-004 (경미) 만료 승인
- 재현: `t02_approval.py` — v3 promote 승인을 QA DB 에서 `expires_at = now()-1분` → decide 409 `already_decided`(PASS, production 불변) 그러나 `GET approvals?state=pending` 에 남음 · `state=expired` 0건 · 같은 v3 promote 재요청 202 가 만료된 같은 approval_id 를 반환(부분 고유 색인 `ON CONFLICT … WHERE state='pending'`) → v3 는 다시 승인할 길이 없다. 정상 운영에서 expires_at 을 넣는 코드가 없어 지금은 도달 불가(D-73 가설).

### DEF-QA3-005 (경미) 화면 5 409 안내 사라짐
- 재현: `t05_ui.py` — 탭 A(approver) · 탭 B(admin) 가 같은 대기 카드를 연 뒤 A 승인 → B 승인 클릭. 서버는 B 에 409 를 냈고(콘솔 `409 (Conflict)`) production 은 1회만 바뀜(v1→v4). 그러나 `ApprovalCard` 가 409 에서 `onDone()` 으로 목록을 다시 읽어 카드(와 그 안의 ErrorBox)가 언마운트 → B 화면에 "이미 결정된 승인" 문구 0(`qa3-ui-approvals-tabB-409-1024.png`). screen-map 5 "409 처리".

### DEF-QA3-006 (경미) current 결정 변수 범위
- 재현: `POST /tenants/ks/tasks/maintenance_timing/optimize` `{"fixed":…, "current":{"stop_after_hours":1000}}` → 200 needs_approval, current.conditions 1000; `-5` 도 200. 조절 변수 current 는 min/max 검사(422, PASS)와 불일치. `tasks/optimize.py` current 처리.

## 2. 게이트 요약 (QA3 실측)

```
G-S02  팩·등록부 로드          FAIL  불량 5종 실기동: R1·R2·R3·R5 기동 거부(프로세스 종료) 4/4 · R4 실경로 FAIL(DEF-QA3-001). gates/check_registry.py 는 PASS(콜백 주입 — 실경로 아님)
G-S03  화면                PASS  화면 1~6 × 1024·390 = 12+12 장 HTTP 200 · 가로 스크롤 0 · 페이지 오류 0 · 콘솔 오류는 의도한 4xx 자원 로드뿐 · 빈 상태 "운영 모델 없음 (model_not_ready)" · 미연결 · 목표 없음 · 합성 배지 · 키 없는 안내 · 오류 상자 out_of_bounds/forbidden 표시. 경미 DEF-QA3-005. make e2e 8 passed(ml_qa3_db)
G-M02  과제 대응             PASS  원천 직접 대조: ks · sw 각 엔드포인트 7(api/main.py:71-118) + 모델 묶음 3(회귀 4 · 분류 3 · IsolationForest) + 최적화 1(ks np.arange 0.5h · sw itertools.product 격자) + 화면 5(App.tsx overview·models·predict·optimize·data) = 16 × 2 = 32 = task-map 32 · 미대응 0. 경로 실측 13/14(KS-E6 · SW-E6 은 DEF-QA3-003)
G-M09  감시·승인             FAIL  치명 0 (승인 경로) — 두 탭 동시 승인 200·409 · 승인/반려 경합 하나만 · 재결정 409 · 새 후보 도착 production 불변 · rollback 승인 요청만 → 승인 시 교체 · 드리프트 → candidate → staging+pending(monitor), production 불변 · 기준선 미달 후보 stage 0 · 승인 0 · 과제당 production ≤1 · production 전부 approval_id. FAIL 사유 = 만료 승인(DEF-QA3-004) · 화면 409(DEF-QA3-005)
G-M10  새 회사              PASS  빈 tmp 등록부 → make tenant NEW=yn PACK=_template CSV=<tmp> → yn.yaml 1개만 → db-seed → make doctor(eval 연결 · train/actuals 미연결) → API train(eval) 202 → make worker → stage → 승인 → predict 200 18키(target_value · target_risk). 저장소 tenants/·packs/·src/ 해시 diff 0 · 코드 수정 0줄
G-M13  최적화               PASS  ks 결정 변수 0..48 step 0.5 = 97점 · 경계(72→145, 0→1, 0.4→1, 72.5/−0.5/0/501 → 422) · 불가능 제약 → review · feasible false · least_violation(위반 오름차순) · ok/needs_approval 0 · sw 공간 1,080 = QA 계산(production lock p1/p99 ∩ min/max · step) · 후보 전부 학습 범위 안 · in_train_range_rate 1.0 · line_speed≥24(학습 밖) 요구 시 범위 밖 점 추천 0 · 추천 승인 → production 불변 · 재결정 409 · 두 탭 200/409 · 10,000점 ≤10s(test_optimize) · 경미 DEF-QA3-006
2.3    오류 계약             FAIL  47/48 행 PASS(모르는 키 · NaN · ±Infinity · 1e400 · 깨진 JSON · 필수 누락 · max_imputed 3/4 경계 · min/max · 학습 범위 밖 200 out_of_range · 503 model_not_ready(predict · batch · optimize) · 503 model_artifact_mismatch(report.json 1바이트 · env.lock 버전) · 503 source_disconnected · doctor 200 미연결 · 401 · 403 · 404(다른 회사 · 없는 과제 · 없는 예측 · 다른 회사 trace) · 409 already_decided(재결정 · 만료) · 200 재사용 run_id · 501 7경로). FAIL 1 = DEF-QA3-002. reject 정책 rejected 행은 1차 과제 8개가 모두 predict_with_warning(D-07)이라 실요청 대상 없음
```

판정 행 합계(all_rows.txt): PASS 177 · WARN 7 · FAIL 4 (+ R4 실경로 FAIL 1).

## 3. 판정 행 (발췌 — 전체는 outputs/qa3/all_rows.txt)

```
2.3  production 없음 predict ks.remaining_hours  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
2.3  production 없음 predict ks.failure_24h  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
2.3  production 없음 predict ks.sensor_ood  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
2.3  production 없음 predict:batch  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
2.3  production 없음 optimize(uses 미운영)  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
2.3  health model_ready 전부 false  PASS  200 [False, False, False, False]
2.3  overview production null  PASS  200 production=None
G-M09  candidate 를 promote 요청  PASS  HTTP 409 code=invalid_transition (기대 409 invalid_transition)
G-M09  operator 가 stage  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
G-M09  admin stage v1  PASS  200 {'version': 'v1', 'stage': 'staging'}
G-M09  다른 과제 담당 approver 가 promote  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
G-M09  promote = 승인 요청만(202 pending)  PASS  202 {'approval_id': 'apr_01M4R6EVF80YSQK5MFF2FPMC1S', 'state': 'pending'} production=[]
G-M09  같은 대상 promote 재요청 → 같은 approval_id  PASS  202 apr_01M4R6EVF80YSQK5MFF2FPMC1S vs apr_01M4R6EVF80YSQK5MFF2FPMC1S
G-M09  승인 대기 중 predict  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
§6  operator decide  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
§6  viewer decide  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
§6  다른 과제 approver decide(own_task)  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
2.3  다른 회사 키로 decide  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  없는 승인 ID decide  PASS  HTTP 404 code=not_found (기대 404 not_found)
G-M09  역할 거부 뒤 production 그대로  PASS  production=[]
G-M09  두 탭 동시 승인 → 200 1 · 409 1  PASS  codes=[200, 409] 감사 approved=1 production=['v1']
2.3  이미 결정된 승인 재결정(반려)  PASS  HTTP 409 code=already_decided (기대 409 already_decided)
G-M09  승인 직후 새 후보 도착 → production 불변  PASS  v2=candidate production=['v1']
G-M09  새 후보 뒤 predict 는 production v1  PASS  200 model=v1
G-M09  승인 · 반려 동시 → 하나만  PASS  codes=[200, 409] 최종=rejected production=['v1']
G-M09  v2 승인 → production v2 · v1 archived  PASS  {'v1': 'archived', 'v2': 'production'}
2.3  사유 없는 rollback  PASS  HTTP 422 code=missing_required (기대 422 missing_required)
G-M09  archived 아닌 것을 rollback  PASS  HTTP 409 code=invalid_transition (기대 409 invalid_transition)
G-M09  rollback = 승인 요청만(production 불변)  PASS  202 production=['v2']
G-M09  rollback 승인 → v1 production · v2 archived  PASS  200 {'approval_id': 'apr_01M4R6EYYK61AVEE1CQMPC6FTC', 'state': 'approved', 'production_version': 'v1'} {'v1': 'production', 'v2': 'archived', 'v3': 'staging'}
G-M09  models 목록 production 1개  PASS  200 production 항목 1
G-M09  되돌리기 뒤 대기 중 v3 승인 유지  PASS  pending
2.3  만료된 승인 결정  PASS  HTTP 409 code=already_decided (기대 409 already_decided) production=['v1']
G-M09  만료된 승인이 대기열(state=pending)에서 빠짐  WARN  pending 목록에 남음=True state=pending
G-M09  state=expired 조회에 만료 승인 보임  WARN  200 n=0
G-M09  만료 뒤 같은 버전 재요청 → 새 승인  WARN  202 {'approval_id': 'apr_01M4R6EYWW52Q0XTVMHVETPJR6', 'state': 'pending'}
G-M09  승인 요청에 만료 시각(expires_at) 설정  WARN  expires_at 있는 승인 0건(QA 가 손으로 넣은 1건 제외)
G-M09  같은 승인 두 번 결정 감사 0  PASS  중복 []
G-M09  과제당 production ≤ 1  PASS  []
G-M09  production 전부 approval_id 있음  PASS  []
2.3  모르는 입력 키  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input) echo=False
2.3  모르는 최상위 키(이름=반사 문자열)  FAIL(DEF-QA3-002)  HTTP 422 code=invalid_input (기대 422 invalid_input) echo=True
2.3  NaN  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
2.3  Infinity  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
2.3  -Infinity  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
2.3  1e400  PASS  HTTP 422 code=invalid_input (기대 422 ) (1e400 은 invalid_input · out_of_bounds 어느 쪽이든 422)
2.3  숫자 자리에 문자열(반사 문자열)  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input) echo=False
2.3  범주 목록 밖 값(반사 문자열) → out_of_bounds(D-55)  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds) echo=False
2.3  깨진 JSON  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
2.3  필수 변수(machine_code) 누락  PASS  HTTP 422 code=missing_required (기대 422 missing_required)
2.3  선택 변수 3개 누락(= max_imputed 3) → 200 보정  PASS  200 imputed=['press_force', 'vibration', 'motor_current']
2.3  선택 변수 4개 누락(> max_imputed 3)  PASS  HTTP 422 code=missing_required (기대 422 missing_required)
2.3  null 4개(> max_imputed)  PASS  HTTP 422 code=missing_required (기대 422 missing_required)
2.3  min/max 밖 press_force=320.0001  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
2.3  min/max 밖 press_force=179.9  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
2.3  min/max 밖 shot_count=180001  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
2.3  min/max 밖 vibration=-1  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
2.3  max 경계값 320 → 422 아님  PASS  200 status=out_of_range
2.3  학습 범위 밖(181 < p1 182.39) → 200 out_of_range + 경고  PASS  200 status=out_of_range oor=['press_force']
2.3  학습 범위 안 → status ok/watch  PASS  200 status=ok synthetic=True
2.3  합성 모델 응답 synthetic=true + 경고  PASS  synthetic=True warnings=['synthetic_model']
2.3  batch 501건  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
2.3  batch 안 한 건 out_of_bounds  PASS  200 {'items': [{'task': 'ks.remaining_hours', 'type': 'regression', 'tenant': 'ks', 'entity_id': None, 'prediction': {'value': 120.933399, 'unit': 'h', 'interval': 
2.3  viewer predict(역할 밖)  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
2.3  키 없음  PASS  HTTP 401 code=auth_required (기대 401 auth_required)
2.3  틀린 키  PASS  HTTP 401 code=auth_required (기대 401 auth_required)
2.3  다른 회사 키(sw)로 ks predict  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  없는 과제  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  ks 키로 sw 경로  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  없는 예측 ID trace  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  다른 회사 키로 실제 예측 trace  PASS  HTTP 404 code=not_found (기대 404 not_found)
§6  approver trace(admin 전용)  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
2.3  optimize 아닌 과제에 optimize  PASS  HTTP 404 code=not_found (기대 404 not_found)
2.3  2차 GET review  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 PATCH review/x1  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 POST documents  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 GET documents/d1  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 POST quotes  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 GET quotes  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  2차 GET quotes/q1.csv  PASS  HTTP 501 code=not_implemented (기대 501 not_implemented)
2.3  소스 실패 train(dataplatform 미연결)  PASS  HTTP 503 code=source_disconnected (기대 503 source_disconnected)
2.3  같은 스냅숏 · 설정 재요청 → 200 + 기존 run_id  PASS  200 {'run_id': 'run_ad500feb6aadbfe8', 'status': 'succeeded', 'reused': True}
§6  approver train  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
2.3  doctor 200 + 소스별 미연결  PASS  200 {'demo': '연결', 'eval': '연결', 'train': '미연결', 'gateway': '미연결', 'actuals': '미연결'}
G-M08  doctor 목표 없음 표기(D-33)  PASS  target=['있음', '있음', '목표 없음', '목표 없음', '목표 없음']
2.3  산출물 해시 불일치(이미 적재된 모델)  PASS  HTTP 503 code=model_artifact_mismatch (기대 503 model_artifact_mismatch) (바꾸기 전 200)
2.3  되돌린 뒤 다시 200  PASS  200
2.3  env.lock 패키지 버전 바꿈  PASS  HTTP 503 code=model_artifact_mismatch (기대 503 model_artifact_mismatch)
G-M13  기본 params → needs_approval · 후보 5  PASS  200 status=needs_approval n_candidates=97 n_feasible=89 0.05s
G-M13  결정 변수 점 수 = 0..48 step 0.5 = 97  PASS  n_candidates=97
G-M13  후보 결정 변수 ∈ [0, max_delay_hours]  PASS  [48.0, 47.5, 47.0, 46.5, 46.0]
G-M13  후보 전부 제약 충족  PASS  [[True, True], [True, True], [True, True], [True, True], [True, True]]
G-M13  응답 키 18 · prediction/model/prediction_id null · uses 배열  PASS  keys=18 uses=[{'task': 'ks.remaining_hours', 'version': 'v1', 'synthetic': True}]
G-M13  mlp_recommendation needs_approval + 승인 요청(kind=recommendation)  PASS  rec=[{'status': 'needs_approval', 'feasible': True}] approval=[{'approval_id': 'apr_01M4R6KN11D3QPGVWRHF8NENW2', 'state': 'pending', 'kind': 'recommendation', 'approver_role': 'maintenance_lead'}]
G-M13  불가능 제약 → feasible=false · status review · least_violation  PASS  200 status=review feasible=False on_infeasible=least_violation n_feasible=0
G-M13  불가능 제약에서 ok/needs_approval 0  PASS  status=review
G-M13  least_violation best 의 미충족 제약 표시  PASS  unmet=['reserve', 'max_cost']
G-M13  least_violation 후보 위반 오름차순  PASS  [59.3537773428, 59.3571106761, 59.3604440095, 59.3637773428, 59.3671106761]
G-M13  불가능 추천도 needs_approval 로 기록(설비 미적용)  PASS  [{'status': 'needs_approval', 'feasible': False}]
G-M13  reserve 150h(예측 잔여수명보다 큼) → review  PASS  200 review best={'stop_after_hours': 4.0}
G-M13  decision_vars 경계 {'max_delay_hours': 72}  PASS  200 n=145 max=72.0
G-M13  decision_vars 경계 {'max_delay_hours': 0}  PASS  200 n=1 max=0.0
G-M13  decision_vars 경계 {'max_delay_hours': 0.4}  PASS  200 n=1 max=0.0
G-M13  params 경계 {'max_delay_hours': 72.5}  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
G-M13  params 경계 {'max_delay_hours': -0.5}  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
G-M13  params 경계 {'reserve_hours': 0}  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
G-M13  params 경계 {'max_cost_index': 501}  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
G-M13  params 경계 {'zz_param': 1}  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
G-M13  params 경계 {'reserve_hours': '12'}  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
G-M13  params 경계 {'reserve_hours': True}  PASS  HTTP 422 code=invalid_input (기대 422 invalid_input)
G-M13  current.stop_after_hours=1000(결정 변수 max 72 밖) 거부  WARN  200 status=needs_approval current={'stop_after_hours': 1000.0}
G-M13  current.stop_after_hours=-5 거부  WARN  200
G-M13  고정 입력 학습 범위 밖 → review + out_of_range 경고  PASS  200 review ['press_force']
G-M13  고정 입력 min/max 밖  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
§6  viewer optimize  PASS  HTTP 403 code=forbidden (기대 403 forbidden)
G-M13  추천 승인 → production 불변 · rec approved · production_version null  PASS  200 {'approval_id': 'apr_01M4R6KN11D3QPGVWRHF8NENW2', 'state': 'approved', 'production_version': None} rec=approved production 변화=set()
2.3  추천 승인 재결정  PASS  HTTP 409 code=already_decided (기대 409 already_decided)
G-M13  추천 결정 감사 1행  PASS  recommendation.approved 1 · recommendation.create 1 (psql 재확인)
G-M13  추천 승인 두 탭 동시 → 200 1 · 409 1  PASS  {'B': 200, 'A': 409}
G-S03  화면2 예측(1024px) 값 · 상태 · 모델 버전 · 합성 배지  PASS  합성=True 버전v1=True 가로스크롤=False 오류=[]
G-S03  화면2 1024px 가로 스크롤 0  PASS  False
G-S03  화면2 학습 범위 밖 표시(1024px)  PASS  cls=field field-oor
G-S03  화면2 min/max 밖 → 오류 상자 out_of_bounds(1024px)  PASS  code=out_of_bounds 결과카드=False
G-S03  화면2 콘솔 · 페이지 오류(1024px)  PASS  ['console.error: Failed to load resource: the server responded with a status of 422 (Unprocessable Entity)']
G-S03  화면2 예측(390px) 값 · 상태 · 모델 버전 · 합성 배지  PASS  합성=True 버전v1=True 가로스크롤=False 오류=[]
G-S03  화면2 390px 가로 스크롤 0  PASS  False
G-S03  화면2 학습 범위 밖 표시(390px)  PASS  cls=field field-oor
G-S03  화면2 min/max 밖 → 오류 상자 out_of_bounds(390px)  PASS  code=out_of_bounds 결과카드=False
G-S03  화면2 콘솔 · 페이지 오류(390px)  PASS  ['console.error: Failed to load resource: the server responded with a status of 422 (Unprocessable Entity)']
G-S03  화면2 viewer → 403 forbidden 표시  PASS  forbidden
G-S03  화면3 추천 · '설비로 내려가지 않음' · 가로 스크롤 0  PASS  배지 '승인 필요'(needs_approval 한국어 표기) · 후보 5 · 학습 범위 안 100% · 합성 배지 (스크린샷 확인) hscroll=False 오류=[]
G-S03  화면3 불가능 제약 → least_violation · 검토 필요 표시  PASS  least=True
G-S03  화면3 390px 가로 스크롤  PASS  hscroll=False sw=390
G-M09  화면5 두 탭: A 승인 → B 승인 클릭 409 already_decided 표시  FAIL(DEF-QA3-005)  서버 409 정상 · production 1회만 변경 · 그러나 B 탭에 오류 문구 없이 카드만 사라짐 — 이전 production=['v1'] A 뒤=['v4'] B 오류=None 최종=['v4']
G-M09  화면5 409 뒤 B 탭 목록 새로 고침(대기 카드 사라짐)  PASS  버튼 남음=False
G-S03  화면5 콘솔 · 페이지 오류  PASS  ['console.error: Failed to load resource: the server responded with a status of 409 (Conflict)']
G-S03  화면5 operator(조회만) — 승인 버튼 노출 여부 · 누르면 403  PASS  버튼 노출=True 결과=forbidden
G-S03  화면5 viewer → forbidden 표시  PASS  forbidden
G-S03  키 없는 첫 방문 안내  PASS  True
G-M13  sw 공간 크기 = QA 계산(학습 범위 ∩ min/max · step)  PASS  응답 1080 · QA 1080 · 원천 전수 8,400(D-31) · 0.06s
G-M13  sw 후보 5 전부 학습 범위 ∩ min/max 격자 위  PASS  [{'set_temp': 150.0, 'set_pressure': 4.0, 'line_speed': 18.0, 'ink_usage': 14.0, 'dwell_time': 65.0}, {'set_temp': 150.0, 'set_pressure': 5.0, 'line_speed': 18.0, 'ink_usage': 14.0, 'dwell_time': 65.0}]…
G-M13  in_train_range_rate = 1.0  PASS  1.0
G-M13  sw 기본 → needs_approval · 충족 후보만 상위  PASS  status=needs_approval n_feasible=314
G-M13  sw 원천 끝점 제외 확인(set_temp 140·210, line_speed 24 등)  PASS  QA 축 구간 {'set_temp': (141.195, 209.105), 'set_pressure': (2.02, 5.97), 'line_speed': (6.3275, 23.8425), 'ink_usage': (10.2469, 29.82), 'dwell_time': (20.445, 79.2)}
G-M13  min_line_speed 24(학습 범위 밖) → 범위 밖 점 추천 0 · review  PASS  status=review feasible=False best.line_speed=21.0 학습구간=(6.3275, 23.8425)
G-M13  sw 불가능 제약 3개 → feasible false · review · least_violation · ok 0  PASS  review n_feasible=0
G-M13  current → improvement 계산  PASS  200 {'process_cost': 17.714286}
G-M13  current 조절 변수 min/max 밖  PASS  HTTP 422 code=out_of_bounds (기대 422 out_of_bounds)
G-M13  고정 필수(print_type) 누락  PASS  HTTP 422 code=missing_required (기대 422 missing_required)
G-M13  fixed 에 조절 변수 넣기 → 422  PASS  422 invalid_input
G-M13  sw 1080점 탐색 시간(≤10s 기준은 10,000점)  PASS  최대 0.05s 중앙 0.04s
G-M09  드리프트 fixture → 재학습 접수 · production 불변  PASS  사유=['psi:vibration'] psi.vibration=(5.5979, 'retrain') production ['v4']→['v4']
G-M09  작업자 등록 → candidate · production 불변  PASS  v5 candidate · v4 production
G-M09  감시 → staging + 승인 요청(pending, monitor) · production 불변  PASS  v5 staging · apr pending requested_by=monitor · production v4
G-M09  감시 두 번째 실행 → 새 요청 없음  PASS  []
G-M09  기준선 미달 후보 → stage 0 · 승인 요청 0  PASS  v6=candidate [{'task_id': 'ks.remaining_hours', 'version': 'v6', 'run_id': 'run_74af41b615acd7b3', 'approval_id': None, 'skipped': '기준선 미달 — candidate 로 둔다'}] production=['v4']
G-M09  기준선 미달 후보의 mlp_approval 0  PASS  0
G-S02  불량 등록부 r1_override_type 실기동  PASS  기동=exit R1", f"{ 
G-S02  불량 등록부 r2_missing_required_feature 실기동  PASS  기동=exit R2", f"{full}: 필수 변수 {f} 를 채울 원천이 없다") 
G-S02  불량 등록부 r3_uses_disabled 실기동  PASS  기동=exit R3", f"{full}: 의존 과제 {u} 가 꺼져 있다") 
G-S02  불량 등록부 r4_live_synthetic 실기동  WARN  기동=up(D-27 대로) 그러나 zz4 는 DB 에 production 이 없어 R4 가 실제로 판정됐는지 알 수 없음 — 실경로는 t09 에서 FAIL(DEF-QA3-001) ·  {"status":"ok","db":true,"version":"0.1.0","tenant":"zz4","tasks":[{"task":"zz4.delta_e","model_ready":false,"version":null}]}
G-S02  불량 등록부 r5_plugin_conflict 실기동  PASS  기동=exit R5", f"{full}: 비용식 {module} 이 팩과 회사에 다른 구현으로 있다") 
G-M10  yn 기동 · 과제 2 · model_ready false  PASS  {'status': 'ok', 'db': True, 'version': '0.1.0', 'tenant': 'yn', 'tasks': [{'task': 'yn.target_value', 'model_ready': False, 'version': None}, {'task': 'yn.target_risk', 'model_ready': False, 'version': None}]}
G-M10  doctor API(eval 연결 · train 미연결)  PASS  [('demo', '연결'), ('eval', '연결'), ('train', '미연결'), ('actuals', '미연결')]
G-M10  학습 전 yn.target_value predict  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
G-M10  yn.target_value train(eval CSV) 접수 202  PASS  202 {'run_id': 'run_63f53b70cf660bdc', 'status': 'queued'}
G-M10  학습 전 yn.target_risk predict  PASS  HTTP 503 code=model_not_ready (기대 503 model_not_ready)
G-M10  yn.target_risk train 동시 접수 → 409 train_busy (계약 §3 회사당 1개 — QA 시험 순서 문제, 결함 아님)  PASS  409 {'error': {'code': 'train_busy', 'message': '이 회사의 학습이 이미 진행 중입니다', 'detail': {'rule': 'tenant_concurrency'}}}
G-M10  작업자(make worker) 실행  PASS  ", "status": "succeeded", "champion": "ridge", "beats_baseline": true, "artifact_dir": "<scratch>/art/yn/yn.target_value/run_63f53b70cf660bdc", "version": "v1", "stage": "candidate"}
G-M10  yn.target_value v1 stage→승인→production  PASS  200  202 200 {'approval_id': 'apr_01M4R70AM3WS22GZVA52NVZKGW', 'state': 'approved', 'production_version': 'v1'}  synthetic=False beats=True
G-M10  yn.target_value predict 200 · 18키 · 모델 v1  PASS  200 status=ok model={'name': 'ridge', 'version': 'v1', 'trained_at': '2026-10-12T23:06:59+09:00', 'snapshot_id': 'snp_c5e76af9d7c84cee', 'synthetic': False}
G-M10  yn.target_risk (순차 학습 — 동시 학습은 409 train_busy 계약대로) stage→승인→predict  PASS  200 {'approval_id': 'apr_01M4R70QB356QH68CWCY3N7CF1', 'state': 'approved', 'production_version': 'v1'} predict 200 prob=0.215705 model=v1
G-M02  KS-E1 GET /api/health  PASS  HTTP 200 
G-M02  KS-E2 GET /api/ml/overview  PASS  HTTP 200 
G-M02  KS-E5 GET /api/data/records?limit=2  PASS  HTTP 200 
G-M02  KS-E6 GET /api/data/records/KS-DEMO-0001  FAIL(DEF-QA3-003)  HTTP 404 {'detail': 'LOT를 찾을 수 없습니다'} — 원천 lot_id 형식(KS-DEMO-0001 · SW-DEMO-0001, ml_service.py:34 · :50)인데 호환 목록은 DEMO-0001 을 낸다. compat.entity_prefix 미사용
G-M02  KS-E6 GET /api/data/records/KS-DEMO-9999  PASS  HTTP 404 {'detail': 'LOT를 찾을 수 없습니다'}
G-M02  KS-E7 GET /  PASS  HTTP 404 {'error': {'code': 'not_found', 'message': '찾을 수 없습니다', 'detail': {}}} — 표준은 /app/* (task-map 에 명시), /app/overview 200
G-M02  KS-E7 GET /app/overview  PASS  HTTP 200 
G-M02  KS-E1(std) GET /api/v1/health  PASS  HTTP 200 
G-M02  SW-E1 GET /api/health  PASS  HTTP 200 
G-M02  SW-E2 GET /api/ml/overview  PASS  HTTP 200 
G-M02  SW-E5 GET /api/data/records?limit=2  PASS  HTTP 200 
G-M02  SW-E6 GET /api/data/records/SW-DEMO-0001  FAIL(DEF-QA3-003)  HTTP 404 {'detail': 'LOT를 찾을 수 없습니다'} — 원천 SW-DEMO-0001(ml_service.py:50), 호환 목록은 DEMO-0001
G-M02  SW-E6 GET /api/data/records/SW-DEMO-9999  PASS  HTTP 404 {'detail': 'LOT를 찾을 수 없습니다'}
G-M02  SW-E7 GET /  PASS  HTTP 404 — 표준은 /app/* (task-map 명시), /app/overview 200; {'error': {'code': 'not_found', 'message': '찾을 수 없습니다', 'detail': {}}}
G-M02  SW-E7 GET /app/overview  PASS  HTTP 200 
G-M02  SW-E1(std) GET /api/v1/health  PASS  HTTP 200 
G-S02  R4 실경로 — live 등록부 + 합성 production(qz4.delta_e)  FAIL(DEF-QA3-001)  health model_ready=true · predict 200 status=ok model v1 synthetic=true · tasks disabled=[] (기대: 과제 끄기 · 503 model_not_ready)
```

## 4. 관찰 (결함 아님)
- optimize 1회마다 `mlp_approval(kind=recommendation)` 이 생긴다 — 화면 3 을 탐색만 해도 승인 대기열이 추천 카드로 쌓인다(QA 세션 중 11장). 만료 규칙(D-73)과 함께 정할 것.
- 화면 4(390px)는 가로 스크롤은 없지만 표 열이 글자 단위로 꺾인다(1차 요구는 화면 2·3 의 1024px).
- 화면 5 는 operator 에게도 승인 · 반려 버튼을 보인다(누르면 403 — 서버 방어는 정상).
- `GET /` 는 404 — 원천은 `/` 에서 콘솔을 냈고 표준은 `/app/*`(task-map KS-E7 · SW-E7 에 명시).

## 5. 명령
```
source outputs/qa3/env.sh   # ml_qa3_db · scratchpad 산출물
createdb -h /tmp ml_qa3_db && psql -h /tmp -d ml_qa3_db -f src/mlcore/db/schema.sql && uv run python -m mlcore.db.seed_std
uv run python -m mlcore.train.jobs --submit <t> <task>          # 6과제
uv run python outputs/qa3/mkkeys.py <scratch>/keys.json
MLP_TENANT=ks uv run uvicorn mlcore.api.main:app --port 8203     # sw · yn · 불량 등록부도 같은 포트
QA3_KEYS=… uv run python outputs/qa3/t01_not_ready.py … t11_compat_cover.py
outputs/qa3/t08_bad_registry.sh ; uv run python outputs/qa3/t09_r4_real.py <tmp>
uv run python outputs/qa3/shots.py <label> <tenant> <role>
uv run pytest -q tests/test_optimize.py tests/test_approval.py tests/test_monitor.py tests/test_new_tenant.py tests/e2e   # 51 passed (ml_qa3_db)
uv run python gates/check_registry.py · check_task_cover.py · check_no_autopromote.py · check_routes.py              # 각 PASS
dropdb -h /tmp ml_qa3_db
```
