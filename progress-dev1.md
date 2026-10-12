# progress-dev1.md — 개발1 (데이터 · 학습)

## §1 공표 — `DataSource` · `Snapshot` · `TrainResult` 실제 시그니처 (웨이브 A0, 2026-10-12)

계약 `contracts/interfaces.md` §2 · §3 · §4 와 같다. 다른 점은 `decisions.md` §5 에 올렸다(D-47 ~ D-50).

### 데이터 — `mlcore.data`

```python
# mlcore/data/features.py  (계약은 mlcore/types.py — 파일 없음 · 소유 미정 → D-47)
@dataclass(frozen=True)
class FeatureDef:
    name: str; label: str; dtype: Literal["float", "int", "category", "bool"]
    unit: str | None = None; min: float | None = None; max: float | None = None
    values: tuple[str, ...] | None = None; default: Any = None
    required: bool = True; impute: Literal["median", "most_frequent", "none"] = "median"
    controllable: bool = False; step: float | None = None; std_name: str | None = None
def feature_defs(pack_features: dict[str, dict], names: Sequence[str], categories: dict | None = None) -> list[FeatureDef]

# mlcore/data/sources/base.py  (mlcore.data.sources 에서 다시 내보낸다)
SourceKind = Literal["synthetic", "csv", "gateway", "dataplatform", "mes"]
@dataclass(frozen=True) class SourceHealth: kind, connected, rows, ts_from, ts_to, lag_seconds, feature_coverage, missing_rates, has_target, message
@dataclass(frozen=True) class ReadSpec: tenant_id, task (TaskDef), features (Sequence[FeatureDef]), ts_from=None, ts_to=None, limit=None, columns_map={}
class DataSource(Protocol):
    kind: SourceKind
    def probe(self) -> SourceHealth: ...
    def read(self, spec: ReadSpec) -> pd.DataFrame: ...       # 표준 프레임
class SourceDisconnected(Exception): __init__(self, kind, reason)  # .kind · .reason

# 어댑터
SyntheticSource(pack_dir=None, module=None, *, seed: int, rows: int, categories=None, generate=None, source_ref=None)
SyntheticSource.from_call(call: registry.tenants.SynthCall)   # 학습 작업의 기본 길 — 과제 진입점 synth/<task>.py (D-53)
    # generate(rows, seed, *, categories) 를 부른다. 생성기 없으면 SourceDisconnected (합성 값을 지어내지 않는다)
CsvSource(path: str | Path, *, encoding: str = "utf-8-sig", units: dict[str, float] | None = None)
    # UTF-8(BOM 허용) · ReadSpec.columns_map(원천 열 → 팩 변수) · 단위 배수
make_source(src_cfg: dict, *, pack_dir, pack_meta: dict, categories: dict | None = None) -> DataSource
    # tenants/<t>.yaml sources.<name> 한 항목 → 어댑터 (synthetic · csv 만, 나머지 kind 는 SourceDisconnected("미구현"))

# mlcore/data/frame.py — 표준 프레임 (interfaces §2.1)
META_COLUMNS = ("tenant_id", "task_id", "entity_id", "ts", "group", "target", "_source", "_source_ref")
def standardize(raw: pd.DataFrame, spec: ReadSpec, *, kind: str, source_ref: str) -> pd.DataFrame
    # ts ← 'ts' 또는 task.time_key 열(naive 면 KST 부여) · target ← task.target.name · group ← task.group_key
```

### 스냅숏 — `mlcore.data.snapshot`

```python
@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str          # "snp_" + sha256[:16]
    tenant_id: str; task_id: str
    path: str                 # var/snapshots/<tenant>/<task>/<snapshot_id>.parquet
    sha256: str               # 열 이름 정렬 · 행 (ts, entity_id) 정렬 · 값 정규화 → 정규 CSV 바이트 SHA-256
    rows: int; ts_from: datetime | None; ts_to: datetime | None
    columns: tuple[str, ...]
    missing_rates: dict[str, float]
    ranges: dict[str, dict]   # 수치 {p1, p99} · 범주 {values}
    source_ref: dict; synthetic: bool
def content_sha256(frame: pd.DataFrame) -> str
def freeze(frame, *, tenant_id: str, task: TaskDef, source_ref: dict, synthetic: bool, base_dir: Path | None = None) -> Snapshot
def load(snapshot_id: str, *, base_dir: Path | None = None) -> pd.DataFrame     # 해시 재계산 → 다르면 SnapshotCorrupt
def record(snap: Snapshot, *, test: bool = False) -> None                       # mlp_snapshot INSERT (멱등, ON CONFLICT DO NOTHING)
class SnapshotCorrupt(Exception)
```

### 분할 · 누수 — `mlcore.train.split` · `mlcore.train.guard`(계약 §3 그대로)

```python
@dataclass(frozen=True) class SplitPlan: policy, train_idx, valid_idx, folds=(), boundaries={}
def choose_policy(task: TaskDef, rows: int) -> str
def plan(frame: pd.DataFrame, task: TaskDef, seed: int) -> tuple[SplitPlan, GuardedTest]
    # 인덱스는 frame 의 위치(iloc). 시험 인덱스는 GuardedTest 에만
```

### 학습 — `mlcore.train.trainer`

```python
@dataclass(frozen=True)
class TrainConfig:
    task: TaskDef; snapshot_id: str; seed: int; code_version: str
    candidates: tuple[str, ...]; candidate_params: dict[str, dict]
    def config_hash(self) -> str                 # 정렬 JSON SHA-256 (task.def_hash · seed · code_version · candidates · params; 스냅숏 제외 — DB UNIQUE 가 따로 묶는다)
    @classmethod from_task(task, snapshot_id, *, seed=None, code_version=None) -> TrainConfig

@dataclass(frozen=True) class MetricValue: value: float; baseline: float | None; delta_vs_baseline: float | None

@dataclass(frozen=True)
class TrainResult:
    run_id: str; status: Literal["succeeded", "failed"]
    champion: str | None
    valid_metrics: dict[str, dict[str, float]]
    selection_reason: str
    test_metrics: dict[str, MetricValue]
    beats_baseline: bool
    artifact_dir: str | None                     # var/artifacts/<tenant>/<task>/<run_id>/  (계약은 <version>/ — D-48)
    report: dict
    warnings: list[dict]
    ledger: list[dict]
    artifact_sha256: str | None = None           # 추가(계약 범위 안 최소) — 산출물 4파일 해시 묶음 (D-48)
    synthetic: bool = False                      # 추가 — 스냅숏의 합성 여부를 등록부가 받는다 (D-48)

class StandardTrainer:                            # Trainer Protocol 구현
    def __init__(self, *, features: Sequence[FeatureDef] | None = None, artifact_root: Path | None = None, frame: pd.DataFrame | None = None)
    def train(self, cfg: TrainConfig) -> TrainResult
def train(cfg: TrainConfig, **kw) -> TrainResult   # StandardTrainer(**kw).train(cfg)
calls: int                                        # 학습 호출 계측 카운터 (G-M06 "기동 후 0")
```

산출물(`artifact_dir`): `model.joblib`(sklearn Pipeline, 입력 = features 순서의 DataFrame) · `features.lock.json` · `env.lock` · `report.json`.
파일 쓰기 · 해시 · env.lock 은 개발2 `registry.artifacts.save_artifacts` · `features_lock` 를 그대로 쓴다(적재 대조와 같은 함수).
`features.lock.json` = 개발2 §1.4 모양 `{order, features:{name:{dtype, fill, p1, p99 | values}}, baseline, interval:{method, alpha, q}}`
+ `task_id · task_type · target · positive · clip · threshold(risk review_prob · anomaly 점수 임계) · contamination · score(predict | predict_proba[:,1] | -score_samples) · max_imputed · defined_values`.
학습 범위 · 보정값은 **학습+검증 구간**으로만 계산(시험 제외).

### 작업 — `submit` (계약은 `mlcore/train/` — 위치 D-49)

```python
# mlcore/data/jobs.py — API 가 import 해도 학습 코드가 따라오지 않게 data 쪽에 둔다
def submit(tenant_id: str, task_id: str, *, actor: str, source_role: str | None = None, seed: int | None = None, test: bool = False) -> str
    # 소스(기본 = 회사 mode 이름의 sources 항목) 읽기 → freeze → mlp_snapshot → mlp_train_run(queued). 같은 snapshot+config 면 기존 run_id
    # 실패: SourceDisconnected(503) · NoTarget(목표 없음) · TrainBusy(회사당 동시 1) · KeyError(켜지지 않은 과제)
def read_frame(tenant_id, task_id, *, source_role=None) -> (merged, task, frame, source_ref, synthetic)
# mlcore.train.trainer.submit 은 같은 함수를 다시 내보낸 것(interfaces §4 이름)
# mlcore/train/jobs.py
def execute(run_id: str, *, test: bool = False) -> TrainResult   # queued → running → succeeded|failed, report · log 기록
```

## §2 A0 실측 (2026-10-12)

| 항목 | 실측 | 명령 |
|---|---|---|
| 내 시험 | **68 passed** — test_data_sources 17 · test_data_snapshot 8 · test_split 20 · test_train_trainer 10 · test_determinism 9 · test_train_jobs 4 | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_data_*.py tests/test_split.py tests/test_train_*.py tests/test_determinism.py` |
| 전체 시험 | **160 passed** (개발2 · 개발3 포함), 16 s | `uv run pytest -q` |
| 스냅숏 해시 | 열 순서 · 행 순서 · 정수/실수 표기 · 시간대 표기가 달라도 같은 해시, 값 1e-9 변경 · 결측 1칸이면 다른 해시, 손상 파일 `SnapshotCorrupt` | `tests/test_data_snapshot.py` |
| 소스 | 팩 생성기(ks · sw) → 표준 프레임 720행 · 결측 24 · KST tz. sw `eval`(csv fixture) = `demo`(합성) 내용 동일. 미구현 3종 · 없는 생성기 · 없는 CSV 는 `SourceDisconnected`/`connected=False`(지어내지 않음) | `tests/test_data_sources.py` |
| 분할 | `time_60_20_20` 432/144/144 · train ts < valid ts < test ts · group 경계 교집합 0(그룹 7 · 40 · 333 · 시간상 섞인 그룹) · time_key 가 있으면 random 설정 무시 · 행 < 500 은 `time_cv5`(확장 창 5폴드 + 마지막 20%) | `tests/test_split.py` |
| 누수 계측 | 과제 6(ks 3 · sw 3) ledger = [final_eval(evaluate.py), report] · 위반 0 · 표본 내 평가 `InSampleEvaluation` · 학습기 안 금지 목적 접근은 `TestLeak` 로 올라옴 · **시험 구간 목표 ×3+100 · 변수 1e6 으로 바꿔도 챔피언 · 검증 지표 · 기준선 · q · features.lock 불변** | `tests/test_split.py` · `tests/test_train_trainer.py::test_test_segment_does_not_influence_anything_but_test_metrics` |
| 학습 지표 (시험 1회, 기준선) | ks.remaining_hours gbr MAE **5.568** (기준선 21.219) · R² **0.9199** · 구간 포함률 0.882 / ks.failure_24h rf_clf Brier **0.0576** (0.0586) · AUC **0.6444** · AP 0.1426 / sw.delta_e extra_trees MAE **0.557** (1.087) · R² **0.722** / sw.defect_risk gbc Brier **0.1261** (0.2051) · AUC **0.8686** · AP 0.7823 — 원천 보고값과 자리수 일치(source_inventory · D-52) | `tests/test_split.py` (`trained` 고정 장치) |
| anomaly | ks.sensor_ood flag_rate 0.160 (c 0.08, 이김) · sw.print_ood 0.167 (미달 → candidate 까지) — D-50 | 같은 곳 |
| 결정성 | 과제 6 × 2회 학습: 시험 예측 최대 차이 **0.0** · run_id · 챔피언 · 지표 · 산출물 모델 예측 동일. 소스 열 순서를 바꿔도 같은 예측 | `tests/test_determinism.py` |
| 작업 | submit → mlp_snapshot(720행 · synthetic) + mlp_train_run queued(seed 42) → 같은 요청 멱등 → execute succeeded(report jsonb) → 재실행 거부. eval 역할은 synthetic=false | `tests/test_train_jobs.py` |
| 개발2 연결 | `submit` → `serve.training.run_and_register` → `Registry.register` → v1 candidate(synthetic) → `load_artifacts` 해시 · env.lock 대조 통과 (ks.remaining_hours gbr · sw.delta_e extra_trees, 시험 DB, 뒤 정리) | 수동 1회 (시험 DB) |
| 학습 시간 | 과제당 0.2~0.6 s (720행, OMP 1) | |
| gate 변화 | **G-M05 FAIL → PASS** (C/D 학습기 없음 → test_split 20 passed) · **G-M06 FAIL → PASS** (A 학습기 없음 → test_determinism 9 passed · B 0건 · C test_registry 13 passed) · G-S05 사유 어댑터 0/5 → 2/5(정적 위반 0) · G-M01 PASS 유지(코어 73파일 위반 0). 합계 PASS 10 · FAIL 13 · BLOCKED 1 | `OMP_NUM_THREADS=1 uv run python gates/gate.py` |

주의: G-M06 A 의 "과제 8" 중 optimize 2 는 학습하지 않는다(`NotTrainable` 시험) — 재학습 대조는 학습 과제 6 이다.

## §3 남은 일 · 계약 불일치

- 아키텍트: D-47(types.py) · D-48(TrainResult 3필드 · run 폴더) · D-49(submit 위치 · source_role) · D-50(anomaly 기준선 규칙) 결정.
- 웨이브 A: gateway · dataplatform · mes 어댑터(G-S05) + `tests/test_source_contract.py` · `make train`(Makefile 은 아키텍트) · regression `last_value` 기준선(시계열) · risk 보정(sigmoid · isotonic, 검증 구간) · 후보당 무작위 탐색 20회(spec §5.2) · 이상치 제거 `outlier: iqr` · 작업자(`python -m mlcore.train.jobs --pending` 이 `run_and_register` 를 부를지 — D-57) · 화면 4 · `/runs/{id}`.
