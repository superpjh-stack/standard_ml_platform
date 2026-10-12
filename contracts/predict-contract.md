# 계약 — 표준 예측 응답 (Predict Contract)

> **정본.** 켜진 모든 과제의 `POST /api/v1/tenants/{t}/tasks/{task}/predict` · `predict:batch` · `optimize` 응답은 이 문서의 JSON Schema(§5)를 따른다.
> 출처: `spec.md` §7.1 · §7.2 · §7.3 · §8.1 · §2.3. 검사: `gates/check_contract.py`(G-M04) · `tests/test_compat.py`.
> 첫 공표: 아키텍트(Phase 0). 개발2 가 `serve/contract.py` 의 pydantic 응답 모델로 옮기고, 그 모델이 생성하는 JSON Schema 가 §5 와 같아야 한다.
> **키는 빠지지 않는다.** 유형에 없는 필드는 `null` 이다. 필드를 선택 항목으로 바꾸는 것은 게이트를 낮추는 것이다(goal §4.3).

## 0. 종이 위 대조 — 네 과제가 같은 모양에 들어가는가

| 키 | `ks.remaining_hours` (regression) | `ks.failure_24h` (risk) | `sw.print_ood` (anomaly) | `sw.print_setpoint` (optimize) |
|---|---|---|---|---|
| `task` · `type` · `tenant` | ○ | ○ | ○ | ○ |
| `entity_id` | 요청값 또는 null | 요청값 또는 null | 요청값 또는 null | 요청값 또는 null |
| `prediction` | `{value: 잔여 h, unit: "h", interval: [lo, hi], grade: null, baseline: 학습 평균}` | `{value: 확률, unit: "probability", interval: null, grade: low/watch/high, baseline: 학습 양성률}` | **null** | **null** |
| `probability` | null | 0~1 (= `prediction.value`) | null | null |
| `anomaly` | null | null | `{score, flag, threshold, contamination, contributors}` | null |
| `recommendation` | null | null | null | `{rec_id, feasible, strategy, best, candidates[≤5], current, improvement, …}` |
| `status` | ok · watch · review · out_of_range · rejected | 같음 | ok · review · out_of_range · rejected | needs_approval · review |
| `warnings` · `imputed_fields` · `out_of_range_fields` | 배열(빈 배열 가능) | 배열 | 배열 | 배열 (고정 입력 기준) |
| `explain` | `explain:true` 면 상위 5 기여, 아니면 null | 같음 | 같음 | null |
| `model` | `{name, version, trained_at, snapshot_id, synthetic}` | 같음 | 같음 | **null** (자기 모델이 없다 — `uses` 를 본다) |
| `uses` | null | null | null | `[{task, version, synthetic}]` — 의존 과제의 production 버전 |
| `prediction_id` | `prd_…` (mlp_prediction 1행) | `prd_…` | `prd_…` | null (`recommendation.rec_id` 가 mlp_recommendation 1행) |
| `synthetic` | 모델이 합성 스냅숏이면 true | 같음 | 같음 | `uses` 중 하나라도 합성이면 true |
| `notice` | 팩 · 회사 문구 | 같음 | 같음 | 같음 |

결론: 네 과제가 **같은 18개 키**로 답한다. 옛 6벌의 "한 번 호출에 잔여수명 + 위험 + 이상" 묶음은 표준에서는 과제 3개로 갈라지고, 옛 묶음 응답은 호환 라우터(§6)가 세 과제를 불러 다시 합친다.

## 1. 요청

```json
POST /api/v1/tenants/{t}/tasks/{task}/predict
{
  "inputs": {"<feature>": <number|string|null>, ...},   // features.yaml 이름만. 모르는 키 → 422 invalid_input
  "entity_id": "LOT-…",                                  // 선택. 실측 연결 키
  "explain": false,                                       // 선택. true 면 기여 상위 5
  "model_version": null                                   // 선택. null = production. staging 지정은 approver 이상
}

POST /api/v1/tenants/{t}/tasks/{task}/predict:batch
{"items": [<위 요청과 같은 모양>, ...]}                  // 1 ~ 500건. 501건 이상 → 422 invalid_input

POST /api/v1/tenants/{t}/tasks/{task}/optimize          // type=optimize 과제만. 그 밖 과제 → 404 not_found
{
  "fixed":   {"<controllable:false 변수>": <값>, ...},  // 고정 변수. 빠지면 422 missing_required(보정 규칙은 predict 와 같다)
  "current": {"<controllable:true 변수>": <값>, ...},   // 선택. 현재 조건 — 개선량 계산용
  "params":  {"<과제 params 이름>": <값>, ...},         // 선택. 과제 YAML params 의 min/max 로 검증, 없으면 default
  "entity_id": null
}
```

요청 모델은 pydantic `extra="forbid"` · `allow_inf_nan=False` 다. NaN · Infinity · 모르는 키 · 문자열이 와야 할 자리의 숫자(또는 반대)는 422 `invalid_input` 이며, **입력값을 메시지에 되풀이하지 않는다** (`detail` 에는 `field` 와 규칙 이름만).

## 2. 응답 — 공통 18키

| 키 | 형 | 규칙 |
|---|---|---|
| `task` | string | `<tenant>.<task>` |
| `type` | enum | `regression` · `risk` · `anomaly` · `optimize` (`std/task_types.yaml` phase 1) |
| `tenant` | string | 회사 코드 |
| `entity_id` | string \| null | 요청값 그대로 |
| `prediction` | object \| null | regression · risk 만. 키 5개 `value` · `unit` · `interval` · `grade` · `baseline` 전부 있다 |
| `probability` | number \| null | risk 만. 0 ≤ p ≤ 1. `prediction.value` 와 같은 값 |
| `anomaly` | object \| null | anomaly 만. 키 5개 `score` · `flag` · `threshold` · `contamination` · `contributors` |
| `recommendation` | object \| null | optimize 만 (§3) |
| `status` | enum | `ok` · `watch` · `review` · `out_of_range` · `rejected` · `needs_approval` 중 하나, 유형별 허용값은 §4 |
| `warnings` | array | `{code, field, message}`. `field` 는 null 가능. 코드는 §2.1 |
| `imputed_fields` | array[string] | 보정한 변수 **이름**(라벨 아님) |
| `out_of_range_fields` | array[string] | 학습 범위(p1~p99) 밖 변수 이름 |
| `explain` | object \| null | `{method, top: [{field, contribution}]}` (≤ 5) |
| `model` | object \| null | optimize 만 null. 키 5개 `name` · `version` · `trained_at` · `snapshot_id` · `synthetic` |
| `uses` | array \| null | optimize 만 배열 `[{task, version, synthetic}]` |
| `prediction_id` | string \| null | optimize 만 null. `prd_` 접두 |
| `synthetic` | boolean | 이 답이 합성 스냅숏 모델에서 나왔는가. 화면 배지 |
| `notice` | string | 팩 · 회사 문구(빈 문자열 금지) |

### 2.1 경고 코드

| code | 뜻 | 상태에 미치는 영향 |
|---|---|---|
| `imputed` | 필수 아님 · 결측 → 보정(`impute`) | 없음 |
| `out_of_range` | 학습 범위 밖 (검증 범위 안) | `out_of_range` (정책 `reject` 면 `rejected`) |
| `near_range` | 학습 범위 가장자리 2% 안 | `watch` |
| `threshold_exceeded` | 과제 `thresholds.review_above` 초과 (risk 는 `review_prob`) | `review` |
| `watch_band` | 기준 ± `watch_band` 안 | `watch` |
| `anomaly_input` | anomaly 과제 `flag=true` | `review` |
| `synthetic_model` | 모델이 합성 스냅숏 | 없음 (배지) |
| `infeasible` | optimize 제약 충족 후보 0 → `least_violation` | `review` |
| `constraint_unmet` | 추천의 개별 제약 미충족 (`field` = 제약 이름) | `review` |
| `extrapolation` | optimize 추천 조건이 의존 과제 anomaly 신호에 걸림 | `watch` |

### 2.2 상태 우선순위 (여러 조건이 겹칠 때)

`rejected` > `out_of_range` > `review` > `watch` > `ok`. optimize 는 `review`(제약 미충족) > `needs_approval`(충족 후보 있음).
상태는 **코드**로 판단한다. 화면 문구(`std/statuses.yaml` label)는 팩 · 회사가 바꿀 수 있다.

## 3. optimize 의 `recommendation`

```text
recommendation = {
  rec_id:        "rec_…",                         // mlp_recommendation 1행 (status=needs_approval)
  feasible:      bool,                            // 제약 충족 후보가 1개 이상
  strategy:      "grid" | "random",               // 공간 ≤ max_points 면 grid
  n_candidates:  int,                             // 평가한 점 수
  n_feasible:    int,
  in_train_range_rate: 1.0,                       // 탐색점은 전부 학습 범위 ∩ min/max (G-M13) — 1.0 이 아니면 결함
  objective:     {name, direction: "minimize"|"maximize", tiebreak: [ {name, direction} ]},
  best:          <candidate>,
  candidates:    [<candidate> ≤ 5],               // best 포함, 정렬 순
  current:       <candidate> | null,              // 요청 current 가 있을 때
  improvement:   {<objective name>: number} | null,
  on_infeasible: "least_violation" | null         // 실제로 대체가 쓰였을 때만 값
}
candidate = {
  conditions:  {"<변수>": number|string, ...},    // 조절 변수 + decision_vars
  predictions: {"<target 이름 또는 formula 이름>": number, ...},
  intervals:   {"<target 이름>": [lo, hi] | null, ...},
  constraints: [{name, expr, lhs, rhs, satisfied: bool, slack: number}],
  violation:   number,                            // Σ max(0, 위반량)/|rhs| — 충족이면 0
  objective_value: number
}
```

## 4. 유형별 null 규칙 · 허용 상태 (JSON Schema `allOf` 로 강제)

| type | prediction | probability | anomaly | recommendation | model | uses | prediction_id | 허용 status |
|---|---|---|---|---|---|---|---|---|
| regression | object | **null** | **null** | **null** | object | **null** | string | ok · watch · review · out_of_range · rejected |
| risk | object(`unit="probability"`, `grade` ≠ null) | number | **null** | **null** | object | **null** | string | ok · watch · review · out_of_range · rejected |
| anomaly | **null** | **null** | object | **null** | object | **null** | string | ok · review · out_of_range · rejected |
| optimize | **null** | **null** | **null** | object | **null** | array | **null** | needs_approval · review |

`rejected` 응답도 200 이고 같은 18키를 낸다. 이때 `prediction` · `probability` · `anomaly` 의 **값** 자리는 null 이 아니라 아래처럼 둔다: regression · risk 는 `prediction` 객체를 두되 `value: null` · `interval: null`, anomaly 는 `anomaly` 객체를 두되 `score: null` · `flag: null`. 예측하지 않은 것을 숫자로 지어내지 않는다.

## 5. JSON Schema (정본 — `check_contract.py` 가 이 블록을 그대로 읽는다)

```json predict-response-schema
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "mlp/predict-response/v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["task", "type", "tenant", "entity_id", "prediction", "probability", "anomaly", "recommendation", "status",
               "warnings", "imputed_fields", "out_of_range_fields", "explain", "model", "uses", "prediction_id", "synthetic", "notice"],
  "properties": {
    "task": {"type": "string", "pattern": "^[a-z][a-z0-9]{1,7}\\.[a-z][a-z0-9_]*$"},
    "type": {"enum": ["regression", "risk", "anomaly", "optimize"]},
    "tenant": {"type": "string", "pattern": "^[a-z][a-z0-9]{1,7}$"},
    "entity_id": {"type": ["string", "null"]},
    "prediction": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["value", "unit", "interval", "grade", "baseline"],
      "properties": {
        "value": {"type": ["number", "null"]},
        "unit": {"type": "string"},
        "interval": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "grade": {"enum": ["low", "watch", "high", null]},
        "baseline": {"type": ["number", "null"]}
      }
    },
    "probability": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "anomaly": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["score", "flag", "threshold", "contamination", "contributors"],
      "properties": {
        "score": {"type": ["number", "null"]},
        "flag": {"type": ["boolean", "null"]},
        "threshold": {"type": ["number", "null"]},
        "contamination": {"type": ["number", "null"]},
        "contributors": {"type": "array", "maxItems": 5, "items": {
          "type": "object", "additionalProperties": false, "required": ["field", "contribution"],
          "properties": {"field": {"type": "string"}, "contribution": {"type": "number"}}}}
      }
    },
    "recommendation": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["rec_id", "feasible", "strategy", "n_candidates", "n_feasible", "in_train_range_rate", "objective",
                   "best", "candidates", "current", "improvement", "on_infeasible"],
      "properties": {
        "rec_id": {"type": "string", "pattern": "^rec_"},
        "feasible": {"type": "boolean"},
        "strategy": {"enum": ["grid", "random"]},
        "n_candidates": {"type": "integer", "minimum": 1},
        "n_feasible": {"type": "integer", "minimum": 0},
        "in_train_range_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "objective": {"type": "object", "additionalProperties": false, "required": ["name", "direction", "tiebreak"],
          "properties": {"name": {"type": "string"}, "direction": {"enum": ["minimize", "maximize"]},
                         "tiebreak": {"type": "array", "items": {"type": "object", "required": ["name", "direction"],
                           "properties": {"name": {"type": "string"}, "direction": {"enum": ["minimize", "maximize"]}}}}}},
        "best": {"$ref": "#/$defs/candidate"},
        "candidates": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"$ref": "#/$defs/candidate"}},
        "current": {"oneOf": [{"$ref": "#/$defs/candidate"}, {"type": "null"}]},
        "improvement": {"type": ["object", "null"], "additionalProperties": {"type": "number"}},
        "on_infeasible": {"enum": ["least_violation", null]}
      }
    },
    "status": {"enum": ["ok", "watch", "review", "out_of_range", "rejected", "needs_approval"]},
    "warnings": {"type": "array", "items": {
      "type": "object", "additionalProperties": false, "required": ["code", "field", "message"],
      "properties": {
        "code": {"enum": ["imputed", "out_of_range", "near_range", "threshold_exceeded", "watch_band", "anomaly_input",
                          "synthetic_model", "infeasible", "constraint_unmet", "extrapolation"]},
        "field": {"type": ["string", "null"]},
        "message": {"type": "string"}}}},
    "imputed_fields": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "out_of_range_fields": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "explain": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["method", "top"],
      "properties": {
        "method": {"enum": ["permutation_local", "linear_coef", "tree_path"]},
        "top": {"type": "array", "maxItems": 5, "items": {"type": "object", "additionalProperties": false,
          "required": ["field", "contribution"], "properties": {"field": {"type": "string"}, "contribution": {"type": "number"}}}}
      }
    },
    "model": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["name", "version", "trained_at", "snapshot_id", "synthetic"],
      "properties": {
        "name": {"type": "string"},
        "version": {"type": "string", "pattern": "^v[1-9][0-9]*$"},
        "trained_at": {"type": "string", "format": "date-time"},
        "snapshot_id": {"type": "string", "pattern": "^snp_"},
        "synthetic": {"type": "boolean"}
      }
    },
    "uses": {"type": ["array", "null"], "items": {"type": "object", "additionalProperties": false,
      "required": ["task", "version", "synthetic"],
      "properties": {"task": {"type": "string"}, "version": {"type": "string", "pattern": "^v[1-9][0-9]*$"}, "synthetic": {"type": "boolean"}}}},
    "prediction_id": {"type": ["string", "null"], "pattern": "^prd_"},
    "synthetic": {"type": "boolean"},
    "notice": {"type": "string", "minLength": 1}
  },
  "allOf": [
    {"if": {"properties": {"type": {"const": "regression"}}},
     "then": {"properties": {"prediction": {"type": "object"}, "probability": {"type": "null"}, "anomaly": {"type": "null"},
                             "recommendation": {"type": "null"}, "model": {"type": "object"}, "uses": {"type": "null"},
                             "prediction_id": {"type": "string"},
                             "status": {"enum": ["ok", "watch", "review", "out_of_range", "rejected"]}}}},
    {"if": {"properties": {"type": {"const": "risk"}}},
     "then": {"properties": {"prediction": {"type": "object", "properties": {"unit": {"const": "probability"}}},
                             "probability": {"type": ["number", "null"]}, "anomaly": {"type": "null"},
                             "recommendation": {"type": "null"}, "model": {"type": "object"}, "uses": {"type": "null"},
                             "prediction_id": {"type": "string"},
                             "status": {"enum": ["ok", "watch", "review", "out_of_range", "rejected"]}}}},
    {"if": {"properties": {"type": {"const": "anomaly"}}},
     "then": {"properties": {"prediction": {"type": "null"}, "probability": {"type": "null"}, "anomaly": {"type": "object"},
                             "recommendation": {"type": "null"}, "model": {"type": "object"}, "uses": {"type": "null"},
                             "prediction_id": {"type": "string"},
                             "status": {"enum": ["ok", "review", "out_of_range", "rejected"]}}}},
    {"if": {"properties": {"type": {"const": "optimize"}}},
     "then": {"properties": {"prediction": {"type": "null"}, "probability": {"type": "null"}, "anomaly": {"type": "null"},
                             "recommendation": {"type": "object"}, "model": {"type": "null"}, "uses": {"type": "array", "minItems": 1},
                             "prediction_id": {"type": "null"}, "explain": {"type": "null"},
                             "status": {"enum": ["needs_approval", "review"]}}}}
  ],
  "$defs": {
    "candidate": {
      "type": "object", "additionalProperties": false,
      "required": ["conditions", "predictions", "intervals", "constraints", "violation", "objective_value"],
      "properties": {
        "conditions": {"type": "object", "additionalProperties": {"type": ["number", "string"]}},
        "predictions": {"type": "object", "additionalProperties": {"type": "number"}},
        "intervals": {"type": "object", "additionalProperties": {"type": ["array", "null"], "items": {"type": "number"}}},
        "constraints": {"type": "array", "items": {"type": "object", "additionalProperties": false,
          "required": ["name", "expr", "lhs", "rhs", "satisfied", "slack"],
          "properties": {"name": {"type": "string"}, "expr": {"type": "string"}, "lhs": {"type": "number"},
                         "rhs": {"type": "number"}, "satisfied": {"type": "boolean"}, "slack": {"type": "number"}}}},
        "violation": {"type": "number", "minimum": 0},
        "objective_value": {"type": "number"}
      }
    }
  }
}
```

배치 응답(`predict:batch`)은 `{"items": [...], "next_cursor": null}` 이다. `items[i]` 는 위 스키마의 응답이거나 `{"index": i, "error": {"code", "message", "detail"}}` 다. 순서는 요청 순서와 같다. 한 건의 422 가 다른 건을 막지 않는다.

## 6. 응답 예시 (값은 `(예시)` — 실제 수치는 학습 결과)

### 6.1 `ks.remaining_hours` — regression

```json
{
  "task": "ks.remaining_hours", "type": "regression", "tenant": "ks", "entity_id": "KS-DEMO-0601",
  "prediction": {"value": 112.4, "unit": "h", "interval": [104.1, 120.6], "grade": null, "baseline": 101.7},
  "probability": null, "anomaly": null, "recommendation": null,
  "status": "ok",
  "warnings": [{"code": "imputed", "field": "vibration", "message": "학습 중앙값으로 보정했습니다"},
               {"code": "synthetic_model", "field": null, "message": "합성 데이터로 학습한 모델입니다"}],
  "imputed_fields": ["vibration"], "out_of_range_fields": [],
  "explain": null,
  "model": {"name": "gbr", "version": "v1", "trained_at": "2026-10-13T09:00:00+09:00", "snapshot_id": "snp_3f9c0a1b2c3d4e5f", "synthetic": true},
  "uses": null, "prediction_id": "prd_01JABCDEF0000000000000001", "synthetic": true,
  "notice": "예측값은 참고용이며 설비 정지 · 정비 · 금형 교체는 현장 점검 후 담당자가 결정합니다."
}
```

### 6.2 `ks.failure_24h` — risk

```json
{
  "task": "ks.failure_24h", "type": "risk", "tenant": "ks", "entity_id": "KS-DEMO-0601",
  "prediction": {"value": 0.62, "unit": "probability", "interval": null, "grade": "high", "baseline": 0.07},
  "probability": 0.62, "anomaly": null, "recommendation": null,
  "status": "review",
  "warnings": [{"code": "threshold_exceeded", "field": null, "message": "고장 위험이 검토 기준(0.5)을 넘습니다"}],
  "imputed_fields": [], "out_of_range_fields": [],
  "explain": null,
  "model": {"name": "rf_clf", "version": "v1", "trained_at": "2026-10-13T09:02:00+09:00", "snapshot_id": "snp_3f9c0a1b2c3d4e5f", "synthetic": true},
  "uses": null, "prediction_id": "prd_01JABCDEF0000000000000002", "synthetic": true,
  "notice": "예측값은 참고용이며 설비 정지 · 정비 · 금형 교체는 현장 점검 후 담당자가 결정합니다."
}
```

### 6.3 `sw.print_ood` — anomaly

```json
{
  "task": "sw.print_ood", "type": "anomaly", "tenant": "sw", "entity_id": null,
  "prediction": null, "probability": null,
  "anomaly": {"score": -0.031, "flag": true, "threshold": 0.0, "contamination": 0.08,
              "contributors": [{"field": "set_temp", "contribution": 0.41}, {"field": "dwell_time", "contribution": 0.22}]},
  "recommendation": null,
  "status": "out_of_range",
  "warnings": [{"code": "anomaly_input", "field": null, "message": "학습 분포와 다른 조건 조합입니다"},
               {"code": "out_of_range", "field": "set_temp", "message": "학습 범위(p1~p99) 밖입니다"}],
  "imputed_fields": [], "out_of_range_fields": ["set_temp"],
  "explain": null,
  "model": {"name": "isolation_forest", "version": "v1", "trained_at": "2026-10-13T09:05:00+09:00", "snapshot_id": "snp_9a8b7c6d5e4f3a2b", "synthetic": true},
  "uses": null, "prediction_id": "prd_01JABCDEF0000000000000003", "synthetic": true,
  "notice": "예측값은 참고용이며 인쇄 조건 변경은 시험 인쇄와 품질 담당자 승인 후 진행합니다."
}
```

### 6.4 `sw.print_setpoint` — optimize

```json
{
  "task": "sw.print_setpoint", "type": "optimize", "tenant": "sw", "entity_id": null,
  "prediction": null, "probability": null, "anomaly": null,
  "recommendation": {
    "rec_id": "rec_01JABCDEF0000000000000004", "feasible": true, "strategy": "grid",
    "n_candidates": 5040, "n_feasible": 612, "in_train_range_rate": 1.0,
    "objective": {"name": "process_cost", "direction": "minimize", "tiebreak": [{"name": "delta_e", "direction": "minimize"}]},
    "best": {"conditions": {"set_temp": 160, "set_pressure": 4, "line_speed": 15, "ink_usage": 18, "dwell_time": 50},
             "predictions": {"delta_e": 1.21, "defect_risk": 0.06, "process_cost": 79.5},
             "intervals": {"delta_e": [0.95, 1.48], "defect_risk": null},
             "constraints": [{"name": "max_delta_e", "expr": "delta_e <= max_delta_e", "lhs": 1.21, "rhs": 2.5, "satisfied": true, "slack": 1.29},
                             {"name": "max_risk", "expr": "defect_risk <= max_risk", "lhs": 0.06, "rhs": 0.2, "satisfied": true, "slack": 0.14},
                             {"name": "min_line_speed", "expr": "line_speed >= min_line_speed", "lhs": 15, "rhs": 12, "satisfied": true, "slack": 3}],
             "violation": 0, "objective_value": 79.5},
    "candidates": [{"conditions": {"set_temp": 160, "set_pressure": 4, "line_speed": 15, "ink_usage": 18, "dwell_time": 50},
             "predictions": {"delta_e": 1.21, "defect_risk": 0.06, "process_cost": 79.5},
             "intervals": {"delta_e": [0.95, 1.48], "defect_risk": null},
             "constraints": [{"name": "max_delta_e", "expr": "delta_e <= max_delta_e", "lhs": 1.21, "rhs": 2.5, "satisfied": true, "slack": 1.29},
                             {"name": "max_risk", "expr": "defect_risk <= max_risk", "lhs": 0.06, "rhs": 0.2, "satisfied": true, "slack": 0.14},
                             {"name": "min_line_speed", "expr": "line_speed >= min_line_speed", "lhs": 15, "rhs": 12, "satisfied": true, "slack": 3}],
             "violation": 0, "objective_value": 79.5}],
    "current": null, "improvement": null, "on_infeasible": null
  },
  "status": "needs_approval",
  "warnings": [],
  "imputed_fields": [], "out_of_range_fields": [],
  "explain": null, "model": null,
  "uses": [{"task": "sw.delta_e", "version": "v1", "synthetic": true}, {"task": "sw.defect_risk", "version": "v1", "synthetic": true}],
  "prediction_id": null, "synthetic": true,
  "notice": "추천 조건은 설비에 내려가지 않습니다. 시험 인쇄와 품질 담당자 승인 후 적용합니다."
}
```

(예시는 `candidates` 를 best 1개로 줄였다. 실제 응답은 최대 5개다.)

## 7. 호환 라우터 — 옛 경로 · 옛 키 (spec §15 M4 · D-18)

| 회사 | 옛 경로 | 표준 호출 | 옛 키 ← 표준 |
|---|---|---|---|
| ks | `POST /api/maintenance/predict` | `ks.remaining_hours` + `ks.failure_24h` + `ks.sensor_ood` predict 3회 | `remaining_hours` ← remaining_hours.`prediction.value`(소수 2) · `risk_probability` ← failure_24h.`probability`(소수 4) · `anomaly` ← sensor_ood.`anomaly.flag` · `status` ← "점검 검토"(경고 있음) / "추가 징후 없음" · `warnings` ← message 문자열 배열 · `imputed_fields` ← 라벨 배열 · `model` · `risk_model` ← `model.name` · `version` ← `model.version` · `notice` |
| sw | `POST /api/quality/predict` | `sw.delta_e` + `sw.defect_risk` + `sw.print_ood` | `delta_e`(소수 3) · `risk_probability` · `anomaly` · `status` ← "품질 검토" / "추가 징후 없음" · `equipment` ← 회사 등록부 `compat.equipment_by_print_type` · `model` · `risk_model` · `version` · `notice` |
| ks · sw | `POST /api/ml/optimize` | `ks.maintenance_timing` / `sw.print_setpoint` | `feasible` · `candidate_count` ← `n_candidates` · `feasible_count` · `recommendation` · `alternatives` · `unmet_constraints` · (sw) `current` · `current_cost_index` · `warnings` · `objective` · `notice` |
| ks · sw | `GET /api/ml/overview` | `GET .../overview` 묶음 | `metrics[{model, mae, rmse, r2}]` · `risk_metrics[{model, roc_auc, pr_auc, brier}]` · `split{train, validation, test, method}` · `champion` · `risk_champion` … |
| ks · sw | `GET /api/data/records` | `GET .../records` | `{total, limit, offset, records}` ← `{items, next_cursor, total}` (offset 은 커서로 환산) |

옛 오류 모양(`{"detail": [...]}` 422)도 호환 라우터가 재현한다. 원천 응답과의 일치는 `tests/test_compat.py` 가 원천 저장소 파일에서 읽은 키 목록으로 확인한다.
