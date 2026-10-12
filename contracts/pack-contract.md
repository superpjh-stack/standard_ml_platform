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
  synth/*.py           # 필수 — def generate(rows: int, seed: int) -> pandas.DataFrame (6벌 demo_data() 이관)
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

## 4. 합성 생성기 `synth/*.py`

- 시그니처 `generate(rows: int = 720, seed: int = <pack.yaml synth.seed>) -> pd.DataFrame`. 표준 프레임 열(`entity_id` · `ts` · 변수 · 목표)을 낸다.
- 원천 `demo_data()` 와 **같은 시드에서 행 일치 100%**(G-M12) — 원천의 열 이름을 표준 이름으로 바꾸는 것 외에 값 · 순서를 바꾸지 않는다.
- 엔티티 접두어는 팩 중립(`DEMO-0001`)로 둔다. 원천 접두어(`KS-DEMO-`)는 회사 등록부 `compat.entity_prefix` 가 호환 라우터에서 붙인다.
- 설비 · 금형 코드 같은 회사 고유 범주값은 생성기에 두지 않는다. 필요한 범주는 팩 중립 값(`M1` …)으로 만들고 회사 `feature_map`/`compat` 이 대응한다.

## 5. 1차 팩

| 팩 | 과제 | 근거 |
|---|---|---|
| `press` | `remaining_hours` · `failure_24h` · `sensor_ood` · `maintenance_timing` | spec §2.2 · ks |
| `textile` | `delta_e` · `defect_risk` · `print_ood` · `print_setpoint` | spec §2.2 · sw |
| `_template` | `target_value`(regression) · `target_risk`(risk) | spec §2.2 `regression 1 · risk 1` |
