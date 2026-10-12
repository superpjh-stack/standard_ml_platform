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

## §3 남은 일

- 웨이브 A: `docs/migration-report.md`(G-M12, 행 일치 100% · 8과제 대조) · drift.parquet · psi_hand.json · source_db.sql · compat_expected.json · `tests/fixtures/yn/`(D-51) · `make doctor` · `make tenant` · 감시.
- 아키텍트: D-53 을 pack-contract §4 에 반영 · D-52 사람 확인.
