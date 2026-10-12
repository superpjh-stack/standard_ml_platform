# 계약 — 과제 정의 `packs/<pack>/tasks/<task>.yaml` (Task Contract)

> **정본.** 출처: `spec.md` §3.2 · §3.3 · §5 · §8.1 · §11.3. 검사: `gates/check_tasks.py`(G-M03) · `gates/check_registry.py`(G-S02).
> 과제 YAML 은 **팩 변수 이름**만 쓴다. 원천 테이블 · 열 이름 · 회사 코드는 쓰지 않는다(G-M01). 회사 값은 `tenants/<code>/tasks/<task>.yaml` 덮어쓰기로만.

## 1. 키 (전 유형 공통)

| 키 | 필수 | 형 | 규칙 |
|---|---|---|---|
| `id` | ○ | `<pack>.<task>` | 파일 이름 = `<task>.yaml`. 소문자 · 숫자 · `_` |
| `type` | ○ | enum | `std/task_types.yaml` 의 코드. 1차는 phase 1 만 켤 수 있다. **덮어쓰기 불가** |
| `title` | ○ | string | 화면 제목 |
| `entity` | ○ | enum | `lot` · `equipment_window` · `job` · `drawing` |
| `time_key` | 시계열이면 ○ | string \| null | 있으면 `split` 은 `time_*` 만 허용(누수 규칙). **덮어쓰기로 지울 수 없다** |
| `group_key` | | string \| null | 같은 그룹은 분할 경계를 넘지 않는다. **덮어쓰기로 지울 수 없다**. 시간순 분할에서 시간순 · 같은 시각 묶음 · 그룹 경계를 함께 지키는 자르기 위치가 없으면 **학습 거부** `split_time_group_conflict`(다시 줄 세우지 않는다 — D-85) |
| `features` | 지도 · anomaly ○ | list[str] | 전부 `features.yaml` 에 있어야 한다 |
| `split` | 학습 과제 ○ | enum | `std/split_policies.yaml`. `time_key` 가 있으면 `time_60_20_20` 또는 `time_cv5` |
| `candidates` | 학습 과제 ○ | list[str] | `std/candidates.yaml` 이름, 그 후보의 `types` 에 이 과제 `type` 이 있어야 한다 |
| `candidate_params` | | map | 후보 이름 → 하이퍼파라미터(팩 기본). 원천 값 이관용 |
| `out_of_range` | ○ | enum | `predict_with_warning` · `reject` (D-07: 1차 8과제 모두 `predict_with_warning`) |
| `max_imputed` | | int | 기본 3. 넘으면 422 `missing_required` |
| `approver_role` | ○ | string | 승인 지점. 회사는 **값(담당 역할명)** 은 바꿀 수 있으나 **키를 지우거나 승인을 건너뛰게** 할 수 없다 |
| `monitor` | | map | `psi_warn` · `psi_retrain` · `oor_warn` · `missing_warn_pp` · `perf_drop` · `perf_window_days` (D-06 기본) |
| `notice` | | string | 없으면 `pack.yaml` 기본 문구 |
| `seed` | | int | 학습 · 무작위 탐색 시드. 기본 = 팩 `synth` 시드 |
| `outlier` | | `iqr` \| `{method: iqr, k: 1.5, columns: [...]}` | 기본 꺼짐(D-60). 경계는 **그 학습 구간(폴드 학습 · 재적합 학습)에서만** 재고 그 구간 행만 뺀다 — 검증 · 시험 행은 그대로. 모르는 방법은 학습 failed |
| `candidate_search` | | `{<후보>: {<파라미터>: [값, ...]}}` | 기본 꺼짐(D-60, spec §5.2). 후보당 최대 `std/candidates.yaml` 탐색 횟수(20)회 무작위(시드 = 과제 `seed`), 첫 시도 = `candidate_params` 기본값, 선정은 검증 지표만. 비지도(anomaly)는 탐색하지 않고 경고 `search_skipped` |

## 2. 유형별 키

| 유형 | 키 | 규칙 |
|---|---|---|
| `regression` | `target: {name, unit, direction}` ○ | `direction`: `lower_is_better` · `higher_is_better` · `target_band` |
| | `thresholds: {review_above?, review_below?, watch_band?}` | 상태 판정 (predict-contract §2.2) |
| | `interval: {method: split_conformal, alpha}` ○ | 검증 구간 잔차로만 보정 |
| | `clip: {min?, max?}` | 출력 하한 · 상한(원천 `max(0, …)` 이관) |
| | 기준선 선택 (D-61) | `time_key` 가 있으면 `train_mean` · `last_value`(`std/metrics.yaml baselines`) 중 **검증 구간 선정 지표가 더 나은 쪽**(동률 `train_mean`). 시험 구간은 고르는 데 쓰지 않는다. 두 기준선의 검증 · 시험 지표는 `report.baselines_compared`, 산출물 lock 에 `baseline_kind` |
| `risk` | `target: {name, positive}` ○ | 이진 |
| | `thresholds: {review_prob, watch_prob?}` ○ | 등급 high ≥ review_prob · watch ≥ watch_prob |
| | `calibration: {method: none \| sigmoid \| isotonic}` | 검증 구간으로만 |
| `anomaly` | `contamination` ○ | 0 < c < 0.5. **임계값 = 학습 구간 모델이 낸 검증 구간 점수의 `1 - c` 분위**(표본 밖 점수, `time_cv5` 는 폴드별 검증 점수를 이어 붙인 것). 이 값을 학습+검증 재적합 모델에 그대로 쓴다 — 회귀 구간 `q` 와 같은 방식. 재적합 모델의 표본 내 점수 분위 · 시험 구간은 쓰지 않는다(D-50) |
| | 기준선 판정 | 라벨이 없으므로 우열 대신 **시험 `flag_rate` ∈ `contamination` × `std/metrics.yaml flag_rate.beats_band`([0.5, 2.0])** 이면 `beats_baseline`. 범위 밖이면 candidate 까지(staging 거부) |
| | `candidates: [isolation_forest]` | |
| `optimize` | `uses: [<pack>.<task>, ...]` ○ | 의존 과제가 같은 팩에 있고, 회사에서 켜져 있어야 한다(병합 규칙 3) |
| | `controls: [<feature>, ...]` | `controllable: true` 변수. 생략하면 `features.yaml` 의 controllable 전부 |
| | `fixed: [<feature>, ...]` | 요청에서 받는 고정 입력 — 의존 과제 features 중 controls 를 뺀 것 |
| | `decision_vars: {<name>: {min, max \| max_param, step, unit, label}}` | **모델 입력이 아닌** 결정 변수(예: 정비 대기 시간). 학습 범위가 없으므로 `[min, max]` 만 쓴다 — spec §8.1 보강(D-25) |
| | `params: {<name>: {default, min, max, unit, label}}` | 요청 `params` 로 받는 제약 상한 · 하한 값 |
| | `formulas: {<name>: <formulas 모듈 이름>}` | 팩 `formulas/<module>.py::cost(row, params) -> float` 순수 함수 |
| | `objective: {minimize \| maximize: <name>, tiebreak: [{minimize \| maximize: <name>}]}` ○ | `<name>` 은 uses 과제의 **짧은 이름**(`<pack>.` 뺀 과제 이름 — regression 은 예측값, risk 는 확률) · formula 이름 · decision_var |
| | `constraints: [{name, expr}]` ○ | `expr` = `<lhs> (<=|>=|<|>) <rhs>` 한 줄. lhs · rhs 는 uses 과제의 짧은 이름 · formula · decision_var · controls · `params` 이름 · 숫자 · 단순 `+ - *` |
| | `search: {strategy: grid \| random \| auto, max_points}` ○ | auto = 공간 ≤ max_points 면 grid |
| | `on_infeasible: least_violation` ○ | violation = Σ max(0, 위반량) / max(\|rhs\|, 1e-9) |
| | `warn_with: [<pack>.<anomaly 과제>]` | 선택(D-76, 원천 sw "시험 인쇄로 먼저 확인" 이관). 추천(best) 조건이 그 과제 **production** 모델의 flag 에 걸리면 `warnings` 에 `extrapolation`(field = 그 과제 id — predict-contract §3 코드, D-131)을 넣는다. 목적 · 제약 · 순위에는 쓰지 않는다. production 이 없으면 같은 코드 `extrapolation` 에 문구 `… (model_not_ready)` 로 확인하지 못했음을 보인다(숨기지 않는다). 의존 과제 규칙(병합 규칙 3)을 같이 받는다 |
| | 고정 입력 범위 밖 (D-72) | optimize 의 허용 상태는 `needs_approval` · `review` 뿐 — 고정 입력이 학습 범위 밖이면 경고 `out_of_range`(field = 고정 변수) + `out_of_range_fields` + status `review` |

## 3. 덮어쓰기 (`tenants/<code>/tasks/<task>.yaml`, spec §3.3)

| 바꿀 수 있다 | 바꿀 수 없다 (어기면 기동 거부 — 병합 규칙 1) |
|---|---|
| `thresholds` · `features` 추가/제외(필수 아닌 것) · `candidates` · `candidate_params` · `constraints` 의 값 · `params` 기본값 · `monitor` · `notice` · `title` | `type` · `split`(시간순 → 비시간순) · `time_key` · `group_key` 삭제 · `approver_role` 바꾸기 · 지우기(승인 지점 — tenant-contract R1, D-121) · `target` 바꾸기(목표는 팩 정의만 — D-121) · 목표 열을 입력 변수에 넣기(목표 누수 — D-121) · `uses` 의 과제 바꾸기 · `on_infeasible` 끄기 · `interval` 끄기 |

## 4. 기계 판독 스키마 (`check_tasks.py` 가 이 블록을 읽는다)

```yaml task-schema
common_required: [id, type, title, entity, out_of_range, approver_role]
learned_required: [features, split, candidates]          # regression · risk · anomaly
by_type:
  regression: {required: [target, interval], target_required: [name, unit, direction]}
  risk:       {required: [target, thresholds], target_required: [name, positive], thresholds_required: [review_prob]}
  anomaly:    {required: [contamination]}
  optimize:   {required: [uses, objective, constraints, search, on_infeasible], learned: false}
enums:
  entity: [lot, equipment_window, job, drawing]
  out_of_range: [predict_with_warning, reject]
  direction: [lower_is_better, higher_is_better, target_band]
  on_infeasible: [least_violation]
  search_strategy: [grid, random, auto]
immutable_on_override: [type, split, time_key, group_key, uses, on_infeasible, interval, approver_role, target]   # approver_role · target — D-121
not_removable_on_override: [approver_role]
time_split_policies: [time_60_20_20, time_cv5]
```

## 5. 1차 과제 8 (ks 4 · sw 4)

| 회사 과제 | 팩 과제 | 유형 | 목표 / 대상 | 원천 근거 (migration/source_inventory.md) |
|---|---|---|---|---|
| `ks.remaining_hours` | `press.remaining_hours` | regression | `remaining_hours` (h) | KwangSung `api/ml_service.py:77-94` |
| `ks.failure_24h` | `press.failure_24h` | risk | `failure_24h` | `:80-95` |
| `ks.sensor_ood` | `press.sensor_ood` | anomaly | — (contamination 0.08) | `:96` |
| `ks.maintenance_timing` | `press.maintenance_timing` | optimize | uses remaining_hours · decision `stop_after_hours` | `:132-148` |
| `sw.delta_e` | `textile.delta_e` | regression | `delta_e` (ΔE) | SongWol `api/ml_service.py:96-113` |
| `sw.defect_risk` | `textile.defect_risk` | risk | `defect` | `:99-114` |
| `sw.print_ood` | `textile.print_ood` | anomaly | — (contamination 0.08) | `:115` |
| `sw.print_setpoint` | `textile.print_setpoint` | optimize | uses delta_e · defect_risk · controls 5 | `:154-192` |
