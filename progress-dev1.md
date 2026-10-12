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

## §1.1 공표 — 웨이브 A 추가 시그니처 (2026-10-12)

```python
# mlcore/data/jobs.py — 등록부 루트 주입 (이슈 #4)
TENANTS_DIR_ENV = "MLP_TENANTS_DIR"            # 값 = 폴더 경로, os.pathsep 로 여러 개
def tenants_base_for(tenant_id, tenants_base=None) -> Path | None   # 인자 → 환경변수 목록 중 <code>.yaml 이 있는 첫 폴더 → None(기본 tenants/)
def load_merged(tenant_id, tenants_base=None) -> Merged             # registry.tenants.load_and_merge 를 위 규칙으로
def read_frame(tenant_id, task_id, *, source_role=None, tenants_base=None)
def submit(tenant_id, task_id, *, actor, source_role=None, seed=None, test=False, tenants_base=None) -> str
    # 재시도 정책(D-49 후속, D-W1-05): 같은 스냅숏 · 설정의 failed 실행 → 그 행을 queued 로(started/finished/report/error 비움,
    # 이전 오류는 log 에 덧붙임, created_by = 새 요청자) + mlp_audit action=train.retry(같은 트랜잭션). 다른 queued · running 이 있으면 TrainBusy.
def run_view(run_id, *, tenant_id=None, test=False) -> dict | None  # GET /runs/{id} 본문(계약 키 + report 요약). 없음 · 다른 회사 → None(404)

# mlcore/train/jobs.py — 작업자 (D-57)
def execute(run_id, *, test=False, tenants_base=None) -> TrainResult   # 등록하지 않는다
def work(run_ids) -> list[dict]                                        # run 마다 serve.training.run_and_register — 한 run 실패가 다음을 막지 않음
# CLI: python -m mlcore.train.jobs --pending | <run_id> | --submit <tenant> <task> [--source-role R] [--seed N] [--test]  (실패 있으면 종료 1)

# mlcore/data/calibration.py — 보정 모델(산출물이 참조 — API 가 mlcore.train 을 import 하지 않게 data 쪽, D-W1-11)
class CalibratedModel(model, method, calibrator)   # predict_proba 양성 열만 보정, classes_ = 재적합 모델
def fit_calibrator(method, p_valid, y_valid) / apply_calibrator(method, cal, p)   # sigmoid(로짓 Platt) | isotonic
```

### §1.2 어댑터 5 (G-S05) — `mlcore.data.sources`

| kind | 클래스 | 등록부 키 (`sources.<name>`) | 읽는 방법 |
|---|---|---|---|
| synthetic | `SyntheticSource` | `{kind, seed?, rows?}` | 팩 생성기 |
| csv | `CsvSource` | `{kind, path, encoding?, units?}` | UTF-8(BOM) · 대응표 · 단위 |
| gateway | `GatewaySource.from_config(cfg, connect=None)` | `{kind, table, dsn_env, ts_column?, entity_column?, pivot?{key,value}, window?, agg?(mean·max·min·std), agg_by?, schema?}` | 읽기 전용 세션 SELECT · 세로→가로 · 시간 창 집계 |
| mes | `MesSource.from_config(cfg, connect=None)` | `{kind, tables[허용목록], dsn_env, join_on?, ts_column?, entity_column?, schema?}` | 허용목록 테이블만 · 대응표의 테이블만 읽어 `join_on` 왼쪽 결합 |
| dataplatform | `DataPlatformSource.from_config(cfg, transport=None, limiter=None)` | `{kind, url_env, key_env, view, path?(/v1/readings 가설), params?, page_size?, ts_column?, entity_column?}` | GET 만 · 헤더 x-api-key · 커서 페이지 · 5 req/s(기다림) · 5,000/일(실패) |

공통: DB 는 연결 직후 `SET default_transaction_read_only = on`(autocommit 세션), DSN · URL · 키는 환경변수 **이름**으로만, 실패는 `SourceDisconnected(kind, reason)`(사유에 값 없음 — 예외 종류 · HTTP 상태만), `probe()` 는 예외 대신 `connected=False` + 사유. `make_source(cfg, …, connect=, transport=)` 로 주입.

### §1.3 학습기 옵션 (과제 YAML — 전부 기본 꺼짐 · 키 없으면 A0 동작 그대로)

| 키 | 동작 | 누수 규칙 |
|---|---|---|
| (anomaly) | 임계값 = **학습 구간 모델의 검증 구간 점수 1-c 분위**(time_cv5 = 폴드 이어 붙임) → 재적합 모델에 그대로. 기준선 판정 밴드 = `std/metrics.yaml flag_rate.beats_band` | 시험 미사용 (D-50) |
| (regression · time_key) | 기준선 `train_mean` · `last_value`(time 정렬 직전 행 목표) 중 **검증 구간**에서 나은 쪽 | 시험 미사용 (D-W1-02) |
| `calibration: {method: sigmoid \| isotonic}` | 학습 구간 모델의 검증 확률로 보정기 → 재적합 모델에 씌움(`CalibratedModel`) | 시험 미사용 |
| `candidate_search: {후보: {파라미터: [값…]}}` | 후보당 무작위 탐색 ≤ `std/candidates.yaml search.max_random_trials_per_candidate`(20, 첫 시도 = 기본값, 시드 = 과제 seed), 검증 구간 선정 지표로 고름 | 시험 미사용 (D-W1-01) |
| `outlier: iqr \| {method: iqr, k, columns}` | 각 학습 구간에서만 Q1−k·IQR ~ Q3+k·IQR 경계를 재고 그 구간에서만 뺀다(기본 열 = 수치 변수 + regression 목표). 건수는 `report.outliers` | 검증 · 시험 행 그대로 |

분할: `random_60_20_20` · `stratified_60_20_20` 도 `group_key` 를 지킨다(그룹 단위, D-W1-08), `time_cv5` 폴드 경계도 그룹을 넘지 않는다(D-W1-07).

## §3 웨이브 A 실측 (2026-10-12, 커밋 7d583cf 위 작업 트리)

| 항목 | 실측 | 명령 |
|---|---|---|
| 내 시험 | **114 passed** (A0 68 → +46: test_source_contract 18 · test_train_wave_a 22 · test_train_worker 6) | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_data_*.py tests/test_split.py tests/test_train_*.py tests/test_determinism.py tests/test_source_contract.py` |
| 전체 시험 | 파일 단위 전부 통과. **한 세션 전체 실행은 31 failed · 7 errors / 334 passed** — 21건이 `MLP_TENANTS_DIR` 해석 충돌(D-W1-06 · 이슈 #5, 개발2 · 개발3 파일), 나머지는 다른 담당의 진행 중 시험(B08 `/runs` 라우트 미연결 · 호환 반올림) | `OMP_NUM_THREADS=1 uv run pytest -q` |
| anomaly (D-50) | ks.sensor_ood flag_rate **0.1389** · sw.print_ood **0.1458** (c 0.08, 밴드 0.04~0.16) → **둘 다 beats_baseline=True** (이전 0.160 · 0.167 미달). 임계값 ks 0.5614 · sw 0.5703 = 학습 구간 모델 검증 점수 0.92 분위와 일치 · 시험 구간을 바꿔도 불변 · 밴드를 YAML 에서 [5,6] 으로 바꾸면 False | `tests/test_train_wave_a.py` |
| 기존 과제 지표 | 변화 0: ks.remaining_hours MAE 5.568(21.219) · R² 0.9199 / ks.failure_24h Brier 0.0576 · AUC 0.6444 / sw.delta_e MAE 0.557(1.087) / sw.defect_risk Brier 0.1261 · AUC 0.8686 — 기준선은 모두 train_mean · 양성률(last_value 는 검증에서 짐) | scratchpad 측정 · `tests/test_split.py` |
| 분할 정책 4 누수 | 4 정책 각각: 겹침 0 · 합집합 = 전체 · (시간) 학습+검증 < 시험 · (무작위) 60/20/20 ±1% · (층화) 양성률 ±0.02 · 시험 구간 목표 · 변수를 바꿔도 챔피언 · 검증 지표 · 기준선 · 구간 · 보정 · 임계값 · 탐색 · lock 불변 · ledger = [final_eval, report]. group_key 경계 교집합 0(무작위 · 층화 · time_cv5 폴드) | `tests/test_train_wave_a.py` |
| last_value | 무작위 걸음 목표 → 검증에서 last_value 선택, 시험 기준선 MAE = 손 계산 \|y_t − y_(t−1)\| 평균 · 독립 행이면 train_mean · 비시계열은 비교 없음 | 같은 곳 |
| 보정 | sigmoid · isotonic: fit_on valid, n = 검증 행 수, 산출물 `CalibratedModel`, 확률 합 1 · [0,1], 시험 구간 바꿔도 보정기 불변 | 같은 곳 |
| 탐색 | 격자 100 → 20개(첫 = 기본값) · 시드 고정 재현 · 작은 격자는 전부(ridge 9 · extra_trees 13) · 같은 입력 → 같은 탐색 · 예측 · 비지도는 `search_skipped` | 같은 곳 |
| outlier iqr | 학습 구간 이상치 15 → 폴드 · 재적합에서 ≥ 15 제거, 시험 행 수 그대로, 끔 대비 시험 MAE 개선, 시험 구간 극단값은 경계 · 제거에 안 들어감 · 모르는 방법은 failed | 같은 곳 |
| 어댑터 (G-S05) | 5/5 · 정적 위반 0. MES 사본(ks 3 테이블 · sw 3 테이블, 등록부 대응표 모양): 읽은 뒤 원천 행 수 diff **0**, 읽은 행 = 720, 값 = fixture CSV, ks 는 목표 원천 미확인이라 `목표 없음`. 읽기 전용 세션에서 DELETE → `ReadOnlySqlTransaction`. 허용목록 밖 · 결합 키 없음 → `source_disconnected`. Gateway 세로 형식 240행 → 1시간 창 평균 = pandas 손 계산. dataplatform 가짜 전송: 3 페이지 · GET 만 · 키는 헤더(URL 에 없음) · 12 요청에 2회 대기 · 일 한도 5 초과 실패 · HTTP 500/연결 오류 사유에 주소 · 키 없음. 등록부 실 원천 6항목(ks · sw × train · gateway · actuals) → `SourceDisconnected`, `POST …/train {source_role: train}` → 503 `source_disconnected` 봉투 · 실행 행 0 | `tests/test_source_contract.py` |
| 작업자 · 재시도 | `--submit`/`<run_id>` → run_and_register → candidate · `run_view` 계약 키 · 다른 회사 None · failed 재접수 → queued + `train.retry` 감사 1행 · 다른 과제 queued 면 TrainBusy · 재실행 succeeded → candidate | `tests/test_train_worker.py` |
| 등록부 루트 | `load_and_merge` 를 감싸지 않고 `MLP_TENANTS_DIR` 만으로 임시 회사 학습 · API 학습 요청이 돈다 | 같은 곳 · `test_source_contract::test_train_api_returns_source_disconnected_envelope` |
| 화면 4 | `web/src/screens/Models.tsx` — 모델 버전 표(단계 · 기준선 배지 · 합성 배지) · 선택 버전 시험 지표 대 기준선 + 운영 버전 비교(없으면 "운영 모델 없음 (model_not_ready)") · 학습 접수 · 실행 검증(후보별 검증 지표 · 선정 사유 · 기준선 비교 · 구간/임계값/보정/이상치 · 순열 중요도 막대 · 잔차 분위 · 범주별 오차 · risk 보정 곡선 SVG · 경고). 공용 컴포넌트(개발2)만 사용. `tsc -b` 통과 · `vite build` 통과. `/runs/{id}` 라우트가 아직 없어 실행 검증 칸은 404 를 그대로 보인다(D-W1-04) | `cd web && npm run typecheck` |
| gate | PASS 11 → **18** (개발1 몫: **G-S05 FAIL → PASS**, G-M05 · G-M06 · G-V01 유지). G-S03 은 화면 4 `_placeholder` 해제(1·6 은 개발3). FAIL 5: G-S03 · G-S04 · G-M04 · G-M11 · G-M14 | `OMP_NUM_THREADS=1 uv run python gates/gate.py` |

## §4 다른 담당에 대한 요청 (decisions.md §6)

- 개발2: `GET /api/v1/runs/{run_id}` 라우트(`run_view` 호출, D-W1-04) · `models` 항목에 `run_id` · failed 재접수 응답을 202 로(D-W1-05) · `tests/_dev2.py::use_tenants_dir` 환경변수 복원(D-W1-06) · `test_vertical_slice.py` 머리 주석의 D-57 우회 문구 정리.
- 개발3: `registry.tenants.tenants_dir()` 를 회사 단위 목록 검색으로(D-W1-06 · 이슈 #5) · 원천 DB 익명화 사본 생성(D-W1-10) · 어댑터 등록부 키(join_on · ts_column 등)는 원천 확인 뒤.
- 아키텍트: 과제 키 `outlier` · `candidate_search`(D-W1-01) · 시계열 기준선 선택 규칙(D-W1-02) · 어댑터 키(D-W1-03) · `/runs` 본문 · `models.run_id`(D-W1-04) 계약 반영, Makefile `train` · `worker`(D-W1-12).

## §5 남은 일

- `/runs/{id}` 가 붙으면 화면 4 를 실제 API 로 띄워 확인(1024px), e2e(QA3).
- running 에서 죽은 작업(작업자 비정상 종료) 회수 정책 — 지금은 손으로 failed 처리 뒤 재접수.
- 시계열 결합(`join: {on, window, agg}` — spec §4.2)은 아직 없다(gateway 창 집계만).
- 원천 DB 사본이 생기면 `test_source_contract` 를 그것으로.

## §6 웨이브 C — QA1 결함 수정 실측 (2026-10-12, 기준 9d2febc 위 작업 트리 · 커밋 안 함)

회귀 시험 `tests/test_qa1_regressions.py` 23개 — QA 재현 스크립트(`outputs/qa1/lv_flip.py` · `group_probe*.py` · `guard_bypass_probe.py` · `snapshot_hash_probe.py` · `source_probe.py`)를 시험으로 옮겼다. **고치기 전 16 failed / 7 passed → 고친 뒤 23 passed.**

| 결함 | 처리 | 회귀 시험 | 실측 |
|---|---|---|---|
| DEF-QA1-001 #8 | last_value 기준선을 분할 **뒤** 재적합 구간(학습+검증) 행만으로 잇는다(`trainer.last_value_lag`). 시험 기준선은 final_eval 로 받은 시험 행 + 재적합 구간 | `test_last_value_lag_uses_only_given_rows` · `test_last_value_baseline_ignores_test_targets` · `test_lv_flip_probe_no_longer_flips_baseline` | 시험 목표 +500~5000 교란: `baselines_compared.valid` · 기준선 종류(last_value) 같음 · 시험 지표만 변화. QA lv_flip 배치(60그룹 무작위)는 두 실행 모두 `split_time_group_conflict` 로 거부 — 뒤집힘 0 |
| DEF-QA1-002 #9 | 그룹 블록 재정렬 제거, 시간순 배열에서 그룹 · 같은 시각을 넘지 않는 위치로만 자른다. 못 자르면 `SplitRefused(code="split_time_group_conflict")` → failed (D-85, 개발1 제안 · 아키텍트 확인 요청) | `test_interleaved_groups_refuse_time_split[600·300]` · `test_grouped_time_split_is_strictly_chronological` (6) · `test_split.py::test_interleaved_groups_refuse_instead_of_losing_time_order` | 학습 · 검증 행 중 시험 최초 시각보다 늦은 것 0(QA 585/600 → 0). `report.error.code` · warnings[0].code · `GET /runs/{id}` warnings 코드 같음 |
| DEF-QA1-008 | 위 자르는 위치 규칙에 같은 시각 묶음 불가분 포함(시험 · 검증 · time_cv5 폴드) | `test_same_timestamp_rows_never_straddle_a_boundary` (3) | 3행/시각 1002행: 학습∩검증 시각 0 · 검증∩시험 0(QA 1 · 1) |
| DEF-QA1-006 | `GuardedTest` `__slots__` · copy/deepcopy/pickle 거부 · final_eval 1회 ledger 단위 · overlaps 래퍼당 1회. `gates/check_leakage.py` 정적 우회 패턴(D-86 — gates 수정 사유 기록) | `test_guard_hides_index_from_vars_and_copies` · `test_guard_final_eval_once_per_ledger_and_overlaps_once` · `test_leakage_static_check_flags_bypass_patterns` | 래퍼 자체 시험 14 → **20/20** · 정적 위반 0 · 9개 우회 문구 전부 검출 |
| DEF-QA1-007 | 해시 규칙 v2(중복 키 행 전체 정렬 · 머리줄 `열:종류` · ROW-n 내용 순서) · 기존 v1 파일 호환 검증 (D-87) | `test_hash_stable_for_duplicate_key_rows_in_any_order` · `test_hash_distinguishes_numeric_and_string_columns` · `test_hash_stable_when_source_has_no_entity_id` · `test_legacy_snapshot_files_still_load` | QA 실패 3건 → 0. 기존 var/snapshots 941개 전부 로드. **스냅숏 ID 는 바뀐다**(예 ks.remaining_hours `snp_9c4da71a20764ded`) → 다음 학습은 새 run |
| DEF-QA1-009 | 조회 · 행 수를 명시 `SET TRANSACTION READ ONLY` 트랜잭션으로 · 선택 키 `read_role` → `SET ROLE` · probe 에 쓰기 권한 경고 (D-88) | `test_reads_run_in_read_only_transaction_even_if_session_default_is_off` · `test_read_role_and_write_privilege_warning` | 세션 값을 끄고 쓰기 함수를 부르는 뷰를 SELECT → `source_disconnected` · 원천 쓰기 0. 소유자 계정 probe = "경고: 쓰기 권한 있는 계정 …" |
| D-68 #7 | `test_source_contract.py` 가 `tests/fixtures/{ks,sw}/source_db.sql` 을 임시 스키마에 적재해 읽는다 | `test_source_contract.py` 18 | 18 passed · 행 수 diff 0 |

| 확인 | 결과 | 명령 |
|---|---|---|
| 전체 시험 | **452 passed · 3 skipped · 4 failed** — 실패 4는 모두 `tests/test_compat.py`(optimize 옛 행 키 · overview `products` · sw optimize `anomaly`) — 개발2 · 개발3 가 동시에 고치는 중인 파일(tasks/optimize.py · compat · tenants/*.yaml · compat_expected.yaml, 이 회전 중 수정 시각 확인). 내 파일 변경 전 기준선은 381 passed · 0 failed. 개발1 시험 전부 통과 | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| gate | G-M05 PASS(A 20/20 · B 0 · C/D test_split 20) · G-M06 PASS(determinism 9 · registry 13) · G-S05 PASS(5/5 · 정적 0 · 18) · G-M12 PASS(과제 8 · 행 일치 100%). 합계 PASS 21 · FAIL 2(G-M04 test_compat 4 · G-M13 — 개발2 진행 중, 직후 test_optimize 단독 11 passed) · BLOCKED 1 | `make gate` |
| 이관 지표 | 변화 0 — ks.remaining_hours MAE 5.5683 · RMSE 6.9793 · R² 0.9199 / ks.failure_24h Brier 0.0576 · AUC 0.6444 · AP 0.1426 / sw.delta_e MAE 0.5569 · RMSE 0.7088 · R² 0.7222 / sw.defect_risk Brier 0.1261 · AUC 0.8686 · AP 0.7823 / flag_rate ks 0.1389 · sw 0.1458. 분할 432/144/144 · `cut_moved` 없음 | scratchpad 스크립트(read_frame → StandardTrainer) |

남은 일: D-85 아키텍트 확인(거부 대 계약 예외) · interfaces §2.2 해시 v2 문구 · tenant-contract `read_role` 키(아키텍트) · 실 계정 SELECT 전용 역할(사람, D-13) · 기존 ml_db 등록 모델은 v1 스냅숏 ID 그대로(재학습하면 새 run).

## §7 2차 웨이브 P — 개발1 (2026-10-13, 기준 커밋 283dd31 위 작업 트리 · 커밋 안 함)

### §7.1 공표 — 대기열 학습 측 · 모델 추출기 (다른 담당이 부르는 시그니처)

```python
# mlcore/train/review.py — 항목 초안만(DB 쓰기 · item_id · state 는 B09 개발2 · 일정 작업 개발3)
ORIGINS = ("test_split", "live_residual"); ITEM_KEYS = (task, entity_id, prediction_id, model_version, predicted, actual,
                                                        residual, rule, threshold, reason, origin)
class QueueLeak(TestLeak)                       # 학습 · 검증 · 표본 내 출처, quantile_from ≠ valid, 과제가 안 켠 출처
parse_rule(rule) -> (kind, value)               # {abs_residual_ge: x≥0} | {top_quantile: 0<q<1} 정확히 하나 — 아니면 ValueError
threshold(rule, run_report=None, *, quantile_from="valid", ledger=None) -> {rule, value, from, n, q}
from_run(run_report, rule, *, task_id, model_version, origins, quantile_from="valid", max_items=50, reason=None, ledger=None) -> [item]
from_live(pairs, rule, *, task_id, origins, run_report=None, quantile_from="valid", max_items=50, reason=None, ledger=None) -> [item]
live_pairs(conn, tenant_id, uses_task_id, *, version=None, since=None) -> [{prediction_id, entity_id, model_version, predicted, actual}]
residuals(predict, frame, *, fit_idx, score_idx, ledger=None) -> [row]   # 재적합 구간과 겹치면 InSampleEvaluation(평창식)
# run 보고서(= mlp_train_run.report) 새 키 queue_residuals: {origin, source: final_eval, test: [{entity_id, ts, actual,
#   predicted, residual}], valid_abs, valid_rows, valid_sha256} — regression · risk 만. GET /runs/{id} 는 요약(행 수)만.

# mlcore/data/taskview.py — extract 학습 보기
learn_view(task) -> TaskDef     # model: 블록 → features · candidates · candidate_params · split · target{name: model.target|label} · classes
# 학습기: TRAINABLE += extract(model: 블록 있을 때만, 규칙만이면 NotTrainable). test_metrics = macro_f1 · accuracy(+ majority_class 기준선),
#   보고서 extract_metrics = {labels, macro_f1, accuracy, class_f1, confusion_matrix{labels, matrix}, baseline{class_f1, …}}
#   model.joblib = Pipeline.predict(X) → 클래스 이름(str), features.lock: task_type extract · classes · labels · baseline(최빈 클래스)
#   labels: none → failed labels_none · report {labels: none, metrics: null} (시험 접근 0)
# mlcore/train/metrics.py
extract(y, pred, classes) · extract_detail(y, pred, classes) · extract_eval(pred, truth|None, classes, *, labels) -> {labels, metrics|None}
```

guard 변경(F13-1): 인덱스는 클로저(slot 없음) · 모르는 속성 조회는 ledger `getattr:<이름>` 후 TestLeak · `SplitPlan.boundaries` 에 `test_ts` 없음 →
`GuardedTest.bounds()`(final_eval 뒤에만) · FORBIDDEN += `queue_scoring`. 1차 보고서 모양은 그대로(`split.boundaries.test_ts` 는 보고서에 남는다).

### §7.2 실측

| 항목 | 실측 | 명령 |
|---|---|---|
| G2-R01 | **PASS** — `tests/test_review_queue.py` 31 passed (시험 DB 끝까지 1 포함) · check_leakage PASS | `make gate2` |
| 대기열 시험 내용 | 시험 잔차 = final_eval 행 그대로 · ledger `[final_eval, report]` · 검증 잔차 = 학습 구간 모델 독립 재계산 일치 · \|잔차\| ≥ 4 포함(≥) · 상위 10% = 검증 분위(시험 분위와 다름) · 시험 구간 교란에 임계값 불변 · 출처 6종 거부 + ledger `queue_scoring` · quantile_from 5종 거부 · 평창식 4변형(전체 재적합 같은 데이터 · 재적합 모델로 검증 행 · 보고서 위조 행/분위 · ledger 없음 · source 위조) 거부 · 운영 잔차 prediction_id 필수 · DB jsonb 보고서 · live_pairs SQL | `uv run pytest -q tests/test_review_queue.py` |
| extract 모델 학습 | `tests/test_extract_model.py` 12 passed — 층화 960/320/320(클래스별 240/80/80) · 검증 macro-F1 선정 · 균형 4클래스 기준선 0.1(손 계산) · 불균형 최빈 클래스 · sklearn 독립 재계산 일치 · 시험 설명자 교란에 선정 불변 · labels none 지표 null · 모르는 클래스 failed · 결정성 | `uv run pytest -q tests/test_extract_model.py` |
| F13-1 | **해결** — `tests/test_guard_bypass_r2.py` 5 passed (실행 4종 차단 + 정적 12사례 · 오탐 0 · src 위반 0). QA-R2 재현 스크립트: 여집합만 실행 시 복원 가능(정적이 잡음, 원리상 막을 수 없음 — D2-41) · 나머지 PASS | `PYTHONPATH=src:. uv run python outputs/qa-r2/qa1/guard_bypass_r2.py` |
| 화면 7 | `web/src/screens/Sources.tsx` + `screens/index.ts` 7번 행 · e2e `tests/e2e/test_console_sources.py` 4 passed(ks · sw — doctor 표 = API · 스냅숏 행 · sha · 합성 = models/runs · 1024px 가로 스크롤 0 · viewer 403 그대로) · 화면 4 에 extract 클래스별 F1 · 혼동행렬 | `uv run pytest -q tests/e2e/test_console_sources.py` · `npx tsc --noEmit` |
| 전체 시험 | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` **624 passed · 8 failed · 3 skipped** — 실패 8 은 전부 다른 담당 진행 중: `test_api_contract::test_phase2_routes_are_501` 7(개발2 B09~B11 구현 → 1차 501 시험) · `test_predict_validation::test_reject_policy…` 1(개발3 F20-4 덮어쓰기 키 검사 R1 이 `out_of_range` 거부). 개발1 시험 실패 0 | 이번 회전 |
| make gate (1차) | PASS 20 · FAIL 3 · BLOCKED 1 — FAIL 3 은 개발2 진행 중 파일: G-S06(`tests/test_quote.py` 호스트 'x') · G-M01(`tasks/dxf.py` · `serve/documents.py` · `api/routers/phase2.py` 의 'kd') · G-M09(`api/routers/phase2.py:54` decide 호출처 2). G-M05 PASS(래퍼 자체 시험 20→21 — queue_scoring) | `make gate2` 1차 절 |
| make gate2 | 합계 PASS 24 · FAIL 15 · BLOCKED 2. **G2-R01 FAIL → PASS** · G2-H01 열림 15 → 6(F13-1 은 개발1 몫) | `make gate2` |

### §7.3 요청 (decisions.md D2-41~D2-44)

- 아키텍트: D2-41 check_leakage 패턴 7행 추가(사유 기록) 확인 · D2-42 interfaces §3 `Purpose` 에 `queue_scoring` · D2-44 task-contract §6.2 `model.target`(라벨 열 이름) 키 추가 여부.
- 개발2(B09): test_split 항목 = `review.from_run(GET run 보고서, 과제 rule, origins…)` → mlp_review_item INSERT(version = 모델 버전 · rule · threshold 채움). 추출기 model 은 `model.joblib.predict(X[order])` → 클래스 이름.
- 개발3: 일정 작업 live_residual = `review.live_pairs` → `review.from_live(…, run_report=production run 보고서)` · 같은 prediction_id 1회. `monitor.daily.live_performance` 는 extract(macro_f1)에서 NotImplementedError — extract 는 실측 성능 대상 밖으로 거를 것. doctor `_probe_fixture` 가 extract 과제 변수를 `task.raw["features"]` 로 읽는다 — `mlcore.data.taskview.learn_view(task)` 를 거칠 것. 팩 `rollform-quote` 객체 분류 합성 생성기 라벨 열 = `label`(또는 `model.target`).
- CSV 업로드 API 가 계약에 없다 — 화면 7 은 등록된 csv 소스만 보인다(지어내지 않음).

### §7.4 남은 일

- A2: 팩 `solder` · `kimchi` 학습 과제 · 4개사 이관 재현(`migration/reproduce.py`) — pc 재측정 값 병기(D2-02) · krs IQR 학습 구간(D2-03).
- ot 실데이터(1,600 설명자 합성) 로 extract 학습은 팩 생성기가 생기면 G2-E01 · 이관 대조에서.

## §8 2차 웨이브 A2 — 개발1 (2026-10-13, 기준 5a51d2f · 태그 core-freeze-2 위 작업 트리 · 커밋 안 함)

### §8.1 한 일 (시험 먼저 — 각 파일 처음 실행 FAIL 확인 뒤 구현)

| 항목 | 파일 | 내용 |
|---|---|---|
| 팩 solder | `packs/solder/{pack,features,baselines}.yaml` · `synth/{solder_lots,joint_strength}.py` · `formulas/material_cost.py` · `tasks/{joint_strength,recipe_optimize,residual_review}.yaml` · `tests/test_solder_formulas.py` | 변수 8(sn · ag · cu · sb · flux % · 온도 · 혼합 분 · 공급사 `values_from: tenant`, 중립 S1~S3) · 생성기 = 원천 `make_sample_data()` RNG 순서 그대로(효과는 목록 위치) · joint_strength 후보 5(원천 하이퍼파라미터) · `outlier: iqr` 1.5 · `input_rules` 조성 합 99.9~100.1 · recipe_optimize derived `sn_pct` · random 5,000 · `max_cost` optional · 비용 지수 최소 · 목표 강도 제약 · residual_review `abs_residual_ge: 4.0` |
| 팩 kimchi 나머지 | `packs/kimchi/tasks/recipe_optimize.yaml` · `formulas/material_cost.py` · `pack.yaml` tasks 3 · `sensory_score.yaml` `input_rules` 98~102 · `baselines.yaml` recipe_optimize 행 · `tests/test_kimchi_formulas.py` · README | derived `seasoning_pct` · random 3,500 · 제약 `scale` 3 · 5 · least_violation |
| 이관 재현 | `migration/reproduce.py` `run_phase2` · `--phase2 [--tenants-base]` → `outputs/reproduce-krs-pc.json` | 원천 절차 재현(원천 코드를 읽어 다시 씀 · 실행 0) + 표준 값(StandardTrainer · `train.review` · 코어 `Optimizer.space`) 나란히, 행 6 · `compare` · `diff_pct` · `within_10pct` · `reason` |
| 시험 | `tests/test_solder_pack.py` 13 · `tests/test_kimchi_optimize.py` 4 · `tests/test_reproduce_krs_pc.py` 8 · 팩 시험 4 | 아래 실측 |

### §8.2 원천 대조 실측 (같은 합성 시드 — `migration/reproduce.py --phase2`, 2.9 s)

| 과제 | 원천 절차 재현 | 표준 | 차이 | 대조 · 사유 |
|---|---|---|---|---|
| krs.joint_strength | svr · 80/20(568/142, IQR 전체 10행 제거) · 시험 MAE 2.0199 · RMSE 2.6349 · R² 0.9043 | gbr · random_60_20_20 432/144/144 · IQR 학습 구간 5행 · 시험 MAE **2.0935** · RMSE 2.9711 · R² 0.8677 (기준선 MAE 6.9701) | MAE +3.65% · **RMSE +12.76%** · R² −4.05% | ±10% — RMSE 밖, 사유: 원천 시험 RMSE 선정 누수(K1, 원천 값 낙관) · IQR 전체(K6 ↔ D2-03) · 분할 · RobustScaler |
| krs.residual_review | 정제 전체 710행 채점(K4) · \|잔차\| ≥ 4 = 27 | 시험 144행 · 대기열 **16** | — | 제외(모수 다름) |
| krs.recipe_optimize | 시드 4765 · 충족률 0.2658 · 최저 비용 51.71 | 수락 5,000(뽑음 5,064) · 충족 774/5000 = **0.1548** · 최저 비용 61.25 | — | 제외(K2 · 표집 · 범위) |
| pc.sensory_score | gbr · 78/22(327/93) · 시험 MAE 1.7912 · R² 0.4814 / **표본 내** MAE 1.0829 · R² 0.7716 | gbr · **time_cv5**(420 < 500) 시험 84 · MAE **1.5375** · RMSE 1.9540 · R² 0.4747 | MAE −14.17% | 제외(D2-02 — 재측정 정본 · 원천 시험 · 표본 내 병기) |
| pc.residual_review | 표본 내 q90 2.3190 · 넘음 42 · 표시 8 | 검증 q90 **4.2338** · 시험 84 · 대기열 **3** | — | 제외 |
| pc.recipe_optimize | 시드 927 · 충족률 0.1554 | 수락 3,500(뽑음 4,738) · 충족 517/3500 = **0.1477** | — | 제외 |

kimchi 기준선(아키텍트 D2-39) MAE 1.5375 · queue 3 · 임계 4.2338 과 같다(재현 확인). solder 기준선 새로 적음(아키텍트 확인 요청).

### §8.3 확인

| 항목 | 실측 | 명령 |
|---|---|---|
| 새 시험 | 25 + 팩 4 passed | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_solder_pack.py tests/test_kimchi_optimize.py tests/test_reproduce_krs_pc.py packs/solder packs/kimchi` |
| 전체 | **870 passed · 3 skipped · 1 xfailed · 2 failed** — 실패 2 는 개발3 진행 중 `packs/rollform-quote`(주석 'ot' G-M01 · 추출기 파일 없음) | `OMP_NUM_THREADS=1 uv run pytest -q --ignore=tests/e2e` |
| 코어 동결 | `git diff core-freeze-2 -- src/mlcore web/src/components std contracts` **0줄** · 미추적 0 | 직접 실행 |
| make gate | PASS 22 · FAIL 1(G-M01 = rollform-quote 'ot', 개발3) · BLOCKED 1 — 내 팩 G-M01 위반 0(rollform 제외 실행 PASS) | `make gate` |
| make gate2 | 41행 PASS 34 · FAIL 5 · BLOCKED 2 · **G2-C01 PASS** · G2-P01 = 회사 없음 krs · rollform baselines(내 팩 solder · kimchi 통과) · G-M12(6사) 과제 행 없음(이관 보고서 — 개발3) | `make gate2` |

### §8.4 요청 · 발견

- **개발3 (`tenants/krs.yaml`):** pack `solder` · enable `krs.joint_strength` · `krs.recipe_optimize` · `krs.residual_review` · `sources.demo {synthetic, seed 20260917, rows 720}` · `compat.entity_prefix "KS-"` · `categories.supplier` 3값(원천 순서 — 효과가 위치에 묶임). **원천 값 `A · B · C` 를 그대로 넣으면 G-M01 이 깨진다** — 한 글자 금지어가 packs · 코어에서 27곳 걸림(코어는 동결). 겹치지 않는 표기 + 옛 값은 호환 쪽에서 바꾸기를 권함.
- **개발3 (`tenants/pc.yaml`):** `pc.recipe_optimize` 켜기. 그 뒤 `OMP_NUM_THREADS=1 uv run python migration/reproduce.py --phase2`(--tenants-base 없이)로 JSON 다시 생성 — 지금 파일은 임시 등록부로 만든 것(`meta.tenants_base` 에 표기, 값은 범주 위치만 같으면 같다).
- **개발3 (이관 보고서):** `outputs/reproduce-krs-pc.json` 행 6 → `docs/migration-report.md`. pc 행에는 "재측정" · "원천" 두 말이 다 있어야 G-M12(6사) 통과.
- **아키텍트:** ① D2-02 · kimchi baselines 주석은 `time_60_20_20` 인데 실제 정책은 `time_cv5`(행 420 < 500, std D-05) — 문구 정리 ② solder baselines 값 확인 ③ krs RMSE +12.76% 는 사유(원천 시험 구간 선정)로 남김 — 넓히지 않음.
- 코어 결함(2차): **없음**.
