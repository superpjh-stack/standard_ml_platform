# 계약 — 표준 AI Agent 플랫폼용 `ml.*` 도구 (Agent Tools Contract)

> **정본.** 출처: `spec.md` §13 · §18-10 · goal2 §2 G2-I01 · §7 D2-08. 검사: `tests/test_agent_tools.py`(웨이브 P, 개발2).
> 상대 형식 근거(읽기 전용, `../Standard AI Agent Platform` HEAD `d33bdf2`): `contracts/tool-contract.md:7-44` · `src/agentcore/tools/registry.py:26-145` · `contracts/interfaces.md:15,46`.
> **우리 쪽은 계약 · 어댑터 · 시험만 만든다.** Agent 플랫폼 저장소에 쓰지 않는다. 그쪽 `packs/ml/` 등록은 그 팀이 이 문서를 보고 한다.

## 0. 이름 — 정본 이름과 Agent 이름 (정본 결함 D2-16)

spec §13 · goal2 의 이름 `ml.predict` · `ml.explain` · `ml.recommend` · `ml.monitor_summary` 는 Agent 계약의 이름 규칙 `^_?[a-z][a-z0-9-]*\.(get|list|find|compare|calculate|draft)_[a-z0-9_]+$`(tool-contract.md:7)에 맞지 않는다(동사 접두 없음). goal2 G2-I01 은 둘 다 요구한다 → **Agent 에 등록되는 이름은 규칙을 따르고, 정본 이름은 별칭으로 둔다.**

| 정본 이름 (spec §13) | Agent 도구 이름 | LLM 노출 이름 (`.` → `__`, tool-contract.md:9) | 호출하는 ML API |
|---|---|---|---|
| `ml.predict` | `ml.calculate_prediction` | `ml__calculate_prediction` | B03 `POST /api/v1/tenants/{t}/tasks/{task}/predict` |
| `ml.explain` | `ml.get_explanation` | `ml__get_explanation` | B15 `GET /api/v1/predictions/{prediction_id}/trace?view=explain` |
| `ml.recommend` | `ml.calculate_recommendation` | `ml__calculate_recommendation` | B04 `POST /api/v1/tenants/{t}/tasks/{task}/optimize` (`request_approval: false`) |
| `ml.monitor_summary` | `ml.get_monitor_summary` | `ml__get_monitor_summary` | B02 `GET …/tasks` + B06 `GET …/tasks/{task}/overview` |

- 네임스페이스 `ml` 은 Agent 의 코어 네임스페이스(`kb data sensor rule lineage metrics calc hub action`, tool-contract.md:8)가 아니다 → Agent 쪽에서 **팩 `ml`** 로 등록한다(그 팀 결정 — `decisions.md` D2-16 에 요청으로 남김).
- 별칭은 우리 쪽 어댑터 · 문서 · 시험에서만 쓴다(`ALIASES = {"ml.predict": "ml.calculate_prediction", …}`).

## 1. ToolMeta (registry.py:26-33 모양 그대로)

| 도구 | `readonly` | `sources` | `roles` (Agent 사용자 등급) | `pii` | `queries` | `label` |
|---|---|---|---|---|---|---|
| `ml.calculate_prediction` | **True** | `["ml"]` | `["admin", "manager", "staff"]` | False | `[]` | "ML 예측" |
| `ml.get_explanation` | **True** | `["ml"]` | `["admin", "manager", "staff"]` | False | `[]` | "예측 근거" |
| `ml.calculate_recommendation` | **True** | `["ml"]` | `["admin", "manager"]` | False | `[]` | "조건 추천" |
| `ml.get_monitor_summary` | **True** | `["ml"]` | `["admin", "manager", "staff"]` | False | `[]` | "모델 감시 요약" |

**넷 다 `readonly=True`**(D2-08). Agent 규칙상 `readonly=False` 는 `draft_*` · `action.propose` 만이다(tool-contract.md:16). ML 쪽에 남는 행은 감사 · 예측 기록(`mlp_prediction` · `mlp_recommendation` · `mlp_audit`)뿐이고, **승인 요청 · 모델 단계 · 설비 · MES 쓰기는 0** 이다. `ml.calculate_recommendation` 은 추천만 — `mlp_approval` 을 만들지 않는다(웨이브 P: optimize 요청 선택 키 `request_approval: bool = true`, 도구는 `false` 로 보낸다).

## 2. 인자 스키마 (pydantic v2 `BaseModel`, Agent 가 `model_json_schema()` 에서 `title` 을 뗀 것을 LLM 에 준다 — registry.py:113-117)

```json agent-tool-args
{
  "ml.calculate_prediction": {
    "type": "object", "additionalProperties": false, "required": ["task", "inputs"],
    "properties": {
      "task":      {"type": "string", "pattern": "^[a-z][a-z0-9]{1,7}\\.[a-z][a-z0-9_]*$", "description": "<회사>.<과제> — ctx.tenant.code 와 회사가 같아야 한다"},
      "inputs":    {"type": "object", "additionalProperties": {"type": ["number", "string", "null"]}},
      "entity_id": {"type": ["string", "null"], "maxLength": 64},
      "explain":   {"type": "boolean", "default": false}
    }
  },
  "ml.get_explanation": {
    "type": "object", "additionalProperties": false, "required": ["prediction_id"],
    "properties": {"prediction_id": {"type": "string", "pattern": "^prd_[0-9A-Z]{26}$"}}
  },
  "ml.calculate_recommendation": {
    "type": "object", "additionalProperties": false, "required": ["task", "fixed"],
    "properties": {
      "task":    {"type": "string", "pattern": "^[a-z][a-z0-9]{1,7}\\.[a-z][a-z0-9_]*$"},
      "fixed":   {"type": "object", "additionalProperties": {"type": ["number", "string", "null"]}},
      "current": {"type": ["object", "null"]},
      "params":  {"type": ["object", "null"]}
    }
  },
  "ml.get_monitor_summary": {
    "type": "object", "additionalProperties": false, "required": [],
    "properties": {
      "task": {"type": ["string", "null"], "pattern": "^[a-z][a-z0-9]{1,7}\\.[a-z][a-z0-9_]*$", "description": "없으면 회사의 켜진 과제 전부"},
      "days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7}
    }
  }
}
```

`choices(tenant)`(registry.py:118-131)로 `task` 에 그 회사의 켜진 과제 목록(B02)을 enum 으로 준다. 회사는 인자가 아니라 `ToolCtx.tenant.code` 에서 온다(registry.py:93-101) — 인자의 `task` 회사 접두가 다르면 `denied`.

## 3. 결과 — `ToolResult` (registry.py:48-73 · tool-contract.md:22-44)

| 필드 | 값 |
|---|---|
| `status` | `ok` · `empty` · `disconnected` · `denied` · `error` (아래 §3.1) |
| `source` | `"ml"` |
| `rows` | ≤ 200 (§3.2) |
| `demo_data` | 응답 `synthetic`(합성 스냅숏 모델) 이면 True — **숨기지 않는다** |
| `truncated` · `complete` | 모니터 요약이 과제 > 200 일 때만 truncated |
| `last_collected_at` | 예측 · 추천 시각 또는 감시 마지막 날(KST ISO-8601) |
| `cite` | ok 이면 ≥ 1 (§3.3) |
| `summary` | ≤ 200자 한국어. 입력값 · 키 · 내부 경로를 넣지 않는다 |

### 3.1 상태 대응 (ML HTTP → Agent status)

| ML 응답 | Agent `status` | cite |
|---|---|---|
| 200 | `ok` | 예측 · 추천 · 요약 근거 ≥ 1 |
| 200 · 목록 0 (감시 요약 대상 없음) | `empty` | `query` 1 (`ml:monitor_summary@<call_id>`) · complete True |
| 503 `model_not_ready` · `model_artifact_mismatch` · `source_disconnected` · 연결 실패 | `disconnected` | `query` 1, snapshot 키 정확히 `{connector: "ml", query: <도구 이름>, complete: false, error_code: <ML 오류 코드 \| "unreachable">}` (registry.py:68-76 · `disconnected()` 도우미 :80-90) — **기본값 · 대체 예측을 만들지 않는다** |
| 401 · 403 · 404(다른 회사) | `denied` | 없음 (registry.py:196-197) |
| 422 · 404(없는 과제 · 예측 ID) | `error` | 없음 · summary "인자 오류: <field>" (입력값 되풀이 0) |
| 200 + 예측 `status: out_of_range` · `rejected` | `ok` | 그대로 — rows 에 `status` 를 담고 summary 에 "학습 범위 밖" 을 쓴다(실패를 보인다) |

### 3.2 rows 모양

| 도구 | rows (1행 = 1 dict) |
|---|---|
| `calculate_prediction` | 1행 `{prediction_id, task, type, value, unit, interval, probability, grade, anomaly_flag, status, warnings: [code], model_version, synthetic}` — 표준 18키(predict-contract §2)에서 뽑는다 |
| `get_explanation` | 1행 `{prediction_id, task, model_version, algo, trained_at, snapshot_id, snapshot_rows, snapshot_range, synthetic, contributors: [{feature, contribution}] \| null, notice}` — 원천 소스 위치(`sources[].ref`)는 넣지 않는다 |
| `calculate_recommendation` | ≤ 5행 후보 `{rank, conditions, predictions, constraints_met, violation, in_train_range}` + summary 에 `feasible` · `rec_id` |
| `get_monitor_summary` | 과제당 1행 `{task, type, production_version, synthetic, predictions_yesterday, monitor_level, alerts, pending_approvals}` |

### 3.3 cite — 근거는 `prediction_id` (spec §13)

| 도구 | `kind` | `ref` | `subject` | `snapshot` |
|---|---|---|---|---|
| `calculate_prediction` | `row` | `ml:mlp_prediction/<prediction_id>` | `{"task": …, "entity": <entity_id 또는 "-">}` | `{value, unit, status, model_version}` |
| `get_explanation` | `row` | `ml:mlp_prediction/<prediction_id>` | `{"task": …, "model": <version>}` | `{snapshot_id, algo}` |
| `calculate_recommendation` | `row` | `ml:mlp_recommendation/<rec_id>` | `{"task": …}` | `{feasible, best: conditions}` + 의존 예측마다 `row` cite 하나 더(`uses` 버전) |
| `get_monitor_summary` | `row` | `ml:mlp_monitor_daily/<task>@<day>` | `{"task": …, "range": "<from>~<to>"}` | `{level, alerts}` |

`ref` 형식 `ml:<table>/<pk>` 는 Agent 의 `mes:<table>/<pk>` 형식(tool-contract.md:32)을 본뜬 것이다 — Agent 쪽에 형식 추가 요청(D2-16). `subject` 는 비우지 않는다(빈 subject 는 Agent 가 거부 — tool-contract.md:44).

## 4. 인증 · 한도 · 금지

- Agent 플랫폼은 회사마다 ML API 키 1개(`mlp_api_key.consumer = "agent"`, 역할 `operator`)를 쓴다. 키 값은 Agent 쪽 환경변수(그쪽 접두 `AGENT_`)에만 — 이 저장소 · 이슈 · 로그에 적지 않는다.
- `get_explanation` 은 B15 trace 를 **축약 보기**(`?view=explain` — 모델 · 스냅숏 · 기여만, 원천 ref 없음)로 부른다. 축약 보기는 operator 이상, 전체 trace 는 admin 그대로(웨이브 P: `std/roles.yaml` 에 `trace_explain` 권한 행 추가 · 개발2 라우터).
- 시간 한도: 도구 호출 1회 ≤ 5 s(예측 p95 200 ms 계약 — G-M14). 넘으면 `disconnected` · error_code `timeout`.
- **쓰기 0:** 4 도구는 승인 요청 · 승격 · 되돌리기 · 학습 · 실측 등록 · 대기열 판정 · 견적 확정을 부르지 않는다. 시험이 4 도구 호출 전후 `mlp_approval` · `mlp_model_version.stage` · `mlp_train_run` · `mlp_actual` · `mlp_review_item.state` · `mlp_quote` 행 수가 같음을 확인한다(QA2 관점, goal2 §3.3).

## 5. 계약 시험 (`tests/test_agent_tools.py`, G2-I01)

1. 위 `agent-tool-args` 블록의 4 스키마가 JSON Schema 로 유효하고, 어댑터 `mlcore/integrations/agent_tools.py`(웨이브 P, 개발2 — 코어 동결 전)의 pydantic 모델이 같은 스키마를 낸다.
2. 시험 DB · 합성 회사(ks · sw, 2차 끝에는 6개사)에서 FastAPI `TestClient` 로 4 도구를 호출 → 결과가 §3 모양(상태 · cite 불변식 — registry.py:62-76 와 같은 검사를 우리 시험이 다시 구현)과 일치.
3. production 없음 → `disconnected`(error_code `model_not_ready`) · 다른 회사 과제 → `denied` · 모르는 키 → `error` · 합성 모델 → `demo_data: True`.
4. 쓰기 0(§4) · 이름이 Agent 규칙 정규식에 맞음 · 별칭 4 → 이름 4 대응.
