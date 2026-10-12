# 표준 ML 플랫폼 (Standard ML Platform)

## 1. 한 줄 소개

회사마다 따로 만들어 온 제조 ML 서비스(품질 예측 · 불량 위험 · 예지보전 · 조건 최적화 · 작업시간 추정 · CAD 견적 …)의 **공통 골격을 한 벌만 두고**, 문제의 모양은 **과제 유형(Task Type)**, 업종마다 다른 변수 · 제약 · 비용식은 **업종 팩(Industry Pack)**, 회사마다 다른 데이터는 **데이터 소스 어댑터**와 **회사 등록부**로 붙이는 ML 서비스 플랫폼이다. 코어를 고치지 않고 `tenants/<code>.yaml` · 과제 정의(`tasks/*.yaml`) · 데이터 소스 설정만 바꿔 새 회사의 ML 서비스 한 벌을 띄우는 것이 목표다.

```
 ┌──────────────── 회사 (tenants/<code>.yaml · 회사마다 하나) ─────────────────┐
 │ 업종 팩 선택 · 켤 과제 · 데이터 소스(참조) · 임계값 · 비용 계수 · 승인자 · KPI │
 └───────────────┬───────────────────────────────────────────┬─────────────────┘
                 │                                           │
 ┌───────────────▼──────────── 업종 팩 (업종마다 하나) ─────────▼─────────────────┐
 │ solder · kimchi · press · textile · eto · rollform-quote …                    │
 │ 변수 사전(단위 · 범위 · 조절 가능 여부) · 과제 정의(tasks/*.yaml) · 제약 · 비용식 │
 │ 합성 데이터 생성기(데모용) · 평가 기준선                                        │
 └───────────────┬──────────────────────────────────────────────────────────────┘
                 │ pack.yaml + features.yaml + tasks/*.yaml + formulas/*.py + synth/*.py
 ┌───────────────▼──────────── 표준 코어 (업종 무관 · 고치지 않는다) ──────────────────┐
 │ 과제 유형 7 : 회귀 · 위험 분류 · 이상 탐지 · 조건 최적화 · 검토 대기열 ·           │
 │               문서/도면 추출 · 원가/견적 계산                                       │
 │ 데이터 : 소스 어댑터(합성 · CSV · Gateway · Data Platform · MES 읽기) · 표준 프레임 │
 │ 학습 : 전처리 공장 · 후보 모델 · 분할 정책 · 챔피언 선정 · 재적합 · 시험 1회        │
 │ 모델 등록부 : 버전 · 데이터 해시 · 지표 · 챔피언 · 승인 상태 · 산출물 파일         │
 │ 추론 : 표준 예측 계약 · 입력 검증 · 결측 보정 · 범위 밖 경고 · 예측 기록           │
 │ 운영 : 드리프트(PSI · 범위) · 결측률 · 성능 추적 · 재학습 승인 · 감사 로그          │
 │ Python 3.12 · FastAPI · scikit-learn · PostgreSQL 17 · React 콘솔                │
 └──────────────────────────────────────────────────────────────────────────────┘
```

## 2. 왜 표준이 필요한가

같은 공급기업이 2026년에 스마트공장 사업으로 6개 회사에 ML 서비스를 만들었다. 6벌 모두 같은 생성 절차(`~/.codex/skills/manufacturing-ml-service-maker`)에서 나왔다. 복사 순서는 고려솔더 → 평창 → 광성 → 송월, 송월 → 원터치 → 경동이다. 구조는 같은데 이름 · 계약 · 평가 방식은 저장소마다 조금씩 달라졌다. 그리고 6벌 모두 **합성 데이터를 기동할 때마다 메모리에서 다시 학습**한다.

| 반복된 비용 | 실제 사례 |
|---|---|
| 골격 복사 | `api/{main,ml_service,config}.py` · `web/src/{App,api,types}.tsx` · `tests/test_api.py` 구조가 6벌 동일. 전처리 `Pipeline(ColumnTransformer[중앙값 보정 + 표준화, OneHot])` 를 6곳에서 각자 정의. 원터치 · 경동 `storage.py` 는 파일명 · 환경변수 말고는 같다 |
| 계약의 난립 | 예측 경로가 `/api/quality/predict`(고려솔더 · 평창 · 송월), `/api/maintenance/predict`(광성)로 갈렸고, 원터치 · 경동은 `POST /api/quotes` 안에 숨어 있다. 출력 키도 `predicted_strength` · `prediction_score` · `remaining_hours` · `delta_e` 로 다르다 |
| 평가 방식의 불일치 | 분할이 무작위 80/20 · 78/22 · 시간순 60/20/20 · 층화로 다르다. 선정 지표도 RMSE · MAE · Brier · macro-F1 로 다르다. 평창은 전체 데이터로 재적합한 뒤 같은 데이터로 대기열을 채점한다(표본 내 평가) |
| 모델이 남지 않는다 | 모델 파일 · 등록부 · 버전 이력이 없다. 재기동하면 다시 학습한다. 버전은 코드 상수(`MODEL_VERSION` · `VERSION`)이거나 아예 없다 |
| 실데이터와 끊김 | Data Gateway · Data Platform 이 7개사에 있는데, ML 6벌 중 실데이터를 읽는 곳은 0곳이다. 데이터 허브 `problem.md` F9 가 같은 문제를 지적한다 |
| 운영 장치 없음 | 인증 · 회사 분리 · 감사 · 드리프트 감시 · HTTPS · 재학습 승인이 없다. 실제 VPS 배포는 광성 한 곳(HTTP · 인증 없음)뿐이다 |

표준 플랫폼은 이것을 **코어 한 벌 + 과제 유형 + 업종 팩 + 회사 등록부**로 바꾼다. 새 회사는 코어를 복사하지 않고 **의존**한다. 변수 · 목표 · 제약 · 비용식은 `features.yaml` · `tasks/*.yaml` 로 선언한다. 학습 · 평가 · 등록 · 예측 계약 · 감시는 코어가 정한다.

## 3. 근거 자산

플랫폼의 과제 유형 · 계약 · 학습 절차는 아래 구축물에서 뽑았다. 수치는 2026-10 기준 각 저장소 값이며, 모든 데이터는 **합성 데이터**다.

| 회사 (코드 · 업종) | 저장소 (`../…`) | 과제 | 목표 변수 | 챔피언 · 지표 (합성) |
|---|---|---|---|---|
| 고려솔더 (`krs` · 솔더 배합) | `Koreal Solder ML AI` | 접합 강도 회귀 · 배합 최적화(무작위 5,000) · 잔차 검토 대기열 | `joint_strength_mpa` | 5종 중 RMSE 최소 |
| 평창꽃순이김치 (`pc` · 김치) | `PyoungChang ML AI` | 관능 점수 회귀 · 배합/공정 최적화(무작위 3,500) · 잔차 대기열(상위 10%) | `sensory_score` | Ridge/ET/GBR 중 선택 |
| 광성정밀 (`ks` · 프레스) | `KwangSung ML AI` | 잔여수명 회귀 · 24시간 고장 위험 분류 · 이상 탐지 · 정비 시점 탐색 | `remaining_hours` · `failure_24h` | 시험 MAE 5.57h · R² 0.92 · AUC 0.64 |
| 송월타월 (`sw` · 날염) | `SongWol ML AI` | 색차 회귀 · 불량 확률 분류 · 이상 탐지 · 인쇄 조건 격자 탐색(8,400점) | `delta_e` · 불량 | ExtraTrees MAE 0.557 · GBC AUC 0.868 |
| 원터치 (`ot` · 롤포밍 형강) | `OneTouch ML AI` | 도면 객체 분류(외곽/홀/슬롯/기타) · 가공 분 회귀 · 견적 계산 | 객체 종류 · 가공 분 | macro-F1 기준 선정 |
| 경동글로벌텍 (`kd` · 수주생산 장비) | `KyungDong ML AI` | DXF 영역 검출(규칙) · BOM 추출 · 작업시간 회귀 · 견적 계산 | `hours` | Ridge 시험 MAE 4.1h |

함께 쓰는 기준 자산:

| 자산 | 경로 | 가져오는 것 |
|---|---|---|
| 광성 ML 방법론 | `KwangSung ML AI/docs/methodology.md` · `verification.md` | 시간순 분할 → 검증 선정 → 학습+검증 재적합 → 시험 1회. 결측 3개까지 보정. `extra=forbid` · `allow_inf_nan=False` |
| 광성 배포 기록 | `KwangSung ML AI/docs/deployment.md` · `deploy/hostinger.compose.yaml` | VPS 배포 절차 · 메모리 768MB · CPU 1 · 커밋 SHA 이미지 태그 |
| 송월 테이블 대응 | `SongWol ML AI/docs/*` | 예측 결과의 MES 테이블 대응(`PRT_COLOR_PREDICTIONS.PRED_DELTA_E` · `PRT_QUALITY_PREDICTIONS.DEFECT_PROB`) |
| 경동 고객 답변 | `KyungDong ML AI/data/reference/customer_answers.json` | D-160 도면 영역 3종 결정, 정답 라벨이 없으면 IoU/F1 을 내지 않는다는 원칙 |
| 표준 데이터 허브 | `../Standard Data Hub` | 회사 코드(`krs` · `pc` · `ks` · `sw` · `ot` · `kd`) · ML 을 소비자로 등록 · 태그 → 모델 계보 · 학습 가능 데이터 지도 |
| 회사별 Data Platform | `../<회사> Data Platform` | 설비 데이터 읽기 API · Athena 뷰(학습 데이터 원천) |
| 표준 AI Agent 플랫폼 | `../Standard AI Agent Platform` | ML 을 Agent 도구(`ml.predict` · `ml.explain`)로 노출하는 지점(그쪽 `problem.md` §4.2) |
| 표준 MES · Data Hub 형식 | `../Standard MES Platform` · `../Standard Data Hub` | 문서 형식 · 기술 스택 · 오류 계약 · 게이트 방식 |

## 4. 플랫폼이 하는 일과 하지 않는 일

| 구분 | 플랫폼이 한다 | 플랫폼이 하지 않는다 |
|---|---|---|
| 데이터 | 어댑터로 Gateway · Data Platform · MES · CSV 를 **읽기 전용**으로 읽어 표준 프레임(`entity_id` · `ts` · 변수 · 목표)으로 만들고, 학습 스냅숏을 해시로 고정한다 | 원천 DB · S3 · Gateway 에 쓰기. 원천 데이터의 장기 보관(Data Platform 이 한다) |
| 학습 | 과제 유형별 표준 절차로 후보를 학습하고 챔피언을 정해 등록부에 올린다 | 사람 승인 없는 운영 모델 교체 |
| 추론 | 표준 예측 계약으로 예측 · 확률 · 이상 여부 · 경고 · 보정된 필드를 돌려주고, 모든 예측을 기록한다 | 설비 · 공정 설정값의 직접 변경. 최적화 결과는 **추천**이고, 실제 적용은 사람이 MES 나 설비에서 한다 |
| 최적화 | 조절 가능한 변수의 범위와 제약 안에서 추천 조건을 찾고, 제약을 못 맞추면 위반이 가장 적은 후보와 그 위반 내용을 보여 준다 | 제약을 어긴 조건을 "정상" 으로 표시하기 |
| 견적 | 도면 · BOM 추출 결과와 ML 작업시간을 결정적 비용식에 넣어 견적 **초안**을 만들고, 사람이 고친 값을 남긴다 | 검토(`reviewed`) 없는 견적 확정 · 발송 |
| 운영 | 드리프트 · 결측률 · 실측 대비 성능을 재고, 기준을 넘으면 재학습 후보를 만들어 승인 대기열에 올린다 | 자동 재학습 후 자동 배포 |
| 표준 | 과제 유형 · 예측 계약 · `mlp_*` 테이블 · 지표 이름 · 상태 코드 · 준수도 | 회사 MES 의 예측 결과 테이블 이름 변경(대응표만 둔다) |

## 5. 어떻게 쓰는가 (사용 시나리오)

1. **회사 등록.** `tenants/_template.yaml` 을 복사해 `tenants/sw.yaml` 을 만든다. 업종 팩(`textile`) · 켤 과제(`sw.delta_e` · `sw.defect_risk` · `sw.print_setpoint`) · 데이터 소스(Data Platform 뷰 이름 · 키 **참조(환경변수 이름)**) · 임계값 · 승인자를 적는다.
2. **연결 확인.** `make doctor TENANT=sw` 가 소스마다 행 수 · 기간 · 변수 대응률 · 결측률을 재 본다. 연결 실패는 숨기지 않고 `미연결` 로 표시한다. 실데이터가 없으면 팩의 합성 생성기로 `demo` 모드를 연다.
3. **학습.** `make train TENANT=sw TASK=sw.delta_e` 가 스냅숏을 고정하고, 후보 4종을 같은 분할로 학습한다. 챔피언 · 지표 · 데이터 해시를 등록부에 `candidate` 로 올린다.
4. **승인.** 품질 담당이 콘솔의 모델 비교 화면에서 현재 운영 모델과 후보의 시험 지표 · 변수 중요도 · 잔차를 보고 `production` 으로 승인한다.
5. **운영.** MES 화면 · 현황판 · AI Agent 가 `POST /api/v1/tenants/sw/tasks/sw.delta_e/predict` 를 부른다. 모든 예측이 `mlp_prediction` 에 남는다. 실측 ΔE 가 들어오면 성능이 갱신되고, 드리프트가 기준을 넘으면 재학습 후보가 대기열에 오른다.
6. **새 업종.** 팩이 없는 업종은 `packs/_template` 을 복사해 변수 사전 · 과제 2개 · 합성 생성기 · 기준선부터 채운다.

## 6. 문서 구성

| 문서 | 내용 |
|---|---|
| `intro.md` | 이 문서. 플랫폼 소개 · 근거 자산 · 하는 일과 하지 않는 일 |
| `problem.md` | 풀려는 문제 · 핵심 질문 · 목표 G1~G12 · 범위 · 가정 · 확정 필요 사항 Q1~Q12 |
| `spec.md` | 시스템 구성 · 과제 유형 · 과제 정의 규격 · 데이터 소스 · 학습 · 모델 등록부 · 추론 계약 · 최적화 · 운영 감시 · 데이터 모델 · 팩/회사 등록부 · 화면/API · 연동 · 게이트 · 수용 기준 |

구현 단계에서는 여기에 `goal.md` · `contracts/` · `decisions.md` · `progress.md` 가 더해진다. 형식은 `../Standard MES Platform` · `../Standard Data Hub` · `../Standard AI Agent Platform` 의 것을 따른다.

## 7. 용어

| 용어 | 뜻 |
|---|---|
| 회사 (Tenant) | ML 서비스를 쓰는 도입기업 하나. `tenants/<code>.yaml` 하나로 정의된다. 코드는 데이터 허브의 회사 코드를 그대로 쓴다 |
| 업종 팩 (Industry Pack) | 업종 공통의 변수 사전 · 과제 정의 · 제약 · 비용식 · 합성 생성기 묶음 |
| 과제 유형 (Task Type) | 업종을 건너 재사용되는 ML 문제의 모양. `regression` · `risk` · `anomaly` · `optimize` · `review_queue` · `extract` · `quote` 7종 (`spec.md` §2) |
| 과제 (Task) | 과제 유형 하나를 회사 데이터에 적용한 것. 예: `sw.delta_e`(회귀), `ks.failure_24h`(위험 분류). `tasks/*.yaml` 로 선언 |
| 변수 (Feature) | 모델 입력. 이름 · 단위 · 범위 · 기본값 · 필수 여부 · **조절 가능 여부**(최적화 대상인지)를 갖는다 |
| 데이터 소스 (Source) | 학습 · 추론 데이터를 읽는 읽기 전용 어댑터. 합성 · CSV · Gateway · Data Platform · MES |
| 스냅숏 (Snapshot) | 학습에 쓴 데이터의 고정본. 행 수 · 기간 · 내용 해시를 가지며, 같은 스냅숏과 시드로 다시 학습하면 같은 모델이 나와야 한다 |
| 챔피언 (Champion) | 후보 모델 중 검증 지표로 선정된 모델. 등록부에서 `candidate → staging → production → archived` 로 움직인다 |
| 예측 계약 (Predict Contract) | 모든 과제가 같은 모양으로 돌려주는 예측 응답(`spec.md` §7.2) |
| 드리프트 (Drift) | 운영 입력 분포가 학습 스냅숏과 달라진 정도. PSI · 범위 밖 비율 · 결측률로 잰다 |
| `미연결` / `범위 밖` / `검토 필요` / `승인 필요` | 플랫폼이 지어내지 않을 때 쓰는 표준 상태 (`spec.md` §7.3) |
| `[기준]` / `[가설]` | `spec.md` 표기. `[기준]` 은 근거 구축물 둘 이상에서 이미 쓰는 것, `[가설]` 은 플랫폼을 만들며 새로 정한 것 |
