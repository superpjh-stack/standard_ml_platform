# 계약 — 코어 인터페이스 (DataSource · Snapshot · SplitPolicy · Trainer · Registry · Predictor · Optimizer)

> **정본.** 출처: `spec.md` §4 · §5 · §6 · §7 · §8.1. 시그니처가 바뀌면 이 문서를 먼저 고친다(아키텍트).
> 소유 · 첫 공표: `DataSource` · `Snapshot` · `TrainResult` = 개발1(A0 초반, `progress-dev1.md` §1), `Predictor.predict()` · 응답 모델 = 개발2(A0 첫 작업, `progress-dev2.md` §1). 공표 시 이 문서와 다르면 `계약 불일치` 로 올린다.
> 모든 타입은 코어(`src/mlcore`) 안에 있고, **업종 · 회사 이름을 모른다**. 과제 · 변수 · 소스 정보는 전부 `TaskDef` · `FeatureDef` · `SourceSpec`(YAML 에서 로드)로 들어온다.

## 1. 공통 타입 (D-47 확정 — 소유자 파일에 둔다, `mlcore/types.py` 는 만들지 않는다)

한 파일은 한 사람만 고친다(goal §3.2). 주인 없는 `types.py` 를 두지 않고, 타입은 그것을 만드는 담당의 모듈에 둔다. 다른 모듈은 아래 위치에서 import 한다(모양은 아래 정의 그대로).

| 타입 | 위치 | 담당 |
|---|---|---|
| `FeatureDef` · `feature_defs()` | `mlcore/data/features.py` | 개발1 |
| `SourceKind` · `SourceHealth` · `ReadSpec` · `DataSource` · `SourceDisconnected` | `mlcore/data/sources/base.py` (`mlcore.data.sources` 에서 다시 내보냄) | 개발1 |
| `TaskDef` | `mlcore/registry/tenants.py` | 개발3 |
| `Status` | `mlcore/serve/contract.py` | 개발2 |
| `Stage` · `ModelRef` | `mlcore/registry/models.py` | 개발2 |
| `TaskType` | `std/task_types.yaml` 키(코드 상수 없음) — 형 표기가 필요하면 `str` | — |

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Sequence
import pandas as pd

TaskType   = Literal["regression", "risk", "anomaly", "optimize", "review_queue", "extract", "quote"]   # std/task_types.yaml
Status     = Literal["ok", "watch", "review", "out_of_range", "rejected", "needs_approval"]             # std/statuses.yaml
Stage      = Literal["candidate", "staging", "production", "archived"]
SourceKind = Literal["synthetic", "csv", "gateway", "dataplatform", "mes"]

@dataclass(frozen=True)
class FeatureDef:            # features.yaml 한 항목 (contracts/feature-contract.md)
    name: str; label: str; dtype: Literal["float", "int", "category", "bool"]
    unit: str | None = None; min: float | None = None; max: float | None = None
    values: tuple[str, ...] | None = None; default: Any = None
    required: bool = True; impute: Literal["median", "most_frequent", "none"] = "median"
    controllable: bool = False; step: float | None = None; std_name: str | None = None

@dataclass(frozen=True)
class TaskDef:               # 병합(팩 + 회사 덮어쓰기) 후 과제 정의 (contracts/task-contract.md)
    id: str                  # <tenant>.<task>
    pack_id: str             # <pack>.<task>
    type: TaskType
    raw: dict                # 검증된 YAML 전체
    def_hash: str            # 정렬 JSON 의 SHA-256
```

## 2. 데이터 — `mlcore/data/`

```python
@dataclass(frozen=True)
class SourceHealth:
    kind: SourceKind
    connected: bool                     # False 면 doctor 표시는 "미연결"
    rows: int | None
    ts_from: datetime | None; ts_to: datetime | None
    lag_seconds: float | None
    feature_coverage: float | None      # 과제 features 중 대응된 비율 0~1
    missing_rates: dict[str, float]
    has_target: bool | None             # False 면 "목표 없음"
    message: str                        # 사람이 읽는 사유(키 · 호스트 · DSN 값 금지)

@dataclass(frozen=True)
class ReadSpec:
    tenant_id: str
    task: TaskDef
    features: Sequence[FeatureDef]
    ts_from: datetime | None = None; ts_to: datetime | None = None
    limit: int | None = None
    columns_map: dict[str, str] = field(default_factory=dict)   # tenants/<t>.yaml feature_map (원천 열 → 팩 변수)

class DataSource(Protocol):
    kind: SourceKind
    def probe(self) -> SourceHealth: ...                     # 실패해도 예외를 삼키지 않는다 → connected=False + message
    def read(self, spec: ReadSpec) -> pd.DataFrame: ...       # 표준 프레임(§2.1). 실패 시 SourceDisconnected 를 올린다

class SourceDisconnected(Exception):                          # API 계층이 503 source_disconnected 로 바꾼다
    def __init__(self, kind: SourceKind, reason: str): ...
```

**읽기 전용 규칙(G-S05):** 어댑터 모듈에 `INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|COPY … FROM` SQL 문자열, `requests.post|put|patch|delete` · `httpx` 비 GET 호출, 쓰기 모드 `open(…, "w")` 가 0 이다(`gates/check_sources.py`). DB 어댑터는 연결 직후 `SET default_transaction_read_only = on` 을 건다. dataplatform 어댑터는 키당 5 req/s · 5,000/일 한도를 클라이언트에서 지킨다.

### 2.1 표준 프레임 열

`tenant_id` · `task_id` · `entity_id` · `ts`(tz 포함 KST) · `group`(선택) · `<features.yaml 변수>` · `target`(지도학습) · `_source` · `_source_ref`. 열 순서는 의미가 없고, 스냅숏 해시는 **열 이름 정렬 후** 계산한다.

### 2.2 스냅숏 (`mlcore/data/snapshot.py`)

```python
@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str                    # "snp_" + sha256[:16]
    tenant_id: str; task_id: str
    path: str                           # var/snapshots/<tenant>/<task>/<snapshot_id>.parquet
    sha256: str                         # 열 이름 정렬 · 행은 (ts, entity_id) 정렬 · 값 정규화 후 Parquet 바이트가 아니라 정규 CSV 바이트의 해시
                                        # 해시 규칙 v2 (D-87): 같은 (ts, entity_id) 가 겹치면 나머지 열 전체(열 이름 정렬)의 정규화 값으로 이어 정렬
                                        # (입력 행 순서 무관) · 머리줄 = `열이름:종류`(num · str · ts · null) · entity_id 없으면 ROW-n 을 내용 순서로.
                                        # Parquet 표지 mlp_hash_rule=v2, 표지 없는 기존 파일은 v1 로 검증해 읽는다
    rows: int; ts_from: datetime | None; ts_to: datetime | None
    columns: tuple[str, ...]
    missing_rates: dict[str, float]
    ranges: dict[str, dict]             # 수치 {p1, p99} · 범주 {values: [...]} — 학습 범위
    source_ref: dict; synthetic: bool

def freeze(frame: pd.DataFrame, *, tenant_id: str, task: TaskDef, source_ref: dict, synthetic: bool) -> Snapshot: ...
def load(snapshot_id: str) -> pd.DataFrame: ...          # 해시 재계산 → 다르면 SnapshotCorrupt
```

## 3. 분할 · 누수 계측 — `mlcore/train/split.py` · `mlcore/train/guard.py`

```python
@dataclass(frozen=True)
class SplitPlan:
    policy: Literal["time_60_20_20", "time_cv5", "stratified_60_20_20", "random_60_20_20"]
    train_idx: tuple[int, ...]; valid_idx: tuple[int, ...]    # time_cv5 는 folds 를 따로 둔다
    folds: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...] = ()
    boundaries: dict                    # 시간 경계 · 그룹 경계 기록

def choose_policy(task: TaskDef, rows: int) -> str: ...  # time_key 있으면 time_* 강제, rows < 500 이면 time_cv5 (std/split_policies.yaml)
def plan(frame: pd.DataFrame, task: TaskDef, seed: int) -> tuple[SplitPlan, "GuardedTest"]: ...
```

**계측 래퍼 (Phase 0 공표, `gates/check_leakage.py` 와 공유):** 시험 구간 인덱스는 `SplitPlan` 에 없다. `GuardedTest` 만 가지고 있고, 꺼낼 때마다 `AccessLedger` 에 목적과 호출 위치가 남는다.

```python
Purpose = Literal["final_eval", "report", "selection", "calibration", "interval", "threshold", "baseline", "queue"]
ALLOWED = {"final_eval", "report"}       # report = 시험 1회 평가 뒤의 순열 중요도 · 잔차 표 (spec §5.4)

class TestLeak(Exception): ...           # 금지 목적 접근 · final_eval 2회째 접근 · final_eval 전 report 접근

class AccessLedger:
    def record(self, purpose: Purpose, n_rows: int, where: str) -> None: ...
    def events(self) -> list[dict]: ...  # [{purpose, n_rows, where, order}]
    def violations(self) -> list[dict]: ...

class GuardedTest:
    def __init__(self, idx: Sequence[int], ledger: AccessLedger): ...
    def take(self, frame: pd.DataFrame, purpose: Purpose) -> pd.DataFrame: ...   # 금지 목적이면 기록 후 TestLeak
    def __len__(self) -> int: ...       # 길이 조회는 접근이 아니다
    # __iter__ · __getitem__ · __array__ 는 TestLeak — 인덱스를 직접 꺼낼 수 없다
```

`check_leakage` 는 (1) 래퍼 자체 시험, (2) 과제 8 각각의 fixture 학습을 래퍼 아래에서 돌려 `ledger.violations() == []` · `final_eval` 정확히 1회, (3) 정적 검사: `GuardedTest.take(` 호출 위치가 `train/evaluate.py` · `train/report.py` 뿐, `_idx` 직접 접근 0, (4) 표본 내 평가 픽스처(학습 구간 = 평가 구간)가 `InSampleEvaluation` 으로 거부되는지, (5) `time_key` 과제가 시간순 · `group_key` 경계를 지키는지(경계 양쪽 그룹 교집합 0) 를 본다. **시험 모드에서도 래퍼를 끄는 설정은 없다.**

## 4. 학습 — `mlcore/train/`

```python
@dataclass(frozen=True)
class TrainConfig:
    task: TaskDef; snapshot_id: str; seed: int; code_version: str
    candidates: tuple[str, ...]                 # std/candidates.yaml 이름
    candidate_params: dict[str, dict]           # 팩 기본 + 과제 덮어쓰기
    def config_hash(self) -> str: ...           # 정렬 JSON SHA-256 — 멱등 키

@dataclass(frozen=True)
class MetricValue:
    value: float; baseline: float | None; delta_vs_baseline: float | None   # spec §2.4 — 지표는 항상 이 세 값

@dataclass(frozen=True)
class TrainResult:
    run_id: str; status: Literal["succeeded", "failed"]
    champion: str | None                        # 후보 이름
    valid_metrics: dict[str, dict[str, float]]  # 후보별 검증 지표
    selection_reason: str
    test_metrics: dict[str, MetricValue]        # 시험 1회
    beats_baseline: bool
    artifact_dir: str | None                    # var/artifacts/<tenant>/<task>/<run_id>/ — 저장소 루트 기준 상대 경로 (D-48)
    report: dict                                # report.json 내용 (spec §5.4)
    warnings: list[dict]
    ledger: list[dict]                          # AccessLedger.events()
    artifact_sha256: str | None = None          # §5 산출물 해시 규칙(D-58). 등록부가 다시 재서 다르면 등록 거부
    synthetic: bool = False                     # 스냅숏의 합성 여부(정본은 mlp_snapshot.synthetic — 등록부는 DB 행을 쓴다)
    test_predictions: tuple[float, ...] = ()    # 시험 1회 예측(결정성 대조 G-M06 · 보고용). 선정 · 보정에 쓰지 않는다

class Trainer(Protocol):
    def train(self, cfg: TrainConfig) -> TrainResult: ...
    # 절차 고정: 학습 구간 후보 학습 → 검증 구간 선정 · 구간 · 보정 · 임계값 → 학습+검증 재적합 → GuardedTest.take("final_eval") 1회 → 보고
```

**산출물 폴더는 실행(run) 단위다(D-48).** 버전 번호 `v<n>` 은 등록부가 `register()` 때 붙이므로 학습 시점에 모른다. 그래서 학습기는 `var/artifacts/<tenant>/<task>/<run_id>/` 에 쓰고, 등록부는 그 경로를 `mlp_model_version.artifact_path` 에 적는다. 한 실행은 한 버전만 된다(`register` 는 같은 `run_id` 면 기존 버전을 돌려준다). 버전 → 폴더 대응은 등록부 행이 정본이다. spec §6.2 의 `<version>/` 표기와 다르다 → `decisions.md` D-48 정본 결함.

### 4.1 작업 접수 · 실행 (D-49 · D-57 확정)

```python
# mlcore/data/jobs.py — 학습 코드(mlcore.train)를 import 하지 않는다. API 가 이것만 부른다(G-M06 B 정적 검사).
def submit(tenant_id: str, task_id: str, *, actor: str, source_role: str | None = None,
           seed: int | None = None, test: bool = False) -> str: ...
    # 소스(source_role, 없으면 회사 mode 와 같은 이름의 sources 항목) 읽기 → snapshot.freeze → mlp_snapshot → mlp_train_run(queued) → run_id
    # 같은 snapshot + config 면 기존 run_id (run_id = "run_" + sha256(tenant|task|snapshot|config_hash)[:16] — 결정적, db-schema §ID)
    # 실패: SourceDisconnected(→ 503 source_disconnected) · NoTarget(→ 503 source_disconnected, detail.rule = no_target, 문구 "목표 없음")
    #       TrainBusy(→ 409 train_busy — 회사당 queued · running 1개, spec §5.5) · KeyError(켜지지 않은 과제 → 404 not_found)
# mlcore.train.trainer.submit 은 같은 함수를 다시 내보낸 이름이다(학습 쪽 호출용). API 는 mlcore.data.jobs 를 쓴다.

# mlcore/train/jobs.py — 학습 실행 (개발1)
def execute(run_id: str, *, test: bool = False) -> TrainResult: ...   # queued → running → succeeded | failed (report · log 기록). 등록하지 않는다
def pending(*, test: bool = False) -> list[str]: ...                  # queued run_id 목록(접수 순)

# mlcore/serve/training.py — 학습 성공 → candidate 등록의 유일한 접착부 (개발2)
def run_and_register(run_id: str) -> tuple[TrainResult, ModelRef | None]: ...   # execute → succeeded 면 Registry.register (항상 candidate)
```

**실행 주체는 API 밖 작업자 프로세스다.** `uv run python -m mlcore.train.jobs --pending`(또는 `<run_id>`)가 queued 를 하나씩 집어 **`serve.training.run_and_register(run_id)` 를 부른다** — `execute` 만 부르고 등록을 빠뜨리는 길은 두지 않는다. `make train TENANT= TASK=` 는 `submit` 뒤 같은 프로세스에서 `run_and_register` 를 부른다. API 프로세스는 접수(202 queued)까지만 하고 학습을 돌리지 않는다(배경 작업 · 스레드 없음 — G-M06 · G-M14 RSS). 시험(G-V01 등)은 작업자 대신 `run_and_register` 를 직접 부른다.

학습 프로세스는 `OMP_NUM_THREADS=1` 이다. 학습 함수는 **API 기동 경로에서 호출되지 않는다**(G-M06 계측: `train.calls` 카운터가 기동 후 0).

## 5. 등록부 · 산출물 — `mlcore/registry/models.py` · `mlcore/registry/artifacts.py`

```python
@dataclass(frozen=True)
class ModelRef:
    tenant_id: str; task_id: str; version: str; stage: Stage
    algo: str; snapshot_id: str; run_id: str; synthetic: bool
    artifact_sha256: str; trained_at: datetime
    # 덧붙임(기본값 있음): artifact_path: str · env_lock: dict · beats_baseline: bool · metrics: dict

class Registry(Protocol):
    def register(self, result: TrainResult, *, tenant_id: str, task_id: str) -> ModelRef: ...   # 항상 candidate
    def stage(self, tenant_id: str, task_id: str, version: str, *, actor: str) -> ModelRef: ... # candidate→staging: 기준선 이김 · 차단 경고 없음 · live 면 synthetic=False
    def get(self, tenant_id: str, task_id: str, version: str | None = None) -> ModelRef: ...     # None = production. 없으면 ModelNotReady
    def list(self, tenant_id: str, task_id: str) -> list[ModelRef]: ...
    def request_promotion(self, tenant_id: str, task_id: str, version: str, *, actor: str, action: Literal["promote", "rollback"], reason: str | None) -> str: ...
    # ↑ mlp_approval(pending) 만 만든다. stage 를 production 으로 바꾸지 않는다.

class ModelNotReady(Exception): ...         # → 503 model_not_ready
class ArtifactMismatch(Exception): ...      # → 503 model_artifact_mismatch
class InvalidTransition(Exception): ...     # → 409 invalid_transition (detail.rule = 규칙 이름 — D-54)

def save_artifacts(artifact_dir: str, model: object, report: dict, features_lock: dict) -> str: ...  # model.joblib · report.json · features.lock.json · env.lock → sha256
def load_artifacts(ref: ModelRef) -> "LoadedModel": ...  # SHA-256 · env.lock(패키지 버전) 대조, 다르면 ArtifactMismatch
def artifact_sha256(artifact_dir: str) -> str: ...
def current_env_lock() -> dict: ...
```

**산출물 규칙 (D-58 확정, `mlcore/registry/artifacts.py`):**
- 파일 4개 고정: `model.joblib` · `features.lock.json` · `env.lock` · `report.json`. 쓰기는 학습기가 `save_artifacts` 로만 한다(적재 대조와 같은 함수).
- `artifact_path` 는 **저장소 루트 기준 상대 경로**(`var/artifacts/<tenant>/<task>/<run_id>`). 절대 경로 · 홈 경로를 DB 에 적지 않는다.
- `artifact_sha256 = sha256( Σ "<파일 이름>\0<파일 sha256 hex>\n" )` — 4파일을 이름순으로 이어 붙인 바이트의 SHA-256. 폴더 이름은 해시에 들어가지 않는다.
- `env.lock = {"python": "<major.minor>", "packages": {numpy, pandas, scikit-learn, scipy, joblib: "<버전>"}}`.
- 적재 때 (1) 파일 해시 = 등록부 `artifact_sha256`, (2) `env.lock` 파일 = 등록부 `env_lock`, (3) `env.lock` = 현재 프로세스 `current_env_lock()` 를 모두 대조하고, 하나라도 다르면 `ArtifactMismatch`(detail.rule = `sha256` · `env_lock_registry` · `env_lock`, 파일 · 폴더가 없으면 `file_missing` · `dir_missing`). 등록 때도 (1) 을 다시 잰다(`sha256_at_register`).

## 6. 승인 — `mlcore/approval/`

```python
def decide(approval_id: str, *, actor: str, actor_role: str, approve: bool, reason: str | None,
           request_id: str | None = None) -> dict: ...   # → {approval_id, state, production_version}
class AlreadyDecided(Exception): ...                     # → 409 already_decided
```

**권한 판정 위치 (D-56 확정):** 회사 범위(다른 회사 승인 → 404 `not_found`)와 `own_task`(그 과제의 `approver_role` 담당이 아니면 403 `forbidden`)는 **API 계층**(`api/routers/models.py` + `auth.require_own_task`)이 `decide` 를 부르기 전에 본다 — 담당 목록 · 키 범위는 인증 계층의 지식이다. `decide` 는 역할(`approver` · `admin`)을 다시 보고, 아니면 거부한다(심층 방어). `request_id` 는 감사 행(`mlp_audit.request_id`)에 그대로 적는다. `decide` 를 부르는 곳은 이 API 경로 하나다(감시 · 작업자 · 스크립트는 부르지 않는다).

**`production` 을 쓰는 유일한 코드 경로다(G-M09 · `check_no_autopromote`).** 한 트랜잭션 안에서: `UPDATE mlp_approval SET state=… WHERE approval_id=%s AND state='pending' AND (expires_at IS NULL OR expires_at > now()) RETURNING …` — 0행이면 `AlreadyDecided`(→ 409) · 승인이면 기존 production → `archived` · 대상 → `production` · `mlp_audit` INSERT. 동시 2건이면 하나만 성공한다. 감시(monitor)는 `request_promotion` 까지만 부른다.

## 7. 추론 — `mlcore/serve/`

```python
@dataclass(frozen=True)
class PredictRequest:
    inputs: dict[str, Any]; entity_id: str | None = None; explain: bool = False; model_version: str | None = None

class Predictor(Protocol):
    def predict(self, tenant_id: str, task_id: str, req: PredictRequest, *, caller: str, channel: str = "api") -> dict: ...
    # 반환 dict 는 contracts/predict-contract.md §5 스키마를 만족한다. mlp_prediction 1행 INSERT 후 prediction_id 를 채운다.
    def predict_batch(self, tenant_id: str, task_id: str, reqs: Sequence[PredictRequest], *, caller: str) -> dict: ...  # ≤ 500

# 입력 검증 3단 — 순서 고정
def validate_format(inputs: dict, features: Sequence[FeatureDef]) -> None: ...   # 모르는 키 · NaN · Inf · 형 → InvalidInput(422)
def validate_bounds(inputs: dict, features: Sequence[FeatureDef]) -> None: ...   # min/max 밖 · 범주 values(또는 회사 categories) 밖 → OutOfBounds(422, detail.rule = min|max|values) — D-55
def impute(inputs: dict, features, lock: dict, max_imputed: int) -> tuple[dict, list[str]]: ...  # 필수 누락 · 한도 초과 → MissingRequired(422)
def range_check(inputs: dict, lock: dict) -> tuple[list[str], list[str]]: ...    # (out_of_range_fields, near_range_fields) — 학습 범위 p1/p99
```

유형별 추론부는 `mlcore/tasks/{regression,risk,anomaly,optimize}.py` 의 `TaskKind` 구현이다. `review_queue` · `extract` · `quote` 는 같은 인터페이스의 골격만 두고 `NotImplementedTaskType`(→ 501 `not_implemented`) 을 낸다.

```python
class TaskKind(Protocol):
    type: TaskType
    def score(self, model: "LoadedModel", frame: pd.DataFrame, task: TaskDef) -> list[dict]: ...  # 행별 prediction/probability/anomaly 조각
    def status(self, piece: dict, task: TaskDef, oor: list[str], near: list[str]) -> tuple[Status, list[dict]]: ...
```

## 8. 최적화 — `mlcore/tasks/optimize.py`

```python
@dataclass(frozen=True)
class OptimizeRequest:
    fixed: dict[str, Any]; current: dict[str, Any] | None = None; params: dict[str, float] | None = None; entity_id: str | None = None

class Optimizer(Protocol):
    def space(self, task: TaskDef, locks: dict[str, dict], params: dict) -> "SearchSpace": ...
    # 조절 변수(controllable: true): [학습 범위 p1, p99] ∩ [min, max] 를 step 간격으로. 학습 범위 밖 점은 만들지 않는다.
    # decision_vars(모델 입력이 아닌 결정 변수 — 예: 대기 시간): [min, max(또는 params 상한)] 를 step 간격으로.
    def optimize(self, tenant_id: str, task_id: str, req: OptimizeRequest, *, caller: str) -> dict: ...
    # 공간 ≤ search.max_points → grid, 아니면 random(seed 고정, max_points 개).
    # uses 과제의 production 모델로 일괄 예측 → formulas 계산 → 제약 평가 → 목적 · tiebreak 정렬 → 상위 5.
    # 충족 0 이면 on_infeasible=least_violation: violation 최소(동률이면 목적) + status=review.
    # 결과는 mlp_recommendation(needs_approval) 1행. 설비 · MES 에 쓰지 않는다.

def formula(row: dict, params: dict) -> float: ...   # 팩 formulas/<name>.py 의 순수 함수 모양 (spec §8.1)
```

## 9. 감시 — `mlcore/monitor/`

```python
def psi(expected: pd.Series, actual: pd.Series, *, bins: int = 10, categorical: bool = False) -> float: ...  # 수치 10분위(학습 스냅숏 기준 경계), 범주 빈도, 0 빈도는 1e-6 바닥
def run_daily(tenant_id: str, day: "date", *, retrain_source: str | None = None) -> list[dict]: ...
# mlp_monitor_daily 행. 재학습 후보 조건이면 data.jobs.submit(작업자가 run_and_register → candidate) →
# (D-77) 기준선을 이긴 candidate 만 registry.stage(actor="monitor", 감사 기록) → registry.request_promotion(action=promote, actor="monitor").
# 기준선 미달은 candidate 로 둔다. 감시가 할 수 있는 전이는 candidate→staging 과 승인 **요청**까지 — production 은 approval.decide() 만(G-M09).
# retrain_source 기본 = 회사 mode(D-80 가설). 같은 스냅숏이면 run_id 재사용 → 새 candidate 없음(지어내지 않는다).
```

PSI 세부(D-79): 경계 = 기대 분포(production 모델의 학습 스냅숏 전체) 10분위(선형 보간 · 결측 제외 · 중복 경계 제거) · 구간 (a, b] · 비율 바닥 1e-6 후 재정규화하지 않음 · 결측은 PSI 에서 빼고 결측률(기대 대비 %p)로 따로 · 운영 값 0건이면 nan(0 으로 꾸미지 않음) · 범위 밖 = 산출물 `features.lock.json` p1/p99.

## 10. 로더 — `mlcore/registry/packs.py` · `tenants.py`

```python
def load_pack(code: str) -> "Pack": ...            # pack.yaml · features.yaml · tasks/*.yaml 스키마 검증 (contracts/pack-contract.md)
def load_tenant(code: str) -> "Tenant": ...        # tenants/<code>.yaml + tenants/<code>/tasks/*.yaml 덮어쓰기 병합
def merge(pack: "Pack", tenant: "Tenant") -> dict[str, TaskDef]: ...   # 병합 규칙 5 위반 → RegistryRejected(rule, detail) — 기동 거부
```

**등록부 루트 `MLP_TENANTS_DIR` — 한 규칙(D-65).** 값 = 폴더 경로, `os.pathsep` 로 여러 개(호출 시점에 읽는다).
- 회사 하나를 읽을 때: 목록 중 `<code>.yaml` 이 있는 **첫 폴더**, 없으면 저장소 `tenants/`. 구현은 `registry.tenants.tenant_base(code)` = `data.jobs.tenants_base_for(code)`(같은 규칙, API · 작업자 · 감시 · 시험 공용).
- 새 회사를 만들 때 · 회사 목록(`all_codes`, seed): 목록의 **첫 폴더**(없으면 `tenants/`).
- 시험은 환경변수를 블록 안에서만 바꾸고 되돌린다(`monkeypatch.setenv` · `tests/_dev2.use_tenants_dir`) — 프로세스에 남기지 않는다.
