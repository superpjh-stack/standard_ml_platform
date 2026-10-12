# progress-dev3.md — 개발3 (팩 · 회사 · 감시 · 이관)

## 2차 웨이브 A2 — 개발3 (2026-10-13, 태그 core-freeze-2 위 작업 트리, 커밋 안 함) — 결정 D2-60 ~ D2-65

### 한 일 (파일)

| 묶음 | 파일 |
|---|---|
| 팩 `rollform-quote` | `pack.yaml`(synth jobs 900 · `synth.tasks.cad_objects` 1,600) · `features.yaml`(작업 8 + 기하 설명자 6) · `tasks/{machining_minutes,cad_objects,quote}.yaml` · `synth/{jobs,machining_minutes,cad_objects,sample_dxf}.py` · `extractors/{geometry_objects,object_classifier}.py` · `formulas/quote.py` · `samples/sample.dxf` · `baselines.yaml`(D2-62 확인 요청) |
| 회사 | `tenants/ot.yaml` · `tenants/ot/tasks/quote.yaml`(재질별 density · price_kg) · `tenants/krs.yaml`(demo + CSV · live 불가 D2-01 · 공급사A/B/C D2-61) · `tenants/pc.yaml`(`pc.recipe_optimize` 켬 — 개발1 요청) |
| fixture | `tests/fixtures/ot/{snapshot.parquet,snapshot.csv,source_drawing.json,source_quotes.json}` · `tests/fixtures/krs/{snapshot.parquet,snapshot.csv}` (생성: `migration/make_fixtures.py` · `migration/source_expected.py --tenant ot` — 원천 SQLite `mode=ro`) |
| 이관 | `migration/source_expected.py`(ot 키 묶음 추가 · kd 출력 불변 확인) · 새 `migration/reproduce_quote.py`(ot · kd 표준 재측정 + 원천 절차 재현 + 저장 견적 대조 → `outputs/reproduce-ot-kd.json`) · `migration/reproduce.py --phase2` 재실행(개발1 도구 · 등록부 tenants/) |
| 문서 | `docs/task-map.md` 6사 100 단위 · `docs/migration-report.md` §7~§12(2차 과제 12) |
| 시험 | 새 `tests/test_rollform_quote_pack.py`(21) · `tests/test_ot_quote_flow.py`(6, DB · API) · `tests/test_export_hub.py` +1 (6사) |

### 실측

| 항목 | 실측 | 명령 |
|---|---|---|
| 행 일치 | ot 작업 900 · 설명자 1,600 원천 참조와 100% · 원천 절차 시험 MAE **0.3166** = 원천 저장 견적 `test_mae` · 예측 1.3286 = 저장 `minutes_per_piece` | `pytest tests/test_rollform_quote_pack.py` |
| 추출 | 샘플 전개도 객체 9개 점 · 면적 · 둘레 · 라벨 · 점수(0.99/1.0)가 원천 저장 분석과 같다 · counts 1/6/2/0 · 1200 × 160 · 기하 8 사유 · 상한 413(vertices · points) · 요소 2,000 초과 413 entities(API) | 같은 시험 · `tests/test_ot_quote_flow.py` |
| 견적 | 표준 Decimal **726,484** = 원천 현행 식 726,484(원 단위) · 저장 **726,487** = 반올림 전 분 경로(앞 판, D2-60 — 가공비 +2 · 가산 +1) · .5 경계 사례 193.5 → 표준 194 / 원천 float 193 (D2-07a) | `uv run python migration/reproduce_quote.py` |
| 지표 (시험 1회) | ot.machining_minutes 표준 ridge MAE 0.2956 ↔ 원천 절차 0.3166 (−6.63%) · ot.cad_objects logreg macro-F1 1.0 (기준선 0.1, 혼동행렬 대각 80×4) ↔ 원천 절차 Extra Trees 1.0 · kd.labor_hours 3.7017 ↔ 보고 4.1071 (−9.87%) · krs MAE +3.65% · RMSE +12.76%(사유 K1 · K6) · pc 재측정 1.5375 ↔ 원천 1.7912 · 표본 내 1.0829 | `outputs/reproduce-ot-kd.json` · `outputs/reproduce-krs-pc.json` |
| 허브 6사 | `make export-hub DATE=2026-10-12` → 회사 6 · 소비자 92 · 변수 131 · 시험 12 passed (extract `model.features` · quote `inputs` 누락 = 코어 결함(2차) D2-63, 고치지 않음) | `make export-hub` · `pytest tests/test_export_hub.py` |
| 팩 4 baselines | eto 3.7017 · kimchi 1.5375 · solder 2.0935 = 재현 도구 값과 같다 · rollform-quote 0.2956 / 1.0 새로 적음(D2-62) | 위 두 JSON |
| pytest | **941 passed · 3 skipped · 1 xfailed · 0 failed** (83 s) | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| make gate | **PASS 23 · BLOCKED 1** | `make gate` |
| make gate2 | **41행 PASS 39 · BLOCKED 2(D-13) · FAIL 0** — G-S02 · G-M03 · G-M02(100/100) · G-M12(6사, 과제 20) · G2-P01 · G2-C01 · G2-I02 PASS. 첫 실행은 G-M14 bench FAIL(같은 시각 다른 담당 bench 컨테이너 `mlpbench-sw-*` 와 겹침) → 단독 bench PASS 30.97 ms → 재실행 FAIL 0 | `make gate2` · `gates/bench.py --compose` |
| 코어 동결 | `git diff core-freeze-2 -- src/mlcore web/src/components std contracts` **0줄** · 미추적 0 | 직접 실행 |

### 요청

- **아키텍트:** D2-62 rollform-quote baselines 값 확인 · D2-60(저장 견적 판 차이) 사람 확인 · D2-63 코어 결함(허브 내보내기 extract/quote 입력) 웨이브 P 여부.
- **개발2:** `tenants/ot.yaml` · `tenants/krs.yaml` 의 `compat.routes` 와 `tenants/{ot,krs}/compat.py` — ot 샘플 도면 `packs/rollform-quote/samples/sample.dxf`(pack_file · document_demo), `input_rename` 은 등록부에 있음, krs 공급사 옛 표기 A·B·C ↔ 공급사A·B·C 변환. kd `samples/sample.dxf` 는 재질이 회사 값이라 팩에 두지 않았다.
- **오케스트레이터:** bench 컨테이너 이름이 담당 간 겹친다(동시 gate 실행 시 G-M14 FAIL) — 동시에 돌리지 않도록.

## 2차 웨이브 P — 개발3 (2026-10-13, 기준 커밋 283dd31 위 작업 트리, 커밋 안 함) — 결정 D2-30 ~ D2-40

### 2차 §1 공표 (다른 담당이 쓰는 모양)

```python
# mlcore/registry/packs.py — 유형 3 키 검사(task-contract §6.1~§6.3). Pack.extractors = {이름: sha256}(R5)
validate_task(name, task, pack_code, features, all_tasks, pack_path=None) -> list[str]
validate_document(name, doc, sc, ceiling=None) · validate_rates(name, rates)        # 덮어쓰기 검사도 같은 함수
# mlcore/registry/tenants.py
material_aliases(merged) -> {별칭 대문자: 정규 값}   ·   normalize_category(merged, value) -> str
#   덮어쓰기: 모르는 키 → RegistryRejected("R1", "… 모르는 덮어쓰기 키 …") (DEF-QAR2-004)
# mlcore/monitor/review.py — 대기열 일정 작업(감시 뒤, task-contract §6.1 schedule)
run_review(tenant_id, day, *, merged=None) -> [ {task_id, uses, version, rule, threshold, threshold_from, pairs, created, skipped?, error?} ]
# mlcore/monitor/hub_export.py — make export-hub [DATE=]
build(day, *, codes=None) -> dict   ·   write(day, *, out_dir=None) -> Path   # var/export/hub/<date>.json (mlp-hub-export/1)
# mlcore/monitor/scheduler.run_once = 승인 요청 → 감시 → run_review → export_hub_after(day)
```

추출기 플러그인(개발2 2차 §2.1.1 모양 그대로) `packs/eto/extractors/{cad_regions,bom_text}.py` — `extract(raw, filename, *, unit, limits, model=None, context=None)`.
**개발2 요청:** 코어가 `context={"categories": 회사 categories, "material_aliases": tenants.material_aliases(merged)}` 를 넘겨 달라(bom_text 재질 검사 — 없으면 검사 없이 경고).
cad_regions 결과의 `preview`(bbox · paths · texts · scale_to_mm · source_unit · unsupported)는 화면 9 미리보기용 — 코어가 버려도 된다.
견적식 `packs/eto/formulas/quote.py` — `prepare(inputs, lines) -> {total_mass_kg}` · `quote(inputs, lines, predicted={"labor_hours": D}, rates) -> {lines[amount], costs{material, labor, outsource, markup, subtotal, vat}, total, predicted}`.

### 2차 실측

| 항목 | 실측 | 검증 명령 |
|---|---|---|
| 1. 등록부 유형 3 키 · 모르는 덮어쓰기 키 | 정상 팩 통과 · review_queue 14 · extract 15 · quote 16 거부 사례 · 덮어쓰기 모르는 키 4 · 허용 7 · 금지 16 · material_aliases 6 · 추출기 R5 · 저장소 등록부 회귀 — **86 passed** | `uv run pytest -q tests/test_registry_phase2.py` |
| 2. 대기열 일정 작업 | pc 학습 → 승인 → 예측 12 · 실측 8 → 검증 잔차 분위 임계값으로 항목 생성 · 재실행 0 · 늦은 실측 1 · max_items · production 없음 · 증거 없음 거부 · 스케줄러 연결 — **8 passed** (`test_monitor.py` 15 그대로) | `uv run pytest -q tests/test_monitor_review.py tests/test_monitor.py` |
| 3. 허브 내보내기 | 계약 스키마 통과 · 허브 schema.sql CHECK ⊇ · 허브 `registry.validate` 별도 프로세스 읽기 전용 import(허브 src · companies mtime 불변) · 비밀 · IP · URL · 입력/예측값 0 · 같은 날짜 같은 바이트 — **11 passed**. `make export-hub DATE=2026-10-12` → 회사 4 · 소비자 58 · 변수 96 (`var/export/hub/`, git 무시) | `uv run pytest -q tests/test_export_hub.py` |
| 4. 1차 잔여 | F7-7(D-123 앱 LOGIN 역할) 5 · F7-8(임시 DB teardown) 8 · F20-3(CONFIRM 명령줄만, 가짜 psql) 24 · F20-4 → `check_followups` 해결 32 · 열림 1(F7-5 아키텍트) | `uv run python gates/check_followups.py` |
| 5. 팩 eto · kimchi / 회사 kd · pc | kd 원천 절차 재현 시험 MAE **4.1071** · RMSE **5.0456** · R² **0.9956** · 샘플 58.146 h (원천 문서와 같음) · pc 행 일치 100%(420 · 결측 15) · 샘플 도면 영역 3 · BOM 4 · Σ650 kg · 경고 문구 = 원천 저장 결과 · 원천 저장 견적 2건 원 단위 일치(8,486,493 · 5,235,023) — 추출 **22** · 견적식 **10** · 합성 **6** passed | `uv run pytest -q tests/test_extract_eto.py tests/test_formula_eto_quote.py tests/test_synth_phase2.py` |
| 전체 시험 | **754 passed · 3 skipped** (--ignore=tests/e2e, 다른 담당 작업 포함) | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| make gate | **PASS 23 · BLOCKED 1** (G-M14 는 bench 를 앱 LOGIN 역할로 다시 재서 PASS — compose p95 28.2 ms · 기동 1.68 s · RSS 250 MB, D2-34) | `make gate` |
| make gate2 (2차 줄) | **G2-I02 FAIL → PASS** · **G2-H01 열림 15 → 1**(F7-5 아키텍트만) · G2-R01 · G2-E01 · G2-Q01 · G2-I01 PASS(개발1 · 2 시험 포함) · 6사 판정 팩 없음 4 → 2 · 회사 없음 4 → 2 (rollform-quote · solder · krs · ot — A2) · G2-P01 FAIL(남은 팩 · 회사 + baselines 값) | `make gate2` (합계 41행 — PASS 27 · FAIL 12 · BLOCKED 2, bench 재측정 전 실행 기준) |
| 정적 | G-M01 PASS(코어 113 · 팩 55 파일 위반 0) · G2-Q01 정적 PASS(견적식 2 파일) · G-S02 · G-M03 PASS(팩 5 · 회사 5 · 과제 YAML 14) · G-M11 PASS | `gates/check_core_terms.py` · `check_decimal.py` · `check_registry.py` · `check_tasks.py` · `check_deploy.py` |

### 2차 요청 · 남은 일

- **아키텍트:** D2-31(과제 이름 `quote` ↔ 유형 코드 — G-M01 금지어, `eto.quote` · `kd.quote` 보류) · D2-30(task-schema 에 `overridable_on_override` · 2차 규칙 표) · D2-33(review_item 부분 고유 색인) · D2-34(`gates/bench.py` 대행 확인) · D2-36(Makefile 대행 확인) · D2-39(baselines 값).
- **오케스트레이터:** 옛 시험 DB `ml_grants_check_db` 삭제 허락(D2-35 — 지우지 않았다).
- **개발2:** 추출기 `context` 인자(D2-37). **개발1:** 코어 주석 '평창식' → 일반어(D2-38, pc 별칭을 넣으면 G-M01).
- 남은 일(A0-2 · A2): `eto.quote` · `kd.quote`(D2-31 뒤) · kimchi `recipe_optimize` · 팩 solder · rollform-quote · 회사 krs · ot · task-map 6사 · 이관 보고서 · 허브 내보내기 6사.

## §1 공표 — 합성 생성기 노출 (웨이브 A0, 2026-10-12)

개발1 의 synthetic 어댑터가 쓴다. 계약과 다른 점은 `decisions.md` D-53(계약 불일치).

### 생성 함수 (팩 쪽, `packs/<pack>/synth/*.py`)

```python
def generate(rows: int = <pack.yaml synth.rows>, seed: int = <pack.yaml synth.seed>, *,
             categories: dict[str, list[str]] | None = None) -> pandas.DataFrame
```

- 반환 열: `entity_id`(`DEMO-0001`…) · `ts`(tz `Asia/Seoul`, 1시간 간격) · `features.yaml` 변수 · **목표 열(과제 `target.name` 이름)**.
  팩 안 과제가 생성기를 공유하면 목표 열이 여럿이다 — press: `remaining_hours` · `failure_24h`, textile: `delta_e` · `defect`, _template: `target_value` · `target_risk`.
  표준 프레임의 `target` · `tenant_id` · `task_id` · `_source` · `_source_ref` 열은 어댑터가 만든다(`target` ← 과제 `target.name` 열, anomaly 는 목표 없음).
- `categories`: 회사 등록부 `categories`(`values_from: tenant` 범주). 없으면 팩 중립 값(press `M1~M4` · `P1~P3`). textile · _template 은 받기만 하고 쓰지 않는다.
- 모듈 해석: 과제 진입점 `synth/<task>.py` 가 있으면 그것, 없으면 `pack.yaml synth.module`(공용). A0 진입점: `press/synth/remaining_hours.py` · `textile/synth/delta_e.py` (공용 모듈을 그대로 내보낸다).
  공용 모듈(`press_lots.py` · `print_lots.py` · `template_rows.py`)은 상대 import 가 없어 **`pack.yaml synth.module` 을 파일 경로로 바로 읽어도 된다**(개발1 `SyntheticSource(pack_dir, module, …)` 그대로 동작). 진입점까지 쓰려면 아래 로더를 쓴다.

### 로더 (코어 쪽, `mlcore.registry`)

```python
# mlcore/registry/packs.py
@dataclass(frozen=True)
class SynthSpec: pack: str; task: str | None; path: Path; seed: int; rows: int
def synth_spec(pack: Pack, task: str | None = None) -> SynthSpec      # 과제 → 실제 .py 경로 · pack.yaml 시드 · 행 수
def load_synth(pack: Pack, task: str | None = None) -> Callable        # generate 함수 (synth/ 를 패키지로 import)
# load_pack() 은 이제 pack.yaml synth.module 파일 존재 · seed/rows 정수를 검사한다(없으면 PackInvalid)

# mlcore/registry/tenants.py
@dataclass(frozen=True)
class SynthCall:
    tenant_id: str; task_id: str; spec: SynthSpec; seed: int; rows: int
    categories: dict[str, list[str]]; target: str | None; source_ref: dict
    def generate(self, rows: int | None = None, seed: int | None = None) -> pandas.DataFrame
def synth_call(merged: Merged, task_id: str, role: str = "demo") -> SynthCall
    # 시드: tenants/<t>.yaml sources.<role>.seed > pack.yaml synth.seed · rows: sources.<role>.rows > pack.yaml synth.rows
    # role 소스가 synthetic 이 아니면 ValueError, 켜진 과제가 아니면 KeyError
    # source_ref = {kind: synthetic, role, module: <저장소 상대 경로>, seed, rows, synth_sha256: <synth/*.py 묶음 해시>}
```

사용 예: `call = tenants.synth_call(tenants.load_and_merge("ks"), "ks.remaining_hours"); raw = call.generate()` → `raw[call.target]` 이 목표.

### fixture (`tests/fixtures/{ks,sw}/`)

`snapshot.parquet`(생성기 출력 그대로, 720행 · 13열) · `snapshot.csv`(같은 내용, UTF-8 BOM, `ts` 문자열 `+09:00`) — `sources.eval` 이 가리킨다. 생성 `uv run python migration/make_fixtures.py --tenant all --kind all`.

## §1.2 공표 — 과제 8 정의 완성 (웨이브 A, 2026-10-12) — 개발2 optimize 가 쓴다

정의 파일은 `packs/{press,textile}/tasks/*.yaml` (계약 `task-contract.md` §2 · §4 스키마 통과, `gates/check_tasks.py` G-M03 PASS). 원천 값과 대조는 `packs/*/tests/test_*_formulas.py`(손 계산 기대값).

| 회사 과제 | 유형 | 핵심 |
|---|---|---|
| `ks.remaining_hours` | regression | 변수 9 · `time_60_20_20` · 후보 ridge · random_forest · extra_trees · gbr · interval split_conformal α 0.1 · clip min 0 |
| `ks.failure_24h` | risk | 목표 `failure_24h` positive 1 · review_prob 0.5 · 후보 logreg · rf_clf · gbc |
| `ks.sensor_ood` | anomaly | contamination 0.08 · isolation_forest |
| `ks.maintenance_timing` | optimize | 아래 |
| `sw.delta_e` | regression | 변수 9 · review_above 3.5 · 후보 4 (gbr 200/3/0.05) |
| `sw.defect_risk` | risk | 목표 `defect` · review_prob 0.5 · logreg max_iter 1000 |
| `sw.print_ood` | anomaly | contamination 0.08 |
| `sw.print_setpoint` | optimize | 아래 |

### optimize 2 — 개발2 `tasks/optimize.py` 가 읽는 키

| 키 | `ks.maintenance_timing` | `sw.print_setpoint` |
|---|---|---|
| `uses` | `[press.remaining_hours]` | `[textile.delta_e, textile.defect_risk]` |
| `controls` | `[]` (센서는 조절 안 함) | `set_temp · set_pressure · line_speed · ink_usage · dwell_time` (학습 범위 ∩ min/max, step 10 · 1 · 3 · 4 · 15) |
| `fixed` | 변수 9 전부 (요청 `fixed`) | `absorb_rate · fabric_strength · print_type · color_tone` |
| `decision_vars` | `stop_after_hours: {min 0, max_param: max_delay_hours, step 0.5}` — 모델 입력 아님, 학습 범위 없음 | 없음 |
| `params` (요청 · 기본 · 범위) | `reserve_hours` 12 [1,150] · `max_delay_hours` 48 [0,72] · `max_cost_index` 140 [1,500] | `max_delta_e` 2.5 [0.5,8] · `max_risk` 0.2 [0.01,0.9] · `min_line_speed` 12 [6,24] |
| `formulas` | `maintenance_cost` → `packs/press/formulas/maintenance_cost.py::cost(row, params)` — row 키 `stop_after_hours` · `remaining_hours` | `process_cost` → `packs/textile/formulas/process_cost.py::cost(row, params)` — row 키 `ink_usage` · `line_speed` · `set_temp` · `dwell_time` |
| `objective` | minimize `maintenance_cost`, tiebreak maximize `stop_after_hours` | minimize `process_cost`, tiebreak minimize `delta_e` |
| `constraints` | `remaining_hours - stop_after_hours >= reserve_hours` · `maintenance_cost <= max_cost_index` | `delta_e <= max_delta_e` · `defect_risk <= max_risk` · `line_speed >= min_line_speed` |
| `search` | grid · max_points 10000 (max_delay 48 → 97점) | grid · max_points 10000 (원천 8,400점 · 표준은 학습 범위 교차로 줄어든다 — D-31) |
| `on_infeasible` | least_violation | least_violation |

- 식 안 이름: `remaining_hours` · `delta_e` 는 uses 과제의 **짧은 이름**(회귀 = 예측값), `defect_risk` 는 risk 과제 짧은 이름(= 확률). 원천 ks 는 `L` 을 소수 2자리로 반올림한 뒤 비용을 계산했다(호환 라우터만 재현). sw 원천은 비용을 소수 2자리로 반올림(호환 라우터만).
- violation 정규화: 계약 `Σ max(0, 위반량) / max(|rhs|, 1e-9)` — 원천 `max(reserve,1)` · `max(max_risk,.01)` 과 요청 하한(1 · 0.01) 때문에 같은 값.
- 원천 sw 는 추천 조건이 이상 탐지(IsolationForest)에 걸리면 "시험 인쇄" 경고를 붙였다. 계약 `uses` 는 anomaly 과제 값을 정의하지 않아 옮기지 못했다 → `decisions.md` D-W3-01(계약 보강 요청).

## §2 A0 실측 (2026-10-12)

| 항목 | 실측 | 명령 |
|---|---|---|
| 과제 정의 | `press.remaining_hours` · `textile.delta_e` + 두 팩 `features.yaml` — 원천 조사(§1.2-1.3 · §2.2-2.3)와 같다(변수 9 · 범위 · step · 후보 4 · 하이퍼파라미터 · 시간순). 변경 없음, 계약 스키마 통과 | `tests/test_packs_registry.py` |
| 생성기 | press · textile · _template 공용 모듈 3 + 과제 진입점 2 | `ls packs/*/synth/*.py` |
| 시험 | **31 passed** (test_synth 20 · test_packs_registry 11), 2.3 s | `OMP_NUM_THREADS=1 uv run pytest -q` |
| ks 원천 대조 | 행 720 · 결측 24 · 중복 0 · 범위 밖 0 · 챔피언 GBR / RF · 검증 MAE 5.213 · R² 0.9143 · 시험 **MAE 5.568 · RMSE 6.979 · R² 0.9199 · AUC 0.6444 · AP 0.1426 · Brier 0.0576 — 8값 자리수 일치** | `tests/test_synth.py` (근거 `KwangSung ML AI/docs/verification.md:30-34` · `tests/test_api.py:25,27`) |
| sw 원천 대조 | 행 720 · 결측 24 · 중복 0 · 범위 밖 0 · 불량률 31.5% · DTF/연한 색상 41건 · 챔피언 ET / GBC · 검증 MAE 0.520 · R² 0.752 · 시험 **MAE 0.557 · RMSE 0.709 · R² 0.722 일치**. 불량 AUC 0.8686 · AP 0.7823 · Brier 0.1261 (문서 0.868 · 0.781 · 0.127, 차이 ≤ 0.0013 — D-52) | 같은 파일 (근거 `SongWol ML AI/docs/verification.md:18,23-24`) |
| 범주 중립성 | 팩 중립 범주(`M1~M4` · `P1~P3`)로 만든 행을 ks 범주로 바꾸면 ks 프레임과 완전히 같다 | `test_neutral_categories_give_same_rows_as_tenant` |
| fixture 결정성 | 2회 생성 해시 같음 — ks parquet `bc49ed49…` · csv `3f6a10ce…`, sw parquet `360751ef…` · csv `c3ff085a…` | `uv run python migration/make_fixtures.py --tenant all --kind all` |
| gate 변화 | G-M03 **FAIL(synth 위반 3) → PASS**. G-S02 · G-M01 · G-S06(2행) PASS 유지. G-M12 사유 "합성 생성기 미이관 ['press','textile']" → `[]` (migration-report 는 A). 합계 PASS 6 → 7 | `make gate` |

## §2.1 웨이브 A 실측 (2026-10-12, 기준 커밋 7d583cf, 커밋 안 함)

| 항목 | 실측 | 명령 |
|---|---|---|
| 과제 8 정의 | 8/8 계약 스키마 통과 · optimize 2 비용식 원천 손 계산 대조(ks 6점 · sw 4점 + 반올림 77.96) · 공간 ks 97점 · sw 원천 격자 8,400 | `uv run python gates/check_tasks.py` · `uv run pytest -q packs/` (14 passed) |
| G-M02 task-map | 32/32 (ks 16 · sw 16) · 미대응 0 | `uv run python gates/check_task_cover.py` |
| G-M12 이관 대조 | 4과제 12지표 ±10% 안(최대 −0.71% sw Brier) · 표준 재현 ks MAE 5.5683 · RMSE 6.9793 · R² 0.9199 · AUC 0.6444 · AP 0.1426 · Brier 0.0576 / sw MAE 0.5569 · RMSE 0.7088 · R² 0.7222 · AUC 0.8686 · AP 0.7823 · Brier 0.1261 · anomaly flag ks 0.1389 · sw 0.1458(밴드 안) · optimize ks 후보 97 = 97 · 충족 89 / sw 1,080(원천 8,400 — D-31 사유) · 충족 314(원천 1,054). 2회 실행 JSON 바이트 같음 | `OMP_NUM_THREADS=1 uv run python migration/reproduce.py` (3 s) · `uv run python gates/check_migration.py` |
| 감시 | PSI 손 계산 3사례(5.248899 · 0.6·ln2.5 · 0) · drift PSI 9+9 변수 = 순수 파이썬 계산(rel 1e-9) · ks vibration 5.598 / sw absorb_rate 5.367 retrain · 나머지 < 0.2. 드리프트 → 접수(run_id) → 작업자 candidate v2 → 감시 stage → 승인 요청 pending(requested_by monitor) · production v1 그대로 · 두 번째 요청 0. 예측 모드 volume 6 · live_perf MAE 10.0(실측 연결 6) | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_monitor.py` (15 passed, 2.5 s) |
| doctor | ks · sw demo/eval 연결 720행 · 대응률 100% · 결측 각 8/720 · train/gateway/actuals 미연결(D-13) · 정적 대응률 ks 66.7% · sw 77.8% · ks 목표 없음(D-33) · CSV 없음 → 미연결 · 목표 열 없음 → 목표 없음 · 출력에 환경변수 값 0 | `uv run python -m mlcore.monitor.doctor --tenant ks` · `uv run pytest -q tests/test_doctor.py` (7 passed) |
| 새 회사 | 빈 등록부 → `make_tenant --new yn<hex> --pack _template --csv <tmp>` → seed 1회사 2과제 → doctor eval 600행 → train(eval) ×2 → stage → promote → decide → predict 18키 · synthetic=false. 생성 파일 = 등록부 루트의 `<code>.yaml` 1개, 저장소 tenants · fixtures · var 에 0 | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_new_tenant.py` (3 passed) |
| API (B02 · B06 · B12 · B14 · doctor) | 6 시험: 목록 4과제 · 폼 메타(values_from → 회사 값) · overview(production 없음 = null · model_ready false) · 감시 경고 배지 · records cursor 페이징 720 · 잘못된 cursor 422 · viewer 감시 403 · 다른 회사 키 404 ×6 경로 | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_ops_api.py` |
| 원천 DB 사본 (D-W1-10) | `tests/fixtures/{ks,sw}/source_db.sql` — 테이블 3+3 · 720행 · 대응 열 값 = snapshot(오차 0) · 재생성 바이트 같음 | `uv run pytest -q tests/test_fixture_source_db.py` (4 passed) |
| 화면 1 · 6 | `Overview.tsx`(서버 · 과제표 · 운영 버전/`운영 모델 없음 (model_not_ready)` · 합성 배지 · 어제 예측 · 승인 대기 · 감시 배지 · 대상 데이터 표 · CSV BOM/수식 주입 방지) · `Monitor.tsx`(변수별 PSI · 범위 밖 · 결측 추이 · 실측 성능/`실측 없음` · 재학습 후보 → 승인 대기열 링크 · doctor 표). `_placeholder` 0 | `cd web && npx tsc -b && npm run build` (성공) |
| 전체 시험 | **375 passed · 3 failed · 3 skipped** (41 s). 실패 3 = 다른 담당: `test_api_contract.py` B08 `GET /runs/{id}` 미구현(개발1) · `test_compat.py` 옛 키 반올림 2(개발2). 건너뜀 3 = test_compat 케이스 없음(개발2). 개발3 시험 실패 0 | `OMP_NUM_THREADS=1 uv run pytest -q` |
| make gate | **PASS 18 · FAIL 5 · BLOCKED 1** (전 PASS 11). 개발3 몫 **G-M02 · G-M08 · G-M09 · G-M10 · G-M12 FAIL → PASS**. 기존 PASS 유지. 남은 FAIL: G-S03(e2e 없음) · G-S04(B08) · G-M04(compat) · G-M11(compose) · G-M14(bench) — 개발3 담당 아님 | `OMP_NUM_THREADS=1 uv run python gates/gate.py` |

## §3 요청 · 남은 일

요청:
- **아키텍트**: `Makefile` `doctor` · `tenant`(CSV 인자) · `monitor` 대상 연결(D-W3-07). D-W3-01 ~ 08 결정(특히 D-W3-02 감시의 staging, D-W3-04 덧붙인 API 키). D-52 · M5 뒤 `baselines.yaml` 값 기입 — 재현값은 위 표(`migration/reproduce.py`).
- **개발2**: `api/main.py` 에 `ops.router` 등록 — 반영된 것 확인(`include_router(ops.router)`). `tests/_dev2.py::use_tenants_dir` 의 환경변수 되돌리기(D-W1-06 개발2 몫).
- **개발1**: D-W1-06 개발3 몫 고침(`registry.tenants.tenant_base` = `tenants_base_for` 규칙). D-W1-10 원천 DB 사본 `tests/fixtures/<t>/source_db.sql` 제공 — 모양은 개발1 시험의 사본과 같다(`FX_KEY` · `FX_AT` · 등록부 대응 열, 스키마 없음 → `SET search_path`). gateway 원장(EIF_PLC_RAW · PRC_MONITOR_DATA) 사본이 필요하면 모양(열 · 창)을 알려 주면 만든다.

남은 일:
- 화면 1 · 6 실제 브라우저 확인(1024px 포함) — e2e(G-S03)는 QA3 · 개발2 Playwright(D-40) 뒤.
- `compat_expected.json`(G-M04, 개발2 요청 시) · 스케줄러 상주 실행 운영 문서 · 감시 `source_health` 지표(doctor 결과를 일일 행으로).
- D-W3-01 이 정해지면 `print_setpoint.yaml` 에 이상 경고 키.



## §2.2 웨이브 C 실측 — 결함 수정 (2026-10-12, 기준 커밋 9d2febc, 커밋 안 함 · 이번 회전 아키텍트 권한 포함)

결함마다 회귀 시험을 먼저 써서 실패를 확인한 뒤 고쳤다(빨강 → 초록). 결정은 `decisions.md` D-120 ~ D-126.

| 결함 | 수정 전(시험 실패) | 수정 후 | 명령 |
|---|---|---|---|
| DEF-QA3-001 #17 R4 실경로 | `health` delta_e model_ready **True** · predict **200**(QA3 재현 그대로) | live 기동 → delta_e disabled · predict 404(503 은 개발2 요청 D-120a) · defect_risk(CSV 학습) 200 synthetic=false · DB 없음 → live 과제 전부 끔 · demo 는 DB 안 봄 · **7 passed** | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_r4_live_path.py` |
| G-S02 R4 판정 | `lambda tid: True` 주입 | 실기동 경로 시험 통과로만 셈(건너뜀 = FAIL) · 5/5 PASS | `uv run python gates/check_registry.py` |
| DEF-QA1-003 · 004 #10 #11 | approver_role 변경 · target 변경 · 목표 ∈ 입력 **8 failed** | R1 거부 · **10 passed** · G-M03 변형 4 → **7/7** | `uv run pytest -q tests/test_override_rules.py` · `gates/check_tasks.py` |
| DEF-QA1-005 #12 doctor | 소스별 기대 **6 failed** | sw gateway 0.0% 목표 없음 · actuals 77.8% 있음 · train null(미확인) / ks gateway 0.0% · actuals 66.7% · 목표 없음 · **9 passed** | `uv run pytest -q tests/test_doctor.py` · `make doctor TENANT=sw` |
| DEF-QA2-009 #16 append-only | replica 우회 · mlp_app DELETE 보유 **4 failed** | ENABLE ALWAYS · mlp_app 최소 권한 · 보호 구간 2회 재적용 데이터 유지 · **7 passed**(기존 DB `ml_grants_check_db` · 새 DB `ml_grants_fresh_db` 둘 다) · ml_db · ml_test_db 에 `make db-grants`(ml_test_db mlp_audit 행 유지) | `uv run pytest -q tests/test_schema_grants.py` · `MLP_GRANTS_DB=ml_grants_fresh_db …` |
| #7 Makefile | `make db-reset` 즉시 삭제 | `db-schema` · `db-reset` · `gate-full` CONFIRM=1 없으면 exit 2(실측 3/3) · `setup` 비파괴 · `db-grants` 추가 | `make db-reset` → rc 2 |
| G-S06 outputs 위생 | FAIL 3건(`.invalid`) | `.invalid` 만 허용 · 실 호스트는 그대로 FAIL(시험) · **13 passed** · G-S06 PASS | `uv run pytest -q tests/test_check_secrets_hosts.py` |
| compat.optimize_rename | 없음 | ks · sw 기입(원천 줄 근거) — test_compat ks 행 키에 `cost_index` 반영 | `tenants/{ks,sw}.yaml` |

- 전체 시험: **456 passed · 3 skipped · 0 failed** (45 s, 이 시점 개발1 · 2 작업 트리 포함) — `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e`.
- `make gate`: **PASS 21 · FAIL 2 · BLOCKED 1**. 개발3 몫 G-S02 · G-S06(2행) · G-M03 · G-M08 · G-M09 · G-M10 · G-M12 PASS 유지. FAIL 2 = 남의 몫 진행 중: G-M04(`tests/test_compat.py` 개발2 가 새로 쓴 DEF-QA2-001 · 010 회귀 시험 4 — 행 키 `reserve_hours` · `anomaly` · overview 키) · G-M14(bench docker 네트워크 포트 설정 실패 — 환경).

### 요청 (웨이브 C)
- **개발2 (D-120a)**: ① live 회사 + `ref.synthetic` production → 503 `model_not_ready`(predict · batch · optimize uses · 호환) — 기동 뒤 승인된 합성 모델은 병합이 못 본다. ② `catalog.get` 이 `merged.disabled` 과제면 503 `model_not_ready`(지금 404). 들어오면 `tests/test_r4_live_path.py::test_live_boot_refuses_synthetic_prediction` 를 503 만 받게 좁힌다. ③ 호환 optimize 의 ks `reserve_hours` · sw `anomaly` · 미충족 · objective 문구를 회사 값으로 두려면 키 이름을 알려 달라 — 원천을 읽어 기입한다.
- **오케스트레이터 · 아키텍트**: task-contract §3 표 · §4 `immutable_on_override` 에 approver_role · target 추가(D-121, 계약 파일은 이번 내 파일 목록 밖). compose 앱 계정을 `mlp_app` 구성원 LOGIN 역할로(D-123). `make image` 는 커밋 뒤 다시.
- 시험 DB 2개를 새로 만들었다(`ml_grants_check_db` 상시 · `ml_grants_fresh_db` 1회 확인용) — 지우지 않았다(DB 삭제 금지).

## §2.3 웨이브 C 마무리 (2026-10-12, 개발3 + 아키텍트 권한, 커밋 안 함)

| 항목 | 실측 | 명령 |
|---|---|---|
| 호환 회사 값(D-132) | ks: optimize_row · optimize_derived(reserve_hours) · unmet · objective 문구 · overview_values(products) / sw: optimize_rename + `print_ood: anomaly` · optimize_row · row_round · unmet · objective · anomaly 문구 · overview_values(print_types · color_tones) · overview_controls — 원천 `api/ml_service.py` 파일:줄 주석. 기대값 파일 수정 0 | `uv run pytest -q tests/test_compat.py` 35 passed · 3 skipped |
| warn_with | `print_setpoint.yaml warn_with: [textile.print_ood]` · 병합 규칙 3 이 warn_with 도 본다(시험 1) · 불량 픽스처 r5 에 print_ood 켬(R5 만 어기게) | `tests/test_override_rules.py` 11 passed |
| R4 503 | 개발2 D-120a 반영 → 회귀 시험을 503 `model_not_ready` 만 받게 좁힘 | `tests/test_r4_live_path.py` 7 passed |
| 계약 | task-contract §1 group_key(D-85) · §2 warn_with = `extrapolation`(D-131) · §3 · §4 approver_role · target(D-121) / tenant-contract §1 D-132 키 · read_role(D-88) / interfaces §2.2 해시 v2(D-87) | — |
| 정리 | `ml_grants_check_db` · `ml_grants_fresh_db` dropdb(내가 만든 것만). `tests/test_schema_grants.py` 는 다음 실행 때 `ml_grants_check_db` 를 새로 만든다(새 DB 확인 경로) | — |
| 전체 | pytest 459 passed · 3 skipped · e2e 10 passed · make gate 2회 PASS 23 · BLOCKED 1 | — |
