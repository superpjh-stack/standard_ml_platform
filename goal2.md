# /goal2 — 표준 ML 플랫폼 2차 구축 (유형 +3 · 팩 +4 · 회사 +4 · 화면 +4 · API +3 묶음 · 연동 2)

> **이 문서가 2차 엔지니어링 메타프롬프트다.** `/loop` 는 매 회전 이 문서를 판정 기준으로 읽는다.
> 루프 프로토콜 · 상태 파일 · 멈추지 않기 규칙 · 역할 · 공통 서두는 **`goal.md` §4 · §5 · §6 · §8 을 그대로 쓴다.** 이 문서는 2차에서 달라지는 것만 적는다.
> 1차 결과(커밋 `ff1a311`, `progress.md` 최종 보고): gate PASS 23 · BLOCKED 1(D-13), pytest 459 · e2e 10, QA 재검증 치명 0.

| 항목 | 값 | 출처 |
|---|---|---|
| 정본 | `intro.md` · `problem.md` · `spec.md` · `goal.md` · `goal2.md` (사람만 고친다) | — |
| 근거 · 원천 (읽기 전용) | `../Koreal Solder ML AI` · `../PyoungChang ML AI` · `../OneTouch ML AI` · `../KyungDong ML AI` (+1차 원천 2) · `../Standard AI Agent Platform` · `../Standard Data Hub` | `intro.md` §3 |
| **2차 범위** | 유형 **`review_queue` · `extract` · `quote`** · 팩 **`solder` · `kimchi` · `rollform-quote` · `eto`** · 회사 **`krs` · `pc` · `ot` · `kd`** · 화면 **7~10** · API **B09 review · B10 documents · B11 quotes** · 연동 **Agent `ml.*` 도구 계약 · 데이터 허브 `make export-hub`** · 1차 경미 결함 정리 | `goal.md` §10 · `spec.md` §8.2~8.4 · §12 · §13 · §18 |
| 규모 (2차 끝) | 유형 7 · 팩 6 + `_template` · 회사 6 + `_template` · 화면 10 · API 15 묶음 · 소스 어댑터 5 · mlp 테이블 16(변경 없음이 목표) | `spec.md` |
| 핵심 | **코어 동결** — 유형 3 을 넣는 웨이브 P 가 끝나면 `core-freeze-2` 태그. 그 뒤 `src/mlcore/` 변경 **0줄**로 팩 4 · 회사 4 를 붙인다. 바꿔야 하면 1차 결함으로 `decisions.md` 에 올리고 웨이브 P 로 되돌아간다 | `goal.md` §10 · `spec.md` 머리말 |
| 범위 밖 | 실데이터 `production`(키가 없으면 `BLOCKED (D-13)`) · 딥러닝/비전 · 설비 자동 적용 · 정답 라벨 작성 · 원천 수정 | `problem.md` §5 |
| 완료 기준 | **6개사가 코드 수정 없이 등록부 · 팩만으로 기동되고, 6개사 기존 기능 전부(task-map 100%)가 표준 과제로 돌며, 1차 게이트 전부 + 2차 게이트 전부 PASS(BLOCKED 는 D-13 실연결만), QA 재검증 치명 0** | `spec.md` §18 |

---

## 0. 이 문서를 어떻게 쓰는가

### 0.1 루프 기동

```
/loop goal2.md 를 판정 기준으로 표준 ML 플랫폼 2차를 만든다
```

한 회전은 `goal.md` §4.2 와 같다. 판정 명령만 `make gate` → **`make gate2`**(1차 게이트 전부 + §2 의 2차 게이트)로 바뀐다. 웨이브 순서는 Phase P0 → P → (`core-freeze-2`) → A0-2 → A2 → B2 → C2.

### 0.2 1차와 다른 점

- **코어를 두 번 열지 않는다.** 웨이브 P 에서 유형 3 · B09~B11 · 화면 7~10 공용 부품 · 연동 어댑터 · 1차 경미 결함을 **한꺼번에** 코어에 넣고 1차 게이트를 다시 통과시킨 뒤 동결한다. A2 이후는 팩 · 회사 · 화면 데이터 · 시험 · 문서만 바뀐다(G2-C01).
- **사람이 고친 값이 정본이 되는 과제가 있다.** `extract` 는 사람이 검토 · 수정한 인식값이, `quote` 는 확정된 견적 스냅숏이 이후 계산의 입력이다. 수정 이력(`overrides`)을 잃으면 결함이다.
- **정답이 없으면 지표를 내지 않는다.** 도면 인식은 라벨이 없으므로 IoU · F1 을 만들지 않고 `labels: none` 을 표시한다(경동 D-160). 규칙 추출기는 원천과의 **결과 일치**로 판정한다.
- **평창 수치는 다시 잰다.** 원천의 표본 내 평가 수치는 대조 대상이 아니다. 표준 절차로 다시 잰 값을 보고서에 원천 값과 나란히 적는다(±10% 대조 제외, 사유 기록).
- **돈 계산은 Decimal 이다.** 견적은 `Decimal` · `ROUND_HALF_UP` 으로 원천과 원 단위까지 같아야 한다. float 경로가 하나라도 있으면 결함이다.
- **연동은 계약만, 상대 저장소는 읽기만.** Agent 플랫폼 · 데이터 허브에 쓰지 않는다. 우리 쪽 계약 · 내보내기 파일 · 시험만 만들고, 상대 쪽 형식은 그 저장소 파일을 읽어 맞춘다.

---

## 1. 목표

끝났다고 말할 수 있는 상태는 이것뿐이다.

1. **코어 동결(웨이브 P 끝):** 유형 7 · API 15 · 화면 1~10 의 코어 부분이 들어간 상태로 1차 게이트 PASS 23 · BLOCKED 1 이 유지되고, `core-freeze-2` 태그가 찍힌다.
2. **수직 관통(A0-2):** `kd.quote`(DXF 업로드 → `cad_regions`/`bom_text` 추출 → 사람 검토 · 수정 → `labor_hours` 예측 → 비용식 → 견적 확정 → CSV)와 `pc.residual_review`(학습 → 승인 → 운영 예측 → 실측 → 잔차 대기열 → 검토 결과)가 API 로 끝까지 돈다.
3. 6개사가 `make run TENANT=<code>` 로 기동되고, `docs/task-map.md` 가 6개사 기존 기능 **100%** 를 대응한다.
4. 4개사 이관 대조(`docs/migration-report.md`)가 같은 합성 시드로 원천 보고 지표와 ±10% 안이거나 행별 사유를 갖는다. 평창은 재측정 값 + 원천 값 병기.
5. 화면 7~10 이 e2e(1024px)를 통과하고, API B09~B11 이 오류 계약 · CSV 수식 주입 방지를 지킨다.
6. Agent `ml.*` 도구 계약(`contracts/agent-tools.md`)과 계약 시험이 있고, `make export-hub` 출력이 데이터 허브 수확기 형식(그 저장소 파일을 읽어 확인)을 통과한다.
7. 1차 경미 결함 이슈(#7 · #13 · #16 · #19 · #20)가 해결되거나 사유와 함께 남는다.
8. QA 재검증 치명 0.

### 재사용 자산

| 자산 | 위치 | 쓰임 |
|---|---|---|
| 1차 플랫폼 | 이 저장소 `src/mlcore` · `packs/{press,textile}` · `tenants/{ks,sw}` · `gates/` | 유형 4 · 소스 5 · 등록부 · 감시 · 게이트 — **모양을 따라 만든다** |
| 잔차 대기열 | `../Koreal Solder ML AI/api/ml_service.py`(|잔차| ≥ 4 MPa) · `../PyoungChang ML AI/api/*`(상위 10%) | `review_queue` 규칙 · 기대값. 평창 **평가 방식은 가져오지 않는다** |
| 배합 최적화 | 고려솔더 · 평창 무작위 탐색 5,000 · 3,500 · 위반 순위 대체 | `optimize` 의 `random` 전략 대조 |
| 도면 · 견적 | `../KyungDong ML AI/api/{cad,quote,storage}.py` · `data/reference/customer_answers.json`(D-160) · `../OneTouch ML AI/api/*` · `data/demo/` · `scripts/generate_sample_data.py` | 규칙 추출기 · 객체 분류 · BOM 텍스트 · Decimal 견적식 · `overrides` · `reviewed` 규칙 · 5 MiB · 20,000 엔티티 상한 |
| Agent 도구 | `../Standard AI Agent Platform/contracts/tool-contract.md` · `spec.md` §5 | `ml.predict` · `ml.explain` · `ml.recommend` · `ml.monitor_summary` 의 이름 규칙 · `ToolMeta` · 근거(Cite) 모양 |
| 데이터 허브 | `../Standard Data Hub/companies/*.yaml` · `src/datahub/*/harvest*` · `contracts/` | 소비자(ML) · 과제 · 변수 · 소스 · 호출 수 내보내기 형식 |

---

## 2. 수용 게이트 — `make gate2`

**1차 게이트(G-V01 · G-S01~07 · G-M01~14)는 전부 그대로 유지하되, 판정 대상이 6개사로 넓어진다**(예: G-M02 는 6개사 task-map, G-M04 는 켜진 과제 전부, G-M12 는 6개사 이관 대조, G-S02 는 회사 6 + `_template`). 아래는 2차에서 더해지는 게이트다.

| # | 항목 | 게이트 | 검증 |
|---|---|---|---|
| G2-C01 | 코어 동결 | `core-freeze-2` 태그 이후 `git diff core-freeze-2 -- src/mlcore web/src/components std contracts` **0줄**(웨이브 P 로 되돌아가 태그를 다시 찍은 경우 그 사유가 `decisions.md` 에 있다). A2 이후 커밋이 바꾼 파일은 `packs/` · `tenants/` · `web/src/screens/` 데이터 · `tests/` · `docs/` · `migration/` 뿐 | `gates/check_core_freeze.py` |
| G2-V01 | 2차 수직 관통 | §1-2 의 `kd.quote` · `pc.residual_review` 흐름이 API 로 끝까지 — 견적 금액이 원천 견적식과 원 단위 일치, 대기열 항목이 시험 구간 · 운영 잔차에서만 | `tests/test_vertical_slice_2.py` |
| G2-T01 | 유형 3 계약 | `review_queue` · `extract` · `quote` 가 `std/task_types.yaml` · `contracts/` 에 있고, 각 유형의 입력 · 출력 · 상태 전이 · 오류가 계약 시험을 통과. 2차 유형 경로의 501 은 0 | `gates/check_contract.py`(확장) · `tests/test_types_phase2.py` |
| G2-R01 | 대기열 누수 | 대기열은 시험 구간 잔차 또는 실측이 붙은 운영 예측 잔차로만 만든다. 학습 · 검증 구간 잔차를 쓰면 실패(guard 계측). 평창식 전체 재적합 후 같은 데이터 채점 픽스처는 거부 | `gates/check_leakage.py`(확장) · `tests/test_review_queue.py` |
| G2-E01 | 추출 | 규칙 추출기(kd 영역 3종 · BOM 텍스트) 결과가 원천 샘플 DXF 에서 원천 코드와 같다(원천을 **읽어** 기대값 작성, 실행 금지). 객체 분류(ot)는 1,600 합성 설명자로 학습 · macro-F1 보고. 정답 라벨이 없는 도면은 IoU/F1 없음 + `labels: none`. 5 MiB · 20,000 엔티티 상한 · 잘못된 DXF → 422 | `tests/test_extract.py` |
| G2-Q01 | 견적 | 견적식이 `Decimal` · `ROUND_HALF_UP` 만 쓴다(float 경로 정적 검사 0). 원천 견적 fixture 와 원 단위 일치. `reviewed: true` + `review_note` ≥ 5자 없으면 확정 422. 사람 수정 → `overrides` 기록. 확정 견적은 모델이 바뀌어도 금액 불변(스냅숏). CSV 수식 주입 방지 · UTF-8 BOM | `tests/test_quote.py` · `gates/check_decimal.py` |
| G2-P01 | 팩 · 회사 | 팩 `solder` · `kimchi` · `rollform-quote` · `eto` 가 `features.yaml` · 과제 ≥ 2 · `synth/` · `baselines.yaml` · 시험을 갖고, 회사 `krs` · `pc` · `ot` · `kd` 가 로드된다. 6벌 `demo_data()` 와 팩 `synth/` 행 일치 100%(4개사 추가분) | `gates/check_registry.py` · `gates/check_tasks.py` · `tests/test_synth.py` |
| G2-S01 | 화면 7~10 | 7 데이터 소스 · 스냅숏 · 8 검토 대기열 · 9 도면 추출 · 견적 · 10 감사 · 예측 추적이 6개사에서 HTTP 200 · `_placeholder` 0 · 1024px 가로 스크롤 0 · 회사 화면 코드 0 | `tests/e2e/` |
| G2-A01 | API 15 | B09 `/review*` · B10 `/documents*` · B11 `/quotes*` 포함 15 묶음 200 · 오류 계약 · 역할(§6 확장) · 회사 범위 404 · 목록 `{items, next_cursor}` | `tests/test_api_contract.py` |
| G2-I01 | Agent 도구 | `contracts/agent-tools.md` 에 `ml.predict` · `ml.explain` · `ml.recommend` · `ml.monitor_summary` (읽기 · 추천만, 결과의 `prediction_id` 가 근거). Agent 플랫폼 `tool-contract.md` 의 이름 규칙 · 인자 스키마 · `ToolMeta(readonly)` 모양을 따른다. 계약 시험이 FastAPI 로 4 도구를 호출해 스키마 일치 | `tests/test_agent_tools.py` |
| G2-I02 | 허브 내보내기 | `make export-hub` 가 6개사 과제 · 변수(`std_name`) · 소스 · 일 호출 수를 데이터 허브 수확기 형식으로 낸다. 형식은 `../Standard Data Hub` 파일을 읽어 맞추고, 그 저장소의 검증 함수가 있으면 **읽기 전용으로 import 해** 통과(쓰기 0) | `tests/test_export_hub.py` |
| G2-H01 | 1차 잔여 | #7 · #13 · #16 · #19 · #20 의 각 항목이 해결(회귀 시험) 또는 `decisions.md` 사유. D-123(compose 앱 계정 = `mlp_app` 구성원 LOGIN) 해결 | `gates/check_followups.py` (이슈 항목 목록 대조) |
| G2-L01 | 실데이터 | 사람이 `.env` 에 키를 넣은 회사에서 `make train-live` → `production` 1과제. 키가 없으면 `BLOCKED (D-13)` | `make doctor-live` · `train-live` |

### 2.1 오류 계약 추가 (2차 유형)

| 상황 | 응답 |
|---|---|
| DXF 가 아님 · 깨짐 | 422 `invalid_document` |
| 5 MiB · 20,000 엔티티 초과 | 413 `document_too_large` |
| 정답 라벨 없음(평가 요청) | 200 + `labels: none` · 지표 null |
| 검토 없는 견적 확정 | 422 `missing_required` (`reviewed` · `review_note`) |
| 확정된 견적 수정 | 409 `quote_locked` |
| 대기열 항목 재검토(이미 닫힘) | 409 `already_decided` |

---

## 3. 팀 편성과 웨이브

```
Phase P0  원천 조사 4사 · 유형 3 계약 · 화면 7~10 계약 · 연동 계약 · 게이트 2차분 (아키텍트 단독)
   ↓
웨이브 P  코어 확장 (개발 3, 병렬) — 유형 3 · B09~B11 · 화면 7~10 공용부 · 연동 · 1차 경미 결함
   ↓  ── 1차 게이트 재통과 + G2-T01 · G2-R01 · G2-H01 → `git tag core-freeze-2`
웨이브 A0-2 수직 관통 (kd.quote · pc.residual_review) — 팩 `eto` · `kimchi` 최소분         → G2-V01
   ↓
웨이브 A2 팩 4 · 회사 4 · 화면 데이터 · 이관 대조 · 허브 내보내기 (코어 0줄)              → G2-* 전부
   ↓
웨이브 B2 QA 3 (병렬) → 웨이브 C2 수정 → QA 재검증 (치명 0 까지 반복)
```

### 3.1 Phase P0 — 아키텍트

1. `migration/source_inventory.md` 에 4개사 절 추가 — 엔드포인트 · `FEATURE_META` · 후보 · 분할 · 보고 지표(실측값) · 최적화 공간 · 대기열 규칙 · 추출 규칙 · 견적식 · 화면 · 시험 수를 **파일을 직접 열어** 파일:줄로. G-M02 · G-M12 의 분모가 된다.
2. `contracts/` 갱신: `task-contract`(유형 3 키) · `predict-contract`(대기열 · 추출 · 견적 응답 모양, 18키 원칙과의 관계) · `api-contract`(B09~B11 경로 · 역할 · 오류 §2.1) · `screen-map`(7~10 소유자) · `db-schema`(16 테이블로 충분한지 — 부족하면 `표준 변경 요청`) · 새 `agent-tools.md` · 새 `hub-export.md`.
3. `gates/` 에 `check_core_freeze.py` · `check_decimal.py` · `check_followups.py` 와 `make gate2`. 아직 대상이 없으면 정직하게 FAIL.
4. `decisions.md` 에 §7 의 D2-01~ 를 옮긴다. `progress.md` 에 2차 절.

### 3.2 개발 3명 (웨이브 P · A2 공통 소유)

| 담당 | 웨이브 P (코어) | 웨이브 A2 (데이터) | 화면 |
|---|---|---|---|
| **개발1** 데이터 · 학습 | `review_queue` 학습 · 잔차 계산(guard 경유) · `extract` 의 모델 기반 추출기 학습(객체 분류) · #13 잔여 | 팩 `solder` · `kimchi` 의 학습 과제 · 4개사 이관 재현(`migration/reproduce.py`) | 7 데이터 소스 · 스냅숏 |
| **개발2** 추론 · 승인 · API | `extract` 서비스(업로드 · 상한 · 규칙/모델 추출기 인터페이스) · `quote` 흐름(Decimal · 검토 · overrides · 스냅숏 · CSV) · B09~B11 · Agent 도구 4 · #16 · #19 · #20 | 4개사 호환 라우터(옛 경로 · 옛 키) | 8 검토 대기열 · 9 도면 추출 · 견적 · 10 감사 · 예측 추적 |
| **개발3** 팩 · 회사 · 감시 · 이관 | 등록부가 유형 3 의 과제 키를 검증 · 대기열 일정 작업(감시 스케줄러) · `make export-hub` · D-123 · #7 | 팩 `rollform-quote` · `eto` (추출기 · 견적식 플러그인) · 회사 4 등록부 · task-map 6개사 · 이관 보고서 | — |

- 웨이브 P 에서 공용 부품(상태 배지 · 지표 표 · 폼 생성기 확장 · 문서 뷰어)은 개발2 소유 `web/src/components/` 하나만.
- **A2 에서 코어를 고쳐야 하면 고치지 않는다.** `decisions.md` 에 `코어 결함(2차)` 으로 올리고 오케스트레이터가 웨이브 P 로 되돌릴지 정한다.

### 3.3 QA 3명 (웨이브 B2) — `goal.md` §3.3 의 관점 + 2차분

| 담당 | 2차에서 더 보는 것 |
|---|---|
| QA1 데이터 · 학습 · 평가 | 대기열 누수 · 평창 재측정 · 고려솔더 IQR 이상치 제거가 검증/시험을 보는지 · 객체 분류 층화 분할 · 4개사 이관 대조를 원천 코드로 재계산 |
| QA2 추론 · 계약 · 보안 | DXF 파서 공격(거대 엔티티 · 깊은 중첩 · 악성 텍스트) · 업로드 상한 · 견적 float 경로 · CSV 수식 주입 · Agent 도구가 쓰기를 하지 않는지 · 허브 내보내기에 비밀값 · 실데이터가 섞이지 않는지 · 코어 동결 위반 |
| QA3 화면 · 흐름 · 새 회사 | 화면 7~10 · 견적 검토 → 수정 → 확정 → 재수정 409 · 대기열 동시 검토 · 6개사 `make tenant` · task-map 6개사를 원천으로 대조 |

치명 기준은 `goal.md` §3.3 에 더해: **확정 견적 금액이 바뀜 · 사람 수정 이력 소실 · 라벨 없이 IoU/F1 이 나옴 · 대기열이 학습 구간 잔차로 채워짐 · A2 이후 코어가 바뀜.**

---

## 4. 루프 프로토콜

`goal.md` §4 를 그대로 따른다. 달라지는 점만:

- 판정 명령은 `make gate2`. 종료 판정은 `CONFIRM=1 make gate-full` + `make gate2` 2회 연속.
- 웨이브 P 의 끝 = 1차 게이트 전부 PASS(BLOCKED 는 D-13) + G2-T01 · G2-R01 · G2-H01 PASS → 오케스트레이터가 `git tag core-freeze-2` 를 찍는다(로컬). 태그 뒤 코어 결함이 나오면 웨이브 P 로 되돌아가 고치고 태그를 다시 찍되, 그 사유를 `decisions.md` 에 남긴다.
- 커밋 메시지 접두: `2차 P:` · `2차 A0:` · `2차 A:` · `2차 C:`.
- push 는 사람이 요청할 때만.

### 4.1 종료 조건 (EXIT)

1. 1차 게이트 전부 + G2-C01 · G2-V01 · G2-T01 · G2-R01 · G2-E01 · G2-Q01 · G2-P01 · G2-S01 · G2-A01 · G2-I01 · G2-I02 · G2-H01 PASS (BLOCKED 는 G-M08 doctor-live · G2-L01 의 D-13 만)
2. `CONFIRM=1 make gate-full` PASS
3. QA 2차 리포트 3종 + 재검증 치명 0
4. 연속 2회전 실측 변화 없음

멈출 때 `progress.md` 맨 위에 2차 최종 보고 — 게이트 판정표, 6개사 과제 표(유형 · 챔피언 · 지표 · 기준선 · 원천 값 · 차이 · 사유), 견적 대조표, 추출 대조표, 코어 동결 실측, 사람 결정 목록, 열린 이슈.

---

## 5. 에이전트 기동 프롬프트

`goal.md` §5 공통 서두를 그대로 쓰고, 끝에 이 두 줄을 더한다.

> 지금은 **2차**다. 판정 기준은 `goal2.md`, 명령은 `make gate2`. 웨이브 A2 이후에는 `src/mlcore/` · `web/src/components/` · `std/` · `contracts/` 를 고치지 않는다 — 고쳐야 하면 `decisions.md` 에 `코어 결함(2차)` 으로 올리고 멈춘다.
> 견적은 `Decimal` 만, 추출은 라벨 없으면 지표 없음, 대기열은 시험 · 운영 잔차만. DB 를 지우는 명령은 `CONFIRM=1` 이 있어도 오케스트레이터 허락 없이 돌리지 않는다.

역할별 할 일은 §3.2 표와 §2 게이트를 그대로 지시문으로 쓴다.

---

## 6. 역할 · 권한 추가 (`std/roles.yaml` — G2-A01 기대값)

| 화면 · API | admin | approver | operator | viewer |
|---|---|---|---|---|
| 7 데이터 소스 · 스냅숏 | ○ | 조회 | ✕ | ✕ |
| 8 검토 대기열 · `GET/PATCH .../review*` | ○ | ○ (자기 과제) | 조회 | ✕ |
| 9 도면 추출 · 견적 · `POST .../documents` · `POST .../quotes` · 확정 | ○ | ○ | ○ (확정은 ✕) | ✕ |
| 10 감사 · 예측 추적 | ○ | ✕ | ✕ | ✕ |

견적 **확정**은 approver 이상으로 둔다 `[가설 D2-04]`.

---

## 7. 결정 대장 추가 (Phase P0 에서 `decisions.md` 로)

| # | 확인 필요 | 기본값 (가설) | 한 곳 |
|---|---|---|---|
| D2-01 | 고려솔더 소스 | 실데이터 없음 → `demo`(합성) + CSV 업로드. `live` 불가 표시 | `tenants/krs.yaml` |
| D2-02 | 평창 재측정 | 표준 절차(시간순 또는 무작위 60/20/20 · 시험 1회)로 다시 잰 값이 정본. 원천 표본 내 수치는 병기만, ±10% 대조 제외 | `docs/migration-report.md` |
| D2-03 | 고려솔더 IQR 이상치 제거 | 학습 구간에서만 계산(1차 `outlier: iqr` 그대로). 원천과 지표 차이는 사유 기록 | `packs/solder/tasks/*.yaml` |
| D2-04 | 견적 확정 권한 | approver 이상 | `std/roles.yaml` |
| D2-05 | 문서 원본 보관 | `mlp_document.raw_sha256` + 파일 `var/documents/<tenant>/<sha>.dxf`(커밋 금지) · 보존 1년 | `contracts/db-schema.md` |
| D2-06 | 도면 영역 종류 | 경동 D-160 의 3종(title_block · bom_table · rev_table) | `packs/eto/extractors/*` |
| D2-07 | 견적 통화 · 반올림 | KRW 원 단위 · `ROUND_HALF_UP` · 원천 단계별 반올림 순서 그대로 | `packs/*/formulas/quote.py` |
| D2-08 | Agent 도구 노출 | `ml.predict` · `ml.explain` · `ml.recommend` · `ml.monitor_summary` 4개, 전부 `readonly` (`ml.recommend` 는 추천만 — 승인 요청은 만들지 않는다) | `contracts/agent-tools.md` |
| D2-09 | 허브 내보내기 주기 | `make export-hub` 수동 + 감시 일일 작업 뒤 1회 파일 생성(`var/export/hub/<date>.json`, 커밋 금지) | `monitor/` |
| D2-10 | 포트 · DB | 1차와 같다(8200 · 5190 · ml_db · ml_test_db). QA 는 전용 DB · 포트 | `.env.example` |
| D2-11 | 대기열 기준 | 고려솔더 \|잔차\| ≥ 4 MPa · 평창 상위 10% (원천 그대로) — 팩 기본값, 회사 덮어쓰기 가능 | `packs/{solder,kimchi}/tasks/residual_review.yaml` |
