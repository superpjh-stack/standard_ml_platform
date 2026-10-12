# progress-dev2.md — 개발2 (등록부 · 추론 · 승인)

> 담당: `src/mlcore/registry/models.py` · `registry/artifacts.py`(interfaces §5 경로) · `serve/*` · `tasks/*` · `approval/` · `audit/` · `auth/` · `api/{main,middleware,errors}.py` · `api/routers/{models,predict,train}.py`
> 시험: `tests/test_registry.py` · `tests/test_approval.py` · `tests/test_trace.py` · `tests/test_predict_*.py` · 공용 도우미 `tests/_dev2.py`

## 2차 §1 공표 — 웨이브 P (2026-10-13, 기준 커밋 283dd31) — 추출기 · 견적식 플러그인 · 공용 컴포넌트

> 개발1(모델 추출기 학습 · 화면 7) · 개발3(팩 `eto` · `rollform-quote` 추출기 · 견적식)이 이 모양을 따른다. 계약 정본은 `task-contract.md` §6.2 · §6.3 · `predict-contract.md` §8 — 아래는 그 구현 시그니처다(계약 기대값과 같고, 더한 것은 선택 키뿐).

### 2.1.1 추출기 — `packs/<pack>/extractors/<name>.py` (코어 로더 `mlcore.tasks.extract`)

```python
# 모듈 수준 (task-contract §6.2 그대로)
NAME = "cad_regions"; VERSION = "1.0.0"; KIND = "rule"            # 또는 "model"
def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None) -> dict: ...

# 코어 프로토콜 (mlcore/tasks/extract.py) — 위 모듈이 그대로 만족한다
class Extractor(Protocol):
    NAME: str; VERSION: str; KIND: Literal["rule", "model"]
    def extract(self, raw: bytes, filename: str, *, unit: str, limits: dict, model: LoadedModel | None = None) -> dict: ...
class ExtractError(ValueError):            # 추출기가 올린다 — code = "invalid_document"(422) | "document_too_large"(413)
    def __init__(self, code: str, rule: str, message: str = ""): ...   # rule = format·binary·parse·unit / bytes·entities·vertices·points
```

**입력** (코어가 미리 검사한 뒤 부른다 — 추출기는 같은 검사를 다시 하지 않아도 된다):
- `raw` — 업로드 원본 바이트(≤ `limits.max_bytes`). 코어가 이미 확인: 확장자 `.dxf` · 바이너리 DXF 아님 · 텍스트 해독(UTF-8-sig → cp949 → cp1252) · 그룹 코드 쌍 파싱 · 모델 공간 엔티티 수 ≤ `limits.max_entities`.
- `filename` — 경로를 뗀 150자 이하 이름.
- `unit` — **코어가 정한 원본 단위** `"mm" | "inch" | "cm" | "m"`: 헤더 `$INSUNITS` 1·4·5·6 이 있으면 헤더(우선), 없거나 0 · 그 밖이면 요청 `unit_override`(mm · inch), 둘 다 없으면 코어가 422 `invalid_document`(rule `unit`) — 추출기까지 오지 않는다. mm 환산 배수 `mlcore.tasks.dxf.SCALE_TO_MM[unit]`.
- `limits` — `{"max_bytes", "max_entities", "unit_override"}` (과제 `document` 상한, 팩 · 회사가 낮춘 값). 팩 고유 상한(꼭짓점 · 점 수)은 추출기가 보고 넘치면 `ExtractError("document_too_large", "vertices"|"points")`.
- `model` — `KIND == "model"` 일 때만. 그 extract 과제의 **등록부 production 산출물**(`registry.artifacts.load_artifacts` 의 `LoadedModel`: `.model` · `.lock`). production 이 없으면 코어가 503 `model_not_ready`(추출 전체를 하지 않는다 — 규칙 결과만으로 꾸미지 않는다).
- 코어 DXF 읽개(선택 사용): `mlcore.tasks.dxf.read(raw, max_entities=...) -> DxfDoc{header: dict, entities: list[Entity{type, layer, codes: list[(int, str)]}], entity_count, encoding}` — ezdxf 없이 ASCII DXF 그룹 코드만 읽는다(외부 의존 0). 추출기가 ezdxf 를 쓰려면 의존성 추가 요청(아키텍트 — G-S07).

**출력** (dict — 모르는 키는 버리지 않고 422 아님, 코어가 계약 키만 골라 담는다):
`{"regions": [...], "objects": [...], "bom_rows": [...], "confidence": float | None, "counts": {str: int}, "dimensions": {...} | None, "warnings": [str]}`
— 항목 모양은 predict-contract §8.2(`regions[]` 필수 `id · label · bbox · texts · evidence · status`, `objects[]` 필수 `id · label · model_label · confidence · bbox · review_reason`, `bom_rows[]` 필수 `name · material · quantity · mass_kg · source`). 쓰지 않는 칸은 빈 배열. 좌표는 mm.
**합침** (과제 `extractors` 순서대로): 배열은 이어 붙임 · `counts` 는 키별 합 · `dimensions` 는 처음의 non-null · `confidence` 는 model 추출기 값의 평균(규칙만이면 null) · `warnings` 이어 붙임. 응답 `extractor[]` = `{name, version, kind, model_version}`.
**금지:** 원본을 쓰지 않는다 · 네트워크 0 · 라벨 없으면(`labels: none`) 지표를 만들지 않는다(코어가 `metrics: null` 강제).

### 2.1.2 견적식 — `packs/<pack>/formulas/<module>.py` (코어 로더 `mlcore.tasks.quote`)

```python
def quote(inputs: dict, lines: list[dict], predicted: dict[str, Decimal], rates: dict[str, Decimal]) -> dict: ...
def prepare(inputs: dict, lines: list[dict]) -> dict: ...      # 선택 — 예측 전 파생 입력(예: Σ 품목 중량 → 회귀 입력). 순수 · Decimal
```
- `inputs` 값: JSON 숫자는 **`Decimal`**(요청을 `json.loads(parse_float=Decimal)` 로 읽는다 — float 를 거치지 않는다), 정수는 `int`, 범주는 `str`. `lines` 안 숫자도 같다.
- `predicted` = `{<uses 과제 짧은 이름>: Decimal(str(예측값))}` — 예: `{"labor_hours": Decimal("58.14612…")}`. 반올림(원천 소수 4자리)은 견적식이 한다.
- `rates` = 과제 `rates`(회사 덮어쓰기 병합 뒤) 를 `Decimal(문자열)` 로.
- 반환: `{"lines": [{"name": str, "amount": Decimal, ...}], "costs": {name: Decimal}, "total": Decimal, "predicted": {name: Decimal}?}` — 금액은 **원 단위 정수 Decimal**(코어가 `amount == amount.to_integral_value()` 를 확인, 아니면 500 · float 이면 500). `predicted`(선택)는 견적에 실제 쓴 값(응답 `predictions[].value`), 없으면 받은 값 그대로.
- 규칙: `Decimal` · `quantize(..., rounding=ROUND_HALF_UP)` 만, float 리터럴 · `float()` · `round()` · `math` 0 (`gates/check_decimal.py`).

### 2.1.3 화면 7~10 공용 컴포넌트 — `web/src/components/` (개발2 소유, `index.ts` 에서 내보낸다)

| 컴포넌트 · 함수 | 모양 | 쓰는 화면 |
|---|---|---|
| `useList<T>(path)` | `{items, total, next, loadMore, reload, error, loading}` — `{items, next_cursor}` 목록 + 커서 | 7 · 8 · 9 · 10 |
| `apiUpload<T>(path, form: FormData)` | multipart POST, 오류 봉투 → `ApiError` | 9 (7 의 CSV 업로드도 같은 함수) |
| `Money({value})` · `MoneyTable({costs, total, lines?, currency})` | 원 단위 **문자열**을 그대로 · 천 단위 구분만(문자열 연산 — Number 변환 0) | 9 |
| `DocumentViewer({doc})` | SVG 미리보기(영역 · 객체 bbox) + 영역 / 객체 / BOM 표 + `LabelsNotice` | 9 |
| `LabelsNotice({labels, metrics})` | `labels: none` → "정답 라벨 없음 — 지표 없음 (labels: none)" | 7 · 9 |
| `KeyValue({rows})` | `dl.kv` 표 | 7 · 8 · 10 |
| `IdLink({id})` | `prd_…` → `/app/trace?prediction_id=…` | 8 · 9 |
| `StateBadge` (확장) | 대기열 `open · confirmed_issue · false_alarm` · 견적 `draft · pending_confirm · confirmed` 추가 | 8 · 9 |
| 타입 `ReviewItem` · `DocumentExtraction` · `Quote` | predict-contract §8.1~8.3 그대로 | 8 · 9 |

기존 `ConnectionBar` · `ErrorBox` · `TaskPicker({types})` · `MetricTable` · `StatusBadge` · `SyntheticBadge` · `FeatureForm` 은 그대로.

## 2차 §2 웨이브 P 실측 (2026-10-13, 기준 커밋 283dd31 + 미커밋 · 커밋 안 함)

### 한 일 (담당 파일만)
- **추출 서비스** `tasks/dxf.py`(ASCII DXF 읽개 — 바이너리 · 파싱 · 엔티티 상한 · 단위) · `tasks/extract.py`(Extractor 프로토콜 · 로더 · 합침) · `serve/documents.py`(업로드 → 상한 413 · 422 rule format/binary/parse/unit · 원본 `var/documents/<tenant>/<sha>.dxf`(`MLP_DOCUMENT_DIR`) · `mlp_document` size/entity_count/labels · labels none → metrics null).
- **견적** `serve/quotes.py`(Decimal · ROUND_HALF_UP 만 — check_decimal 통과, 요청 `parse_float=Decimal`, 응답 `serve/jsonout.py` 로 Decimal 그대로 · 금액 문자열) — 초안 → revisions(overrides 누적) → confirm(reviewed + 메모 ≥ 5자 → pending_confirm + 승인 kind=quote) → B13 decide(approver 이상) → confirmed 새 행 · 반려/만료 → draft 새 행 · 409 quote_locked · CSV(BOM · 수식 주입 방지). `approval/__init__.py` 에 quote 결정 · 만료 되돌림, F20-5(TTL inf · nan · > 1년 거부). `serve/validate.ml_inputs`(모델 입력 경계 변환).
- **대기열 B09** `serve/review.py`(목록 · 판정 open → confirmed_issue|false_alarm 한 번, 409 already_decided, 감사).
- **API** `api/routers/phase2.py`(B09 · B10 · B11 — api-contract §6 경로 11, multipart 는 표준 email 파서 · 스트림 상한), `v1.py` 501 스텁 제거, `serve/predict.py` 2차 유형 predict 404 `type_route`.
- 포크: Agent 어댑터 `integrations/agent_tools.py` + optimize `request_approval` · trace `?view=explain` · 화면 8 · 9 · 10 + `web/src/components/Phase2.tsx` 등(2차 §1.3) · F7-4 · F7-11 · F7-12 · F16-8 · F16-9 · F19-3 · F20-1 · F20-2.
- 시험: `tests/test_types_phase2.py` 15 · `tests/test_extract.py` 16 · `tests/test_quote.py` 10 · `tests/test_agent_tools.py` 7 · `tests/test_followups_dev2.py` · `tests/test_web_followups.py` · `tests/e2e/test_console_phase2.py` 8 · `test_api_contract.py` +2(phase2 경로 type_route · 역할/범위/목록). 시험 팩 도우미 `tests/_phase2.py`(시험용 추출기 · 견적식 — 원천 식 아님). `test_predict_validation` 의 out_of_range 덮어쓰기 → 병합 결과 직접(F20-4 로더가 모르는 키 거부).

### 실측
| 항목 | 값 | 명령 |
|---|---|---|
| pytest | **724 passed · 3 skipped · 0 failed** (기준 462) | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| e2e | 22 passed | `uv run pytest -q tests/e2e` |
| 빌드 | 통과 | `cd web && npm run build` |
| make gate (1차 24행) | PASS 22 · FAIL 1(G-M14) · BLOCKED 1 — G-M14 는 bench compose 의 db 초기화 실패: 개발3 F7-7 의 `docker/initdb/20-app-login.sh` 가 `MLP_DB_APP_USER/PASSWORD` 를 요구하는데 `gates/bench.py` 임시 env 에 없다(내 변경과 무관, 수동 재현 `dependency db failed to start`) | `make gate2` 1차 절 |
| make gate2 | G2-E01 · G2-Q01 · G2-I01 **PASS**(P0 FAIL), G2-T01 · G2-A01 · G2-S01 은 남은 사유가 계약 표(§1 단계 · screen-map ○)뿐, G2-H01 열림 1(F7-5 아키텍트) | `make gate2` |

### 요청
- **아키텍트:** ① api-contract §1 의 B09~B11 행을 단계 1 로 + §6 행 합치기(코드 · 시험 준비됨 — `test_phase2_routes_exist_and_route_by_type` 는 P2 0 이 되면 자동으로 빈다) ② screen-map 7~10 `○` ③ `gates/bench.py` compose env 에 앱 LOGIN 변수(D-123) ④ `check_routes` 문구 "2차 501 3/3" → 경로 존재 ⑤ (선택) `mlp_prediction.channel` CHECK 에 `quote` — 지금은 견적 예측을 `api` 로 기록 ⑥ (선택) `auth.allowed_sub(role, area, sub)` — 하위 권한표(explain_view · quotes.confirm) 판정(지금은 trace.py 도우미).
- **개발3:** ① 과제 상세(GET …/tasks/{task})에 quote 의 `inputs` · `recognized` · `rates`, extract 의 `document` 를 내 주면 화면 9 가 인식값을 폼에 채운다 ② 팩 추출기 · 견적식은 2차 §1.1 · §1.2 모양(견적 `inputs` 중 features.yaml 밖 이름은 0 이상 수치로 검증, 예측 전 파생은 `prepare`) ③ 견적식 원천 대조 fixture 가 생기면 `tests/test_quote.py` · `test_extract.py` 에 원천 일치 시험을 더한다(개발2).

### 남은 일
G2-E01 의 원천 추출기 결과 일치 · G2-Q01 의 원천 견적 원 단위 대조(팩 생긴 뒤) · 감사 행 조회 API(계약에 없음 — 화면 10 은 trace 의 caller/channel/ts 만) · 4개사 호환 라우터(A2).

## §1 공표 (웨이브 A0 첫 작업 — 2026-10-12)

`contracts/interfaces.md` §5 · §6 · §7 을 그대로 구현한다. 더한 것은 **선택 키워드 인자**뿐이다(기존 호출을 깨지 않는다).

### 1.1 추론 — `mlcore.serve`

```python
# mlcore/serve/predict.py
@dataclass(frozen=True)
class PredictRequest:
    inputs: dict[str, Any]; entity_id: str | None = None; explain: bool = False; model_version: str | None = None

class Predictor:
    def __init__(self, catalog: "TaskCatalog", registry: Registry | None = None): ...
    def predict(self, tenant_id: str, task_id: str, req: PredictRequest, *, caller: str, channel: str = "api") -> dict: ...
    #   반환 = contracts/predict-contract.md §5 를 만족하는 18키 dict. mlp_prediction 1행 INSERT 후 prediction_id 를 채운다.
    #   순서: 과제 확인(없으면 NotFound 404) → validate_format(422 invalid_input) → validate_bounds(422 out_of_bounds)
    #         → check_missing(422 missing_required) → Registry.get(503 model_not_ready) → load_artifacts(503 model_artifact_mismatch)
    #         → impute → range_check → TaskKind.score/status → 응답 모델 검증 → serve.record INSERT
    def predict_batch(self, tenant_id, task_id, reqs: Sequence[PredictRequest], *, caller: str) -> dict: ...   # A 웨이브

# mlcore/serve/validate.py — 순서 고정
def validate_format(inputs: dict, features: Mapping[str, dict]) -> None        # InvalidInput
def validate_bounds(inputs: dict, features: Mapping[str, dict]) -> None        # OutOfBounds
def check_missing(inputs, features, max_imputed: int) -> list[str]            # MissingRequired (모델 없이 판정 가능)
def impute(inputs, features, lock: dict, max_imputed: int) -> tuple[dict, list[str]]
def range_check(inputs: dict, lock: dict, skip: Iterable[str] = ()) -> tuple[list[str], list[str]]   # (oor, near)
```

`features` 는 계약대로 **`Sequence[FeatureDef]`**(`mlcore.data.features`, D-47 — 웨이브 A 에서 바꿈). 병합된 features.yaml dict(`{이름: 정의}`)도 `serve.validate.as_defs()` 로 같은 FeatureDef 로 바꿔 받는다. 과제 목록 `serve.catalog.TaskSpec.defs` = 과제 변수 순서의 FeatureDef(최적화 과제는 fixed + controls).
`predict_batch(…) -> {"items": [응답 | {index, error}], "next_cursor": None}` — 1~500건, 건별 422 는 그 자리만, 503 은 전체 실패, 기록은 한 트랜잭션(웨이브 A 구현).

### 1.2 응답 모델 — `mlcore/serve/contract.py` (pydantic 2)

`PredictResponse` — 18키 전부 필수(`Optional` 이어도 기본값 없음 → 키 누락 시 검증 실패):
`task · type · tenant · entity_id · prediction · probability · anomaly · recommendation · status · warnings · imputed_fields · out_of_range_fields · explain · model · uses · prediction_id · synthetic · notice`.
하위: `Prediction{value, unit, interval, grade, baseline}` · `Anomaly{score, flag, threshold, contamination, contributors}` · `Recommendation`(§3 12키) · `Warning{code, field, message}` · `Explain{method, top}` · `ModelInfo{name, version, trained_at, snapshot_id, synthetic}` · `Use{task, version, synthetic}`. 전부 `extra="forbid"`.
요청: `PredictBody{inputs, entity_id, explain, model_version}` · `ActualBody{entity_id, value, observed_at}` — `extra="forbid"` · `allow_inf_nan=False` · 입력값은 `StrictInt | StrictFloat | StrictStr | None`(bool 거부).
응답은 내보내기 전에 `PredictResponse` 검증 + 시험에서 §5 JSON Schema(jsonschema) 검증을 둘 다 통과해야 한다.

### 1.3 등록부 — `mlcore/registry/models.py` · `artifacts.py`

```python
@dataclass(frozen=True)
class ModelRef: tenant_id; task_id; version; stage; algo; snapshot_id; run_id; synthetic; artifact_sha256; trained_at
               # + artifact_path: str · env_lock: dict · beats_baseline: bool · metrics: dict (덧붙임 — 기본값 있음)

class Registry:
    def register(self, result, *, tenant_id: str, task_id: str) -> ModelRef        # 항상 candidate, 버전 v<n> 부여
    def stage(self, tenant_id, task_id, version, *, actor: str) -> ModelRef        # candidate→staging (기준선 · 차단 경고 · live 합성)
    def get(self, tenant_id, task_id, version: str | None = None) -> ModelRef      # None=production, 없으면 ModelNotReady
    def list(self, tenant_id, task_id) -> list[ModelRef]
    def request_promotion(self, tenant_id, task_id, version, *, actor, action: "promote"|"rollback", reason) -> str   # apr_… (pending 만)

class ModelNotReady(Exception)     # 503 model_not_ready
class ArtifactMismatch(Exception)  # 503 model_artifact_mismatch
class InvalidTransition(Exception) # 409 (규칙 이름은 detail.rule)

def save_artifacts(version_dir, model, report, features_lock) -> str   # model.joblib · report.json · features.lock.json · env.lock → sha256
def load_artifacts(ref: ModelRef) -> LoadedModel                       # 해시 · env.lock 대조, 다르면 ArtifactMismatch
def artifact_sha256(version_dir) -> str                                # sha256( "<파일>\0<파일 sha256>\n" × 4, 파일 이름순 )
def current_env_lock() -> dict                                         # {"python": "3.12", "packages": {numpy, pandas, scikit-learn, joblib, scipy}}
```

`register(result)` 가 쓰는 `TrainResult` 필드: `run_id · status(succeeded 만) · champion · test_metrics · beats_baseline · artifact_dir · report · warnings`. **스냅숏 · 합성 여부 · 코드 버전은 `mlp_train_run` → `mlp_snapshot` 행에서 읽는다**(TrainResult 에 없다). 즉 학습기가 register 전에 두 행을 써 두어야 한다.

### 1.4 산출물 모양 (개발1 과 맞출 것 — 학습기가 `save_artifacts` 로 쓴다)

- `model.joblib` — `predict(DataFrame)`(regression) · `predict_proba(DataFrame)[:, 1]`(risk) 를 가진 객체(전처리 포함 Pipeline). 입력 열 = `features.lock.json` 의 `order`.
- `features.lock.json` —
  `{"order": [변수…], "features": {name: {"dtype", "fill": 보정값(학습 구간 median/most_frequent) | null, "p1", "p99"(수치) | "values"(범주)}}, "baseline": 학습 평균(회귀) | 학습 양성률(risk), "interval": {"method": "split_conformal", "alpha", "q"} | null}`
  — `artifacts.features_lock(...)` 도우미가 이 모양을 만든다.
- `env.lock` — `current_env_lock()` 의 JSON. 다르면 적재 거부.

### 1.5 승인 — `mlcore/approval`

```python
def decide(approval_id: str, *, actor: str, actor_role: str, approve: bool, reason: str | None,
           request_id: str | None = None) -> dict      # {approval_id, state, production_version}
class AlreadyDecided(Exception)   # 409 already_decided (이미 결정 · 만료 · 없음 아님)
```
한 트랜잭션: `UPDATE mlp_approval … WHERE approval_id=%s AND state='pending' AND (expires_at IS NULL OR expires_at > now()) RETURNING` → 0행이면 AlreadyDecided → 과제 모델 행 `FOR UPDATE` → 기존 production `archived` → 대상 `production`(promoted_at · promoted_by · approval_id) → `audit.write(conn=…)`. 회사 범위(404) · `own_task`(403) 는 API 가 decide 전에 본다.

### 1.6 API (contracts/api-contract.md 경로 그대로)

| 경로 | 파일 | 역할 |
|---|---|---|
| `POST /api/v1/tenants/{t}/tasks/{task}/predict` | `api/routers/predict.py` | operator+ |
| `POST …/actuals` · `GET /api/v1/predictions/{id}/trace` | `api/routers/predict.py` | operator+ · admin |
| `GET …/models` · `POST …/models/{v}/stage` · `POST …/models/{v}/promote` · `POST …/models/{v}/rollback` | `api/routers/models.py` | approver(조회) · admin · approver |
| `GET /api/v1/tenants/{t}/approvals` · `POST /api/v1/approvals/{id}/decide` | `api/routers/models.py` | operator(조회) · approver(own_task) |
| `POST …/train` | `api/routers/train.py` → `serve/training.py` | admin — 개발1 `mlcore.data.jobs.submit`(없으면 `mlcore.train.trainer.submit`)을 **요청 처리 중에만** 지연 import 해 부른다(기동 경로 0). 202 queued · 멱등 200 `reused: true` |

작업자 접착부: `serve/training.py::run_and_register(run_id)` = `mlcore.train.jobs.execute(run_id)` → 성공이면 `Registry.register()` (D-57).

### 1.6.1 최적화 · 호환 (웨이브 A 공표)

```python
# mlcore/tasks/optimize.py — interfaces §8
@dataclass(frozen=True) class OptimizeRequest: fixed: dict; current: dict | None = None; params: dict | None = None; entity_id: str | None = None
class Optimizer:
    def __init__(self, catalog: TaskCatalog, registry: Registry | None = None): ...
    def space(self, task, locks: list[dict], params: dict, defs: dict[str, FeatureDef]) -> SearchSpace   # axes · kinds · ranges · size · strategy · points
    def optimize(self, tenant_id, task_id, req: OptimizeRequest, *, caller: str, channel: str = "api") -> dict   # 18키 (recommendation)
def load_formula(merged, module) -> Callable   # tenants/<code>/formulas/ 우선, 없으면 packs/<pack>/formulas/<module>.py::cost(row, params)

# mlcore/serve/compat/__init__.py — 호환 (D-18)
class Compat: resolve(method, path) · predict(body) · optimize(body) · overview() · records(query) · record(lot_id) · health()
# 경로 = tenants/<code>.yaml compat.routes, 옛 요청 키 = compat.input_rename, 상태 문구 = compat.status_text,
# 반올림 = compat.round (D-W2-02), 장비 = compat.equipment_by_<변수>, 옛 회귀 키 = 과제 target.name
```
API: `POST …/predict:batch`(operator) · `POST …/optimize`(operator, `{fixed, current?, params?, entity_id?}`) · 호환 `/api/{rest}`(app 맨 끝, compat.routes 만).
`approval.decide()` 는 kind=recommendation 도 결정한다(→ `mlp_recommendation.status`, production 불변 — D-W2-05). `request_promotion` evidence 에 `shadow` (D-W2-06).

### 1.7 웹 공용 컴포넌트 — `web/src/components/` (웨이브 A 첫 공표, 2026-10-12)

화면 1~6 은 **`import {…} from '../components'`** 로만 쓴다(같은 것을 화면 안에 다시 만들지 않는다). 회사 · 팩 이름 0.

| 모듈 | 내보내는 것 | 쓰임 |
|---|---|---|
| `api.ts` | `api<T>(method, path, body?)` — `/api/v1` + `X-API-Key`, 오류 봉투 → `ApiError{status, code, message, detail}` · `tpath('/tasks')` → `/tenants/{t}/tasks` · `useApi<T>(path\|null, deps)` → `{data, error, loading, reload}` · `useConnection()` · `getConnection()` | 연결(회사 코드 · 키)은 브라우저 localStorage 에만 |
| `types.ts` | `Status` · `FeatureMeta` · `ParamMeta` · `TaskInfo` · `PredictResponse`(18키) · `Recommendation` · `Candidate` · `Warning` · `Metric{value, baseline, delta_vs_baseline}` · `ListResponse<T>{items, next_cursor, total?}` · `named(x)` (dict/배열 메타 → 배열) | |
| `StatusBadge.tsx` | `<StatusBadge status labels?/>` (상태 6) · `<SyntheticBadge synthetic/>` · `<RangeBadge inRange? rate?/>` · `<StateBadge state/>` (승인 pending… · 단계 candidate…) · `STATUS_LABEL` | |
| `MetricTable.tsx` | `<MetricTable metrics caption? compare?/>` — 값 · 기준선 · Δ · "기준선 이김/못 이김" (+ 비교 열, 예: production) · `fmt(v)` · `beats(name, m)` | 화면 1 · 4 · 5 |
| `FeatureForm.tsx` | `<FeatureForm features values onChange highlight?={imputed, outOfRange} disabled?/>` · `initialValues(features)` · `toInputs(features, values)` (빈 칸 → null = 보정 대상) | 화면 2 · 3 (features.yaml 로 폼 생성) |
| `Common.tsx` | `<ConnectionBar/>` · `<ErrorBox error/>`(503 model_not_ready → "운영 모델 없음 (model_not_ready)", 숨기지 않음) · `<TaskPicker value onChange types? exclude?/>` · `<Warnings warnings/>` · `<Notice text/>` | |
| `components.css` | `.card` `.row` `.cols` `table.grid` `.badge-*` `.kv` `button.primary` — 1024px 에서 줄바꿈(가로 스크롤 0) | |

**개발3 에 요청(B02):** `GET /tenants/{t}/tasks` → `{items: [{task, type, title, …}], next_cursor}`, `GET /tenants/{t}/tasks/{task}` → `{task, type, title, features: [FeatureMeta…](과제 변수 순서, values_from: tenant 는 회사 categories 로 채운 values), controls?, fixed?, params?, decision_vars?, uses?, approver_role, …}`. `FeatureMeta` = features.yaml 항목 + `name`. 폼은 배열 · dict 둘 다 받는다(`named()`). 서버 쪽 같은 모양은 `mlcore.serve.catalog.TaskSpec.features`(이름 → 병합 정의) 를 그대로 쓰면 된다.

## §2 웨이브 A0 실측 (2026-10-12)

### 만든 파일

| 파일 | 내용 |
|---|---|
| `src/mlcore/registry/models.py` | `ModelRef` · `Registry`(register · stage · get · list · request_promotion) · `ModelNotReady` · `InvalidTransition` |
| `src/mlcore/registry/artifacts.py` | `save_artifacts` · `load_artifacts`(해시 · env.lock 대조, 파일 상태 캐시) · `artifact_sha256` · `features_lock` · `current_env_lock` · `ArtifactMismatch` — 개발1 `train/artifacts.py` 가 이것을 그대로 쓴다 |
| `src/mlcore/approval/__init__.py` | `decide()` (production 유일 쓰기 경로) · `AlreadyDecided` · `get` |
| `src/mlcore/serve/{errors,ids,contract,catalog,validate,predict,record,actuals,trace,training}.py` | 오류 · ULID · pydantic 18키 · 과제 목록 · 검증 3단 · Predictor · 예측 기록 · 실측 · 추적 · 학습 접착부 |
| `src/mlcore/tasks/{base,regression,risk}.py` | `TaskKind` · 상태 우선순위 · 회귀(구간 · clip · 기준) · 위험(등급 · 기준) |
| `src/mlcore/auth/__init__.py` (수정) | `require` · `require_own_task` · `at_least` · `Forbidden`(403) |
| `src/mlcore/api/main.py` (수정) · `api/routers/{_common,predict,models,train}.py` | 라우트 11개 · 오류 처리기(ServeError · AuthRequired) |
| `tests/_dev2.py` · `test_registry.py` · `test_approval.py` · `test_trace.py` · `test_predict_contract.py` · `test_predict_validation.py` | 시험마다 새 회사 코드(임시 tenants 폴더 + 실제 로더) — 추가만 테이블을 지우지 않고 격리 |

### 실측

| 항목 | 실측 | 명령 |
|---|---|---|
| 개발2 시험 | **61 passed** (registry 13 · approval 13 · trace 9 · predict_contract 9 · predict_validation 17) | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_registry.py tests/test_approval.py tests/test_trace.py tests/test_predict_contract.py tests/test_predict_validation.py` |
| 전체 시험 | 160 passed (개발1 · 개발3 포함) | `OMP_NUM_THREADS=1 uv run pytest -q` |
| 승인 경합 | 같은 승인 2스레드 × 3회 → 매번 성공 1 · `AlreadyDecided` 1 · 감사 1행. 다른 승인 2건 동시 → 둘 다 차례로 성공 · production 1 | `tests/test_approval.py::test_concurrent_*` |
| 한 트랜잭션 | 감사 INSERT 실패 → 승인 pending · 단계 staging 그대로(전부 롤백) | `test_audit_failure_rolls_back_everything` |
| production 쓰기 경로 | 1 (decide 안 1 · 밖 0) | `uv run python gates/check_no_autopromote.py` |
| 산출물 대조 | model.joblib 1바이트 추가 → 503 `model_artifact_mismatch`(rule sha256) · scikit-learn 버전 다름 → 503(rule env_lock) | `test_artifact_hash_mismatch_refused` · `test_package_version_mismatch_refused` |
| 수직 관통 손 확인 | 임시 DB 에서 개발1 실제 `submit` → `run_and_register` → stage → 승인 → predict → trace: ks.remaining_hours gbr v1 (값 103.09 h, 구간 [92.41, 113.76]) · sw.delta_e extra_trees v1 (1.861 ΔE) · trace 스냅숏 720행 · 해시 · 소스(synthetic, 생성기 경로 · sha256) | scratchpad 스크립트(커밋 안 함), 임시 DB 는 지웠다 |

### make gate 변화 (개발2 해당)

| 게이트 | 전 (Phase 0) | 후 |
|---|---|---|
| G-M06 | FAIL — 학습기 없음 · test_registry.py 없음 | **PASS** — A test_determinism 9 (개발1) · B 기동 경로 학습 코드 0 · C test_registry 13 passed |
| G-M07 | FAIL — test_trace.py 없음 | **PASS** — test_trace 9 passed |
| G-M09 | FAIL — decide() 없음 | FAIL — 쓰기 경로 1(decide 안) · test_approval 13 passed · **tests/test_monitor.py 없음(개발3, 웨이브 A)** |
| G-S04 | 1/12 | 5/12 (B01 · B05 · B07 · B13 · B15). B03 은 `predict:batch`, B08 은 `GET /runs/{id}`(개발1) 가 없어 미완 |
| G-M04 | B predict 미구현 | B test_predict_contract 9 passed — C test_compat.py(호환 라우터, 웨이브 A) 없음 |

### 남은 것 · 다른 사람에게 필요한 것

- 개발1: 작업자가 `execute` 뒤 `Registry.register()` 를 부르게 할지(`serve.training.run_and_register` 사용) 정하기 — D-57. `TrainResult.artifact_sha256` 를 주면 등록 때 다시 재서 다르면 거부한다.
- 개발3: `tests/test_monitor.py` 가 있어야 G-M09 PASS. 감시는 `Registry().request_promotion(...)` 까지만 부른다.
- 아키텍트: D-54(오류 코드 `invalid_transition` · `train_busy`) · D-57(작업 실행 주체).
- 다음 단계(개발2): `tests/test_vertical_slice.py`, `predict:batch`, anomaly · optimize 추론부, 호환 라우터.

## §3 웨이브 A0 통합 — G-V01 (2026-10-12, 기준 커밋 762e5e7, 커밋 안 함)

`tests/test_vertical_slice.py` — `ks.remaining_hours`(팩 press) · `sw.delta_e`(팩 textile) 2건 파라미터화, 같은 시험 본문 · 같은 mlcore 코드.

흐름(전부 FastAPI TestClient, 실제 auth 경로 — `mlp_api_key` 해시 조회 → 미들웨어 → `auth.require` / `require_own_task`):
`POST …/train`(operator 403 · 키 없음 401 · admin 202 queued · 재요청 200 reused) → **작업 실행 → candidate** → `GET …/models`(candidate · `beats_baseline` · 시험 MAE < 기준선) → candidate 상태 predict 503 `model_not_ready` → `POST …/stage`(approver 403 · admin 200 staging) → `POST …/promote`(다른 과제 approver 403 · approver 202 pending, 여전히 503) → `GET /approvals?state=pending` → `POST /approvals/{id}/decide`(operator 403 · approver 200 production · 재결정 409 `already_decided`) → `POST …/predict`(viewer 403 · operator 200, 18키 · JSON Schema · regression null 규칙 · 구간 안 값) → `mlp_prediction` 1행(outputs = 응답) → `POST …/actuals`(linked = [pid]) → `GET /predictions/{id}/trace`(approver 403 · admin 200: 모델 · 실행 · 스냅숏 sha256 = `mlp_snapshot.sha256` · 소스 참조 = 스냅숏 `source_ref` · 실측) → 다른 회사 admin 키 404.

### 우회 (기록)

- **D-57 (작업 실행 주체 미정):** `POST …/train` 은 queued 만 만든다. 시험은 작업자 진입점 `serve.training.run_and_register(run_id)`(= `train.jobs.execute` → `Registry.register()`)를 **직접 부른다**. 아키텍트가 작업자/배경 작업을 정하면 그 경로로 바꾼다. 시험 머리 주석에도 적었다.
- **격리(_dev2 방식):** 시험마다 `tenants/<ks|sw>.yaml` 을 새 코드로 임시 폴더에 복사. 개발1 학습기는 `registry.tenants.load_and_merge(code)` 를 기본 폴더로 부르므로, 시험에서만 `monkeypatch` 로 **그 임시 코드만** 임시 폴더를 보게 감쌌다(다른 코드는 원래 함수). 코어 코드 변경 0. 다른 개발자 파일 수정 0 · 요청 0.
- 결함: G-V01 을 막는 개발2 결함 없음(수정 0).

### 실측

| 항목 | ks.remaining_hours | sw.delta_e |
|---|---|---|
| 챔피언 · 버전 | gbr v1 | extra_trees v1 |
| 시험 MAE / 기준선 | 5.568 h / 21.219 (보고값 5.57) | 0.557 / 1.087 (보고값 0.557) |
| 예측(보정값 입력) · 구간 | 103.086 h · [92.41, 113.76] | 1.861 · [0.722, 3.000] |
| 스냅숏 | 720행 · sha256 64자 · synthetic · `packs/press/synth/remaining_hours.py` seed 42 | 720행 · synthetic · `packs/textile/synth/delta_e.py` seed 42 |

| 명령 | 결과 |
|---|---|
| `OMP_NUM_THREADS=1 uv run pytest -q tests/test_vertical_slice.py` | 2 passed (2.7 s) |
| `OMP_NUM_THREADS=1 uv run pytest -q` | **162 passed** (전 160 + 2) |
| `make gate` | **G-V01 PASS** · 합계 PASS 11 · FAIL 12 · BLOCKED 1 (전 PASS 10 — 다른 PASS 전부 유지: G-S01 · S02 · S06×2 · S07 · M01 · M03 · M05 · M06 · M07) |

## §4 웨이브 A 실측 (2026-10-12, 기준 커밋 7d583cf, 커밋 안 함)

### 한 일 (담당 파일만)

| 항목 | 파일 | 내용 |
|---|---|---|
| 공용 컴포넌트(먼저 공표 §1.7) | `web/src/components/{api,types}.ts` · `{StatusBadge,MetricTable,FeatureForm,Common}.tsx` · `components.css` · `index.ts` | 상태 배지 · 지표 표(기준선 이김/못 이김) · features.yaml 폼 생성기 · 연결 · 오류 상자(503 그대로) · 과제 선택 |
| 화면 2 · 3 · 5 | `web/src/screens/{Predict,Optimize,Approvals}.tsx` | 예측 시험(18키 · 경고 · 보정 · 범위 강조) · 조건 추천(후보 5 · 제약 충족표 · 학습 범위 배지 · least_violation 상자 · "설비로 내려가지 않음") · 승인 대기열(모델 · 추천 카드 · 지표 비교 · 그림자 차이 · 사유 · 409 처리 · 커서) — `_placeholder` 0 |
| anomaly 추론 | `tasks/anomaly.py` | 점수(`-score_samples`) · flag(lock threshold ≥) · 기여 변수(보정값 국소 치환, 상위 5) · watch 없음 |
| optimize | `tasks/optimize.py` | 학습 범위 ∩ min/max · step 격자, decision_vars [min, max_param], grid/random 자동(seed 고정), 제약 식(+ − × 만, ast 검사), violation Σ/|rhs|, 목적+tiebreak lexsort, 상위 5, current · improvement, least_violation + review, uses production 버전, mlp_recommendation + 승인 요청 |
| batch · 검증 | `serve/predict.py` · `serve/validate.py` · `serve/catalog.py` · `serve/contract.py` | predict:batch ≤ 500 · FeatureDef 입력(D-47) · 모르는 키 field 반사 제한(D-W2-07) |
| D-54 후속 | `registry/models.py` · `serve/training.py` | rollback 사유 없음 → 422 `missing_required`(field reason) · TrainBusy detail `{rule: tenant_concurrency}` · 꺼진 과제 → 404 |
| 승인 | `approval/__init__.py` · `api/routers/models.py` · `registry/models.py` | 추천 결정 · 역할 먼저(operator decide 403) · 그림자 예측 차이 |
| 인증 · CORS | `api/main.py` | CORS 설정 목록만(`*` 무시) · 기동 등록부 루트 = `data.jobs.load_merged`(MLP_TENANTS_DIR) · 개발3 `ops` 라우터 등록(요청 이행) · 호환 잡이 맨 끝 |
| 호환 라우터 | `serve/compat/__init__.py` · `api/routers/compat.py` | 옛 경로 5 (health · 묶음 predict · optimize · overview · records(+상세)) · 옛 키 · 옛 422 `{"detail": […]}` |
| 시험 | `tests/test_optimize.py`(11) · `test_auth.py`(18) · `test_api_contract.py`(38) · `test_compat.py`(38, skip 3) · `test_predict_contract.py`(+18 → 27) · `test_approval.py`(+1) · `test_registry.py`(D-54) · `test_vertical_slice.py`(monkeypatch 제거) · `_dev2.py`(real_production) · `compat_expected.yaml`(원천 파일:줄 기대값) | |

### 실측

| 항목 | 실측 | 명령 |
|---|---|---|
| 전체 시험 | **369 passed · 3 failed · 3 skipped** (40 s). 실패 3 = 남의 몫: `test_api_contract::test_phase1_route_exists[B08 GET /runs/{run_id}]`(개발1 미구현) · `test_compat::test_bundle_predict_old_keys_and_values[ks · sw]`(개발3 `compat.round` 미기입 — D-W2-02, 값은 120.933399 대 원천 규칙 120.93) | `OMP_NUM_THREADS=1 uv run pytest -q -p no:cacheprovider` |
| 개발2 시험 | optimize 11 · auth 18 · api_contract 37/38 · compat 33/35(+3 skip) · predict_contract 27 · predict_validation 17 · registry 13 · approval 14 · trace 9 · vertical_slice 2 | 파일별 pytest |
| 켜진 과제 8 predict 계약 (G-M04 B) | 8/8 — 학습 6(개발1 실제 학습 → 승인 → production: ks gbr · rf_clf · isolation_forest / sw extra_trees · gbc · isolation_forest) predict · batch 스키마 통과, 최적화 2 optimize 스키마 통과 · uses = production 버전 · predict 는 404 | `tests/test_predict_contract.py` |
| ks.maintenance_timing (1차원) | grid **97점**(원천 candidate_count 97 과 같음) · in_train_range_rate 1.0 · 상위 5 = 독립 재계산(의존 모델 직접 → 비용식 → 제약 → 비용 ↑ · 대기 ↓)과 일치 · 불가능(reserve 150 · cost 1) → feasible false · n_feasible 0 · review · least_violation = 전수 최소 | `tests/test_optimize.py` |
| sw.print_setpoint (5차원) | grid **1,080점**(원천 8,400 — 학습 범위 ∩ 로 끝점 제외, D-31) · 학습 범위 밖 점 **0** · 학습 범위 안 격자점 누락 0 · best = 전수 독립 계산 최소 비용(동률 ΔE) · 불가능 제약 충족 후보 **0** | 같은 파일 |
| 10,000 점 | random 10,000점 2회 0.15 s(≤ 10 s), 같은 시드 → 같은 best | `test_ten_thousand_points_within_ten_seconds_and_random_is_deterministic` |
| batch 500 | 500건 200 · 오류 0 · 0.22 s (≤ 3 s, 참고 — 정식 G-M14 는 make bench) · 501건 422 · 0건 422 · 건별 422 는 `{index, error}` | `test_batch_limits` |
| 역할 4 | goal §6 표 7영역 × 4역할 = roles.yaml · `auth.allowed` · 실제 HTTP 11경로 모두 일치, trace admin 만, own_task 403, staging 지정 예측 approver+ | `tests/test_auth.py` |
| 회사 범위 | 다른 회사 키 → 404 (predict · models · approvals · promote · tasks · trace · decide — decide 뒤 승인 pending 그대로) | 같은 파일 |
| CORS | 설정 원점만 허용 · `*` 는 설정에 있어도 무시 · 목록 비면 헤더 0 | `test_cors_only_configured_origins` |
| 오류 계약 | 401 · 403 · 404 · 422(5종) · 409(already_decided · invalid_transition · train_busy) · 422 missing_required(rollback reason) · 501(2차 8경로) · 503 model_not_ready 봉투 `{error:{code,message,detail}}` + X-Request-Id · 입력값 반사 0 | `tests/test_api_contract.py` |
| 호환 | ks · sw 옛 경로 5 · 옛 키 순서 그대로(묶음 predict · optimize · overview · records · health) · 옛 422 `{"detail":[{loc,msg,type}]}` · 원천 시험 케이스(잘못된 값 5·6 · 결측 · Infinity · 페이징 6) 재현 · 키 없음 401 · viewer 403 · 다른 회사 404 | `tests/test_compat.py` |
| vertical slice | monkeypatch(코드 바꿔 끼우기) 제거 → 개발1 공식 주입(`MLP_TENANTS_DIR`, monkeypatch.setenv) — 2 passed | `tests/test_vertical_slice.py` |
| 웹 | `npm run build` 성공(tsc -b + vite, 271 kB js) · G-M01 PASS(코어 95파일 위반 0) · 화면 6 파일 `Placeholder` 0 | `cd web && npm run build` · `uv run python gates/check_core_terms.py` |

### make gate 변화

| 게이트 | 전 (7d583cf, PASS 11) | 후 |
|---|---|---|
| G-M13 | FAIL — test_optimize.py 없음 | **PASS** — 11 passed |
| G-M04 | FAIL — test_compat.py 없음 | FAIL — A 91/91 · B **27 passed(과제 8)** · C 33 passed / **2 failed(개발3 compat.round)** |
| G-S04 | FAIL — 5/12 | FAIL — **11/12**(없음 B08 개발1) · test_api_contract 37 passed / 1 failed(B08) |
| G-M11 | FAIL — test_auth.py 없음 | FAIL — test_auth **18 passed** · `docker-compose.yml 없음`(개발2 몫 아님) |
| G-S03 | FAIL — placeholder 6/6 | FAIL — placeholder 0 · `tests/e2e/ 없음`(D-W2-08) |
| 합계 | PASS 11 · FAIL 12 · BLOCKED 1 | **PASS 18 · FAIL 5 · BLOCKED 1** (개발1 · 3 몫 포함, 기존 PASS 전부 유지) |

### §5 요청 · 남은 일

- 개발3: `tenants/{ks,sw}.yaml compat.round` (D-W2-02 — 이것만 들어오면 G-M04 PASS 기대) · 선택 `compat.optimize_rename`.
- 개발1: `GET /api/v1/runs/{run_id}` (B08 — G-S04 마지막 1묶음). 라우터 파일을 만들면 `api/main.py` 등록은 개발2 가 한다(ops 처럼).
- 아키텍트: `MLP_TENANTS_DIR` 한 규칙(D-W2-03) · optimize 범위 밖 상태(D-W2-04) · 추천 승인(D-W2-05) · `docker-compose.yml`(G-M11 배포 부분).
- 개발2 다음: `tests/e2e/` 1024px(D-W2-08, Playwright 의존성) · 호환 records 를 B12 행 함수로(D-W2-09) · anomaly 기여 변수의 batch 속도(행마다 치환 프레임).

## §6 웨이브 C — 결함 수정 (2026-10-12, 기준 커밋 9d2febc + 미커밋 · 커밋 · 이슈 닫기 안 함)

### 6.1 공표 — 호환 응답 회사 값 키 (D-132) · **개발3 에 기입 요청**

`tenants/<code>.yaml compat` 아래. 코어는 키를 읽기만 한다(`serve/compat/__init__.py`). 값은 원천 코드를 읽어 `tests/compat_expected.yaml` 에 옮긴 기대값과 같아야 `tests/test_compat.py` 4건(ks · sw × optimize · overview)이 통과한다.

| 키 | 모양 | ks 값(원천 KwangSung `api/ml_service.py`) | sw 값(원천 SongWol `api/ml_service.py` · `config.py`) |
|---|---|---|---|
| `optimize_rename` (있음 + 추가) | {표준 예측 · 비용식 · **묶음 anomaly 과제 짧은 이름**: 옛 행 키} | 그대로 `{maintenance_cost: cost_index}` | 기존 3개 + `print_ood: anomaly` (:184 행 열 anomaly) |
| `optimize_row` | [옛 행 키 순서] — 있으면 이 키만 낸다 | `[stop_after_hours, cost_index, reserve_hours, violation]` (:138-139) | `[set_temp, set_pressure, line_speed, ink_usage, dwell_time, pred_delta_e, risk_probability, cost_index, violation, anomaly]` (:184) |
| `optimize_derived` | {옛 키: "표준 이름 식"} (+ − × 만) | `{reserve_hours: "remaining_hours - stop_after_hours"}` (:138 life − times) | 없음 |
| `optimize_row_round` | {옛 키: 자리} | 없음 (행 반올림 없음) | `{pred_delta_e: 4, risk_probability: 4, violation: 4, cost_index: 2}` (:156 · :186) |
| `optimize_unmet_text` | {제약 이름: 옛 문구} | `{reserve: 요청한 잔여수명 여유시간 미충족, max_cost: 정비 비용지수 상한 초과}` (:144-145) | `{max_delta_e: 목표 색차(ΔE) 상한 미충족, max_risk: 불량 위험 상한 초과, min_line_speed: 최소 라인속도 미충족}` (:179-181) |
| `optimize_objective_text` | 문자열 | `제약 충족 후보 중 데모 비용지수 최소화, 동률이면 더 늦은 시점 선택` (:148) | `제약 충족 후보 중 데모 공정 비용지수 최소화, 동률이면 예측 색차가 작은 조건` (:192) |
| `optimize_anomaly_text` | 문자열(추천 행이 anomaly 면 옛 warnings 맨 앞) | 없음 | `추천 조건이 학습 분포와 다른 조합입니다. 시험 인쇄로 먼저 확인하세요.` (:182) |
| `overview_values` | {옛 키: 범주 변수} | `{products: product_type}` (:163) | `{print_types: print_type, color_tones: color_tone}` (:212) |
| `overview_controls` | 옛 키 이름 | 없음 | `controls` (:212) |

미리 확인: 위 값을 임시 회사 사본에만 넣은 스크래치 플러그인(저장소 tenants/ 미변경)으로 `tests/test_compat.py` **35 passed · 3 skipped**. 같이 요청: `packs/textile/tasks/print_setpoint.yaml` 에 `warn_with: [textile.print_ood]`(D-76 · D-131, 선택 — 없어도 호환 행 anomaly 는 묶음 anomaly 과제로 낸다).

### 6.2 결함별 처리 · 회귀 시험 (먼저 실패 확인 → 고침)

| 결함 | 처리 | 회귀 시험 (고치기 전 → 후) |
|---|---|---|
| DEF-QA2-001 #14 중대 | 옛 행을 회사 값 키(6.1)로 조립 · 미충족 문구 · objective 문구 · sw current_cost_index 반올림 · sw 행 anomaly(묶음 anomaly production flag) | `test_compat::test_optimize_old_keys[ks·sw]` 행 키 · 순서 · 반올림 · reserve 관계 · 문구 — FAIL → **개발3 값 대기**(시뮬레이션 PASS) |
| DEF-QA2-002 #15 중대 | 미들웨어가 `/api/` 모든 쓰기 시도 감사(401 · 다른 회사 404 · 호환 포함) | `test_write_attempts_are_audited_*` 2 — FAIL → PASS |
| DEF-QA3-002 = QA2-004 #16 중대 | `safe_field` — 계약 필드 이름 · 색인만, 나머지 `*` | `test_422_never_echoes_request_keys`(7경로) — FAIL → PASS |
| DEF-QA3-003 #18 중대 | `compat.entity_prefix` 적용 · 원천 LOT 번호 상세 · 검색 | `test_compat::test_records_old_paging_and_detail[ks·sw]` — FAIL → PASS |
| DEF-QA2-003 | batch 건별 pydantic 검증 | `test_batch_one_malformed_item_does_not_block_others` — FAIL → PASS |
| DEF-QA2-005 | 같은 바이트 해시 · 적재 | `test_artifact_bytes_hashed_are_bytes_loaded`(경합 창 5지점) — FAIL(after=3) → PASS |
| DEF-QA2-006 | 400 → 422 invalid_input | `test_huge_integer_literal_is_422` — FAIL → PASS |
| DEF-QA2-007 | StrictBool | `test_explain_is_strict_bool` — FAIL → PASS |
| DEF-QA2-008 | 없는 버전 404 (api-contract §3) | `test_unknown_model_version_is_404` — FAIL → PASS |
| DEF-QA2-010 | 개요 missing_cells · duplicate_lots · impossible_cells · importance · evaluated · 범주 목록 · controls, 나머지 differs 사유 | `test_compat::test_overview_old_keys` — FAIL → **개발3 값 대기**(overview_values · overview_controls 만 남음) |
| health 관찰 | 적재 대조 반영 | `test_health_reflects_artifact_check` — FAIL → PASS |
| X-Request-Id 관찰 | 64자 · 문자 제한 | `test_request_id_is_bounded` — FAIL → PASS |
| DEF-QA3-004 (#7 · D-73) | D-130 만료 | `test_approval_expiry_*` 2 — FAIL → PASS |
| DEF-QA3-005 | 결정 결과 · 409 안내를 목록 위 상자로 | `tests/e2e/test_approvals_409.py`(ks · sw 두 탭) — 옛 Approvals.tsx 로 2 failed → 새 코드 PASS |
| DEF-QA3-006 | current 결정 변수 [min, max\|params] | `test_optimize_current_decision_var_bounds` — FAIL → PASS |
| D-76 warn_with | `Optimizer.anomaly_flags` · `_warn_with` (경고 코드 D-131) | compat 행 anomaly 로 간접 · 팩 키는 개발3 |
| D-120a (개발3 요청) | `catalog.require_servable` — 꺼진 과제 503 · live+합성 503 | `test_disabled_task_predict_is_503` · `test_live_tenant_synthetic_production_is_503` · 개발3 `tests/test_r4_live_path.py` 7 passed |

새 D 번호: D-130 ~ D-134(decisions.md 맨 끝). D-81(호환 records 를 B12 행 함수로)은 이번 회전에 하지 않았다 — 지금은 production 스냅숏 행(등록부)으로 낸다.

### 6.3 실측

| 명령 | 결과 |
|---|---|
| `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` | **453 passed · 4 failed · 3 skipped**(45.6 s, test_optimize 시험 대역 고친 뒤 재실행 11 passed). 실패 4 = `test_compat::test_optimize_old_keys[ks·sw]` · `test_overview_old_keys[ks·sw]` — 6.1 회사 값(개발3 `tenants/*.yaml`) 미기입. 같은 값을 임시 사본에만 넣으면 35 passed |
| `uv run pytest -q tests/test_wave_c_dev2.py` | 15 passed |
| `uv run pytest -q tests/e2e` | **10 passed**(기존 8 + 새 `test_approvals_409.py` ks · sw) |
| `make gate` | **PASS 22 · FAIL 1 · BLOCKED 1** — G-S04 · G-M09 · G-M11 · G-M13 · G-M14 PASS 유지, G-M04 FAIL = 위 compat 4건(행 키 시험을 새로 조였다 — 개발3 값이 들어오면 PASS 기대). BLOCKED = doctor-live(D-13) |
| `cd web && npm run build` | 성공 (271.6 kB js) |

### 6.4 요청 · 남은 일

- **개발3**: 6.1 표 값 기입(`tenants/ks.yaml` · `sw.yaml compat`) → G-M04 PASS. 선택 `print_setpoint.yaml warn_with`.
- **아키텍트**: D-131 경고 코드 enum(`anomaly_flag`) · tenant-contract §1 에 D-132 키 목록 · D-130 만료 기간 확인.
- 개발2 다음: D-81(호환 records → B12 행 함수) · 원천 records 행 키 순서 대조(`equip_code` 등) · 호환 bundle anomaly 가 rejected 일 때 false 대신 null 검토(QA2 관찰).

## 2차 §3 웨이브 A0-2 + A2 실측 (2026-10-13, 기준 커밋 5a51d2f · 태그 core-freeze-2 · 커밋 안 함)

### 한 일 (담당 파일만 — 코어 0줄)
- **G2-V01** `tests/test_vertical_slice_2.py` — (a) kd.quote: 실제 auth 로 DXF 업로드(영역 3 · BOM 4 = 원천 저장 도면) → 모델 없음 503 → labor_hours 학습 → stage → promote → decide(production) → 초안(사람 수정 SUPPORT 4→5, overrides 1) → 개정(원천 BOM — overrides 이력 유지) → 확정 요청(422 검토 없음 · 짧은 메모) → 대기 중 수정 409 → approver 결정 → 확정 스냅숏 → CSV(BOM · 품목 금액 · 수식 주입) → 확정 뒤 수정 · 재확정 409 → 새 모델 v2 승격 뒤에도 확정 금액 · 근거 불변. (b) pc.residual_review: 운영 모델 없음 → 항목 0 · 대기열 predict 404 type_route → 학습 → 승인 → 운영 예측 12 · 실측 8 → 일정 작업 → 항목 출처 test_split(시험 구간 = 스냅숏 시간순 끝 20% 안 · 학습/검증 행 0) · live_residual(실측 붙은 예측만, 잔차 = 실측 오프셋) · 임계값 = 검증 잔차 분위 → PATCH(operator · 다른 과제 approver 403 · approver 200) → 재검토 409 → 재실행 새 항목 0.
- **호환 4개사** — 등록부 `compat.routes` 객체 경로 + 플러그인 `tenants/{kd,pc,ot,krs}/compat.py`: kd 9 경로 · pc 5 · ot 10 · krs 6 (원천 `api/main.py` 를 읽어 옛 키 · 순서 · 문구 · 옛 오류 `{"detail": 문구}` · 422 목록). 기대값 `tests/compat_expected.yaml` kd · pc · ot · krs(파일:줄, differs 사유), 시험 `tests/test_compat.py` +46(원천 시험 `tests/test_api.py` 의 판정을 옮김 — kd 12 · ot 14 무효 입력 등).
- **e2e** `tests/e2e/test_console_ot_quote.py` — 화면 9 에서 ot 견적: 업로드(기하 규칙 + 분류 모델) → 인식값이 폼 초기값 → 초안(금액 = 서버 문자열) → 홀 수 수정 revision(overrides 표) → 확정 요청 → approver 결정 → 확정 · 잠금, 1024px 가로 스크롤 0 · 페이지 오류 0. 회사 화면 코드 0(등록부 · 팩 데이터만).

### 견적 대조 (kd 샘플 — 원천 저장 견적 `tests/fixtures/kd/source_quotes.json` QT-c32bb3ece4ad)
| 칸 | 원천 | 표준(API) | 비고 |
|---|---|---|---|
| 품목 금액 4 | 2,246,400 · 1,263,600 · 534,600 · 47,520 | 같음 | 공수 무관 |
| 소재비 · 외주비 | 4,092,120 · 0 | 같음 | 공수 무관 |
| 공수 · 가공비 · 가산 · 부가세 · 합계 | 58.146 h → 2,616,570 · 1,006,304 · 771,499 · 8,486,493 | 표준 모델 공수(4자리)로 원천 식(`quote.py:5-17`, 시험 안 Decimal 재작성)과 원 단위 일치 · 같은 확정 스냅숏에 원천 공수 58.146 을 넣으면 8,486,493 | 공수는 표준 재학습 값이라 다름 |

### 실측
| 항목 | 값 | 명령 |
|---|---|---|
| pytest | **946 passed · 3 skipped · 1 xfailed(D2-A2-01 strict) · 0 failed** | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| e2e | **23 passed** (+1 ot 화면 9) | `uv run pytest -q tests/e2e` |
| make gate | **PASS 23 · BLOCKED 1** | `make gate` |
| make gate2 | **PASS 39 · BLOCKED 2 · FAIL 0** — G2-V01 PASS(2 passed · 1 xfailed) · G2-C01 PASS | `make gate2` |
| 동결 경로 diff | **0줄 · 새 파일 0** | `git diff core-freeze-2 -- src/mlcore web/src/components std contracts \| wc -l` |

### 코어 결함(2차) · 요청 — decisions.md
- D2-A2-01 견적 CSV 합계 행 없음(`quotes.to_csv` 가 과제 `csv` 를 요약 거르개로) — strict xfail 로 표시.
- D2-A2-02 호환 optimize 가 1차 모양뿐 → pc · krs `/api/ml/optimize` 멈춤(현재 배합을 지어내야 함).
- D2-A2-03 표준 견적 수량 0 · 1.5 허용(옛 경로는 플러그인이 원천 범위로 422).
- D2-A2-04 개발3: kd `/api/cad/sample.dxf` · `/api/cad/demo` · ot `/api/data/demo` 는 팩 samples 파일이 생기면.
- D2-A2-05 호환 records 쿼리 변환 훅 없음 → krs supplier · q · state 필터 · 기본 limit 재현 불가.
- 게이트: `tests/e2e/test_console_ot_quote.py` 는 G2-S01 판정 파일 목록(gates/gate2.py)에 없다 — 아키텍트가 넣을지 결정.

## 2차 웨이브 C2 — QA 결함 수정 (코어 재진입, 2026-10-13, 기준 HEAD ad8e979 · 커밋 안 함) — 결정 D2-90 ~ D2-95

### 고친 것 (먼저 실패하는 회귀 시험 → 수정)
| 결함 | 수정 | 시험 |
|---|---|---|
| DEF-QA22-002 #31 (중대) | 과제 키 `line_limits`(원천 BomRow 규칙 · 범주 + material_aliases 정규화 · 모르는 키 422) + 코어 기본(스칼라 · 0 이상 · 견적식 계산 불가 422 `line_value` · 음수 금액 422 `negative_amount`). 500 0 · 음수 견적 0 | `tests/test_c2_dev2.py` 24건(kd 실제 팩 · BomRow 값 주입) |
| #30 코어 (QA22-001) | 추출기 자식 프로세스(forkserver) 실행 · 시간 20 s · 배열당 5,000 · 결과 4 MiB 상한 → 413 `time`·`items`·`result_bytes` · 원본 · 행 0 | 폭탄 추출기 시험 팩 4건 |
| QA22-003 | `safe_cell` 앞 공백 · 줄바꿈 뒤 수식(원천 `lstrip()` 의 상위 집합) · 화면 1 CSV 도 | 11건 |
| QA22-004 | 원본 NUL · 결과 NUL → 422 `nul`, INSERT 실패 시 원본 정리 | 2건 |
| QA22-006~008 | kd/ot 옛 견적 없는 도면 404 원천 문구 · kd/ot 개요 4자리 · warning 원천 문구 · krs 조성 합 문자열 422 · pc 배합 합 pydantic 모양 · kd 내보내기 파일 이름. 나머지 4건 `compat_expected.yaml differs` 사유 | `tests/test_compat.py::test_c2_*` 4건 |
| QA23-002 | `serve.catalog.model_required/uses_of/serving_ready` — health · overview · 화면 1 유형별 표시("모델 불필요 (규칙)" · 의존 과제 버전) | 1건 |
| QA23-004 · 005 | B09 목록 `can_decide` → 화면 8 결정 버튼 숨김 · 공용 409 문구 "이미 결정되었습니다" | 1건 + 계약 시험 2 갱신 |
| 개발1 요청 | `test_vertical_slice_2.py` 실측 시각 → now+1h (D2-80) | 통과 |

### 실측
| 항목 | 값 | 명령 |
|---|---|---|
| pytest | **1087 passed · 3 skipped · 1 xfailed(strict — eto line_limits 팩 값 대기) · 0 failed** | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| e2e | **23 passed** | `uv run pytest -q tests/e2e` |
| 웹 빌드 | 성공 (tsc -b + vite, 309.9 kB js) | `cd web && npm run build` |
| 개별 게이트 | G-M01 · G2-Q01 · G-M03 · G-S02 · G-S04 · G-S01 · G-M05 · G-M04 PASS. G-S06 FAIL 3 = QA 산출물(`outputs/qa2-1/*.out` · `qa2-2/probe_quote.py`) — 내 파일 아님 | `uv run python gates/check_*.py` |
| gate · gate2 · bench | 돌리지 않음(지시) | — |

### 요청
- **개발3:** `packs/eto/tasks/quote.yaml` 에 `line_limits`(값 = `tests/test_c2_dev2.py::KD_LINE_LIMITS`) → strict xfail 지우기 · 로더 `_validate_quote` 가 `serve.quotes.validate_line_limits` 호출 · 내가 고친 `api/routers/ops.py` overview · `screens/Overview.tsx` 확인(D2-94).
- **아키텍트:** 계약 3곳(task-contract §4 document_limits · §6.2 · §6.3 line_limits · immutable, api-contract §2 health/overview · B09 · B11 · §6.1) 확인 후 `core-freeze-2` 재태그.
