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
