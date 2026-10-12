# progress-dev2.md — 개발2 (등록부 · 추론 · 승인)

> 담당: `src/mlcore/registry/models.py` · `registry/artifacts.py`(interfaces §5 경로) · `serve/*` · `tasks/*` · `approval/` · `audit/` · `auth/` · `api/{main,middleware,errors}.py` · `api/routers/{models,predict,train}.py`
> 시험: `tests/test_registry.py` · `tests/test_approval.py` · `tests/test_trace.py` · `tests/test_predict_*.py` · 공용 도우미 `tests/_dev2.py`

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

`features` 는 `FeatureDef` 대신 **features.yaml 항목 dict**(병합 후, `values_from: tenant` 는 회사 `categories` 로 채움)다 — `mlcore/types.py` 가 아직 없어서다. `types.py` 가 생기면 그 `FeatureDef` 를 받도록 바꾼다(모양은 같다).

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
