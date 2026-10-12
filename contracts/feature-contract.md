# 계약 — 변수 사전 `packs/<pack>/features.yaml` (Feature Contract)

> **정본.** 출처: `spec.md` §3.1 · §5.1 · §7.3 · §8.1. 검사: `gates/check_tasks.py`(G-M03) · `gates/check_core_terms.py`(G-M01).
> 입력 폼 · 입력 검증 · 결측 보정 · 학습 범위 판정 · 최적화 공간은 **전부 이 파일에서 나온다**. 코드 안 `FEATURE_META` dict 는 0 이어야 한다(G-M03).

## 1. 모양

```yaml
# 최상위: <변수 이름>: {키...}  +  예약 키 std_name
<name>:
  label: 사람이 읽는 이름          # 필수
  dtype: float | int | category | bool   # 필수
  unit: "℃"                         # 수치 필수(무차원은 "-")
  min: 150                          # 수치 필수 — 입력 검증 범위(물리적으로 가능한 값)
  max: 210
  values: [..]                      # category 필수 (또는 values_from)
  values_from: tenant               # 범주 값 목록이 회사마다 다를 때(설비 코드 등) — tenants/<code>.yaml: categories.<name> 에서 받는다
  default: 180                      # 폼 기본값(선택)
  required: true                    # 필수 · 기본 true. false 면 impute 로 보정
  impute: median | most_frequent | none   # required:false 일 때. 기본 수치 median · 범주 most_frequent
  controllable: false               # 최적화 대상 여부. 기본 false
  step: 1                           # controllable:true 면 필수 — 탐색 간격
  integer: false                    # true 면 소수 거부(원천 ks shot_count)
std_name: {<name>: <허브 std/fields.yaml 이름>, ...}   # 선택
```

## 2. 규칙

| # | 규칙 | 검사 |
|---|---|---|
| F1 | 변수 이름은 소문자 `snake_case`, 팩 안에서 유일 | check_tasks |
| F2 | 수치는 `min < max`, `default` 는 `[min, max]` 안 | check_tasks |
| F3 | `controllable: true` 면 `step > 0`, 공간 크기 = Π floor((max-min)/step)+1 을 계산할 수 있어야 한다 | check_tasks |
| F4 | 원천 테이블 · 열 이름(대문자 `XXX_YYY.ZZZ` 꼴) · 회사 코드 · 회사명 0 | check_core_terms |
| F5 | 과제 `features` 의 모든 이름이 이 파일에 있다 | check_tasks |
| F6 | `values` 는 문자열. 회사 고유 코드(설비 코드 · 품목명 등)는 `values` 에 넣지 않고 `values_from: tenant` 로 두며, 값은 `tenants/<code>.yaml: categories` 에 둔다 | check_core_terms · check_registry |

## 3. 세 가지 범위

| 범위 | 출처 | 쓰임 | 벗어나면 |
|---|---|---|---|
| 검증 범위 | `features.yaml` `min` / `max` | 입력 검증 | 422 `out_of_bounds` |
| 학습 범위 | 스냅숏 `ranges` 변수별 p1 / p99 (범주는 본 값 목록) | 범위 판정 · 최적화 공간 | 200 `out_of_range`(또는 `rejected`) |
| 탐색 공간 | 학습 범위 ∩ 검증 범위, `step` 격자 | `optimize` | 만들지 않는다 |

학습 범위 근접(`near_range`)은 p1~p99 폭의 2% 안쪽 가장자리다.

## 4. 범주 변수

범주 값이 검증 범위의 `values`(또는 `values_from: tenant` 면 회사 `categories`) 밖이면 422 `out_of_bounds`(detail.rule = `values` — 수치 min/max 밖과 같은 "있을 수 없는 값", D-55), 문자열이 아니면 422 `invalid_input`, 학습 스냅숏에서 본 적 없는 값이면 `out_of_range_fields` 에 넣는다(OneHot `handle_unknown="ignore"`).
