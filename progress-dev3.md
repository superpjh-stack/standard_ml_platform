# progress-dev3.md — 개발3 (팩 · 회사 · 감시 · 이관)

## §1 공표 — 합성 생성기 노출 (웨이브 A0, 2026-10-12)

개발1 의 synthetic 어댑터가 쓴다. 계약과 다른 점은 `decisions.md` D-53(계약 불일치).

### 생성 함수 (팩 쪽, `packs/<pack>/synth/*.py`)

```python
def generate(rows: int = <pack.yaml synth.rows>, seed: int = <pack.yaml synth.seed>, *,
             categories: dict[str, list[str]] | None = None) -> pandas.DataFrame
```

- 반환 열: `entity_id`(`DEMO-0001`…) · `ts`(tz `Asia/Seoul`, 1시간 간격) · `features.yaml` 변수 · **목표 열(과제 `target.name` 이름)**.
  팩 안 과제가 생성기를 공유하면 목표 열이 여럿이다 — press: `remaining_hours` · `failure_24h`, textile: `delta_e` · `defect`, _template: `target_value` · `target_risk`.
  표준 프레임의 `target` · `tenant_id` · `task_id` · `_source` · `_source_ref` 열은 어댑터가 만든다(`target` ← 과제 `target.name` 열, anomaly 는 목표 없음).
- `categories`: 회사 등록부 `categories`(`values_from: tenant` 범주). 없으면 팩 중립 값(press `M1~M4` · `P1~P3`). textile · _template 은 받기만 하고 쓰지 않는다.
- 모듈 해석: 과제 진입점 `synth/<task>.py` 가 있으면 그것, 없으면 `pack.yaml synth.module`(공용). A0 진입점: `press/synth/remaining_hours.py` · `textile/synth/delta_e.py` (공용 모듈을 그대로 내보낸다).
  공용 모듈(`press_lots.py` · `print_lots.py` · `template_rows.py`)은 상대 import 가 없어 **`pack.yaml synth.module` 을 파일 경로로 바로 읽어도 된다**(개발1 `SyntheticSource(pack_dir, module, …)` 그대로 동작). 진입점까지 쓰려면 아래 로더를 쓴다.

### 로더 (코어 쪽, `mlcore.registry`)

```python
# mlcore/registry/packs.py
@dataclass(frozen=True)
class SynthSpec: pack: str; task: str | None; path: Path; seed: int; rows: int
def synth_spec(pack: Pack, task: str | None = None) -> SynthSpec      # 과제 → 실제 .py 경로 · pack.yaml 시드 · 행 수
def load_synth(pack: Pack, task: str | None = None) -> Callable        # generate 함수 (synth/ 를 패키지로 import)
# load_pack() 은 이제 pack.yaml synth.module 파일 존재 · seed/rows 정수를 검사한다(없으면 PackInvalid)

# mlcore/registry/tenants.py
@dataclass(frozen=True)
class SynthCall:
    tenant_id: str; task_id: str; spec: SynthSpec; seed: int; rows: int
    categories: dict[str, list[str]]; target: str | None; source_ref: dict
    def generate(self, rows: int | None = None, seed: int | None = None) -> pandas.DataFrame
def synth_call(merged: Merged, task_id: str, role: str = "demo") -> SynthCall
    # 시드: tenants/<t>.yaml sources.<role>.seed > pack.yaml synth.seed · rows: sources.<role>.rows > pack.yaml synth.rows
    # role 소스가 synthetic 이 아니면 ValueError, 켜진 과제가 아니면 KeyError
    # source_ref = {kind: synthetic, role, module: <저장소 상대 경로>, seed, rows, synth_sha256: <synth/*.py 묶음 해시>}
```

사용 예: `call = tenants.synth_call(tenants.load_and_merge("ks"), "ks.remaining_hours"); raw = call.generate()` → `raw[call.target]` 이 목표.

### fixture (`tests/fixtures/{ks,sw}/`)

`snapshot.parquet`(생성기 출력 그대로, 720행 · 13열) · `snapshot.csv`(같은 내용, UTF-8 BOM, `ts` 문자열 `+09:00`) — `sources.eval` 이 가리킨다. 생성 `uv run python migration/make_fixtures.py --tenant all --kind all`.

## §1.2 공표 — 과제 8 정의 완성 (웨이브 A, 2026-10-12) — 개발2 optimize 가 쓴다

정의 파일은 `packs/{press,textile}/tasks/*.yaml` (계약 `task-contract.md` §2 · §4 스키마 통과, `gates/check_tasks.py` G-M03 PASS). 원천 값과 대조는 `packs/*/tests/test_*_formulas.py`(손 계산 기대값).

| 회사 과제 | 유형 | 핵심 |
|---|---|---|
| `ks.remaining_hours` | regression | 변수 9 · `time_60_20_20` · 후보 ridge · random_forest · extra_trees · gbr · interval split_conformal α 0.1 · clip min 0 |
| `ks.failure_24h` | risk | 목표 `failure_24h` positive 1 · review_prob 0.5 · 후보 logreg · rf_clf · gbc |
| `ks.sensor_ood` | anomaly | contamination 0.08 · isolation_forest |
| `ks.maintenance_timing` | optimize | 아래 |
| `sw.delta_e` | regression | 변수 9 · review_above 3.5 · 후보 4 (gbr 200/3/0.05) |
| `sw.defect_risk` | risk | 목표 `defect` · review_prob 0.5 · logreg max_iter 1000 |
| `sw.print_ood` | anomaly | contamination 0.08 |
| `sw.print_setpoint` | optimize | 아래 |

### optimize 2 — 개발2 `tasks/optimize.py` 가 읽는 키

| 키 | `ks.maintenance_timing` | `sw.print_setpoint` |
|---|---|---|
| `uses` | `[press.remaining_hours]` | `[textile.delta_e, textile.defect_risk]` |
| `controls` | `[]` (센서는 조절 안 함) | `set_temp · set_pressure · line_speed · ink_usage · dwell_time` (학습 범위 ∩ min/max, step 10 · 1 · 3 · 4 · 15) |
| `fixed` | 변수 9 전부 (요청 `fixed`) | `absorb_rate · fabric_strength · print_type · color_tone` |
| `decision_vars` | `stop_after_hours: {min 0, max_param: max_delay_hours, step 0.5}` — 모델 입력 아님, 학습 범위 없음 | 없음 |
| `params` (요청 · 기본 · 범위) | `reserve_hours` 12 [1,150] · `max_delay_hours` 48 [0,72] · `max_cost_index` 140 [1,500] | `max_delta_e` 2.5 [0.5,8] · `max_risk` 0.2 [0.01,0.9] · `min_line_speed` 12 [6,24] |
| `formulas` | `maintenance_cost` → `packs/press/formulas/maintenance_cost.py::cost(row, params)` — row 키 `stop_after_hours` · `remaining_hours` | `process_cost` → `packs/textile/formulas/process_cost.py::cost(row, params)` — row 키 `ink_usage` · `line_speed` · `set_temp` · `dwell_time` |
| `objective` | minimize `maintenance_cost`, tiebreak maximize `stop_after_hours` | minimize `process_cost`, tiebreak minimize `delta_e` |
| `constraints` | `remaining_hours - stop_after_hours >= reserve_hours` · `maintenance_cost <= max_cost_index` | `delta_e <= max_delta_e` · `defect_risk <= max_risk` · `line_speed >= min_line_speed` |
| `search` | grid · max_points 10000 (max_delay 48 → 97점) | grid · max_points 10000 (원천 8,400점 · 표준은 학습 범위 교차로 줄어든다 — D-31) |
| `on_infeasible` | least_violation | least_violation |

- 식 안 이름: `remaining_hours` · `delta_e` 는 uses 과제의 **짧은 이름**(회귀 = 예측값), `defect_risk` 는 risk 과제 짧은 이름(= 확률). 원천 ks 는 `L` 을 소수 2자리로 반올림한 뒤 비용을 계산했다(호환 라우터만 재현). sw 원천은 비용을 소수 2자리로 반올림(호환 라우터만).
- violation 정규화: 계약 `Σ max(0, 위반량) / max(|rhs|, 1e-9)` — 원천 `max(reserve,1)` · `max(max_risk,.01)` 과 요청 하한(1 · 0.01) 때문에 같은 값.
- 원천 sw 는 추천 조건이 이상 탐지(IsolationForest)에 걸리면 "시험 인쇄" 경고를 붙였다. 계약 `uses` 는 anomaly 과제 값을 정의하지 않아 옮기지 못했다 → `decisions.md` D-W3-01(계약 보강 요청).

## §2 A0 실측 (2026-10-12)

| 항목 | 실측 | 명령 |
|---|---|---|
| 과제 정의 | `press.remaining_hours` · `textile.delta_e` + 두 팩 `features.yaml` — 원천 조사(§1.2-1.3 · §2.2-2.3)와 같다(변수 9 · 범위 · step · 후보 4 · 하이퍼파라미터 · 시간순). 변경 없음, 계약 스키마 통과 | `tests/test_packs_registry.py` |
| 생성기 | press · textile · _template 공용 모듈 3 + 과제 진입점 2 | `ls packs/*/synth/*.py` |
| 시험 | **31 passed** (test_synth 20 · test_packs_registry 11), 2.3 s | `OMP_NUM_THREADS=1 uv run pytest -q` |
| ks 원천 대조 | 행 720 · 결측 24 · 중복 0 · 범위 밖 0 · 챔피언 GBR / RF · 검증 MAE 5.213 · R² 0.9143 · 시험 **MAE 5.568 · RMSE 6.979 · R² 0.9199 · AUC 0.6444 · AP 0.1426 · Brier 0.0576 — 8값 자리수 일치** | `tests/test_synth.py` (근거 `KwangSung ML AI/docs/verification.md:30-34` · `tests/test_api.py:25,27`) |
| sw 원천 대조 | 행 720 · 결측 24 · 중복 0 · 범위 밖 0 · 불량률 31.5% · DTF/연한 색상 41건 · 챔피언 ET / GBC · 검증 MAE 0.520 · R² 0.752 · 시험 **MAE 0.557 · RMSE 0.709 · R² 0.722 일치**. 불량 AUC 0.8686 · AP 0.7823 · Brier 0.1261 (문서 0.868 · 0.781 · 0.127, 차이 ≤ 0.0013 — D-52) | 같은 파일 (근거 `SongWol ML AI/docs/verification.md:18,23-24`) |
| 범주 중립성 | 팩 중립 범주(`M1~M4` · `P1~P3`)로 만든 행을 ks 범주로 바꾸면 ks 프레임과 완전히 같다 | `test_neutral_categories_give_same_rows_as_tenant` |
| fixture 결정성 | 2회 생성 해시 같음 — ks parquet `bc49ed49…` · csv `3f6a10ce…`, sw parquet `360751ef…` · csv `c3ff085a…` | `uv run python migration/make_fixtures.py --tenant all --kind all` |
| gate 변화 | G-M03 **FAIL(synth 위반 3) → PASS**. G-S02 · G-M01 · G-S06(2행) PASS 유지. G-M12 사유 "합성 생성기 미이관 ['press','textile']" → `[]` (migration-report 는 A). 합계 PASS 6 → 7 | `make gate` |

## §2.1 웨이브 A 실측 (2026-10-12, 기준 커밋 7d583cf, 커밋 안 함)

| 항목 | 실측 | 명령 |
|---|---|---|
| 과제 8 정의 | 8/8 계약 스키마 통과 · optimize 2 비용식 원천 손 계산 대조(ks 6점 · sw 4점 + 반올림 77.96) · 공간 ks 97점 · sw 원천 격자 8,400 | `uv run python gates/check_tasks.py` · `uv run pytest -q packs/` (14 passed) |
| G-M02 task-map | 32/32 (ks 16 · sw 16) · 미대응 0 | `uv run python gates/check_task_cover.py` |
| G-M12 이관 대조 | 4과제 12지표 ±10% 안(최대 −0.71% sw Brier) · 표준 재현 ks MAE 5.5683 · RMSE 6.9793 · R² 0.9199 · AUC 0.6444 · AP 0.1426 · Brier 0.0576 / sw MAE 0.5569 · RMSE 0.7088 · R² 0.7222 · AUC 0.8686 · AP 0.7823 · Brier 0.1261 · anomaly flag ks 0.1389 · sw 0.1458(밴드 안) · optimize ks 후보 97 = 97 · 충족 89 / sw 1,080(원천 8,400 — D-31 사유) · 충족 314(원천 1,054). 2회 실행 JSON 바이트 같음 | `OMP_NUM_THREADS=1 uv run python migration/reproduce.py` (3 s) · `uv run python gates/check_migration.py` |
| 감시 | PSI 손 계산 3사례(5.248899 · 0.6·ln2.5 · 0) · drift PSI 9+9 변수 = 순수 파이썬 계산(rel 1e-9) · ks vibration 5.598 / sw absorb_rate 5.367 retrain · 나머지 < 0.2. 드리프트 → 접수(run_id) → 작업자 candidate v2 → 감시 stage → 승인 요청 pending(requested_by monitor) · production v1 그대로 · 두 번째 요청 0. 예측 모드 volume 6 · live_perf MAE 10.0(실측 연결 6) | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_monitor.py` (15 passed, 2.5 s) |
| doctor | ks · sw demo/eval 연결 720행 · 대응률 100% · 결측 각 8/720 · train/gateway/actuals 미연결(D-13) · 정적 대응률 ks 66.7% · sw 77.8% · ks 목표 없음(D-33) · CSV 없음 → 미연결 · 목표 열 없음 → 목표 없음 · 출력에 환경변수 값 0 | `uv run python -m mlcore.monitor.doctor --tenant ks` · `uv run pytest -q tests/test_doctor.py` (7 passed) |
| 새 회사 | 빈 등록부 → `make_tenant --new yn<hex> --pack _template --csv <tmp>` → seed 1회사 2과제 → doctor eval 600행 → train(eval) ×2 → stage → promote → decide → predict 18키 · synthetic=false. 생성 파일 = 등록부 루트의 `<code>.yaml` 1개, 저장소 tenants · fixtures · var 에 0 | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_new_tenant.py` (3 passed) |
| API (B02 · B06 · B12 · B14 · doctor) | 6 시험: 목록 4과제 · 폼 메타(values_from → 회사 값) · overview(production 없음 = null · model_ready false) · 감시 경고 배지 · records cursor 페이징 720 · 잘못된 cursor 422 · viewer 감시 403 · 다른 회사 키 404 ×6 경로 | `OMP_NUM_THREADS=1 uv run pytest -q tests/test_ops_api.py` |
| 원천 DB 사본 (D-W1-10) | `tests/fixtures/{ks,sw}/source_db.sql` — 테이블 3+3 · 720행 · 대응 열 값 = snapshot(오차 0) · 재생성 바이트 같음 | `uv run pytest -q tests/test_fixture_source_db.py` (4 passed) |
| 화면 1 · 6 | `Overview.tsx`(서버 · 과제표 · 운영 버전/`운영 모델 없음 (model_not_ready)` · 합성 배지 · 어제 예측 · 승인 대기 · 감시 배지 · 대상 데이터 표 · CSV BOM/수식 주입 방지) · `Monitor.tsx`(변수별 PSI · 범위 밖 · 결측 추이 · 실측 성능/`실측 없음` · 재학습 후보 → 승인 대기열 링크 · doctor 표). `_placeholder` 0 | `cd web && npx tsc -b && npm run build` (성공) |
| 전체 시험 | **375 passed · 3 failed · 3 skipped** (41 s). 실패 3 = 다른 담당: `test_api_contract.py` B08 `GET /runs/{id}` 미구현(개발1) · `test_compat.py` 옛 키 반올림 2(개발2). 건너뜀 3 = test_compat 케이스 없음(개발2). 개발3 시험 실패 0 | `OMP_NUM_THREADS=1 uv run pytest -q` |
| make gate | **PASS 18 · FAIL 5 · BLOCKED 1** (전 PASS 11). 개발3 몫 **G-M02 · G-M08 · G-M09 · G-M10 · G-M12 FAIL → PASS**. 기존 PASS 유지. 남은 FAIL: G-S03(e2e 없음) · G-S04(B08) · G-M04(compat) · G-M11(compose) · G-M14(bench) — 개발3 담당 아님 | `OMP_NUM_THREADS=1 uv run python gates/gate.py` |

## §3 요청 · 남은 일

요청:
- **아키텍트**: `Makefile` `doctor` · `tenant`(CSV 인자) · `monitor` 대상 연결(D-W3-07). D-W3-01 ~ 08 결정(특히 D-W3-02 감시의 staging, D-W3-04 덧붙인 API 키). D-52 · M5 뒤 `baselines.yaml` 값 기입 — 재현값은 위 표(`migration/reproduce.py`).
- **개발2**: `api/main.py` 에 `ops.router` 등록 — 반영된 것 확인(`include_router(ops.router)`). `tests/_dev2.py::use_tenants_dir` 의 환경변수 되돌리기(D-W1-06 개발2 몫).
- **개발1**: D-W1-06 개발3 몫 고침(`registry.tenants.tenant_base` = `tenants_base_for` 규칙). D-W1-10 원천 DB 사본 `tests/fixtures/<t>/source_db.sql` 제공 — 모양은 개발1 시험의 사본과 같다(`FX_KEY` · `FX_AT` · 등록부 대응 열, 스키마 없음 → `SET search_path`). gateway 원장(EIF_PLC_RAW · PRC_MONITOR_DATA) 사본이 필요하면 모양(열 · 창)을 알려 주면 만든다.

남은 일:
- 화면 1 · 6 실제 브라우저 확인(1024px 포함) — e2e(G-S03)는 QA3 · 개발2 Playwright(D-40) 뒤.
- `compat_expected.json`(G-M04, 개발2 요청 시) · 스케줄러 상주 실행 운영 문서 · 감시 `source_health` 지표(doctor 결과를 일일 행으로).
- D-W3-01 이 정해지면 `print_setpoint.yaml` 에 이상 경고 키.


