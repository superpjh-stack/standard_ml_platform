# 계약 — 회사 등록부 `tenants/<code>.yaml` (Tenant Contract)

> **정본.** 출처: `spec.md` §11.2 · §11.3 · §4.1 · §10.2-5. 검사: `gates/check_registry.py`(G-S02) · `check_secrets.py` · `check_tenant_bleed.py`(G-S06).
> **회사 차이는 여기에만 둔다.** 원천 테이블 · 열 이름(`feature_map`), 소스 위치, 승인자, 호환 라우터 값. **비밀값은 환경변수 이름만**(`*_env`). 확인하지 못한 값은 `# 미확인` 주석과 함께 `null`.

## 1. 키

```yaml
code: sw                      # 필수. 허브 회사 코드(../Standard Data Hub/companies/<code>.yaml)와 같다. 파일 이름 = <code>.yaml
name: <회사명>                # 필수
pack: textile                 # 필수. packs/<pack> 존재
mode: demo                    # 필수. demo | eval | live — 1차 루프는 demo/eval 만 (D-13)
hub_company: sw
aliases: [...]               # 회사명 별칭 — 코어 · 팩 금지어 검사(G-M01)에 쓴다
tasks:
  enable: [sw.delta_e, ...]   # 필수. <code>.<pack 과제 이름>. 의존(uses) 과제도 켜져야 한다
sources:                      # role → 어댑터 설정. 값이 아니라 위치 · 환경변수 이름
  demo:    {kind: synthetic, seed: 42}       # 선택 tasks: {<과제>: {rows?, seed?}} — 과제별 합성 행 수 · 시드(pack-contract §4 우선순위, D2-45)
  eval:    {kind: csv, path: tests/fixtures/<code>/snapshot.csv}
  train:   {kind: dataplatform, view: <뷰 이름 # 미확인>, url_env: MLP_<CODE>_DP_URL, key_env: MLP_<CODE>_DP_KEY}
  actuals: {kind: mes, tables: [<허용목록>], dsn_env: MLP_<CODE>_MES_RO_DSN, read_role: <SELECT 전용 DB 역할 # 선택>}   # read_role(gateway · mes 선택) — 연결 직후 SET ROLE, 실패 → source_disconnected (D-88)
feature_map:                  # 원천 열 → 팩 변수. 원천 이름은 여기에만 (G-M01)
  <TABLE>.<COLUMN>: <팩 변수>
target_map: {<TABLE>.<COLUMN>: <과제 target>}
unmapped: {<팩 변수>: "<사유>"}   # 원천 대응이 없는 변수 — doctor 가 대응률 < 100% 경고
approvers: {<approver_role>: [<사람 · 역할 ID>]}
notify: {webhook_env: MLP_<CODE>_SLACK_WEBHOOK}
compat:                       # 호환 라우터(D-18)만 쓰는 회사 고유 값
  entity_prefix: "SW-DEMO-"
  routes: [/api/quality/predict, /api/ml/optimize, /api/ml/overview, /api/data/records]
  # 2차 객체 항목(api-contract §5 · D2-45): {path: "/api/cad/{id}", method: GET, action: document_get, task: <과제>, shape?, params?}
  #   회사 옛 모양은 tenants/<code>/compat.py 의 parse_<동작> · shape_<동작> (predict-contract §7.1) — 기동 때 T0 검사
  round: {delta_e: 3, risk_probability: 4}           # 옛 응답 반올림 자리(D-71 · D-W2-02). 없으면 반올림 안 함(위험 확률만 기본 4)
  optimize_rename: {delta_e: pred_delta_e}           # 선택 — 표준 예측 · 비용식 · 묶음 anomaly 과제 짧은 이름 → 옛 행 키 (anomaly 값 = production flag, 모델 없으면 null — D-132)
  # 아래는 모두 선택(D-132) — 원천 코드를 읽어 파일:줄 주석과 함께 적는다. 없으면 표준 이름 · 문구 그대로
  optimize_row: [set_temp, ..., cost_index, violation]   # 옛 추천 행 키 순서 — 있으면 이 키만 낸다
  optimize_derived: {reserve_hours: "remaining_hours - stop_after_hours"}   # 옛 키: 표준 이름 식(+ − × 만, 제약 식 검사기)
  optimize_row_round: {pred_delta_e: 4}               # 옛 행 키: 반올림 자리
  optimize_unmet_text: {max_delta_e: "<옛 문구>"}      # 제약 이름 → 옛 미충족 문구
  optimize_objective_text: "<옛 objective 문구>"
  optimize_anomaly_text: "<추천 행 anomaly 일 때 옛 경고 — warnings 맨 앞>"
  overview_values: {print_types: print_type}           # 옛 개요 키: 범주 변수(값 목록 = 팩 values 또는 회사 categories)
  overview_controls: controls                          # 옛 개요 키 이름: 조절 변수 목록
labels: {}                    # 회사 문구 덮어쓰기
```

## 2. 규칙

| # | 규칙 | 어기면 |
|---|---|---|
| T1 | `*_env` · `*_dsn_env` · `key_env` 는 `^MLP_[A-Z0-9_]+$` 이름. 값(URL · DSN · 키 · IP · 호스트)을 적지 않는다 | G-S06 FAIL |
| T2 | 다른 회사 코드 · 회사명 · 데이터 파일 경로가 없다(`tests/fixtures/<자기 code>/` 만) | G-S06 FAIL |
| T4 | 새 회사 연습(G-M10 · spec §17-9 "CSV 업로드")의 CSV 는 **커밋하지 않는다.** 시험이 `migration/make_fixtures.py --kind template_csv --out <tmp>` 로 만들고, 임시 등록부 폴더에서 `make tenant` 가 만든 `tenants/yn.yaml` 의 `sources.eval.path` 가 그 파일을 가리킨다. 1차에는 `tenants/yn*` · `tests/fixtures/yn/` 을 커밋하지 않는다("빈 폴더에서 처음부터" 를 되풀이할 수 있게 — D-51) | G-S06 · G-M10 |
| T3 | 병합 규칙 5(spec §11.3) — 아래 | 기동 거부(G-S02) |
| T5 | 등록부 루트는 저장소 `tenants/` 가 기본이고, 시험 · 새 회사 연습만 `MLP_TENANTS_DIR`(`os.pathsep` 목록)로 바꾼다. 해석 규칙은 `interfaces.md` §10 하나(D-65) | 시험 오염 · FileNotFound |

### 2.1 병합 규칙 5 (기동 거부)

| # | 규칙 | 불량 픽스처 (`tests/fixtures/bad_registry/`) |
|---|---|---|
| R1 | 덮어쓰기로 `type` · 누수 규칙(`split` · `time_key` · `group_key`) · 승인 지점(`approver_role`)을 바꿀 수 없다 | `r1_override_type.yaml` |
| R2 | 켜진 과제의 필수 `features` 가 `feature_map` 또는 합성 소스로 전부 채워진다(필수 누락 → 거부, 선택 누락 → doctor 경고) | `r2_missing_required_feature.yaml` |
| R3 | `uses` 의 의존 과제가 켜져 있다 | `r3_uses_disabled.yaml` |
| R4 | `mode: live` 인데 production 이 합성 스냅숏이면 그 과제만 끄고 `model_not_ready` | `r4_live_synthetic.yaml` (기동은 하되 해당 과제 disabled — 검사 기대값 명시) |
| R5 | 같은 이름 · 다른 구현의 플러그인(비용식 · 추출기) 금지 | `r5_plugin_conflict.yaml` |

R4 는 "기동 거부" 가 아니라 "과제 끄기" 다(spec §11.3-4). G-S02 의 "불량 픽스처 5종은 전부 기동 거부" 와 어긋난다 → `decisions.md` D-27.

## 3. 2차 — 회사 4 (krs · pc · ot · kd) (Phase P0 아키텍트, goal2 §1 · §7)

| 회사 | 팩 | mode | 소스 | 과제(enable) | 회사 값(등록부에만) |
|---|---|---|---|---|---|
| `krs` | `solder` | demo | `demo: synthetic`(seed 20260917, rows 720) · `eval: csv` — **`live` 불가**(실데이터 없음, D2-01 — `sources.train` 을 두지 않고 doctor 는 "live 불가 (D2-01)") | joint_strength · recipe_optimize · residual_review | `categories.supplier`(원천 A · B · C) · `compat.entity_prefix: "KS-"`(1차 ks 와 겹침 주의 — source_inventory K7) |
| `pc` | `kimchi` | demo | `demo: synthetic`(seed 42, rows 420) · `eval: csv` | sensory_score · recipe_optimize · residual_review | `categories.cabbage_origin` · `categories.line` · `compat.entity_prefix: "PC-K-"` |
| `ot` | `rollform-quote` | demo | `demo: synthetic`(seed 42, 작업 900 · 설명자 1,600) · 문서 = 업로드(B10) | machining_minutes · cad_objects · quote | `categories.material` · `categories.profile` · 견적 `rates` 덮어쓰기(단가 — 원천 예시값, 승인 단가 아님) |
| `kd` | `eto` | demo | `demo: synthetic`(seed 42, 900) · 문서 = 업로드(B10) | labor_hours · drawing_regions · quote | `categories.material`(8) · `categories.product`(6) · `material_aliases`(STS=SUS 통합 — 고객 회신 D-160 ②, 팩이 아니라 회사 값) · 견적 `rates` |

- 등록부 키는 §1 그대로다. 2차에 **새 최상위 키는 `material_aliases` 하나**(선택 — 범주 값 정규화 표 `{<별칭>: <정규 값>}`, 추출기 · 견적 입력 검증 전에 적용). 웨이브 P 개발3 이 로더에 넣는다.
- 과제 덮어쓰기(`tenants/<code>/tasks/<task>.yaml`)로 대기열 `rule` 값 · 견적 `rates` 값 · `document` 상한(낮추기만)을 바꿀 수 있다(`task-contract.md` §6.4).
- 4개사 모두 1차와 같이 `demo` 로 기동한다. 실데이터 키가 들어오기 전 `live` 는 없다(D-13 · G2-L01).
- 회사 등록부 · 팩에 원천 저장소의 고객사명 · 사업자번호 · 포트 · 주소를 옮기지 않는다(D-20, source_inventory D4).
