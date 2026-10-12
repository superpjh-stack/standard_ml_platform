# 기능 명세 — 표준 ML 플랫폼

> 표기
> - `[기준]` 근거 구축물 둘 이상에서 이미 쓰는 것. `[기준: X]` 는 그 출처.
> - `[가설]` 플랫폼을 만들며 새로 정한 것. `[가설 Qn]` 은 `problem.md` §8 의 확정 필요 사항과 연결.
> - 근거 구축물: `../Koreal Solder ML AI` · `../PyoungChang ML AI` · `../KwangSung ML AI` · `../SongWol ML AI` · `../OneTouch ML AI` · `../KyungDong ML AI`, `../Standard Data Hub`, `../Standard AI Agent Platform`, `../Standard MES Platform`, `../<회사> Data Platform`.
> - 회사 코드는 데이터 허브 등록부(`../Standard Data Hub/companies/*.yaml`)를 따른다: `krs`(고려솔더) · `pc`(평창) · `ks`(광성) · `sw`(송월) · `ot`(원터치) · `kd`(경동).

> **구축 단계.** 1차 = 코어 전부 + 팩 `press` · `textile` + 회사 `ks` · `sw` + 과제 유형 `regression` · `risk` · `anomaly` · `optimize` + 화면 1~6. 2차 = 팩 `solder` · `kimchi` · `rollform-quote` · `eto` + 회사 `krs` · `pc` · `ot` · `kd` + 과제 유형 `review_queue` · `extract` · `quote` + 화면 7~10. 1차 범위는 광성 · 송월이 같은 방법론(시간순 분할 · 재적합 · 결측 보정)을 이미 쓰고 있다는 점에서 골랐다. **2차의 게이트는 "코어 코드 변경 0줄"** 이다(`extract` · `quote` 유형 추가는 2차 시작 전에 코어에 넣는다). 아래 명세는 두 단계를 합친 최종 모양이다.

## 1. 시스템 구성

### 1.1 계층

```
 소비자 계층      운영 콘솔(React) · MES 화면/현황판 · AI Agent 도구 · 외부(ERP 등)
      │  공개 API /api/v1 — API 키 · 역할(viewer / operator / approver / admin) · 회사 범위
 ─────▼────────────────────────────────────────────────────────────────────────
 서비스 계층      추론(predict · explain) · 최적화(optimize) · 검토 대기열 · 견적 흐름
                  입력 검증 · 결측 보정 · 범위 검사 · 예측 기록
 ─────▼────────────────────────────────────────────────────────────────────────
 모델 계층        모델 등록부(버전 · 상태 · 승인) · 산출물 저장(joblib + SHA-256)
                  학습 서비스(전처리 공장 · 후보 · 분할 정책 · 선정 · 재적합 · 시험 · 설명)
 ─────▼────────────────────────────────────────────────────────────────────────
 데이터 계층      데이터 소스 어댑터(synthetic · csv · gateway · dataplatform · mes)
                  표준 프레임 변환 · 변수 대응 · 스냅숏(해시 고정)
 ─────▼────────────────────────────────────────────────────────────────────────
 운영 계층        감시(드리프트 · 결측 · 실측 성능) · 재학습 후보 · 감사 로그 · 일정 작업
 ─────▼────────────────────────────────────────────────────────────────────────
 저장 계층        PostgreSQL 17 — mlp_* (등록부 · 스냅숏 · 예측 · 감시 · 승인 · 감사)
                  파일 저장소 var/artifacts/<tenant>/<task>/<version>/ (선택: S3)
```

### 1.2 기술 스택 `[기준: 6개사 ML AI · Standard MES Platform]`

| 영역 | 선택 | 근거 |
|---|---|---|
| 언어 · 패키지 | Python 3.12 · `uv` (lock 고정) | 표준 MES · 데이터 허브. 기존 3.11/3.12 혼재(F11) 정리 |
| API | FastAPI · pydantic v2 (`extra="forbid"` · `allow_inf_nan=False`) | 6벌 공통. 엄격 검증은 광성 · 송월 `[기준]` |
| ML | scikit-learn · numpy · pandas · joblib. 선택: LightGBM `[가설 Q2]` | 6벌 공통 |
| 도면 | ezdxf | 경동 · 원터치 `api/cad.py` |
| DB | PostgreSQL 17 · psycopg 3 | 표준 MES · 데이터 허브. 기존 SQLite(원터치 · 경동) 대체 |
| 콘솔 UI | React 19 · TypeScript · Vite · lucide (정확한 버전 고정) | 6벌 `web/`. 평창 `latest`(F11) 금지 |
| 일정 작업 | 앱 내 스케줄러(APScheduler) 1개 프로세스 | `[가설]` — 회사당 VPS 1대 규모 |
| 시험 | pytest · 계약 시험 · 결정성 시험 · Playwright(콘솔) | 6벌 4~11 개 시험 함수 |
| 배포 | Docker Compose(app + db, DB 포트 비공개) · 역방향 프록시 HTTPS | 광성 Hostinger 배포 · 표준 MES |

### 1.3 실행 모드

| 모드 | 용도 | 데이터 | 운영 모델 |
|---|---|---|---|
| `demo` | 시연 · 개발 | 팩 합성 생성기 · 데모 CSV | 합성 모델 허용. 모든 응답 `synthetic: true` |
| `eval` | 게이트 · 회귀 시험 | 고정 스냅숏(`tests/fixtures/`) | 시드 고정. 결정성 검사 |
| `live` | 운영 | 실데이터 소스 | 합성 스냅숏 모델은 `production` 금지(기동 검사) |

기동 시 재학습하지 않는다. 등록부의 `production` 모델을 읽어 올리고, 없으면 그 과제는 `503 model_not_ready` 를 낸다 `[가설 — F3 대응]`. `demo` 모드에서만 `make seed` 가 합성 모델을 미리 학습해 등록한다.

## 2. 표준 분류

### 2.1 과제 유형 7 `[가설: 유형 · 근거 기능은 기준]`

| 코드 | 유형 | 묻는 것 | 출력 | 근거 기능 (회사) |
|---|---|---|---|---|
| `regression` | 품질 · 수치 예측 | 이 조건이면 수치가 얼마인가 | 값 · 단위 · 예측 구간 | 접합 강도(krs) · 관능 점수(pc) · 잔여수명(ks) · ΔE(sw) · 가공 분(ot) · 작업시간(kd) |
| `risk` | 위험 분류 | 나쁜 일이 생길 확률은 | 확률 · 등급 · 기준선 대비 | 24시간 고장(ks) · 불량(sw) |
| `anomaly` | 이상 · 분포 밖 탐지 | 이 입력이 평소와 다른가 | 점수 · 여부 · 기여 변수 | IsolationForest(ks · sw) |
| `optimize` | 조건 최적화 | 무엇을 어떻게 바꾸면 목표를 맞추나 | 추천 조건 · 예측값 · 제약 충족/위반 · 후보 n | 배합(krs · pc) · 정비 시점(ks) · 인쇄 조건(sw) |
| `review_queue` | 검토 대기열 | 사람이 다시 봐야 할 건은 | 대상 목록 · 사유 · 우선순위 | 잔차 대기열(krs ≥4MPa · pc 상위 10%) |
| `extract` | 문서 · 도면 추출 | 도면에서 무엇을 뽑나 | 영역 · 객체 · BOM 행 · 신뢰도 | DXF 영역 3종(kd · D-160) · 객체 분류(ot) · BOM 텍스트(kd) |
| `quote` | 원가 · 견적 계산 | 얼마에 만들 수 있나 | 원가 항목 · 합계 · 사람 수정 기록 | 견적식(kd `api/quote.py` · ot Decimal ROUND_HALF_UP) |

규칙:
- 유형은 **입출력 모양과 평가 방식**만 정한다. 비용식 · DXF 규칙 · 정비 비용식 같은 회사 고유 계산은 팩 · 회사 플러그인이다(`problem.md` P2).
- `optimize` · `review_queue` · `quote` 는 **다른 과제의 모델을 쓰는 합성 과제**다. `uses:` 로 의존 과제를 선언하고, 의존 과제의 `production` 버전을 응답에 함께 적는다.
- 6개사 기존 기능은 전부 이 7개 중 하나에 대응해야 한다(G2 검사 `check_task_cover`, 대응표 `docs/task-map.md`).

### 2.2 업종 팩 `[기준: 근거 6개사]`

| 팩 코드 | 업종 | 근거 회사 | 과제 (팩 기본) |
|---|---|---|---|
| `solder` | 솔더 합금 배합 | krs | `joint_strength`(regression) · `recipe`(optimize) · `residual_review`(review_queue) |
| `kimchi` | 김치 · 절임식품 | pc | `sensory_score`(regression) · `recipe_process`(optimize) · `residual_review` |
| `press` | 프레스 · 금형 | ks | `remaining_hours`(regression) · `failure_24h`(risk) · `sensor_ood`(anomaly) · `maintenance_timing`(optimize) |
| `textile` | 섬유 · 날염 | sw | `delta_e`(regression) · `defect_risk`(risk) · `print_ood`(anomaly) · `print_setpoint`(optimize) |
| `rollform-quote` | 롤포밍 · 형강 견적 | ot | `cad_objects`(extract) · `machining_minutes`(regression) · `quote`(quote) |
| `eto` | 수주생산 장비 | kd | `cad_regions`(extract) · `bom_text`(extract) · `labor_hours`(regression) · `quote`(quote) |
| `_template` | 빈 팩 | — | `regression` 1 · `risk` 1 |

과제의 전체 이름은 `<tenant>.<task>`(예: `sw.delta_e`), 팩 정의 이름은 `<pack>.<task>`(예: `textile.delta_e`)다.

### 2.3 표준 응답 상태 `[가설 — 기존 문구 주의/정상 · 점검 검토 · 품질 검토 · 검토 필요 · 추가 징후 없음 통합]`

| 상태 코드 | 뜻 | 화면 문구(기본) |
|---|---|---|
| `ok` | 기준 안 · 학습 범위 안 | 정상 |
| `watch` | 기준 근접(과제의 `watch_band`) 또는 범위 근접 | 주의 |
| `review` | 기준 초과 · 위험 등급 높음 · 이상 입력 | 검토 필요 |
| `out_of_range` | 입력이 학습 범위 밖. 예측은 하되 신뢰 낮음(Q7) | 범위 밖 |
| `rejected` | 거부 정책 과제에서 범위 밖 · 필수 변수 누락 | 예측 불가 |
| `needs_approval` | 최적화 추천 · 견적 초안 · 재학습 후보가 승인 대기 | 승인 필요 |

문구는 팩 · 회사 설정으로 바꿀 수 있지만 **코드는 바꿀 수 없다**. 소비자(MES · Agent)는 코드로 판단한다.

### 2.4 지표 사전 `[가설 — 이름 통일: F2 · F4]`

| 유형 | 선정 지표 | 보고 지표 (전부 같은 키 이름) | 기준선 |
|---|---|---|---|
| `regression` | `mae` | `mae` · `rmse` · `r2` · `mape`(목표 > 0 일 때) · `interval_coverage` | 학습 평균 · (시계열이면) 직전값 |
| `risk` | `brier` | `brier` · `roc_auc` · `pr_auc` · `logloss` · `ece`(보정 오차) · 등급별 정밀도/재현율 | 학습 양성률 상수 |
| `anomaly` | — (비지도) | `flag_rate` · (라벨 있으면) `precision@k` | 기대 오염률(`contamination`) |
| `extract` | `macro_f1` | `macro_f1` · 클래스별 F1 · 혼동행렬 · (영역) `iou` | 라벨 없으면 지표 없음 + `labels: none` `[기준: kd D-160]` |
| `optimize` | — | 제약 충족률 · 예측 개선량(현재 조건 대비) · 탐색 후보 수 · 학습 범위 안 비율 | 현재 조건 |
| `review_queue` | — | 대기열 크기 · 실제 이상 적중률(검토 결과 있을 때) | — |
| `quote` | — | 사람 수정률 · 수정 폭(원) · (실적 있으면) 원가 오차 | — |

모든 지표는 `{value, baseline, delta_vs_baseline}` 으로 함께 저장 · 표시한다. 기준선을 못 이긴 후보는 `candidate` 까지만 갈 수 있다(G5 · P4).

## 3. 과제 정의 규격

### 3.1 `features.yaml` — 팩 변수 사전 `[기준: 6벌 FEATURE_META]`

```yaml
# packs/textile/features.yaml
set_temp:      {label: 설정 온도,  unit: "℃",   dtype: float, min: 150, max: 210, default: 180, required: true,  controllable: true,  step: 1}
set_pressure:  {label: 설정 압력,  unit: bar,   dtype: float, min: 2.0, max: 5.0, default: 3.5, required: true,  controllable: true,  step: 0.1}
line_speed:    {label: 라인 속도,  unit: m/min, dtype: float, min: 10,  max: 30,  default: 20,  required: true,  controllable: true,  step: 1}
absorb_rate:   {label: 원단 흡수율, unit: "%",  dtype: float, min: 40,  max: 95,  required: false, controllable: false, impute: median}
print_type:    {label: 인쇄 방식,  dtype: category, values: [나염, 승화, DTF], required: true, controllable: false}
std_name: {set_temp: temp_set_c, set_pressure: pressure_set_bar}   # 표준 필드 사전 대응(데이터 허브 std/fields.yaml)
```

| 키 | 뜻 |
|---|---|
| `min` / `max` | 입력 검증 범위. 학습 범위는 스냅숏에서 따로 계산해 `out_of_range` 판정에 쓴다 |
| `required` / `impute` | 필수 여부와 결측 보정(median · most_frequent · none). 과제마다 `max_imputed`(기본 3) `[기준: ks]` |
| `controllable` / `step` | 최적화 대상 여부와 탐색 간격. `false` 인 변수는 최적화 때 입력값으로 고정 `[기준: sw 원단 LOT 고정]` |
| `std_name` | 데이터 허브 표준 필드 이름. 회사 간 같은 물리량을 묶는다 |

### 3.2 `tasks/<task>.yaml` — 과제 정의 `[가설]`

```yaml
id: textile.delta_e
type: regression                    # §2.1
title: 색차(ΔE) 예측
entity: lot                         # 행의 단위: lot | equipment_window | job | drawing
time_key: recorded_at               # 시계열이면 필수 — 분할 정책이 쓴다
group_key: fabric_lot               # 같은 그룹은 분할 구간을 넘지 않는다
target: {name: delta_e, unit: "ΔE", direction: lower_is_better}
features: [set_temp, set_pressure, line_speed, ink_usage, dwell_time, absorb_rate, fabric_strength, print_type, color_tone]
thresholds: {review_above: 2.0, watch_band: 0.3}
candidates: [ridge, random_forest, extra_trees, hist_gb]   # §5.2 의 이름
split: time_60_20_20                # §5.3
interval: {method: split_conformal, alpha: 0.1}           # 예측 구간
out_of_range: predict_with_warning  # | reject  [가설 Q7]
approver_role: quality
monitor: {psi_warn: 0.2, psi_retrain: 0.3, oor_warn: 0.05, perf_window_days: 30}
---
id: textile.print_setpoint
type: optimize
uses: [textile.delta_e, textile.defect_risk]
objective: {minimize: delta_e}
constraints:
  - {expr: "delta_e <= 1.5"}
  - {expr: "defect_risk <= 0.10"}
  - {expr: "line_speed >= 18"}
search: {strategy: grid, max_points: 10000}               # grid | random | bayes(이후)
on_infeasible: least_violation                            # [기준: pc 위반 순위 대체]
approver_role: line_lead
```

### 3.3 회사 덮어쓰기

회사는 `tenants/<code>/tasks/` 에 같은 `id` 로 덮어쓴다. 덮어쓸 수 있는 것: `thresholds` · `features` 추가/제외 · `candidates` · `constraints` 값 · `monitor` · `approver_role` · 문구. **덮어쓸 수 없는 것: `type` · `split` 의 누수 규칙(`time_key` · `group_key` 존재 시 시간순 강제) · 승인 지점** (§11.3).

## 4. 데이터 소스

### 4.1 어댑터 `[가설 — 원천 형식은 기준]`

```python
class DataSource(Protocol):
    kind: str                                   # synthetic | csv | gateway | dataplatform | mes
    def probe(self) -> SourceHealth: ...        # 연결 · 행 수 · 기간 · 지연 (doctor 가 쓴다)
    def read(self, spec: ReadSpec) -> pd.DataFrame: ...   # 표준 프레임 반환, 읽기 전용
```

| 어댑터 | 원천 | 읽는 방법 | 근거 |
|---|---|---|---|
| `synthetic` | 팩 `synth/<task>.py` | 시드 고정 생성(기존 6벌 `demo_data()` 이관) | 6벌 공통 |
| `csv` | 업로드 · 폴더 | UTF-8(BOM 허용) · 열 대응표 · 단위 변환 | 목표 실측의 첫 경로(Q8) |
| `gateway` | Data Gateway 원장 DB | 읽기 계정 SELECT, 시간 창 집계(평균 · 최대 · 표준편차) | `../<회사> Data Gateway` |
| `dataplatform` | Data Platform REST(`get_readings`) · Athena silver/gold 뷰 | 키당 5 req/s · 5,000/일 준수. 대량 학습은 Athena | `../<회사> Data Platform/clients/*` |
| `mes` | MES DB 읽기 계정 | 허용목록 테이블만(검사 결과 · 정비 이력 · LOT · 작업지시) | 표준 MES · Agent 플랫폼 SQL 가드 |

모든 어댑터는 쓰기 경로가 없다(읽기 계정 · HTTP GET 만). `check_sources` 가 이를 검사한다.

### 4.2 표준 프레임

| 열 | 뜻 |
|---|---|
| `tenant_id` · `task_id` | 회사 · 과제 |
| `entity_id` | 행 단위 식별자(`lot_id` · `equip_code+window` · `job_id` · `drawing_id`) `[기준: ks 데이터 계약 lot_id]` |
| `ts` | 기준 시각(KST, tz 포함) `[기준: ks recorded_at]` |
| `group` | 분할 그룹(선택) |
| 변수 열 | `features.yaml` 이름. 단위 변환 후 |
| `target` | 목표(지도학습). 없으면 그 과제는 `목표 없음` 으로 학습 불가 |
| `_source` · `_source_ref` | 어댑터 종류와 원천 위치(테이블 · 뷰 · 파일 · 시간 창) |

센서(시계열)와 LOT(행)의 결합은 `join: {on: entity_id, window: "[start, end]", agg: [mean, max, std]}` 로 선언한다. 결합 규칙은 과제 정의에 둔다.

### 4.3 스냅숏 `[가설 — F3 · G6]`

학습마다 표준 프레임을 Parquet 으로 고정한다(`var/snapshots/<tenant>/<task>/<snapshot_id>.parquet`). `mlp_snapshot` 에 행 수 · 기간 · 열 목록 · 결측률 · 학습 범위(변수별 p1/p99) · SHA-256 · 원천 참조 · `synthetic` 여부를 남긴다. 같은 스냅숏 + 같은 시드 + 같은 코드 버전 → 같은 모델(예측 차이 0)이어야 한다(결정성 시험).

## 5. 학습

### 5.1 전처리 공장 `[기준: 6벌 Pipeline(ColumnTransformer)]`

수치 = `SimpleImputer(median)` → `StandardScaler`(트리 모델은 생략), 범주 = `SimpleImputer(most_frequent)` → `OneHotEncoder(handle_unknown="ignore")`. 이상치 제거(krs IQR)는 기본 꺼짐이며 과제 설정 `outlier: iqr` 로 켠다. 제거 건수는 학습 보고서에 남긴다.

### 5.2 후보 모델 이름 사전

| 이름 | 구현 | 유형 |
|---|---|---|
| `ridge` · `svr` · `decision_tree` · `random_forest` · `extra_trees` · `gbr` · `hist_gb` | sklearn 회귀 | regression |
| `logreg` · `rf_clf` · `et_clf` · `gbc` · `hist_gb_clf` | sklearn 분류 (+ `CalibratedClassifierCV` 선택) | risk · extract(분류) |
| `isolation_forest` | sklearn | anomaly |
| `lightgbm` · `lightgbm_clf` | 선택 의존성, 기본 꺼짐 `[가설 Q2]` | regression · risk |

하이퍼파라미터는 팩 기본값 + 과제 덮어쓰기. 탐색은 후보당 최대 20회 무작위 탐색(1차) `[가설]`.

### 5.3 분할 정책 — 바꿀 수 없는 누수 규칙 `[기준: ks · sw methodology]`

| 정책 | 언제 | 절차 |
|---|---|---|
| `time_60_20_20` | `time_key` 가 있으면 **강제** | 시간순 학습 60 · 검증 20 · 시험 20. `group_key` 가 경계를 넘지 않게 자른다 |
| `time_cv5` | 행 < 500 이고 시계열 | 시간순 5폴드 확장 창 검증 + 마지막 20% 시험 `[가설 Q5]` |
| `stratified_60_20_20` | 시계열 아님 · 분류 | 층화 무작위(시드 고정) `[기준: ot]` |
| `random_60_20_20` | 시계열 아님 · 회귀 | 무작위(시드 고정) |

공통 절차: 학습 구간으로 후보 학습 → **검증 구간**으로 챔피언 선정과 예측 구간 · 확률 보정 → 학습+검증으로 재적합 → **시험 구간 1회** 평가 → 보고. 시험 구간은 선정 · 보정 · 임계값 결정 · 대기열 채점에 쓰지 않는다(`check_leakage`). 평창식 "전체 재적합 후 같은 데이터 채점"(F5)은 금지한다. 대기열은 시험 구간 또는 운영 예측 잔차로만 만든다.

### 5.4 설명 · 학습 보고서

학습마다 `report.json` + 콘솔 화면을 만든다. 내용은 다음과 같다.
- 스냅숏 요약과 후보별 검증 지표 · 선정 사유.
- 시험 지표와 기준선(§2.4).
- 순열 중요도(시험 구간) `[기준: ks]`.
- 잔차 분포 · 구간별 오차(설비 · 제품 · 범주별).
- (risk) 보정 곡선.
- (extract) 혼동행렬.
- 경고: 행 < 200 · 목표 불균형 · 결측률 > 30% 변수 · 기준선 미달.

### 5.5 학습 작업

`POST /api/v1/tenants/{t}/tasks/{task}/train` 또는 `make train` 이 작업을 만든다. 작업은 `queued → running → succeeded | failed` 로 움직이고, 기록은 `mlp_train_run` 에 남는다. 회사당 동시 학습은 1개다(768MB 기준). 학습 프로세스는 `OMP_NUM_THREADS=1` 로 돈다 `[기준: ks 배포]`. 같은 스냅숏 · 같은 설정의 학습 요청이 다시 오면 기존 결과를 돌려준다.

## 6. 모델 등록부

### 6.1 상태 전이 `[가설 — G6 · G9]`

`candidate → staging → production → archived`

| 전이 | 조건 | 누가 |
|---|---|---|
| 학습 성공 → `candidate` | 학습 완료 | 시스템 |
| `candidate → staging` | 기준선을 이김 · 경고 중 차단 항목 없음 · `live` 면 `synthetic: false` | ML 담당(operator) |
| `staging → production` | 그림자 비교(운영 입력에 대한 현재 모델 대비 예측 차이 · 최근 실측 성능)를 보고 승인 | 과제의 `approver_role` |
| `production → archived` | 새 `production` 승인 시 자동 | 시스템 |
| 되돌리기 | `archived` 중 하나를 다시 `production` 으로 | approver, 사유 필수 |

과제마다 `production` 은 정확히 하나다(DB 부분 고유 색인). 승인 · 되돌리기는 `mlp_approval` 과 `mlp_audit` 에 남는다. **자동 승격 경로는 코드에 없다**(`check_no_autopromote`).

### 6.2 산출물

`var/artifacts/<tenant>/<task>/<version>/` 아래에 `model.joblib` · `report.json` · `features.lock.json`(변수 · 범주 값 · 학습 범위) · `env.lock`(패키지 버전)을 둔다. 적재할 때 SHA-256 과 패키지 버전을 대조한다. 불일치하면 그 버전을 거부하고 `model_artifact_mismatch` 를 낸다. 버전 이름은 과제 안 일련번호 `v<n>` 이다.

## 7. 추론 계약

### 7.1 요청 `[기준: ks · sw 엄격 검증]`

```json
POST /api/v1/tenants/sw/tasks/sw.delta_e/predict
{
  "inputs": {"set_temp": 182, "set_pressure": 3.4, "line_speed": 20, "ink_usage": 12.5,
             "dwell_time": 35, "absorb_rate": null, "print_type": "나염", "color_tone": "진함"},
  "entity_id": "LOT-20261012-021",          // 선택 — 실측 연결에 쓴다
  "explain": false,                          // true 면 변수 기여 상위 5
  "model_version": null                      // null = production. staging 은 approver 이상만
}
```

여러 건은 `POST .../predict:batch` 로 보낸다(`{"items": [...]}`, 최대 500건).

### 7.2 응답 — 모든 과제 공통 `[가설 — F2 통합]`

```json
{
  "task": "sw.delta_e", "type": "regression",
  "prediction": {"value": 1.21, "unit": "ΔE", "interval": [0.95, 1.48]},
  "probability": null,                       // risk: 0~1
  "anomaly": null,                           // anomaly: {"score": -0.12, "flag": false}
  "status": "ok",                            // §2.3
  "warnings": [{"code": "imputed", "field": "absorb_rate", "message": "중앙값으로 보정"}],
  "imputed_fields": ["absorb_rate"],
  "out_of_range_fields": [],
  "explain": null,
  "model": {"name": "extra_trees", "version": "v7", "trained_at": "2026-10-01T09:00:00+09:00",
            "snapshot_id": "snp_…", "synthetic": false},
  "prediction_id": "prd_…",
  "notice": "예측값은 참고용이며 공정 변경은 담당자 확인 후 진행합니다."
}
```

규칙:
- 유형마다 쓰지 않는 필드는 `null` 로 둔다. **키는 빠지지 않는다**(계약 시험).
- 기존 출력 키(`predicted_strength` · `remaining_hours` · `delta_e` …)는 `prediction.value` + 과제 `target.name` 으로 대신한다. 이관 기간에는 회사 호환 경로(§15 M4)가 옛 키로 바꿔 준다.
- `notice` 는 팩 · 회사 문구다. 6벌 공통 관행 `[기준]`.

### 7.3 검증 · 오류

| 경우 | 처리 |
|---|---|
| 모르는 키 · NaN · Infinity | `422 invalid_input`. 잘못된 값을 메시지에 되풀이하지 않는다 `[기준: 6벌 422 처리기]` |
| 필수 변수 누락 · 보정 한도 초과 | `422 missing_required` |
| `min`/`max` 밖 | `422 out_of_bounds` (검증 범위 — 물리적으로 불가능한 값) |
| 학습 범위 밖(검증 범위 안) | `out_of_range` 상태 + 경고, 또는 `rejected`(과제 정책) |
| `production` 모델 없음 | `503 model_not_ready` — 대체 모델 · 기본값 응답 금지 |
| 산출물 해시 불일치 | `503 model_artifact_mismatch` |
| 권한 · 회사 범위 밖 | `403 forbidden` |
| 소스 실패(학습 · doctor) | `503 source_disconnected` |

오류 형식은 `{code, message, detail}` 이다 `[기준: 표준 MES · Agent 플랫폼 오류 계약]`.

### 7.4 예측 기록 · 실측 연결

모든 예측은 `mlp_prediction` 에 남는다(입력 · 출력 · 상태 · 모델 버전 · 호출자 · 채널). 실측은 두 경로로 들어온다. 하나는 `POST .../actuals`(`{entity_id, value, observed_at}`)이고, 다른 하나는 데이터 소스의 목표 열을 일정 작업이 당겨 오는 것이다. 들어온 실측은 `entity_id` 로 예측과 이어지며, 이것이 운영 성능(§9)의 원천이 된다.

## 8. 합성 과제 흐름

### 8.1 최적화 `optimize` `[기준: krs · pc 무작위 · ks 시간 격자 · sw 전수 격자 통합]`

1. 입력: 고정 변수(`controllable: false`) 값 + 선택적으로 조절 변수의 현재값.
2. 탐색 공간: 조절 변수의 `[학습 범위 p1, p99] ∩ [min, max]` 를 `step` 간격으로 나눈다. 학습 범위 밖은 탐색하지 않는다(P7).
3. 전략: 공간 크기 ≤ `max_points` 면 `grid`, 아니면 `random`(시드 고정 · `max_points` 개). 1차원 시간 탐색(정비 시점)은 `grid` 의 특수형이다.
4. 평가: `uses` 과제들의 `production` 모델로 일괄 예측 → 제약 검사 → 목적 정렬.
5. 결과: 상위 5개 후보(조건 · 예측값 · 구간 · 제약별 충족/여유)와 현재 조건 대비 개선량. 제약을 못 맞추면 `on_infeasible: least_violation` 으로 위반 합이 가장 작은 후보와 위반 내용을 낸다. 이때 `status: review` 다.
6. 추천은 `mlp_recommendation` 에 `needs_approval` 로 남는다. 적용 여부(`applied` · `dismissed`)는 소비자(MES · 콘솔)가 기록한다. 플랫폼은 설비에 쓰지 않는다.

비용식이 있는 목적(정비 비용 · 배합 원가 지수)은 팩 플러그인 `formulas/<name>.py` 의 순수 함수로 둔다. 함수 모양은 `def cost(row: dict, params: dict) -> float` 다 `[기준: ks 비용식 · krs cost index]`.

### 8.2 검토 대기열 `review_queue` `[기준: krs · pc]`

규칙은 `|잔차| ≥ 절대 기준` 또는 `잔차 상위 q%` 다. 대상은 시험 구간 잔차와 운영 예측의 실측 잔차이고, 학습 구간 잔차는 금지한다(§5.3). 항목에는 `entity_id` · 예측 · 실측 · 잔차 · 사유 · 상태(`open` · `confirmed_issue` · `false_alarm`)를 둔다. 검토 결과는 다음 학습의 라벨 후보가 된다.

### 8.3 문서 · 도면 추출 `extract` `[기준: kd · ot]`

- 입력: DXF multipart. 상한은 5 MiB · 엔티티 20,000개다 `[기준: kd]`.
- 처리기: 팩 플러그인 `extractors/<name>.py` 다. 규칙 기반(kd 영역 3종)과 모델 기반(ot 객체 분류)을 같은 인터페이스로 둔다.
- 출력: `{regions[], objects[], bom_rows[], confidence, extractor:{name, version}}`.
- 원본과 결과는 `mlp_document` 에 남긴다.
- 정답 라벨이 없으면 지표를 내지 않고 `labels: none` 을 표시한다 `[기준: kd D-160]`.

### 8.4 견적 `quote` `[기준: kd · ot]`

흐름은 `extract` 결과 → 사람 검토 · 수정 → `regression`(작업시간 · 가공 분) 예측 → 팩 비용식(`Decimal` · `ROUND_HALF_UP`) → 견적 초안이다. 확정하려면 `reviewed: true` 와 `review_note`(≥ 5자)가 있어야 한다 `[기준: kd]`. 사람이 바꾼 인식값은 `overrides` 로 남긴다 `[기준: ot]`. 견적은 `mlp_quote` 에 스냅숏으로 고정하고(이후 모델이 바뀌어도 금액 불변), CSV 내보내기는 수식 주입 방지 · UTF-8 BOM 으로 한다 `[기준: 6벌 CSV]`.

## 9. 운영 감시

### 9.1 일일 작업 (KST 02:00) `[가설 Q6]`

| 지표 | 계산 | 기본 기준 |
|---|---|---|
| `psi` | 변수별, 학습 스냅숏 대비 최근 7일 운영 입력(수치 10분위 · 범주 빈도) | ≥ 0.2 경고 · ≥ 0.3 재학습 후보 |
| `oor_rate` | 학습 범위 밖 입력 비율 | ≥ 5% 경고 |
| `missing_rate` | 변수별 결측(보정) 비율 | 학습 대비 +10%p 경고 |
| `live_perf` | 실측이 붙은 예측의 유형 지표(§2.4), `perf_window_days` 창 | 시험 지표 대비 25% 악화 → 재학습 후보 |
| `volume` | 일 예측 수 · 오류율 | 오류율 ≥ 2% 경고 |
| `source_health` | 소스 `probe()` | 실패 시 `source_disconnected` |

결과는 `mlp_monitor_daily` 에 남는다. 재학습 후보 조건이 맞으면 최근 스냅숏으로 학습 작업을 만들고, 그 결과(`candidate`)를 대기열에 올린다. **배포는 §6.1 승인을 거친다.**

### 9.2 알림

콘솔 배지와 일일 요약을 기본으로 둔다. 메신저(Slack · Telegram) 알림은 회사 설정의 웹훅으로 보낸다 `[가설]`. AI Agent 플랫폼의 브리핑 동선(J10)이 `ml.monitor_summary` 로 읽을 수 있게 한다(§13).

## 10. 데이터 모델 `[가설 — 모든 테이블은 접두어 mlp_]`

### 10.1 테이블

| 테이블 | 내용 | 주요 열 |
|---|---|---|
| `mlp_tenant` | 회사 | `tenant_id` · `name` · `pack` · `mode` |
| `mlp_task` | 과제(정의 해시) | `task_id` · `tenant_id` · `type` · `def_hash` · `enabled` |
| `mlp_source` | 데이터 소스 설정 · 상태 | `source_id` · `kind` · `ref` · `last_probe` · `status` |
| `mlp_snapshot` | 학습 스냅숏 | `snapshot_id` · `task_id` · `rows` · `ts_from/to` · `sha256` · `synthetic` · `ranges` jsonb |
| `mlp_train_run` | 학습 작업 | `run_id` · `snapshot_id` · `config_hash` · `status` · `started/finished_at` · `log` |
| `mlp_model_version` | 모델 버전 | `task_id` · `version` · `run_id` · `algo` · `metrics` jsonb · `stage` · `artifact_sha256` · `code_version` |
| `mlp_prediction` | 예측 기록 | `prediction_id` · `task_id` · `version` · `entity_id` · `inputs` · `outputs` · `status` · `caller` · `ts` |
| `mlp_actual` | 실측 | `task_id` · `entity_id` · `value` · `observed_at` · `source` |
| `mlp_recommendation` | 최적화 추천 | `rec_id` · `task_id` · `fixed_inputs` · `candidates` · `status` · `applied_at` · `applied_by` |
| `mlp_review_item` | 검토 대기열 | `item_id` · `task_id` · `entity_id` · `residual` · `reason` · `state` |
| `mlp_document` | 추출 원본 · 결과 | `doc_id` · `task_id` · `raw_sha256` · `result` · `extractor_version` |
| `mlp_quote` | 견적 스냅숏 | `quote_id` · `doc_id` · `lines` · `total` · `overrides` · `reviewed_by` · `review_note` |
| `mlp_monitor_daily` | 감시 결과 | `task_id` · `day` · `metric` · `feature` · `value` · `level` |
| `mlp_approval` | 승인 대기열 | `approval_id` · `kind`(model · recommendation · quote) · `ref_id` · `state` · `decided_by` · `reason` |
| `mlp_audit` | 감사 로그 | `ts` · `actor` · `action` · `target` · `detail` |
| `mlp_api_key` | API 키(해시) · 역할 · 회사 범위 | `key_hash` · `role` · `tenant_id` · `consumer` |

### 10.2 불변 규칙

1. 모든 행은 `tenant_id` 를 갖고, API 계층에서 키의 회사 범위로 거른다(회사당 배포여도 둔다 `[가설 Q1]`).
2. `mlp_prediction` · `mlp_audit` · `mlp_quote` 는 추가만 한다(UPDATE · DELETE 권한 없음).
3. 과제마다 `stage = 'production'` 은 하나(부분 고유 색인).
4. `mode = live` 회사에서 `synthetic = true` 스냅숏 모델은 `production` 이 될 수 없다(검사 제약 + 기동 검사).
5. 기존 MES 예측 테이블(예: sw `PRT_COLOR_PREDICTIONS.PRED_DELTA_E` · `PRT_QUALITY_PREDICTIONS.DEFECT_PROB`)은 `db/compat/<tenant>.sql` 의 대응 뷰로 제공한다 `[가설 Q11]`.

## 11. 업종 팩 · 회사 등록부

### 11.1 팩 구조

```
packs/textile/
  pack.yaml            # 이름 · 버전 · 코어 최소 버전 · 기본 문구 · 기본 감시 기준
  features.yaml        # §3.1
  tasks/*.yaml         # §3.2
  formulas/*.py        # 비용식 (순수 함수)
  extractors/*.py      # (extract 팩만)
  synth/*.py           # 합성 생성기 — 6벌 demo_data() 이관
  baselines.yaml       # 합성 기준 지표 (회귀 시험용)
  tests/
```

### 11.2 `tenants/<code>.yaml`

```yaml
code: sw
name: 송월타월
pack: textile
mode: live                                   # demo | eval | live
hub_company: sw                              # 데이터 허브 등록부 코드
tasks:
  enable: [sw.delta_e, sw.defect_risk, sw.print_ood, sw.print_setpoint]
sources:
  train:   {kind: dataplatform, view: sw_gold.print_quality_daily, key_env: SW_DP_KEY}
  actuals: {kind: mes, tables: [PRT_QUALITY_HISTORY], dsn_env: SW_MES_RO_DSN}
  demo:    {kind: synthetic, seed: 20260917}
feature_map:                                 # 원천 열 → 팩 변수
  PRT_PRINT_CONDS.SET_TEMP: set_temp
  RCV_MATERIAL_LOTS.ABSORB_RATE: absorb_rate
approvers: {quality: [qa_lead], line_lead: [line2_lead]}
notify: {webhook_env: SW_SLACK_WEBHOOK}
```

비밀값은 환경변수 **이름**만 적는다. 값은 `.env`(커밋 금지)나 배포 비밀로 넣는다.

### 11.3 병합 규칙 — 어기면 기동 거부

1. 회사는 팩 과제를 덮어쓸 수 있으나 `type` · 누수 규칙 · 승인 지점은 바꿀 수 없다.
2. 켜진 과제의 `features` 가 `feature_map` 또는 합성 소스로 전부 채워져야 한다(대응률 < 100% 면 `doctor` 경고, 필수 변수 누락이면 거부).
3. `uses` 의 의존 과제가 켜져 있어야 한다.
4. `mode: live` 인데 `production` 모델이 합성 스냅숏이면 그 과제만 끄고 `model_not_ready` 로 둔다.
5. 같은 이름 · 다른 구현의 플러그인(비용식 · 추출기) 금지.

## 12. 화면 · API

### 12.1 운영 콘솔 화면 10 `[가설 — 6벌 화면 통합]`

| # | 화면 | 사용자 | 기존 대응 |
|---|---|---|---|
| 1 | 회사 · 과제 개요(과제별 운영 버전 · 어제 예측 수 · 경고) | 전원 | 6벌 "운영 개요" |
| 2 | 예측 시험(과제 선택 → 입력 폼 자동 생성 → 표준 응답) | operator | 품질예측 · 예지보전 |
| 3 | 조건 추천(고정 변수 입력 → 후보 5 · 제약 충족표) | operator | 배합최적화 · 정비 시점 탐색 · 인쇄 조건 |
| 4 | 모델 비교 · 검증(후보 · 기준선 · 중요도 · 잔차 · 보정) | ML 담당 · approver | 모델 비교·검증 |
| 5 | 승인 대기열(모델 · 추천 · 견적) | approver | (신규) |
| 6 | 감시(PSI · 범위 밖 · 결측 · 실측 성능 추이) | ML 담당 | (신규) |
| 7 | 데이터 소스 · 스냅숏(doctor 결과 · 대응률 · 기간) | ML 담당 | 데이터 관리 · LOT 데이터 |
| 8 | 검토 대기열 | 품질 | 잔차 검토 |
| 9 | 도면 추출 · 견적(DXF → 영역/객체/BOM → 수정 → 견적) | 영업 · 견적 | CAD 객체인식 · BOM·견적자동화 · 견적 이력 |
| 10 | 감사 · 예측 추적(예측 ID → 모델 → 스냅숏 → 원천) | admin | (신규) |

입력 폼은 `features.yaml` 에서 자동으로 만든다. 회사 화면 코드는 0이다.

### 12.2 API (`/api/v1`)

| 메서드 · 경로 | 내용 | 최소 역할 |
|---|---|---|
| `GET /health` | 프로세스 · DB · 과제별 `model_ready` `[기준: 6벌 /api/health]` | 없음 |
| `GET /tenants/{t}/tasks` · `GET .../tasks/{task}` | 과제 목록 · 정의 · 변수 메타(폼 생성용) | viewer |
| `POST .../tasks/{task}/predict` · `predict:batch` | §7 | operator |
| `POST .../tasks/{task}/optimize` | §8.1 | operator |
| `POST .../tasks/{task}/actuals` | 실측 등록 | operator |
| `GET .../tasks/{task}/overview` | 운영 버전 · 지표 · 기준선 · 감시 요약 `[기준: 6벌 /api/ml/overview]` | viewer |
| `GET .../tasks/{task}/models` · `POST .../models/{v}/promote` · `rollback` | 등록부 · 승격 | ML 담당 · approver |
| `POST .../tasks/{task}/train` · `GET /runs/{id}` | 학습 작업 | ML 담당 |
| `GET .../tasks/{task}/review` · `PATCH .../review/{id}` | 검토 대기열 | 품질 |
| `POST .../documents` · `GET .../documents/{id}` | 추출 | operator |
| `POST .../quotes` · `GET .../quotes` · `GET .../quotes/{id}.csv` | 견적 | operator |
| `GET .../records?search=&limit=20&cursor=` | 표준 프레임 조회(통일: `search` · 기본 20 · 커서) | viewer |
| `GET .../approvals` · `POST /approvals/{id}/decide` | 승인 | approver |
| `GET .../monitor` · `GET /doctor` | 감시 · 소스 점검 | ML 담당 |
| `GET /predictions/{id}/trace` | 예측 추적 | admin |

목록 응답은 모두 `{items, next_cursor, total?}` 모양이다(F2 `items`/`records` 통일).

## 13. 연동

| 상대 | 방향 | 내용 |
|---|---|---|
| Data Platform | 플랫폼 → 읽기 | 학습 스냅숏(Athena 뷰) · 감시용 최근 입력(REST). 키 한도 준수 |
| Data Gateway | 플랫폼 → 읽기 | Data Platform 이 없는 경우의 대안. 읽기 계정 |
| MES | 양방향(API) | MES 가 `predict` · `optimize` 를 부른다. 플랫폼은 MES 검사 결과 · 정비 이력을 읽기 계정으로 읽어 실측으로 쓴다. MES 쓰기는 하지 않는다. 기존 예측 테이블은 대응 뷰(§10.2-5) |
| 표준 AI Agent 플랫폼 | Agent → 플랫폼 | 도구 계약 `ml.predict(task, inputs)` · `ml.explain(prediction_id)` · `ml.recommend(task, fixed)` · `ml.monitor_summary(tenant)`. 모두 읽기 · 추천만. 결과의 `prediction_id` 를 근거(Citation)로 쓴다. 정본 `contracts/agent-tools.md` |
| 표준 데이터 허브 | 허브 → 수확 | `make export-hub` 가 과제 · 변수 · 소스 · 호출 수를 허브 수확기 형식으로 낸다. 허브에서 태그 → 과제 → 화면 계보가 이어진다(허브 G7) |

## 14. 디렉터리 구조 `[가설]`

```
Standard ML Platform/
  intro.md  problem.md  spec.md  goal.md  CLAUDE.md  decisions.md  progress.md
  contracts/            # 예측 계약 · 과제 정의 스키마 · mlp 스키마 · 오류 계약 · agent-tools
  src/mlcore/
    tasks/              # 유형 7: regression · risk · anomaly · optimize · review_queue · extract · quote
    data/               # sources/(synthetic · csv · gateway · dataplatform · mes) · frame · snapshot
    train/              # preprocess · candidates · split · select · report
    registry/           # model registry · artifacts · packs/tenants 로더
    serve/              # predict · validate · impute · range · trace
    monitor/            # psi · perf · scheduler
    approval/  audit/  auth/  api/
  db/schema.sql  db/compat/
  web/                  # React 콘솔
  packs/{solder,kimchi,press,textile,rollform-quote,eto,_template}/
  tenants/{krs,pc,ks,sw,ot,kd,_template}.yaml  tenants/<code>/(tasks|formulas)/
  gates/                # check_* · gate.py
  migration/            # 기존 6벌 FEATURE_META · demo_data · 비용식 → 팩 이관 도구
  tests/
  docker/  docker-compose.yml  Makefile  pyproject.toml  uv.lock
```

## 15. 기존 ML 서비스의 이관 경로 (경로만)

| 단계 | 내용 |
|---|---|
| M1 변수 | 6벌 `api/config.py::FEATURE_META` → `packs/<pack>/features.yaml` (`migration/migrate_features.py`) |
| M2 합성 | 6벌 `demo_data()` → `packs/<pack>/synth/*.py`. 같은 시드에서 같은 행이 나오는지 대조 |
| M3 계산 | 비용식 · 정비 비용식 · DXF 규칙 · 견적식 → `formulas/` · `extractors/`. 기존 시험 케이스를 팩 시험으로 옮긴다 |
| M4 호환 경로 | 기존 경로(`/api/quality/predict` · `/api/maintenance/predict` · `/api/ml/overview` · `/api/data/records`)를 회사 호환 라우터로 제공. 옛 응답 키로 바꿔 준다. 6개월 뒤 제거 `[가설]` |
| M5 기준 대조 | 같은 합성 데이터 · 시드로 표준 플랫폼 지표가 기존 보고 수치(ks MAE 5.57h · sw MAE 0.557 · kd MAE 4.1h 등)와 분할 차이 범위 안인지 확인. 차이는 `docs/migration-report.md` 에 사유와 함께 적는다(평창 표본 내 평가 수치는 대조 대상에서 뺀다) |
| M6 병행 | 광성 VPS(:8013)는 표준 배포가 같은 VPS 에서 `live` 로 뜰 때까지 유지 후 중지 `[가설]` |

## 16. 검증 도구와 게이트

### 16.1 도구 (`gates/`)

| 도구 | 검사 |
|---|---|
| `check_core_terms` | `src/mlcore` · 콘솔 공용 코드에 팩 용어(`delta_e` · `ccp` · `shot_count` · `solder` …) 0건 (G1) |
| `check_task_cover` | 6벌 기존 기능 목록이 전부 `docs/task-map.md` 에서 과제에 대응 (G2) |
| `check_tasks` | 과제 YAML 스키마 · 변수 존재 · `uses` 존재 · 누수 규칙 · 승인 지점 보존 |
| `check_contract` | 켜진 모든 과제의 predict 응답이 §7.2 스키마와 일치(키 누락 0) (G4) |
| `check_leakage` | 시험 구간이 선정 · 보정 · 대기열에 쓰이지 않음. 시계열 과제가 시간순 분할 (G5) |
| `check_determinism` | 같은 스냅숏 + 시드 재학습의 시험 예측 차이 0 (G6) |
| `check_no_autopromote` | `production` 으로 바꾸는 코드 경로가 승인 처리기 하나뿐 (G9) |
| `check_sources` | 어댑터에 쓰기 SQL · 비 GET HTTP 0, DSN 이 읽기 계정 (§4.1) |
| `check_secrets` · `check_tenant_bleed` | 키 · `.env` · 남의 회사 데이터 파일 0 |
| `check_pins` | `uv.lock` · `package-lock.json` 존재, `latest` · 범위 버전 0 (G11) |
| `doctor` | 소스 실연결 · 대응률 · 기간 (G8) |

### 16.2 게이트

`make gate TENANT=<code>` 는 위 도구 전부 + pytest + 팩 기준선 회귀(합성 지표가 `baselines.yaml` 대비 5% 이상 나빠지면 실패)를 돌린다. 하나라도 실패하면 배포하지 않는다.

## 17. 비기능 요구사항

| 항목 | 기준 |
|---|---|
| 지연 | 단건 predict p95 ≤ 200ms(모델 적재 후), batch 500건 ≤ 3초, optimize 10,000점 ≤ 10초 |
| 기동 | 재학습 없이 기동 ≤ 15초(과제 10개 기준) |
| 자원 | app 메모리 ≤ 768MB · CPU 1 에서 위 지연 충족 `[기준: ks 배포]` |
| 가용성 | 소스가 죽어도 예측은 계속된다(소스는 학습 · 감시에만 쓴다). 과제 하나의 모델 오류가 다른 과제를 막지 않는다 |
| 보안 | HTTPS 프록시 뒤 배포 · DB 포트 비공개 · API 키 해시 저장 · 역할 · 회사 범위 · 감사 로그. CORS 는 설정 목록만 |
| 보존 | 예측 · 감사 1년, 집계 영구, 스냅숏 · 산출물은 `production` 이었던 버전은 영구 · 나머지 90일 `[가설 Q10]` |
| 배포 | 단일 `docker-compose.yml`(app · db) · 앱 포트 하나 · 헬스체크 필수 · 이미지 태그 = 커밋 SHA `[기준: ks]` |
| 언어 · 시각 | 한국어 문구 · 상태 코드 영문 · KST |
| 접근성 | 콘솔 대비 WCAG AA · 모바일 폭(현장 태블릿)에서 화면 2 · 3 사용 가능 |

## 18. 수용 기준 (이 명세의 완료 판정)

**1차:** 아래 1~8 을 팩 `press` · `textile`, 회사 `ks` · `sw`, 유형 4종, 화면 1~6 범위로 판정한다.
**2차:** 아래 전체. 2차 동안 `src/mlcore/` 변경은 0줄이어야 한다(바꿔야 하면 1차 결함으로 `decisions.md` 에 올린다).

1. 6개 근거 회사가 `tenants/*.yaml` 로 등록되고, 각 회사의 기존 기능이 전부 과제로 켜져 `make gate` 를 통과한다.
2. 업종 팩 6 + `_template` 이 있고, `docs/task-map.md` 대응률 100%.
3. 코어 금지어 0 · 비밀값 0 · 회사 오염 0 · 고정 안 된 의존성 0.
4. 모든 과제의 predict 응답이 표준 계약 시험을 통과하고, 기존 경로는 호환 라우터로 옛 키를 돌려준다.
5. 누수 검사 · 결정성 검사 통과. 모든 운영 모델이 기준선을 이긴 기록을 갖는다.
6. 재기동 시 재학습 0회. 예측 하나를 콘솔에서 모델 버전 → 스냅숏 → 원천 소스까지 추적한다.
7. 실데이터 소스가 있는 5개사가 `make doctor` 결과(연결 · 대응률 또는 `미연결` · `목표 없음` 사유)를 낸다. 최소 1개 과제가 실데이터 스냅숏 모델로 `production` 이 된다.
8. 드리프트를 일부러 넣은 시험 데이터에서 감시가 재학습 후보를 만들고, 승인 전에는 운영 모델이 바뀌지 않는다.
9. `make tenant NEW=yn PACK=_template` 로 새 회사를 코드 수정 없이 띄워 CSV 업로드 → 학습 → 승인 → 예측까지 하루 안에 끝낸다(시연 기록).
10. AI Agent 플랫폼이 `ml.predict` 도구로 한 과제를 불러 `prediction_id` 근거와 함께 답하고, 데이터 허브에서 그 과제가 ML 소비자로 보인다.
