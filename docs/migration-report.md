# 이관 대조 보고서 — 기존 ML 6벌 → 표준 플랫폼 (G-M12 · M5) — 1차 ks · sw (§0~§6) · 2차 krs · pc · ot · kd (§7~§12)

> 이관 도구 M1~M5 산출물(개발3, 2026-10-12, 웨이브 A). 검사 `gates/check_migration.py`. 허용폭 **±10%**(D-17 — 넓힐 수 없다), 벗어나면 행마다 사유.
> 원천 보고값: `migration/source_inventory.md` §1.4 · §1.5 · §2.4 · §2.5 (원천 `docs/verification.md` 실측 — 원천 코드는 **읽기만**, 실행하지 않았다).
> 표준 재현값: `OMP_NUM_THREADS=1 uv run python migration/reproduce.py` — 개발1 `StandardTrainer` 로 회사 `demo`(합성, 시드 42) 를 시간순 432/144/144 로 학습한 **시험 구간 1회** 지표. optimize 는 같은 도구가 표준 규칙으로 격자를 센 값.
> **표본 내 평가 수치는 쓰지 않는다**: 학습 구간 · 재적합 표본에서 잰 지표는 어느 칸에도 없다. 검증 구간 값은 선정 근거로만 §2 에 적는다.

## 0. 요약

- 행 일치: 100% — ks · sw 의 팩 합성 생성기(`packs/{press,textile}/synth/`)가 원천 `demo_data()` 와 같은 시드에서 같은 행을 낸다(근거 §3).
- 과제 8 중 원천 보고 지표가 있는 4과제 12지표 전부 ±10% 안(최대 차이 0.71%). 보고 지표가 없는 4과제(이상 탐지 2 · 최적화 2)는 행마다 사유와 표준 지표를 적었다.
- 표준에서 새로 생긴 것: 모든 지표의 기준선 비교 · 회귀 예측 구간 · 이상 탐지 임계값의 검증 구간 보정 · 최적화 탐색점의 학습 범위 제한.

## 1. 대조표 (과제 8)

| 과제 | 유형 | 챔피언 원천 → 표준 | 표준 재현 (시험) | 원천 보고 (시험) | 차이 | 판정 · 사유 |
|---|---|---|---|---|---|---|
| ks.remaining_hours | regression | Gradient Boosting → `gbr` | mae = 5.5683 · rmse = 6.9793 · r2 = 0.9199 (기준선 MAE 21.219, 구간 포함률 0.882) | MAE 5.568 · RMSE 6.979 · R² 0.9199 | +0.01% · +0.00% · 0.00% | 통과 (±10% 안) |
| ks.failure_24h | risk | Random Forest → `rf_clf` | roc_auc = 0.6444 · pr_auc = 0.1426 · brier = 0.0576 (기준선 Brier 0.0586 · AUC 0.5) | ROC AUC 0.6444 · AP 0.1426 · Brier 0.0576 | 0.00% · 0.00% · 0.00% | 통과. 기준선(학습 양성률)과의 차이가 작다 — 합성 사건이 드물어(시험 양성 6.25%) 분류력이 약한 것은 원천도 같다(원천 문서 "우수하다고 주장하지 않음") |
| ks.sensor_ood | anomaly | IsolationForest → `isolation_forest` | flag_rate = 0.1389 (contamination 0.08 · 기준선 밴드 [0.04, 0.16] 안 → 기준선 이김) | 보고 없음 | — | 대조 불가 · 사유: 원천은 이상 탐지 지표를 보고하지 않았다(`verification.md` 에 오염률 설정만). 임계값은 원천(라이브러리 기본 = 학습+검증 표본 내 분위)과 달리 학습 구간 모델의 검증 구간 점수 0.92 분위(D-50) |
| ks.maintenance_timing | optimize | 1차원 격자 → 표준 격자(결정 변수) | 후보 97 · 충족 89 · 추천 `stop_after_hours` 48.0 h · 비용지수 60.0 (요청 12 h · 48 h · 140) / 불가능 요청(150 · 48 · 1) → 충족 0 · least_violation | 후보 97 · 충족 있음 (`tests/test_api.py:93`) / 불가능 요청 → 충족 0 · 위반 → 비용 → 늦은 시점 순 | 후보 수 0% | 통과 · 사유: 원천은 충족 수를 보고하지 않아 후보 수 · 가능/불가능 판정만 대조. 결정 변수는 학습 범위가 없어(D-25) 점 수가 같다. 원천은 잔여수명을 소수 2자리로 반올림한 뒤 비용을 계산(호환 라우터만 재현) |
| sw.delta_e | regression | Extra Trees → `extra_trees` | mae = 0.5569 · rmse = 0.7088 · r2 = 0.7222 (기준선 MAE 1.087, 구간 포함률 0.896) | MAE 0.557 · RMSE 0.709 · R² 0.722 | −0.02% · −0.03% · +0.03% | 통과 (±10% 안) |
| sw.defect_risk | risk | Gradient Boosting → `gbc` | roc_auc = 0.8686 · pr_auc = 0.7823 · brier = 0.1261 (기준선 Brier 0.2051) | ROC AUC 0.868 · AP 0.781 · Brier 0.127 | +0.07% · +0.17% · −0.71% | 통과 (±10% 안). D-52 행 §4 — 문서값과 소수 넷째 자리 차이(≤ 0.0013) |
| sw.print_ood | anomaly | IsolationForest → `isolation_forest` | flag_rate = 0.1458 (contamination 0.08 · 밴드 [0.04, 0.16] 안 → 기준선 이김) | 보고 없음 | — | 대조 불가 · 사유: 원천 보고 지표 없음. 임계값 규칙 D-50(ks.sensor_ood 와 같다). 시험 flag 가 c 의 1.8배인 것은 시험 구간 분포 이동으로 보이며 학습 보고서 경고로 남는다 |
| sw.print_setpoint | optimize | 5차원 전수 격자 → 표준 격자(학습 범위 ∩ min/max) | 후보 1,080 (6 × 3 × 5 × 4 × 3) · 충족 314 · 추천 150 ℃ · 4 bar · 18 m/min · 14 g/m² · 65 s · 비용지수 60.25 (요청 ΔE ≤ 2.5 · 위험 ≤ 0.2 · 속도 ≥ 12) / 불가능 요청(0.5 · 0.01 · 24) → 충족 0 · least_violation | 후보 8,400 (8 × 5 × 7 × 6 × 5) · 충족 1,054 / 불가능 → 충족 0 | 후보 −87.1% · 충족 −70.2% | ±10% 밖 · 사유: 탐색 공간 규칙 차이(D-31) — 표준은 학습 범위(p1~p99, 학습+검증 구간) 밖 점을 만들지 않아 각 변수의 양 끝 격자점(예: 140 ℃ · 210 ℃ · 2 bar · 6 bar)이 빠진다. 원천은 학습 범위와 교차하지 않아 끝단 외삽 점을 추천할 수 있었다(원천 결함 S9). 8,400 을 재현하려고 학습 범위 규칙을 끄지 않는다. 불가능 판정은 같다 |

## 2. 선정 근거 — 검증 구간 (원천 대 표준)

| 과제 | 원천 검증 | 표준 검증 (챔피언) | 비고 |
|---|---|---|---|
| ks.remaining_hours | MAE 5.213 · RMSE 6.544 · R² 0.9143 | MAE 5.2126 · RMSE 6.5442 · R² 0.9143 | 같은 후보 4 · 같은 하이퍼파라미터 · 검증 MAE 최소 선정 |
| ks.failure_24h | (Brier 최소 선정, 값 보고 없음) | Brier 0.0596 | 같은 후보 3 |
| sw.delta_e | MAE 0.520 · R² 0.752 | MAE 0.5204 · R² 0.7521 | |
| sw.defect_risk | (Brier 최소 선정) | Brier 0.1369 | |

## 3. 행 일치 근거 (원천 실행 금지 → 간접 판정)

원천 저장소는 실행하지 않는다(goal §0.2). 그래서 원천 `demo_data()` 의 행을 직접 만들어 비교하지 않고, 다음 셋이 **모두** 맞는 것으로 행 일치 100% 로 판정했다(`tests/test_synth.py` 20 시험).

| 근거 | ks | sw |
|---|---|---|
| RNG 호출 순서 · 열 생성식을 원천 파일에서 줄 단위로 옮김 | `ml_service.py:20-38` | `ml_service.py:23-57` |
| 원천 문서 통계 | 720행 · 결측 24 · 중복 0 · 범위 밖 0 | 720행 · 결측 24 · 중복 0 · 범위 밖 0 · 불량률 31.5% · DTF/연한 색상 41건 |
| 같은 시드 · 같은 분할 · 같은 후보로 학습한 지표(행이 하나라도 다르면 바뀌는 값) | 챔피언 2 · 검증 3 · 시험 6 값 자리수 일치 | 챔피언 2 · 검증 2 · 시험 3 값 일치, 불량 3값 차이 ≤ 0.0013 (D-52) |

회사 고유 범주값(ks 설비 · 품목)은 생성기가 아니라 등록부 `categories` 로 들어간다(D-34). 팩 중립 값으로 만든 행을 회사 값으로 바꾸면 회사 프레임과 같다(`test_neutral_categories_give_same_rows_as_tenant`).

## 4. 차이 사유 (행별 사유의 근거)

| # | 차이 | 영향 | 근거 |
|---|---|---|---|
| D-52 | sw 불량 지표: 표준 재현 AUC 0.8686 · AP 0.7823 · Brier 0.1261 ↔ 원천 문서 0.868 · 0.781 · 0.127 | 차이 ≤ 0.0013 (±10% 의 1/10 미만). 같은 프레임의 회귀 지표 · 불량률 · 필터 건수는 완전 일치 → 행 일치 인정 | 추정 원인: 문서값이 원천 코드의 다른 시점에서 잰 값. 원천 실행 금지라 확인은 사람 몫(이슈 #3). `baselines.yaml` 에는 표준 실측을 `value`, 문서값을 `source_reported` 로(아키텍트) |
| D-31 | 최적화 탐색점: 표준 = 학습 범위 ∩ min/max | sw 후보 8,400 → 1,080, 충족 1,054 → 314. ks 는 결정 변수뿐이라 97 = 97 | 표준 규칙(G-M13 · spec §8.1) 우선. 호환 라우터의 `candidate_count` 도 표준 값을 낸다 |
| D-50 | 이상 탐지 임계값: 학습 구간 모델의 검증 구간 점수 `1 - c` 분위 | 시험 flag_rate ks 0.139 · sw 0.146 (원천 규칙이면 0.160 · 0.167) | 원천은 표본 내 점수 분위(라이브러리 기본) — 누수 규칙상 표준이 맞다 |
| D-29 | 순열 중요도: 원천 = 검증 구간(학습 구간 모델) · 표준 = 시험 구간(시험 1회 뒤 `report`) | 지표 값에 영향 없음. 화면 4 중요도 순서는 다를 수 있다 | spec §5.4 |
| D-W3-01 | sw 최적화의 "추천 조건이 이상 탐지에 걸리면 시험 인쇄 경고" | 표준 optimize 는 이 경고를 아직 내지 않는다(계약 `uses` 가 anomaly 값을 정의하지 않음) | 계약 보강 요청(decisions.md D-W3-01) |
| S3 | 원천은 트리 모델에도 StandardScaler | 결과 영향 없음(트리는 단조 변환에 불변). 표준 전처리 공장은 개발1 기준 | source_inventory §6 |
| S4 | 원천에 기준선 · 예측 구간 · 확률 보정 없음 | 표준은 모든 지표에 기준선(학습 평균 · 양성률 · 오염률)과 구간(split conformal, α 0.1)을 낸다. 위 표 괄호 안 | spec §2.4 · §5.3 |
| D-30 | spec 예시 값과 원천 값 차이(ΔE 기준 2.0 ↔ 3.5 · 변수 범위 · 목적) | 팩은 원천 값을 썼다 — 이 대조가 의미 있으려면 원천 값이어야 한다 | decisions.md D-30 |

## 5. 원천 결함 (이관 중 발견 — 원천은 고치지 않는다)

| # | 회사 | 결함 | 표준 처리 |
|---|---|---|---|
| S1 | ks · sw | 기동 시 메모리 학습(`@lru_cache state()`) · 코드 안 버전 상수 | 기동 학습 0 · 버전은 등록부(G-M06) |
| S2 | ks · sw | 순열 중요도를 검증 구간에서 | 시험 구간(D-29) |
| S5 | sw | `ink_usage` 는 API 필수인데 학습 데이터에 결측 8 | features.yaml `required: true` 그대로 · 학습은 보정 |
| S6 | ks | 정비 비용식은 검증되지 않은 데모 가정 | `packs/press/formulas/maintenance_cost.py` 머리말에 같은 경고 |
| S7 | ks | 배포 문서에 공인 주소 · 호스트명 평문 | 표준 저장소로 옮기지 않음(D-20 · D-41) |
| S8 | ks · sw | 오류 응답이 FastAPI 기본 `{"detail": [...]}` | 표준 봉투, 호환 라우터만 옛 모양 |
| S9 | sw | 최적화 격자가 학습 범위를 넘어 외삽 | 학습 범위 ∩ min/max (D-31) |
| S10 | ks · sw | 목록 `offset` · `records` · 기본 15 | `cursor` · `items` · 20 |

## 6. 재현 명령

```
OMP_NUM_THREADS=1 uv run python migration/reproduce.py --json /tmp/repro.json   # 위 §1 · §2 값 (3 s, 임시 폴더만 쓴다)
OMP_NUM_THREADS=1 uv run pytest -q tests/test_synth.py                          # §3 행 일치 근거
uv run python gates/check_migration.py                                          # G-M12
```
같은 머신 · 같은 env.lock · `OMP_NUM_THREADS=1` 에서 두 번 돌려 같은 값(D-19).


---

# 2차 — krs · pc · ot · kd (G-M12 6사 · goal2 §1-4, 개발3 2026-10-13 웨이브 A2)

> 원천 문서에 지표 수치가 있는 것은 **kd 공수 회귀 하나**(`KyungDong ML AI/docs/verification.md:23` MAE 4.1071 · RMSE 5.0456 · R² 0.9956).
> krs · pc · ot 은 기록이 없어(D2-12) **원천 절차 재현값** — 원천 코드를 읽어 같은 시드 · 같은 절차를 이관 도구가 다시 계산한 값(원천 실행 0) — 과 견준다.
> 재현 도구: krs · pc = `migration/reproduce.py --phase2`(개발1 → `outputs/reproduce-krs-pc.json`) · ot · kd = `migration/reproduce_quote.py`(개발3 → `outputs/reproduce-ot-kd.json`).
> 표준 값 = 표준 학습기(`StandardTrainer`) **시험 구간 1회** 지표(합성 demo · 회사 등록부 그대로). 표본 내 지표는 pc 원천 병기 칸에만(D2-02).
> 허용폭 ±10%(D-17, 넓힐 수 없다). 원천 분할 · 선정이 표준 누수 규칙과 달라(D2-21 · K1 · P1 · P3) 같은 수가 나올 수 없는 행은 사유를 적는다.

## 7. 요약 (2차)

- 행 일치: 100% — 4 팩 합성 생성기가 원천 생성기와 같은 시드에서 같은 행(§9). 강한 증거: 원천 절차를 다시 쓰면 kd MAE 4.1071 · RMSE 5.0456 · R² 0.9956(문서값), ot 시험 MAE 0.3166(원천 저장 견적의 `test_mae`)이 소수 4자리까지 같다.
- 원천 보고값이 있는 kd.labor_hours: 표준 MAE 3.7017 = −9.87%(±10% 안), RMSE −9.05%, R² +0.06%.
- 원천 절차 재현과 견준 학습 과제 4(krs · ot): krs MAE +3.65% · R² −4.05% 는 안, **RMSE +12.76% 는 밖 — 사유 K1 · K6**(원천은 시험 구간으로 선정 · 이상치 경계를 분할 전 전체에서). ot 가공 분 MAE −6.63% · 객체 분류 macro-F1 0%.
- 견적: ot 저장 견적 726,487 원 ↔ 표준 Decimal 726,484 원 — **표준 = 원천 현행 식(원 단위 일치)**, 저장값은 그 앞 판(가공비를 반올림 전 분으로 계산)에서 나왔다(D2-60, 3원 = 가공비 단계 2원 + 가산 1원). kd 저장 견적 2건(5,235,023 · 8,486,493 원) 원 단위 일치.
- 추출: ot 샘플 전개도 객체 9개가 원천 저장 분석과 점 · 면적 · 둘레 · 라벨 · 점수까지 같다. kd 영역 3종 · BOM 4행이 원천 저장 결과와 같다.

## 8. 대조표 (2차 과제 12)

| 과제 | 유형 | 챔피언 원천 → 표준 | 표준 재측정 (시험) | 원천 (보고 · 절차 재현) | 차이 | 판정 · 사유 |
|---|---|---|---|---|---|---|
| krs.joint_strength | regression | SVR → `gbr` | mae = 2.0935 · rmse = 2.9711 · r2 = 0.8677 (random_60_20_20 432/144/144, 이상치 학습 구간만) | 절차 재현 MAE 2.0199 · RMSE 2.6349 · R² 0.9043 (무작위 80/20 · 이상치 제거 710행 · 시험 RMSE 선정) | mae +3.65% · rmse +12.76% · r2 −4.05% | rmse ±10% 밖 · 사유: 원천은 **시험 구간으로 모델을 고른다**(K1 — 시험 RMSE 최소 SVR) · IQR 경계를 분할 전 전체 720행에서 잰다(K6 · D2-03) · 분할 80/20 ↔ 60/20/20(D2-21). 표준이 시험을 한 번만 보므로 원천 수치에 맞추려고 선정 규칙을 바꾸지 않는다 |
| krs.recipe_optimize | optimize | 무작위 5,000 → `random` 수락 5,000 | 점 5,000(뽑음 5,064) · 충족률 0.1548 · 추천 5 · least_violation (목표 47 MPa · 공급사 첫째) | 절차 재현 점 5,000 · 충족률 0.2658 · 추천 1 (시드 int(target×100)+ord) | 점 수 0% | 대조 제외 · 사유: 충족률은 의존 모델 · 표집(연속 균등 ↔ 격자 step · 학습 범위 ∩ 요청 범위)에 따라 달라진다. 점 수 · 등식 sn = 100 − 합 · 가능 판정은 같다. 미충족 정렬은 원천 K2(위반량 무시) ↔ least_violation |
| krs.residual_review | review_queue | \|잔차\| ≥ 4 MPa → 같은 규칙 | 시험 구간 잔차 144 행 · 대기열 16 (운영 잔차는 실측이 붙을 때) | 절차 재현 정제 데이터 전체 710 행 채점 · 넘음 27 · 표시 12 | — | 대조 제외 · 사유: 원천은 학습 80% 를 포함한 표본 내 잔차(K4) — 표준은 시험 · 운영 잔차만(G2-R01). 모수가 달라 건수 대조는 뜻이 없다 |
| pc.sensory_score | regression | GBR → `gbr` | **재측정** mae = 1.5375 · rmse = 1.9540 · r2 = 0.4747 (time_cv5 — 420 행 < 500, 시험 84 · 기준선 MAE 2.0952) | **원천** 시험 MAE 1.7912 · R² 0.4814 (무작위 78/22 · 시험으로 선정) / 원천 표본 내(전체 재적합) MAE 1.0829 · R² 0.7716 | mae −14.17% | 대조 제외(D2-02 — 재측정이 정본, 원천 값 병기) · 사유: 원천은 시간 열이 있는데 무작위 분할(P3) · 시험으로 선정(P1) · 화면 수치는 표본 내(P2) |
| pc.recipe_optimize | optimize | 무작위 수락 3,500 → `random` 수락 3,500 | 점 3,500(뽑음 4,738) · 충족률 0.1477 · scale 3 · 5 · least_violation | 절차 재현 점 3,500 · 충족률 0.1554 (시드 927) | 점 수 0% · 충족률 −4.95% | 대조 제외 · 사유: 요청 의존 시드 ↔ 과제 시드 고정 · 연속 균등 ↔ 격자 step. 위반 식(÷3 · ÷5) · 양념 = 100 − 합은 같다 |
| pc.residual_review | review_queue | 상위 10% → `top_quantile 0.10` | 마지막 검증 블록 잔차 0.9 분위 3.5984 → 시험 84 행 중 대기열 6 (D2-106 — 전 4.2338 · 3 은 time_cv5 5겹 풀링 분위, DEF-QA21-003) | 원천 표본 내 0.9 분위 2.3190 · 넘음 42 · 표시 8 | — | 대조 제외(D2-02 · D2-11) · 사유: 원천 임계값은 전체 재적합 모델의 표본 내 분위(P2 · P4) — 표준은 검증 구간 분위를 시험 · 운영 잔차에 |
| ot.machining_minutes | regression | Ridge → `ridge` | mae = 0.2956 · rmse = 0.3720 · r2 = 0.9775 (random_60_20_20 540/180/180 · 기준선 MAE 1.9377 · 구간 포함률 0.911) | 절차 재현 MAE 0.3166 · RMSE 0.4099 · R² 0.9788 (행 순서 540/180/180) = 원천 저장 견적 `test_mae` 0.3166 | mae −6.63% · rmse −9.25% · r2 −0.13% | 통과 (±10% 안). 분할 정책이 다른 사유는 D2-21(원천 행 순서 ↔ 무작위 — 시각 열 없음) |
| ot.cad_objects | extract | Extra Trees → `logreg` (검증 macro-F1 전부 1.0 동률 — 원천은 이름순, 표준은 후보 순서) | macro_f1 = 1.0 · accuracy = 1.0 (stratified_60_20_20 960/320/320 · 기준선 majority_class macro-F1 0.1 · 혼동행렬 대각 80 × 4) | 절차 재현 macro-F1 1.0 · accuracy 1.0 (층화 960/320/320) | 0% | 통과. labels: synthetic — 합성 설명자의 생성 라벨이라 실도면 인식률이 아니다. 업로드 도면 응답은 metrics null. 추출 결과는 원천 저장 분석과 객체 9개 일치(§10) |
| ot.quote | quote | `api/quote.py` → `formulas/quote.py`(Decimal) | 저장 견적 입력 · 원천 절차 예측 1.3286236 분 → 726,484 원 | 원천 저장 726,487 원 · 원천 현행 식 726,484 원 | 저장 대비 −3 원 | 표준 = 원천 현행 식 원 단위 일치. 저장값 차이 사유 D2-60(저장 견적은 가공비를 반올림 전 분으로 계산한 앞 판 — 그 경로로 다시 계산하면 726,487 로 일치). .5 경계 float 차이(D2-07a)는 이 견적에 없다 |
| kd.labor_hours | regression | Ridge → `ridge` | mae = 3.7017 · rmse = 4.5892 · r2 = 0.9962 (random_60_20_20 · 기준선 MAE 62.9053) | **보고** MAE 4.1071 · RMSE 5.0456 · R² 0.9956 (`docs/verification.md:23`, 행 순서 540/180/180) = 절차 재현 같은 값 | mae −9.87% · rmse −9.05% · r2 +0.06% | 통과 (±10% 안). 분할 차이 D2-21 |
| kd.drawing_regions | extract | 규칙 R1~R9 → `cad_regions` · `bom_text` | 원천 샘플 도면 2건: 영역 3종 각 1 · BOM 4행 · 경고 문구 일치 | 원천 저장 결과 2건(`tests/fixtures/kd/source_drawing.json`) | 0 | 통과. labels: none — IoU · F1 을 만들지 않는다(D-160 · D3) |
| kd.quote | quote | `api/quote.py`(float · 짝수 반올림) → `formulas/quote.py`(Decimal · HALF_UP) | 저장 견적 2건 5,235,023 원 · 8,486,493 원 | 원천 저장 같은 값 | 0 원 | 통과 (원 단위 일치 — .5 단계 46,237.5 · 1,006,303.5 도 두 반올림이 같다, `tests/test_formula_eto_quote.py`) |

## 9. 행 일치 근거 (2차 — 원천 실행 금지 → 간접 판정)

| 팩 (회사) | 원천 생성기 | 근거 | 시험 |
|---|---|---|---|
| solder (krs) | `ml_service.py:31-56 make_sample_data()` (시드 20260917 · 720 · 결측 24 · 이상치 5) | 원천을 읽은 참조와 값 · 순서 100% | `tests/test_solder_pack.py` (개발1) |
| kimchi (pc) | `ml_service.py:36-55 _demo_data()` (시드 42 · 420 · 결측 15) | 원천을 읽은 참조와 값 · 순서 100% | `tests/test_synth_phase2.py` |
| rollform-quote (ot) | `ml_service.py:43-58 demo_jobs()` (900 · 결측 12) · `:19-40 geometry_training_data()` (1,600) | 참조와 100% + 원천 절차 시험 MAE 0.3166 = 저장 견적 `test_mae` · 예측 1.3286 = 저장 `minutes_per_piece` | `tests/test_rollform_quote_pack.py` |
| eto (kd) | `ml_service.py:15-29 demo_jobs()` (900 · 결측 12) | 원천 절차 시험 지표 = 문서값 4 자리 · 저장 견적 예측 58.146 h | `tests/test_synth_phase2.py` |

회사 범주값(재질 · 형상 · 공급사 · 산지 · 라인)은 생성기가 아니라 등록부 `categories` 로 들어간다(목록 위치 = 원천 순서). krs 공급사는 원천 한 글자 표기 A · B · C 가 G-M01 금지어와 겹쳐 `공급사A` · `공급사B` · `공급사C` 로 적었다(D2-61, 값 뜻 · 순서 같음 — 옛 표기는 호환 쪽에서 바꾼다).

## 10. 추출 · 견적 대조 근거

| 항목 | 표준 | 원천 저장 (`tests/fixtures/<회사>/source_*.json`, SQLite 읽기 전용 사본) | 시험 |
|---|---|---|---|
| ot 샘플 전개도 (1200 × 160 · 홀 6 · 슬롯 2) | counts outer 1 · hole 6 · slot 2 · other 0 · dimensions 1200 × 160 · 객체 9 개 점(원 32 · 슬롯 34) · 면적 · 둘레 · 점수 0.99 / 1.0 | 같은 값 (첫 경고 문구만 원천 앞 판 문구 — D2-60) | `tests/test_rollform_quote_pack.py::test_sample_drawing_matches_source_stored_analysis` |
| ot 곡선 평탄화 | 원천이 쓰는 ezdxf 1.4 의 원 · 호 · bulge → 3차 베지어 → 적응 이분(0.2 mm, 최소 8) 계산 순서를 팩 추출기에 다시 썼다(외부 의존 0) | ezdxf `make_path().flattening(0.2/scale, 8)` | 같은 시험 |
| ot 기하 검증 8 사유 | 규칙 추출기 3(열린 · 외곽 없음 · 외곽 밖) + 모델 추출기 5(점수 · 외곽 불일치 · 추가 외곽 · 원 아닌 홀 · 곡선 없는 슬롯), 결과 `replaces` | `cad.py:113-124` | `test_geometry_gates_eight_reasons` · `test_model_reasons_score_and_shape` |
| ot 저장 견적 단계 | 소재 423,222 · 준비 31,500 · 가산(저장 base) 86,145 · 부가세(저장 subtotal) 66,044 일치 · 가공비 119,574 ↔ 저장 119,576 | `quotes` 1 행 | `test_stored_quote_reconciliation_to_the_won` · `tests/test_ot_quote_flow.py`(API — 학습 → 승인 → 업로드 → 견적 초안) |
| kd 저장 견적 2 · 도면 2 | 원 단위 · 영역 · BOM 일치 | `quotes` 2 행 · `drawings` 2 행 | `tests/test_formula_eto_quote.py` · `tests/test_extract_eto.py` |

## 11. 차이 사유 (2차)

| # | 차이 | 영향 | 근거 |
|---|---|---|---|
| D2-21 | 원천 분할(krs 80/20 · pc 78/22 · ot · kd 행 순서 540/180/180) ↔ 표준 random_60_20_20 · pc time_cv5 | 시험 행이 달라 지표가 달라진다(kd −9.87% · ot −6.63%) | 시각 열이 없으면 무작위(시각을 지어내지 않는다) |
| K1 · K6 | krs 시험 구간 선정 · 분할 전 IQR | krs RMSE +12.76% | 표준은 검증 선정 · 학습 구간 경계(D2-03) |
| D2-02 | pc 재측정이 정본 | 원천 시험 · 표본 내 값은 병기만 | 원천 P1 · P2 · P3 |
| D2-60 | ot 저장 견적은 현행 원천 식 이전 판(가공비를 반올림 전 분으로) | 726,487 ↔ 726,484 (−3 원) | 원천 현행 `quote.py:13,18` 은 4자리 반올림 분으로 가공비 — 표준은 현행 식(D2-07). 저장 판 경로로 다시 계산하면 726,487 |
| D2-07a | 정확히 .5 인 단계에서 원천 float 곱이 .4999… 로 내려가면 표준이 1원 많다 | 저장 견적 3건에는 없음 · 손 계산 사례(0.043 분 × 900 × 5 = 193.5 → 표준 194 · 원천 193) | `test_half_boundary_case_is_documented_difference` |
| D2-22 | ot 요소 상한 2,000(팩 기본) ↔ kd 20,000 | 넘으면 413 entities | `tests/test_ot_quote_flow.py::test_entity_limit_is_pack_2000` |
| O4 · X6 | ot 꼭짓점 500 · 점 2,000/60,000 초과는 원천 422 ↔ 표준 413 (`vertices` · `points`) | 오류 코드만 다름 | api-contract §6.1 |
| ot 경고 순서 | 원천은 경고 한 목록, 표준은 규칙 · 모델 추출기 경고를 차례로 잇는다 — "검토 대상 N개" 가 "외곽 없음 · 단위" 뒤에 온다 | 문구 같음 · 순서만 | `merge_results` |

## 12. 재현 명령 (2차)

```
OMP_NUM_THREADS=1 uv run python migration/reproduce.py --phase2      # krs · pc → outputs/reproduce-krs-pc.json (개발1)
OMP_NUM_THREADS=1 uv run python migration/reproduce_quote.py         # ot · kd → outputs/reproduce-ot-kd.json (3 s)
OMP_NUM_THREADS=1 uv run pytest -q tests/test_rollform_quote_pack.py tests/test_ot_quote_flow.py tests/test_synth_phase2.py
uv run python gates/check_migration.py                                # G-M12 (1차) · gate2 는 run_phase2
```
