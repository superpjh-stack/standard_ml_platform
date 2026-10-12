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
  demo:    {kind: synthetic, seed: 42}
  eval:    {kind: csv, path: tests/fixtures/<code>/snapshot.csv}
  train:   {kind: dataplatform, view: <뷰 이름 # 미확인>, url_env: MLP_<CODE>_DP_URL, key_env: MLP_<CODE>_DP_KEY}
  actuals: {kind: mes, tables: [<허용목록>], dsn_env: MLP_<CODE>_MES_RO_DSN}
feature_map:                  # 원천 열 → 팩 변수. 원천 이름은 여기에만 (G-M01)
  <TABLE>.<COLUMN>: <팩 변수>
target_map: {<TABLE>.<COLUMN>: <과제 target>}
unmapped: {<팩 변수>: "<사유>"}   # 원천 대응이 없는 변수 — doctor 가 대응률 < 100% 경고
approvers: {<approver_role>: [<사람 · 역할 ID>]}
notify: {webhook_env: MLP_<CODE>_SLACK_WEBHOOK}
compat:                       # 호환 라우터(D-18)만 쓰는 회사 고유 값
  entity_prefix: "SW-DEMO-"
  routes: [/api/quality/predict, /api/ml/optimize, /api/ml/overview, /api/data/records]
labels: {}                    # 회사 문구 덮어쓰기
```

## 2. 규칙

| # | 규칙 | 어기면 |
|---|---|---|
| T1 | `*_env` · `*_dsn_env` · `key_env` 는 `^MLP_[A-Z0-9_]+$` 이름. 값(URL · DSN · 키 · IP · 호스트)을 적지 않는다 | G-S06 FAIL |
| T2 | 다른 회사 코드 · 회사명 · 데이터 파일 경로가 없다(`tests/fixtures/<자기 code>/` 만) | G-S06 FAIL |
| T3 | 병합 규칙 5(spec §11.3) — 아래 | 기동 거부(G-S02) |

### 2.1 병합 규칙 5 (기동 거부)

| # | 규칙 | 불량 픽스처 (`tests/fixtures/bad_registry/`) |
|---|---|---|
| R1 | 덮어쓰기로 `type` · 누수 규칙(`split` · `time_key` · `group_key`) · 승인 지점(`approver_role`)을 바꿀 수 없다 | `r1_override_type.yaml` |
| R2 | 켜진 과제의 필수 `features` 가 `feature_map` 또는 합성 소스로 전부 채워진다(필수 누락 → 거부, 선택 누락 → doctor 경고) | `r2_missing_required_feature.yaml` |
| R3 | `uses` 의 의존 과제가 켜져 있다 | `r3_uses_disabled.yaml` |
| R4 | `mode: live` 인데 production 이 합성 스냅숏이면 그 과제만 끄고 `model_not_ready` | `r4_live_synthetic.yaml` (기동은 하되 해당 과제 disabled — 검사 기대값 명시) |
| R5 | 같은 이름 · 다른 구현의 플러그인(비용식 · 추출기) 금지 | `r5_plugin_conflict.yaml` |

R4 는 "기동 거부" 가 아니라 "과제 끄기" 다(spec §11.3-4). G-S02 의 "불량 픽스처 5종은 전부 기동 거부" 와 어긋난다 → `decisions.md` D-27.
