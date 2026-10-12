# 계약 — 업종 팩 `packs/<pack>/` (Pack Contract)

> **정본.** 출처: `spec.md` §2.2 · §11.1 · §15. 검사: `gates/check_registry.py`(G-S02) · `gates/check_tasks.py`(G-M03) · `gates/check_core_terms.py`(G-M01).
> **팩은 회사를 모른다.** 팩 파일에 회사 코드(`ks` · `sw` …를 식별자로 쓰는 것) · 회사명 · 원천 테이블 · 열 이름 · 설비 코드 · 키 · 호스트가 0 이다.

## 1. 구조

```
packs/<pack>/
  pack.yaml            # 필수
  features.yaml        # 필수 (contracts/feature-contract.md)
  tasks/*.yaml         # 필수, ≥ 2 (contracts/task-contract.md)
  formulas/*.py        # optimize 비용식 — def cost(row: dict, params: dict) -> float 순수 함수
  synth/*.py           # 필수 — 공용 모듈(pack.yaml synth.module) + 선택 과제 진입점 synth/<task>.py. 시그니처 §4 (6벌 demo_data() 이관)
  baselines.yaml       # 필수 — 합성 기준 지표(아키텍트만 고친다 · 좋게만)
  tests/               # 팩 시험(이관한 원천 시험 케이스)
  README.md
```

## 2. `pack.yaml`

```yaml
code: textile                 # 폴더 이름과 같다
name: 섬유 · 날염
version: 0.1.0
core_min: 0.1.0               # 코어 최소 버전
synth: {module: synth/print_lots.py, seed: 42, rows: 720}
notice: "예측값은 참고용이며 …"            # 기본 문구
status_labels: {}             # std/statuses.yaml 문구 덮어쓰기(코드는 못 바꾼다)
monitor: {psi_warn: 0.2, psi_retrain: 0.3, oor_warn: 0.05, missing_warn_pp: 0.10, perf_drop: 0.25, perf_window_days: 30}
tasks: [delta_e, defect_risk, print_ood, print_setpoint]   # tasks/*.yaml 파일 이름과 같다
```

## 3. `baselines.yaml`

```yaml
# 같은 합성 시드 · 같은 분할에서 표준 플랫폼이 낸 시험 지표. spec §16.2: 5% 이상 나빠지면 gate 실패.
<task>: {metric: <name>, value: <number>, measured_by: <커밋 · 날짜>, source_reported: <원천 보고값 | null>}
```

Phase 0 에는 값이 비어 있다(`value: null`). 첫 값은 개발3 이관 대조(M5) 후 **아키텍트가** 적는다. 값이 없으면 기준선 회귀 게이트는 FAIL 이다(가짜 PASS 금지).

## 4. 합성 생성기 `synth/*.py` (D-53 확정)

```python
def generate(rows: int = <pack.yaml synth.rows>, seed: int = <pack.yaml synth.seed>, *,
             categories: dict[str, list[str]] | None = None) -> pandas.DataFrame: ...
```

- **`categories`(키워드 전용)**: 회사 등록부 `categories` — `values_from: tenant` 범주 변수의 회사 값 목록(D-34). `None` 이면 팩 중립 값(`M1` …)을 쓴다. 범주를 쓰지 않는 팩도 이 인자를 받기만 한다(호출 모양을 하나로).
- **반환 열**: `entity_id`(팩 중립 `DEMO-0001` …) · `ts`(tz `Asia/Seoul`) · `features.yaml` 변수 · **목표 열(과제 `target.name` 이름 그대로)**. 팩 안 과제들이 생성기를 공유하면 목표 열이 여럿이다. 표준 프레임의 `target` · `tenant_id` · `task_id` · `group` · `_source` · `_source_ref` 열은 **어댑터(`SyntheticSource`)가** 만든다 — 생성기는 회사 · 과제를 모른다.
- **모듈 해석(둘 다 둔다)**: 과제 진입점 `synth/<task>.py`(spec §4.2 표기)가 있으면 그것, 없으면 `pack.yaml synth.module`(공용). 해석 · 시드 · 행 수는 `registry.packs.synth_spec(pack, task)` 한 곳에서 정한다. 시드 · 행 수 우선순위: `tenants/<t>.yaml sources.<role>.tasks.<task>.seed|rows` > `pack.yaml synth.tasks.<task>.seed|rows` > `tenants/<t>.yaml sources.<role>.seed|rows` > `pack.yaml synth`. 과제별 값(`synth.tasks: {<task>: {rows?, seed?}}`, 웨이브 P 마감 D2-45)은 같은 팩에서 행 수가 다른 생성기(예 rollform-quote 작업 900 행 · 객체 설명자 1,600 행)를 위한 것이다 — 팩 과제가 아닌 이름 · 정수 아닌 값은 PackInvalid. 진입점은 공용 모듈을 다시 내보내기만 해도 된다.
- `load_pack()` 은 `synth.module` 파일이 있고 `seed` · `rows` 가 정수인지 검사한다(없으면 `PackInvalid` — G-M03).
- 원천 `demo_data()` 와 **같은 시드에서 행 일치 100%**(G-M12) — 원천의 열 이름을 표준 이름으로 바꾸는 것 외에 값 · 순서를 바꾸지 않는다.
- 엔티티 접두어는 팩 중립(`DEMO-0001`)로 둔다. 원천 접두어(`KS-DEMO-`)는 회사 등록부 `compat.entity_prefix` 가 호환 라우터에서 붙인다.
- 설비 · 금형 코드 같은 회사 고유 범주값은 생성기에 두지 않는다. 회사 값은 `categories` 인자로만 들어온다(중립 값으로 만든 행을 회사 값으로 바꾸면 회사 프레임과 같아야 한다 — `tests/test_synth.py`).
- 생성기가 없거나 실패하면 어댑터는 `SourceDisconnected` 를 낸다. 합성 값을 대신 지어내지 않는다.

## 5. 1차 팩

| 팩 | 과제 | 근거 |
|---|---|---|
| `press` | `remaining_hours` · `failure_24h` · `sensor_ood` · `maintenance_timing` | spec §2.2 · ks |
| `textile` | `delta_e` · `defect_risk` · `print_ood` · `print_setpoint` | spec §2.2 · sw |
| `_template` | `target_value`(regression) · `target_risk`(risk) | spec §2.2 `regression 1 · risk 1` |

## 6. 2차 팩 4 (Phase P0 아키텍트, goal2 G2-P01)

| 팩 | 과제 (≥ 2) | 합성 생성기 `synth/` | 플러그인 | 원천 |
|---|---|---|---|---|
| `solder` | `joint_strength` · `recipe_optimize` · `residual_review` | `synth/solder_lots.py` — krs `make_sample_data()` 이관(seed 20260917 · 720 행 · 결측 24 · 이상치 5, RNG 순서 그대로) | `formulas/material_cost.py`(조성 단가) | source_inventory §8 |
| `kimchi` | `sensory_score` · `recipe_optimize` · `residual_review` | `synth/kimchi_lots.py` — pc `_demo_data()` 이관(seed 42 · 420 행 · 재추출 루프 포함 · 12h 시각) | `formulas/material_cost.py` | §9 |
| `rollform-quote` | `machining_minutes` · `cad_objects` · `quote` | `synth/jobs.py`(ot `demo_jobs()` 900) · `synth/geometry.py`(`geometry_training_data()` 1,600) | `extractors/geometry_objects.py`(rule+model) · `formulas/quote.py`(Decimal) | §10 |
| `eto` | `labor_hours` · `drawing_regions` · `quote` | `synth/jobs.py`(kd `demo_jobs()` 900) · 샘플 DXF 생성기(`synth/sample_dxf.py`, 원천 `cad.sample_bytes()` 이관 — 시험용) | `extractors/cad_regions.py` · `extractors/bom_text.py` · `formulas/quote.py` | §11 |

- **새 플러그인 폴더 `extractors/`** — 모양은 `task-contract.md` §6.2. `formulas/quote.py` 는 `def quote(inputs, lines, predicted, rates) -> dict` 이고 `Decimal` 만 쓴다(`gates/check_decimal.py` 가 `packs/*/formulas/quote.py` · `src/mlcore/tasks/quote*.py` 를 정적 검사).
- 팩 키워드 · 재질 · 제품군 같은 범주 기본값은 업종 중립으로 두고(예: 재질 `M1`…), 원천의 회사 값은 회사 등록부 `categories` 로만(§4 규칙 그대로). 영역 키워드(DRAWING NO 등)는 업종(도면) 공통 어휘라 팩에 둔다.
- 2차 4 팩의 `baselines.yaml` 은 Phase P0 에 비어 있다(`value: null`) — 이관 대조 뒤 아키텍트가 적는다. 비어 있으면 G2-P01 FAIL.
