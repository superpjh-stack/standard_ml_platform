# 계약 — 데이터 허브 내보내기 `make export-hub` (Hub Export Contract)

> **정본.** 출처: `spec.md` §13 · §18-10 · goal2 §2 G2-I02 · §7 D2-09. 검사: `tests/test_export_hub.py`(웨이브 P, 개발3).
> 상대 형식 근거(읽기 전용, `../Standard Data Hub` HEAD `c0b2818`): `src/datahub/db/schema.sql:118-135`(hub_dataset) · `:180-206`(hub_consumer · hub_usage) · `:224-235`(hub_usage_daily) · `contracts/db-schema.md:46,63-65` · `src/datahub/harvest/h09_ml_inputs.py:4,14,28-45` · `src/datahub/harvest/h07_consumers.py:17-23,210-218` · `src/datahub/measure/m05_api_usage.py:21-34` · `src/datahub/core/registry.py:74-113` · `companies/{ks,sw,krs,pc,ot,kd}.yaml`(`kind: ML` 항목).
> **허브 저장소에 쓰지 않는다.** 우리는 파일을 만들고, 허브 수확기가 그 파일을 읽게 하는 것은 허브 팀 일이다.

## 0. 허브가 지금 ML 에서 읽는 것 — 그리고 비어 있는 것 (정본 결함 D2-17)

- 허브 H9(`h09_ml_inputs.py`)는 회사 등록부의 `{kind: ML, path}` 저장소에서 **`README.md` 첫 40줄만** 읽어 `hub_consumer(kind=MODEL, code="ML:<path>")` 1행을 만든다(:28-41). **`hub_usage` 는 만들지 않는다**(:4) — ML 모델은 계보에서 고립된 노드다.
- 허브에는 **ML 과제 · 변수 · 호출 수를 받는 형식이 없다**("task" 개념 없음). goal2 G2-I02 의 "허브 수확기 형식" 은 아직 존재하지 않는다 → 이 문서가 **허브 테이블 모양에 그대로 들어가는 형식**을 정의하고, 허브 쪽 수확기(가칭 H9b) 추가를 요청한다(D2-17).
- 허브 계보 사슬은 `hub_tag.target_table = hub_dataset.physical_name → hub_lineage → hub_usage → hub_consumer` 다(허브 spec §170-196 · D-36). spec §13 의 "태그 → 과제 → 화면" 은 **과제 = `hub_consumer(kind=MODEL)` 1행, 과제가 읽는 원천 테이블 = `hub_usage`** 로 표현하면 허브 사슬에 그대로 붙는다.

## 1. 파일

| 항목 | 값 |
|---|---|
| 명령 | `make export-hub [DATE=YYYY-MM-DD]` (기본 = 어제 KST) — 감시 일일 작업 뒤 1회도 같은 함수(D2-09) |
| 위치 | `var/export/hub/<date>.json` (커밋 금지 · `.gitignore`) |
| 인코딩 | UTF-8 JSON, 키 정렬 · 들여쓰기 2 — 같은 DB · 같은 날짜면 바이트가 같다 |
| 범위 | 등록부 회사 전부(`_template` 제외). 2차 끝 = 6개사 |
| 금지 | 키 · DSN · URL · IP · 호스트 · 실데이터 행 · 입력값 · 예측값. **정의 · 대응 · 집계만** 낸다(`check_secrets` 가 출력 파일도 검사) |

## 2. 모양 (`hub-export-schema`)

```json hub-export-schema
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "MlpHubExport",
  "type": "object", "additionalProperties": false,
  "required": ["format", "generated_at", "date", "system", "companies"],
  "properties": {
    "format":       {"const": "mlp-hub-export/1"},
    "generated_at": {"type": "string", "format": "date-time"},
    "date":         {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "집계 날짜(KST) — hub_usage_daily.dt_kst"},
    "system":       {"type": "object", "required": ["kind", "name", "code_version"],
                     "properties": {"kind": {"const": "ML"}, "name": {"const": "Standard ML Platform"}, "code_version": {"type": "string"}}},
    "companies": {"type": "array", "items": {
      "type": "object", "additionalProperties": false,
      "required": ["company", "mode", "consumers", "datasets", "usages", "features", "api_usage"],
      "properties": {
        "company": {"type": "string", "pattern": "^[a-z][a-z0-9]{1,7}$", "description": "허브 회사 코드 = tenants/<code>.yaml hub_company"},
        "mode":    {"enum": ["demo", "eval", "live"]},
        "consumers": {"type": "array", "description": "→ hub_consumer (schema.sql:180-193)", "items": {
          "type": "object", "additionalProperties": false,
          "required": ["kind", "code", "name", "state", "synthetic", "origin", "source_ref"],
          "properties": {
            "kind": {"enum": ["MODEL", "SCREEN", "TOOL"]},
            "code": {"type": "string", "description": "MODEL: ML:<tenant>.<task> · SCREEN: ML-S<n> · TOOL: tool:<agent 도구 이름>"},
            "name": {"type": "string", "maxLength": 120},
            "state": {"type": ["string", "null"], "description": "production 버전 | '운영 모델 없음' | '합성 데이터'"},
            "synthetic": {"type": "boolean"},
            "origin": {"const": "MLP"},
            "source_ref": {"type": "string", "pattern": "^[^:]+:\\d+$|^fixture$|^live$", "description": "상대 경로:줄 (허브 db-schema.md:63)"}
          }}},
        "datasets": {"type": "array", "description": "→ hub_dataset (schema.sql:118-135). 과제가 읽는 원천 테이블 · 뷰. 합성 소스는 내지 않는다", "items": {
          "type": "object", "additionalProperties": false,
          "required": ["physical_name", "layer", "source_ref"],
          "properties": {
            "physical_name": {"type": "string", "description": "tenants/<code>.yaml feature_map · target_map · sources 의 TABLE 또는 view"},
            "layer": {"enum": ["L0", "L1", "L2", "L3", "L4", "L5"]},
            "source_ref": {"type": "string"}
          }}},
        "usages": {"type": "array", "description": "→ hub_usage (schema.sql:195-206)", "items": {
          "type": "object", "additionalProperties": false,
          "required": ["consumer_code", "physical_name", "api_path", "declared_in", "source_ref"],
          "properties": {
            "consumer_code": {"type": "string"},
            "physical_name": {"type": ["string", "null"], "description": "null = 합성 · CSV 소스(계보 없음)"},
            "api_path": {"type": "string", "description": "/api/v1/tenants/{t}/tasks/{task}/predict 등 — api_usage 키와 같다"},
            "declared_in": {"enum": ["tenants", "packs", "screen-map", "agent-tools"]},
            "source_ref": {"type": "string"}
          }}},
        "features": {"type": "array", "description": "변수 대응 — 허브 hub_dataset.std_name 채우기 재료", "items": {
          "type": "object", "additionalProperties": false,
          "required": ["task", "std_name", "role", "source_column", "mapped"],
          "properties": {
            "task": {"type": "string"},
            "std_name": {"type": "string", "description": "<pack>.<features.yaml 변수 이름> — 팩 중립 표준 이름"},
            "role": {"enum": ["feature", "target", "control", "fixed"]},
            "source_column": {"type": ["string", "null"], "description": "TABLE.COLUMN (feature_map 키) — 대응 없으면 null"},
            "mapped": {"type": "boolean"}
          }}},
        "api_usage": {"type": "object", "description": "허브 M5 fixture 모양 그대로(m05_api_usage.py:24-34): {날짜: {api_path: {calls, errors, p95_ms, ref, basis}}}",
          "additionalProperties": {"type": "object", "additionalProperties": {
            "type": "object", "additionalProperties": false, "required": ["calls", "errors", "p95_ms", "ref", "basis"],
            "properties": {
              "calls": {"type": ["integer", "null"], "minimum": 0},
              "errors": {"type": ["integer", "null"], "minimum": 0},
              "p95_ms": {"type": ["number", "null"]},
              "ref": {"type": "string", "description": "mlp_prediction@<date> 같은 집계 출처"},
              "basis": {"enum": ["실측", "추정", "가정", "미확인"]}
            },
            "allOf": [{"if": {"properties": {"basis": {"const": "미확인"}}},
                       "then": {"properties": {"calls": {"type": "null"}, "errors": {"type": "null"}, "p95_ms": {"type": "null"}}}}]
          }}}
      }}}
  }
}
```

## 3. 값 규칙

| 항목 | 규칙 |
|---|---|
| 과제 consumer | 켜진 과제마다 `MODEL` 1행 `code = ML:<tenant>.<task>` · `name` = 과제 title · `state` = production 버전 또는 "운영 모델 없음" · `synthetic` = production 이 합성이거나 mode ≠ live · `source_ref = packs/<pack>/tasks/<task>.yaml:1` |
| 화면 consumer | 화면 1~10 중 그 회사 과제가 쓰는 것 `SCREEN` · `code = ML-S<n>` · `source_ref = contracts/screen-map.md:<줄>` |
| Agent 도구 consumer | `TOOL` · `code = tool:ml.calculate_prediction` 등 4 · `source_ref = contracts/agent-tools.md:<줄>` (허브 H7 의 `tool:<name>` 관례 — h07_consumers.py:218) |
| datasets | `feature_map` · `target_map` 키의 TABLE, `sources.*.tables` · `table` · `view` — 미확인 뷰(`# 미확인`)는 내지 않는다. layer 는 원천 그대로 모르면 `L5`(ML 학습 입력 — 허브 spec.md:98) |
| api_usage | `mlp_prediction` 을 (날짜 KST, 과제, 채널) 로 센 값 `basis: 실측`. 오류 수 = 같은 날 `mlp_audit` 의 그 경로 4xx · 5xx. p95 는 기록이 없으면 null · basis `추정` 이 아니라 그 칸만 null(지어내지 않음). 기록 자체가 없는 날 = `미확인` · 숫자 null(0 아님 — 허브 db-schema.md:64) |
| 결정성 | 같은 DB · 날짜 → 같은 파일(정렬: company → kind → code) |

## 4. 계약 시험 (`tests/test_export_hub.py`, G2-I02)

1. `hub-export-schema` 로 출력 검증(Draft 2020-12).
2. **허브 파일을 읽어 대조(읽기 전용):** `../Standard Data Hub/src/datahub/db/schema.sql` 의 `hub_consumer.kind` · `hub_dataset.layer` · `hub_usage_daily.basis` CHECK 값을 정규식으로 읽어 우리 enum 이 그 부분집합인지. 허브 저장소가 없으면 시험은 **FAIL**(건너뜀 0 — 가짜 PASS 금지).
3. **허브 검증 함수 읽기 전용 import:** `datahub.core.registry.validate(data, file)`(registry.py:74-113 — DB 연결 없음)를 `sys.path` 에 허브 `src` 를 더해 import 하고, 6개사 `companies/<code>.yaml` 이 통과하며 각각 `kind: ML` 시스템을 갖는지 · 우리 `hub_company` 와 코드가 같은지 확인. 허브 쪽에 ML 내보내기 검증 함수는 **없다**(§0) — 생기면 이 시험이 그것을 import 하도록 바꾼다. 쓰기 0(허브 폴더 mtime 불변 확인).
4. 출력에 `check_secrets` 금지 패턴 0 · 실데이터 행 0 · 6개사 모두 있음.
