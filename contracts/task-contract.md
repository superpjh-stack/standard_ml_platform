# 계약 — 과제 정의 `packs/<pack>/tasks/<task>.yaml` (Task Contract)

> **정본.** 출처: `spec.md` §3.2 · §3.3 · §5 · §8.1 · §11.3. 검사: `gates/check_tasks.py`(G-M03) · `gates/check_registry.py`(G-S02).
> 과제 YAML 은 **팩 변수 이름**만 쓴다. 원천 테이블 · 열 이름 · 회사 코드는 쓰지 않는다(G-M01). 회사 값은 `tenants/<code>/tasks/<task>.yaml` 덮어쓰기로만.

## 1. 키 (전 유형 공통)

| 키 | 필수 | 형 | 규칙 |
|---|---|---|---|
| `id` | ○ | `<pack>.<task>` | 파일 이름 = `<task>.yaml`. 과제 이름은 소문자 · 숫자 · `_`, 팩 코드는 `-` 도 허용(`rollform-quote` — D2-14). **std 어휘(유형 · 상태 · 오류 코드 · 지표 · 기준선 이름)와 같은 팩 이름은 "과제 이름 = 그 과제 자신의 유형 코드" 하나만 허용**(예 `eto.quote` 의 type `quote`) — 변수 · 목표 · 비용식 이름이나 다른 유형의 과제 이름으로 쓰면 G-M01 팩 위반(D2-31) |
| `type` | ○ | enum | `std/task_types.yaml` 의 코드. 1차는 phase 1 만 켤 수 있다(2차 유형 3 은 웨이브 P 가 phase 1 로 올린 뒤 — §6). **덮어쓰기 불가** |
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
| `input_rules` | | `[{name, expr, between: [lo, hi]}]` | 변수 조합 규칙(원천 krs 조성 합 100 ± 0.1 · pc 배합 합 98~102 이관). `expr` 은 §2 제약과 같은 안전 식(이름 · 숫자 · `+ - *` · 괄호), 이름은 features.yaml 수치 변수(quote 는 `inputs` 도). predict · predict:batch · optimize `fixed` · 견적 `inputs` 에서 형식 → min/max 뒤에 검사, 값이 [lo, hi] 밖이면 422 `invalid_input`(detail `field` = 규칙 `name`, `rule` = `input_rule` — 입력값 되풀이 없음). 식의 변수 중 결측(null)이 있으면 그 규칙은 건너뛴다. **덮어쓰기 불가** |
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
| | `derived: {<feature>: "<식>"}` | 탐색점마다 식으로 계산하는 **모델 입력**(예: 조성 등식 `sn_pct: "100 - ag_pct - cu_pct - sb_pct - flux_pct"`). 대상은 uses 과제의 수치 입력이고 controls · fixed · decision_vars 가 아니다. 식의 이름은 controls · fixed · decision_vars · params. **수락:** 값이 그 변수의 `[min, max]` ∩ 의존 모델 학습 범위(p1~p99) 밖인 점은 버린다(원천 "범위 안 배합만 수락"). `random` 은 시드 고정 순서로 수락된 점이 `search.max_points` 개가 될 때까지 뽑는다(`n_candidates` = 수락 수, 뽑은 수 · 상한 도달은 `mlp_recommendation` 저장본 `acceptance`). 수락 0 이면 422 `invalid_input`(rule `derived_range`). 후보 `conditions` 에 derived 값도 나온다. **덮어쓰기 불가** |
| | `params: {<name>: {default, min, max, unit, label, optional?}}` | 요청 `params` 로 받는 제약 상한 · 하한 값. `optional: true` 면 `default: null` 을 허용하고, 요청에 없으면 **그 이름을 쓰는 제약은 평가하지 않는다**(원천 krs `max_cost: null`) — 응답 `constraints` 에서 빠지고 저장본 `skipped_constraints` 에 남는다. optional 이 아닌데 default 가 없으면 등록부 거부 |
| | `formulas: {<name>: <formulas 모듈 이름>}` | 팩 `formulas/<module>.py::cost(row, params) -> float` 순수 함수 |
| | `objective: {minimize \| maximize: <name>, tiebreak: [{minimize \| maximize: <name>}]}` ○ | `<name>` 은 uses 과제의 **짧은 이름**(`<pack>.` 뺀 과제 이름 — regression 은 예측값, risk 는 확률) · formula 이름 · decision_var |
| | `constraints: [{name, expr, scale?}]` ○ | `expr` = `<lhs> (<=|>=|<|>) <rhs>` 한 줄. lhs · rhs 는 uses 과제의 짧은 이름 · formula · decision_var · controls · derived · `params` 이름 · 숫자 · 단순 `+ - *` · 괄호. `scale`(양수, 선택) = 위반량 분모(원천 pc `max(0, target − pred)/3 + max(0, cost − max)/5` 이관) |
| | `search: {strategy: grid \| random \| auto, max_points, max_draws?}` ○ | auto = 공간 ≤ max_points 면 grid. random 의 `max_points` = 평가할 점 수(원천 krs 5,000 · pc 3,500). `max_draws`(기본 50 × max_points) = derived 수락 표집의 시도 상한 |
| | `on_infeasible: least_violation` ○ | violation = Σ max(0, 위반량) / (`scale` 이 있으면 scale, 없으면 max(\|rhs\|, 1e-9)) |
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
  review_queue: {required: [uses, rule, origins], learned: false}          # 2차 — §6.1 (웨이브 P 로더가 search 검사를 optimize 에만 걸게)
  extract:      {required: [extractors, document, labels], learned: false}  # 2차 — §6.2 (kind: model 추출기는 §6.2 model 블록을 학습 키로 검사)
  quote:        {required: [uses, formula, rates, rounding, currency, confirm], learned: false}   # 2차 — §6.3
enums:
  entity: [lot, equipment_window, job, drawing]
  out_of_range: [predict_with_warning, reject]
  direction: [lower_is_better, higher_is_better, target_band]
  on_infeasible: [least_violation]
  search_strategy: [grid, random, auto]
  review_origin: [test_split, live_residual]          # 2차 — 학습 · 검증 구간 잔차는 값으로 둘 수 없다(G2-R01)
  extractor_kind: [rule, model]
  labels: [none, synthetic, provided]                 # none → 지표 null + labels: none (G2-E01)
  rounding: [ROUND_HALF_UP]                           # 2차 — 견적은 Decimal · ROUND_HALF_UP 만 (G2-Q01)
  currency: [KRW]
immutable_on_override: [type, split, time_key, group_key, uses, on_infeasible, interval, approver_role, target, origins, rounding, currency, formula, extractors, labels, derived, input_rules, input_limits]   # approver_role · target — D-121 · 2차 6키 — §6.4 · derived · input_rules — §1 · §2(웨이브 P 마감) · input_limits — §6.3(재진입 D2-70)
not_removable_on_override: [approver_role]
time_split_policies: [time_60_20_20, time_cv5]
# 웨이브 P 마감(D2-30 요청 반영) — 로더(registry/{packs,tenants}.py)는 이 값을 먼저 읽고, 없을 때만 코드 기본표를 쓴다
overridable_on_override: [thresholds, features, candidates, candidate_params, constraints, params, monitor, notice, title, rule, max_items, reason, document, rates, csv, recognized]   # §3 · §6.4 — 이 밖의 키는 R1(DEF-QAR2-004)
review_rules: [abs_residual_ge, top_quantile]       # §6.1
review_quantile_from: [valid]
review_schedule: [daily_after_monitor]
review_uses_types: [regression, risk]
document_limits: {max_bytes: 5242880, max_entities: 20000}   # spec §8.3 — 팩 · 회사는 낮추기만
document_formats: [dxf]
document_unit_override: [mm, inch]
extract_outputs: [regions, objects, bom_rows]
extract_model_selection: [macro_f1]
quote_uses_types: [regression]
quote_confirm_requires: [reviewed, review_note]
quote_review_note_min: 5
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

## 6. 2차 유형 키 — `review_queue` · `extract` · `quote` (Phase P0 아키텍트, goal2 §2 G2-T01)

> 출처: `spec.md` §8.2 · §8.3 · §8.4 · goal2 §2 · §2.1 · §7(D2-03 · D2-05 · D2-06 · D2-07 · D2-11) · `migration/source_inventory.md` §8~§11.
> **웨이브 P 가 할 일:** `std/task_types.yaml` 의 세 유형 `phase: 2 → 1`, 로더(`registry/packs.py::validate_task`)가 아래 키를 검사하고 `search` 검사를 optimize 에만 건다. §4 블록의 `by_type` · `enums` · `immutable_on_override` 는 이미 이 절에 맞췄다.
> 세 유형 모두 **`/predict` 로 부르지 않는다**(predict-contract §8). 자기 모델이 있는 것은 `extract` 의 `kind: model` 추출기뿐이고, 수치 예측은 `uses` 의 regression 과제(18키 응답)가 한다.

### 6.1 `review_queue` — 검토 대기열 (spec §8.2 · krs · pc)

| 키 | 필수 | 규칙 |
|---|---|---|
| `uses` | ○ | `[<pack>.<regression \| risk 과제>]` 정확히 1개. 잔차 = 실측 − 그 과제 production(또는 채점 대상 run) 예측 |
| `rule` | ○ | 둘 중 하나: `{abs_residual_ge: <수>}`(krs 4.0 MPa) · `{top_quantile: <0<q<1>}`(pc 0.10). 회사 덮어쓰기로 **값만** 바꿀 수 있다(D2-11) |
| `quantile_from` | top_quantile 이면 ○ | 고정값 `valid` — 분위 임계값은 **검증 구간 잔차**(학습 구간 모델이 낸 표본 밖 잔차)로 정해 학습 보고서에 남기고, 시험 구간 · 운영 잔차에 그 임계값을 적용한다. 학습 · 시험 구간 잔차로 분위를 재지 않는다 |
| `origins` | ○ | `review_origin` 부분집합. `test_split` = uses 과제 run 의 시험 구간 잔차(학습 보고서 생성 때 1회 — guard 의 `final_eval` 결과만, 새 시험 접근 0) · `live_residual` = 실측(`mlp_actual`)이 붙은 운영 예측. **학습 · 검증 구간 잔차 · 전체 재적합 후 같은 데이터 채점은 금지**(guard 계측, G2-R01 · std/split_policies.yaml `queue_scoring`) |
| `max_items` | | 한 번 만들 때 최대 항목(기본 50) · 정렬 = \|잔차\| ↓ |
| `reason` | | 항목 사유 문구 틀(`"|잔차| {abs_residual:.2f} ≥ {threshold}"`). 사유는 항목마다 남는다 |
| `schedule` | | `daily_after_monitor`(기본) — 감시 일일 작업 뒤 live_residual 항목 생성(개발3). 같은 (예측 ID) 는 한 번만 |
| `approver_role` | ○ | 공통 키. PATCH(검토 결과)는 이 역할의 approver 이상(goal2 §6 "자기 과제") |

상태 전이: `open → confirmed_issue | false_alarm` 한 번만(닫힌 항목 재검토 409 `already_decided`). 검토 결과는 다음 학습의 라벨 후보(`mlp_review_item.state` 를 학습 소스가 읽을 수 있다 — 자동 재학습 없음).

### 6.2 `extract` — 문서 · 도면 추출 (spec §8.3 · kd · ot)

| 키 | 필수 | 규칙 |
|---|---|---|
| `entity` | ○ | `drawing` |
| `document` | ○ | `{formats: [dxf], max_bytes: ≤ 5242880, max_entities: ≤ 20000, unit_override: [mm, inch]}` — spec 상한을 넘을 수 없고 팩 · 회사가 낮출 수만 있다(ot 2,000 · kd 20,000) |
| `extractors` | ○ | `[{name, kind: rule \| model, module: extractors/<name>.py, version, params?}]` ≥ 1, 순서대로 실행 · 결과 합침. 같은 이름 다른 구현은 병합 규칙 R5. `params` = 그 추출기의 YAML 값(임계값 · 허용차 · 팩 고유 상한 — 예 점수 하한 0.8 · 평탄화 0.2 mm · 꼭짓점 500, 코드 상수 금지) `{이름: 수 \| 문자열 \| bool \| 그 목록}` — 회사는 바꿀 수 없다(extractors 불변) |
| `labels` | ○ | `none`(실도면 정답 없음 — kd D-160) · `synthetic`(합성 설명자 생성 라벨 — ot) · `provided`(사람 정답 — 2차 범위 밖). `none` 이면 평가 요청에 200 + `labels: none` · 지표 null, IoU/F1 을 만들지 않는다 |
| `model` | kind: model 이면 ○ | `{features: [<features.yaml 설명자>], classes: [...], target: <라벨 열 이름, 기본 label>, split: stratified_60_20_20, candidates: [logreg, rf_clf, et_clf], candidate_params, selection: macro_f1}` — `target` 은 합성 설명자 생성기의 라벨 열(변수 아님 — D2-44 확정) — 검증 macro-F1 선정 → 학습+검증 재적합 → 시험 1회(층화). 기준선 = 학습 구간 최빈 클래스(표준 변경 요청 D2-15) |
| `outputs` | | `[regions, objects, bom_rows]` 중 쓰는 것. 출력 모양은 predict-contract §8.2 |

추출기 플러그인 `packs/<pack>/extractors/<name>.py` 의 모양(인터페이스 정본은 웨이브 P 개발2 가 `interfaces.md` 에 공표 — 아래가 기대값):

```python
NAME = "cad_regions"; VERSION = "1.0.0"; KIND = "rule"          # model 이면 "model"
def extract(raw: bytes, filename: str, *, unit: str | None, limits: dict, model=None) -> dict: ...
#  → {"regions": [...], "objects": [...], "bom_rows": [...], "confidence": float | None,
#     "counts": {...}, "dimensions": {...} | None, "unit": "mm", "entity_count": int, "warnings": [...]}
#  잘못된 DXF → ValueError(code="invalid_document"), 상한 초과 → ValueError(code="document_too_large")
#  추출기는 원본을 쓰지 않고 외부로 보내지 않는다(네트워크 0). model 은 등록부 production 산출물에서만 온다
# 선택 인자 context=(받는 추출기에만 — 키워드 context 또는 **kwargs, 웨이브 P 마감 D2-45):
#   {"categories": 회사 categories, "material_aliases": 별칭 대문자 → 정규 값, "params": extractors[].params,
#    "previous": 앞 추출기까지 합친 결과 | None}
# 결과 키 "replaces": ["objects" | "regions" | "bom_rows" | "counts" | "dimensions", …] — 앞 결과를 이어 붙이지 않고 바꾼다
#   (규칙 추출기가 기하 객체 · 검증 사유를 내고 모델 추출기가 같은 객체를 분류해 다시 내는 경우)
```

### 6.3 `quote` — 견적 (spec §8.4 · kd · ot)

| 키 | 필수 | 규칙 |
|---|---|---|
| `uses` | ○ | `[<pack>.<regression 과제>]` — 작업시간(kd `labor_hours` h/대 · ot `machining_minutes` 분/개). production 이 없으면 견적 초안 503 `model_not_ready` |
| `from_extract` | | `<pack>.<extract 과제>` — 인식값의 출처. 있으면 `recognized` 대응 필수 |
| `recognized` | from_extract 이면 ○ | `{<입력 이름>: <추출 결과 경로>}` 예 `{holes: counts.hole, slots: counts.slot, length: dimensions.length, width: dimensions.width}` · kd `{bom: bom_rows}`. 확정 입력과 다르면 `overrides` 1항목(ot 0.001 허용차 — `tolerance`) |
| `inputs` | ○ | 사람이 검토 · 확정하는 입력 이름(features.yaml 변수 + `quantity` · 단가 입력). 검증은 predict 와 같은 3단 |
| `formula` | ○ | `formulas/<module>.py` — `def quote(inputs, lines, predicted, rates) -> dict` 순수 함수, **`Decimal` · `ROUND_HALF_UP` 만**(float 연산 · `round()` · `float()` 0 — `gates/check_decimal.py`, G2-Q01). 단계별 반올림 순서는 원천 그대로(D2-07) |
| `rates` | ○ | `{<이름>: "<10진 문자열>"}` — 단가 · 계수(문자열로 적어 float 를 거치지 않는다). 회사는 **값만** 덮어쓴다. 단가표 이름(`rate_tables`)의 값은 `{<범주 값>: "<10진 문자열>"}` — 팩은 빈 표 `{}`(회사 범주 값을 팩에 두지 않는다), 회사가 칸을 채운다 |
| `rate_tables` | | `{<단가 이름>: <inputs 의 범주 변수>}` — 범주별 단가표(예 재질별 kg 단가 · 밀도). 병합 뒤 칸 = 회사 `categories[<변수>]` 와 정확히 같아야 한다(없는 칸 · 남는 칸 R2). 견적식에는 `rates[<이름>]` 이 `{범주 값: Decimal}` 로 간다. 덮어쓰기 불가(이름 · 변수) |
| `rounding` | ○ | `ROUND_HALF_UP` (덮어쓰기 불가) |
| `currency` | ○ | `KRW` · 원 단위(덮어쓰기 불가) |
| `confirm` | ○ | `{requires: [reviewed, review_note], review_note_min: 5, approver_role: <역할>}` — 확정은 approver 이상(D2-04), 확정 뒤 수정 409 `quote_locked` |
| `input_limits` | | `{<inputs 중 features.yaml 밖 이름>: {min?, max?, integer?}}` — 수량 · 시간 단가 · 외주비 같은 견적 고유 입력의 범위(원천 QuoteInput 이관 — kd 수량 1~1000 정수 · ot 1~10000 정수). 밖이면 422 `invalid_input`(detail `field` = 입력 이름, `rule` = `range` · `integer` — 입력값 되풀이 없음). 없는 이름은 0 이상 숫자만 본다. features.yaml 변수는 여기 두지 않는다(범위 정본 = features.yaml). **덮어쓰기 불가** (D2-A2-03 · 재진입 D2-70) |
| `csv` | | **품목 행** 내보내기 열 순서(없는 열은 빈 칸). 요약(항목 · 값) 행은 늘 전부 낸다 — 합계 · 구성 금액 · 입력 · 단가 · 예측 · 검토(D2-A2-01). 수식 주입 방지(`= + - @ \t \r` 앞 `'`) · UTF-8 BOM 은 코어가 강제 |

견적 금액은 확정 때 `mlp_quote` 스냅숏(입력 · 단가 · 예측 ID · 모델 버전 · 구성 금액)으로 고정된다 — 이후 모델 · 단가가 바뀌어도 확정 금액은 바뀌지 않는다(G2-Q01).

### 6.4 덮어쓰기 (2차분)

| 바꿀 수 있다 | 바꿀 수 없다 (병합 규칙 R1) |
|---|---|
| `rule` 의 값(같은 종류 안) · `max_items` · `reason` · `document` 상한(낮추기만 — 회사별 요소 상한, 예 ot 2,000) · `rates` 값(단가표는 칸 채우기) · `csv` · `recognized.tolerance` | `origins`(학습 구간 추가 불가) · `quantile_from` · `extractors` · `labels` · `formula` · `rounding` · `currency` · `uses` · `confirm.requires` 빼기 |

### 6.5 2차 과제 (팩 4 · 회사 4) — 웨이브 A0-2 · A2 기대값

| 회사 과제 | 팩 과제 | 유형 | 원천 근거 (`migration/source_inventory.md`) |
|---|---|---|---|
| `krs.joint_strength` | `solder.joint_strength` | regression (`random_60_20_20`, outlier iqr 학습 구간) | §8.3 |
| `krs.recipe_optimize` | `solder.recipe_optimize` | optimize (`random`, uses joint_strength) | §8.5 |
| `krs.residual_review` | `solder.residual_review` | review_queue (`abs_residual_ge: 4.0`) | §8.6 |
| `pc.sensory_score` | `kimchi.sensory_score` | regression (`time_60_20_20` → 행 420 < 500 이라 실제 `time_cv5`, time_key = 생산 시각) | §9.3 |
| `pc.recipe_optimize` | `kimchi.recipe_optimize` | optimize (`random`) | §9.5 |
| `pc.residual_review` | `kimchi.residual_review` | review_queue (`top_quantile: 0.10`) | §9.6 |
| `ot.machining_minutes` | `rollform-quote.machining_minutes` | regression (`random_60_20_20`) | §10.3 |
| `ot.cad_objects` | `rollform-quote.cad_objects` | extract (geometry rule + model, labels synthetic) | §10.3 · §10.5 |
| `ot.quote` | `rollform-quote.quote` | quote (uses machining_minutes · from_extract cad_objects) | §10.6 |
| `kd.labor_hours` | `eto.labor_hours` | regression (`random_60_20_20`) | §11.3 |
| `kd.drawing_regions` | `eto.drawing_regions` | extract (cad_regions · bom_text rule, labels none) | §11.5 |
| `kd.quote` | `eto.quote` | quote (uses labor_hours · from_extract drawing_regions) | §11.6 |
