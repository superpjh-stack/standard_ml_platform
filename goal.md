# /goal — 표준 ML 플랫폼 1차 구축 (mlp 테이블 16 · 과제 유형 4 · 소스 어댑터 5 · 팩 2+1 · 회사 2+1 · 화면 6 · API 12)

> **이 문서가 엔지니어링 메타프롬프트다.** `/loop` 는 매 회전마다 이 문서를 판정 기준으로 읽는다. 투입되는 에이전트(아키텍트 1 · 개발 3 · QA 3)도
> 작업 전에 이 문서와 `CLAUDE.md` · `contracts/` · `decisions.md` · `progress.md` 를 먼저 읽는다.
> 여기 적힌 수치는 `spec.md` 에서 센 값이다. 세는 방법은 §9 에 있으니, 의심되면 다시 센다.

| 항목 | 값 | 출처 |
|---|---|---|
| 시스템 | 표준 ML 플랫폼. 업종 무관 **코어 한 벌**에 **과제 유형** · **업종 팩** · **회사 등록부** · **데이터 소스 어댑터**를 붙여, 회사별 ML 서비스를 복사 없이 띄운다 | `intro.md` §1 · §4 |
| 정본 | `intro.md` · `problem.md` · `spec.md` (이 폴더 루트, **사람만 고친다**) | — |
| 근거 · 원천 | `../{Koreal Solder,PyoungChang,KwangSung,SongWol,OneTouch,KyungDong} ML AI` · `../Standard Data Hub` · `../Standard AI Agent Platform` · `../Standard MES Platform` · `../<회사> Data Platform` (**모두 읽기 전용**) | `intro.md` §3 |
| **1차 범위** | 코어 전부. 과제 유형 **`regression` · `risk` · `anomaly` · `optimize`**. 팩 **`press` · `textile` + `_template`**. 회사 **`ks` · `sw` + `_template`**. 화면 **1~6**. 2차 범위는 §10 | `spec.md` 머리말 |
| 규모 (1차) | **mlp 테이블 16**(1차에 전부 만든다) · 과제 유형 4(코드 골격은 7) · 소스 어댑터 **5** · 응답 상태 **6** · 후보 모델 이름 사전 · 분할 정책 **4** · 팩 2 + 1 · 회사 2 + 1 · 화면 6 · **API 12**(검토 대기열 · 문서 · 견적 3묶음은 2차) · 검증 도구 12 | `spec.md` §2 · §4.1 · §5.3 · §10.1 · §12 · §16 |
| 핵심 | **누수 없는 평가**(시간순 강제 · 시험 1회 · 기준선 비교) · **재현되는 모델**(스냅숏 해시 · 결정성 · 재기동 재학습 0) · **하나의 예측 계약**(키 누락 0) · **사람 승인만 운영 교체**(자동 승격 경로 0) · **원천은 읽기만** | `spec.md` §5.3 · §4.3 · §7.2 · §6.1 · §4.1 |
| 범위 밖 | 원천 쓰기 · 추천의 설비 자동 적용 · 딥러닝/비전/GPU · 회사 MES 테이블 이름 변경 · 기존 6벌 철거 · IAM 자체 · (1차) `review_queue` · `extract` · `quote` · 팩 4 · 회사 4 · 화면 7~10 | `problem.md` §5 · §10 |
| 완료 기준 | **ks · sw 2사가 코드 수정 없이 등록부 · 팩만으로 기동된다. 두 회사의 기존 기능 전부가 표준 과제로 돌며, 같은 예측 계약 · 누수 검사 · 결정성 검사를 통과한다. 운영 모델은 승인을 거친 것뿐이고, 예측 하나를 원천 스냅숏까지 추적할 수 있다** | `problem.md` §4.1 · `spec.md` §18 |
| 코드 위치 | `/Users/gerardo92/Desktop/AI Coding/Standard ML Platform` (이 폴더) · 원격 `superpjh-stack/standard_ml_platform` | — |

---

## 0. 이 문서를 어떻게 쓰는가

### 0.1 루프 기동 — 이 한 줄을 붙여 넣는다

```
/loop goal.md 를 판정 기준으로 표준 ML 플랫폼 1차를 만든다. §4.2 한 회전 절차를 그대로 따른다.
progress.md · decisions.md 를 읽고(없으면 §3.1 Phase 0 부터), `make gate` 로 §2 게이트 G-V01 · G-S01~G-S07 · G-M01~G-M14 를 실측한다.
FAIL 중 가장 앞선 웨이브의 항목 하나를 골라 §5 프롬프트로 담당 에이전트를 기동한다(병렬 가능한 것은 한 번에).
보고를 믿지 말고 게이트 명령을 직접 다시 돌려 확인한 뒤, 실측값과 검증 명령을 progress.md 에 적고 커밋한다.
막히면 decisions.md 에 D-번호로 `차단`을 올리고 다음 항목으로 넘어간다. 사람을 기다리며 멈추지 않는다.
게이트를 낮추거나 테스트 · 기준선을 건너뛰지 않는다. §4.4 종료 조건을 만족하면 최종 보고를 쓰고 루프를 멈춘다.
```

중단 후 재개는 `/re-begin` 이나 위 한 줄로 한다. 상태는 전부 파일에 있다(§4.5).

### 0.2 직전 사업(회사별 ML AI 6벌)과 다른 점 — 먼저 알고 시작한다

직전 사업은 **회사 하나의 ML 데모**를 만들었다. 여기는 **ML 서비스를 찍어 내는 틀**을 만든다. 회사 · 업종 이름이 코어에 한 글자라도 들어가면 실패다.

- **코어는 업종을 모르고, 팩은 회사를 모른다.** `delta_e` · `shot_count` · `press_force` 는 팩에만 둔다. 원천 테이블 · 열 이름(`PRT_PRINT_CONDS.SET_TEMP`)은 `tenants/<code>.yaml: feature_map` 에만 둔다(G-M01).
- **변수 · 과제는 YAML 이다.** `FEATURE_META` dict 를 코드에 두지 않는다. 입력 폼 · 검증 · 범위 · 최적화 공간은 모두 `features.yaml` · `tasks/*.yaml` 에서 나온다(G-M03).
- **기동할 때 학습하지 않는다.** 6벌의 `@lru_cache state()` 기동 학습은 금지다. 모델은 등록부의 `production` 버전을 산출물 파일(해시 대조)에서 읽는다. 없으면 `503 model_not_ready` 다(G-M06).
- **평가는 하나의 방식이다.** `time_key` 가 있으면 시간순 분할을 강제한다. 시험 구간은 1회만 쓰고, 선정 · 보정 · 대기열에 쓰지 않는다. 모든 지표는 기준선과 함께 낸다. 평창식 표본 내 평가는 결함이다(G-M05).
- **예측 응답은 한 모양이다.** `predicted_strength` · `remaining_hours` · `delta_e` 같은 옛 키는 호환 라우터에만 남긴다. 표준 응답은 `prediction.value` 이고, 유형에 없는 필드도 `null` 로 둔다(G-M04).
- **운영 교체는 사람만 한다.** 감시는 재학습 **후보**까지만 만든다. `production` 으로 바꾸는 코드 경로는 승인 처리기 하나뿐이다(G-M09).
- **원천은 읽기만 하고 복사본으로 시험한다.** 루프는 실 Data Platform · 실 MES 를 부르지 않는다. 시험은 `tests/fixtures/<tenant>/` 사본과 팩 합성 생성기로 판정한다. 실연결(`doctor-live`)은 사람이 키를 넣은 뒤에만 한다(D-13).
- **기존 6벌은 원천이다.** 읽어서 옮기기만 한다(이관 도구). 그 폴더를 고치거나 실행하지 않는다. 광성 VPS 도 건드리지 않는다.

---

## 1. 목표

**mlp 테이블 16 을 PostgreSQL 에 만든다. 코어(소스 어댑터 · 표준 프레임 · 스냅숏 · 전처리 공장 · 분할 정책 · 챔피언 선정 · 등록부 · 산출물 · 추론 계약 · 최적화 · 감시 · 승인 · 감사 · 인증)를 세운다. 팩 `press` · `textile` 과 회사 `ks` · `sw` 를 등록해 화면 6 · API 12 로 같은 코어를 쓰게 한다. 품질은 게이트로 판정한다.**

끝났다고 말할 수 있는 상태는 다음뿐이다.

1. **수직 관통(웨이브 A0):** `ks.remaining_hours` 와 `sw.delta_e` 가 **같은 코어 코드**로 같은 흐름을 API 로 끝까지 돈다. 흐름은 fixture 스냅숏 → 학습 → `candidate` → 승인 → `production` → `predict` → `mlp_prediction` 기록 → `actuals` 등록 → `trace` 이고, 화면은 없어도 된다(G-V01).
2. 2사가 각각 `make run TENANT=<code>` 로 기동되고 병합 규칙 5(spec §11.3)를 통과한다. 코어 · 팩 코드는 회사마다 한 줄도 다르지 않다.
3. ks · sw 의 기존 기능 **전부**가 `docs/task-map.md` 에서 표준 과제에 대응되고, 그 과제가 켜져 돈다.
   - ks: 잔여수명 · 24시간 고장 · 이상 탐지 · 정비 시점.
   - sw: ΔE · 불량 · 이상 탐지 · 인쇄 조건 격자.
4. 켜진 과제 8개 모두가 다음 검사를 통과한다.
   - 예측 계약 시험과 누수 검사 · 결정성 검사.
   - 기준선을 이긴 기록.
   - 합성 재현 지표가 기존 보고값과 §2 G-M12 허용폭 안에 있거나, 벗어난 사유가 `docs/migration-report.md` 에 있다. 기존 보고값은 ks MAE 5.57h · R² 0.92 · AUC 0.64, sw MAE 0.557 · AUC 0.868 이다.
5. 재기동 시 재학습 0회. 같은 스냅숏 · 시드 재학습의 시험 예측 차이는 0 이다.
6. 감시: 일부러 드리프트를 넣은 fixture 에서 PSI 가 기준을 넘으면 재학습 후보가 승인 대기열에 오른다. 승인 전에는 `production` 버전이 바뀌지 않는다.
7. `make tenant NEW=yn PACK=_template` 로 새 회사를 **코드 수정 0줄**로 띄운다. 이어서 CSV fixture 로 학습 → 승인 → 예측까지 간다.
8. QA 3명의 리포트 3종이 `outputs/` 에 있고 치명 결함이 0이다.

### 재사용 자산 — 새로 짓기 전에 먼저 본다

| 자산 | 위치 | 쓰임 |
|---|---|---|
| 정본 | `intro.md` · `problem.md` · `spec.md` | 유형 · 계약 · 테이블 · 게이트의 출처. 수치가 다르면 `spec.md` 가 맞다 |
| 방법론 기준 구현 | `../KwangSung ML AI/api/{ml_service,config,main}.py` · `docs/methodology.md` · `docs/verification.md` | 시간순 432/144/144 · 검증 선정 → 재적합 → 시험 1회 · Brier 선정 · 결측 3개 보정 · 순열 중요도 · `extra=forbid` · 422 처리기. **구조만** 이식한다. 상수 dict 는 `features.yaml` 로 옮긴다 |
| 격자 최적화 | `../SongWol ML AI/api/ml_service.py` · `docs/*` | 고정 변수 + 조절 변수 5 전수 격자 8,400점 · 제약 3. sw MES 테이블 대응(`PRT_*` · `RCV_MATERIAL_LOTS`) → `tenants/sw.yaml: feature_map` 재료 |
| 위반 순위 대체 | `../PyoungChang ML AI/api/*` | 제약 미충족 시 `least_violation`. **평가 방식(표본 내 채점)은 가져오지 않는다** |
| 합성 생성기 | 6벌 `demo_data()` (시드 42 · 20260917) | `packs/<pack>/synth/*.py` 이관. 같은 시드에서 같은 행이 나오는지 대조한다 |
| CSV · 오류 처리 | 6벌 CSV 내보내기(수식 주입 방지 · BOM) · 422 처리기(입력값 되풀이 금지) | `serve/` 공용 모듈 |
| 배포 | `../KwangSung ML AI/docs/deployment.md` · `deploy/hostinger.compose.yaml` | 768MB · CPU 1 · `OMP_NUM_THREADS=1` · 커밋 SHA 태그. 1차는 로컬 compose 만 |
| 회사 · 표준 필드 | `../Standard Data Hub/companies/{ks,sw}.yaml` · `std/fields.yaml` | 회사 코드 · 착륙 테이블 · `std_name` 대응 |
| 골격 · 게이트 방식 | `../Standard Data Hub/src/datahub/app/` · `../Standard AI Agent Platform/gates/` | FastAPI 앱 구조 · `make gate` 판정표 형식. 패키지명은 `mlcore` |
| 콘솔 UI | `../KwangSung ML AI/web` · `../SongWol ML AI/web` (React · Vite · lucide) | 5화면 레이아웃 · 모델 비교 표 · 최적화 결과 표. 회사 문자열은 가져오지 않는다 |

---

## 2. 수용 게이트

**루프는 매 회전마다 이 표를 실행한다.** 판정은 명령의 출력으로만 한다(`make gate`).

### 2.0 수직 관통 게이트 — 웨이브 A0 의 유일한 목표

| # | 항목 | 게이트 | 검증 |
|---|---|---|---|
| G-V01 | 얇은 수직 관통 | `ks.remaining_hours`(fixture: ks 합성 스냅숏)와 `sw.delta_e`(fixture: sw 합성 스냅숏)가 **같은 `mlcore` 코드와 다른 팩 · 등록부만으로** 끝까지 돈다. 흐름은 `POST .../train` → `candidate`(기준선 비교 포함) → `promote` 승인 → `POST .../predict`(표준 계약) → `mlp_prediction` 1행 → `POST .../actuals` → `GET /predictions/{id}/trace` 가 스냅숏 해시와 소스 참조까지 낸다. 화면은 없어도 된다 | `tests/test_vertical_slice.py` |

### 2.1 구조 게이트

| # | 항목 | 게이트 | 검증 |
|---|---|---|---|
| G-S01 | 스키마 | mlp 테이블 **16**(`contracts/db-schema.md`)이 계약과 실제 DB 의 열 단위까지 같다. `production` 부분 고유 색인이 있다. `mlp_prediction` · `mlp_audit` · `mlp_quote` 는 UPDATE/DELETE 권한이 없다. 전 테이블에 `tenant_id` 가 있다. `live` + `synthetic` 승격을 막는 검사 제약이 있다 | `gates/check_schema.py` |
| G-S02 | 팩 · 등록부 로드 | `packs/{press,textile,_template}` · `tenants/{ks,sw,_template}.yaml` 이 로드된다. 병합 규칙 5(spec §11.3)를 어긴 **불량 픽스처 5종**은 전부 기동 거부된다 | `gates/check_registry.py` |
| G-S03 | 화면 | 화면 **1~6**(`contracts/screen-map.md`)이 전부 HTTP 200 이고 `_placeholder` 는 0건이다. 화면 2 · 3 은 1024px 태블릿 폭에서 가로 스크롤이 없다. 입력 폼은 `features.yaml` 에서 생성되며 회사 화면 코드는 0 이다 | `make check-routes` · `tests/e2e/` |
| G-S04 | API | `/api/v1` **12** 묶음(spec §12.2 중 review · documents · quotes 제외)이 200 이고 오류 계약(§2.3) 모양을 따른다. 역할 · 회사 범위 밖은 403/404, 잘못된 입력은 422 다. 목록 응답은 `{items, next_cursor}` 다 | `make check-routes` · `tests/test_api_contract.py` |
| G-S05 | 읽기 전용 소스 | 소스 어댑터 **5**(synthetic · csv · gateway · dataplatform · mes)가 `DataSource` 인터페이스를 따른다. 어댑터 코드에 쓰기 SQL · 비 GET HTTP 가 0이다. fixture 원천 DB 의 행 수 diff 는 0이다. 실패는 `source_disconnected` 봉투로 내며 예외를 삼키지 않는다 | `gates/check_sources.py` · `tests/test_source_contract.py` |
| G-S06 | 비밀 · 회사 격리 | 키 문자열 · `.env` 커밋 0. 등록부에는 환경변수 **이름**만 있다. 다른 회사의 코드명 · 데이터 파일이 그 회사 폴더 밖에 0이다. 공개 저장소이므로 IP · 호스트명도 0이다 | `gates/check_secrets.py` · `gates/check_tenant_bleed.py` |
| G-S07 | 의존성 고정 | `uv.lock` · `web/package-lock.json` 이 있다. `latest` · `^` · `~` 범위 버전이 0이다. Python 3.12 하나 | `gates/check_pins.py` |

### 2.2 ML 게이트 — `problem.md` §4.1 G1~G12

| # | 항목 | 게이트 | 검증 |
|---|---|---|---|
| G-M01 | 코어 순수성 (G1) | `src/mlcore/` · `web/src/` 공용 코드에서 팩 변수 사전의 단어 · 과제 이름 · 회사 코드 · 회사명 · 원천 테이블 이름이 **0건**이다. `packs/` 에서 회사 코드 · 원천 테이블 이름이 0건이다 | `gates/check_core_terms.py` |
| G-M02 | 과제 대응 (G2) | ks · sw 기존 기능(Phase 0 실측 수: 엔드포인트 · 모델 · 최적화 · 화면 단위)의 **100%** 가 `docs/task-map.md` 에서 표준 과제 · 경로 · 화면에 대응된다. 미대응 0 | `gates/check_task_cover.py` |
| G-M03 | 과제 정의 (G3) | 팩마다 `features.yaml` · 과제 ≥ 2 · `synth/` · `baselines.yaml` 이 있다. 과제 YAML 은 스키마 · 변수 존재 · `uses` 존재 · 누수 규칙(`time_key` 있으면 시간순) · `approver_role` 을 갖춘다. 회사 덮어쓰기로 `type` · 분할 · 승인 지점을 바꾸면 거부된다 | `gates/check_tasks.py` |
| G-M04 | 예측 계약 (G4) | 켜진 과제 **8**개 전부의 `predict` · `predict:batch` 응답이 `contracts/predict-contract.md` JSON Schema 와 일치한다(키 누락 0 · 상태 코드 6종 안). 옛 경로(`/api/maintenance/predict` · `/api/quality/predict` · `/api/ml/overview` · `/api/data/records`)는 호환 라우터가 옛 키로 돌려준다 | `gates/check_contract.py` · `tests/test_compat.py` |
| G-M05 | 누수 없는 평가 (G5) | 시험 구간 인덱스가 선정 · 보정 · 예측 구간 · 임계값 계산에 들어가면 실패한다(계측 래퍼로 접근 기록). 시계열 과제는 시간순이고 `group_key` 경계를 넘지 않는다. 모든 `candidate` 에 기준선 비교가 있다. 기준선을 못 이기면 `staging` 이 거부된다. **표본 내 평가 픽스처**(평창식)는 거부된다 | `gates/check_leakage.py` · `tests/test_split.py` |
| G-M06 | 재현 · 등록부 (G6) | 같은 스냅숏 + 시드 + 코드 버전으로 재학습하면 시험 예측 차이가 0이다. 재기동 시 학습 함수 호출 0회(계측). 산출물 해시 · 패키지 버전이 다르면 `503 model_artifact_mismatch`. `production` 은 과제당 1개 | `gates/check_determinism.py` · `tests/test_registry.py` |
| G-M07 | 예측 추적 (G7) | 예측 1건의 `trace` 가 모델 버전 → 학습 실행 → 스냅숏(해시 · 기간 · 행 수) → 소스 참조를 낸다. `actuals` 는 `entity_id` 로 연결된다. `mlp_prediction` UPDATE 는 거부된다 | `tests/test_trace.py` |
| G-M08 | 소스 · doctor (G8) | `make doctor TENANT=ks|sw` (fixture)가 소스별로 행 수 · 기간 · 변수 대응률 · 결측률을 내거나 `미연결` · `목표 없음` 을 낸다. 실연결(`doctor-live`)은 `BLOCKED (D-13)` 을 허용한다 | `make doctor` · `tests/test_doctor.py` |
| G-M09 | 감시 · 승인 (G9) | PSI · 범위 밖 · 결측 · 실측 성능 계산이 손 계산 fixture 와 일치한다. 드리프트 fixture → 재학습 후보 → `mlp_approval` 이 생기고 `production` 은 그대로다. `production` 을 쓰는 코드 경로는 `approval.decide()` 하나다. **동시 승인 2건 중 하나만 성공하고 하나는 409** 다 | `gates/check_no_autopromote.py` · `tests/test_monitor.py` · `tests/test_approval.py` |
| G-M10 | 새 회사 (G10) | `make tenant NEW=yn PACK=_template` → CSV fixture 소스 → doctor → train → 승인 → predict 가 코드 수정 0줄로 통과한다. 생성된 파일은 `tenants/yn*` 뿐이다 | `tests/test_new_tenant.py` |
| G-M11 | 보안 · 배포 (G11) | API 키는 해시로 저장한다. 역할 4(viewer · operator · approver · admin)가 §6 표대로 거부한다. 다른 회사 키는 404 다. `docker compose config` 기준으로 DB 포트를 외부에 노출하지 않고, 앱 포트는 하나이며 헬스체크가 있다. CORS 는 설정 목록만 허용한다 | `tests/test_auth.py` · `gates/check_deploy.py` |
| G-M12 | 이관 대조 | `docs/migration-report.md` 에서 ks 4과제 · sw 4과제가 같은 합성 시드로 기존 보고 지표와 비교된다. 같은 방법론(시간순 · 재적합)이므로 **±10% 안** 이거나, 벗어나면 원인(분할 경계 · 그룹 · 후보 차이)이 행마다 있어야 한다. 6벌 `demo_data()` 와 팩 `synth/` 의 행 일치는 100% 다 | `gates/check_migration.py` |
| G-M13 | 최적화 | `ks.maintenance_timing`(1차원 격자) · `sw.print_setpoint`(5차원 격자)를 시험한다. 탐색점은 전부 학습 범위 ∩ `min/max` 안이다. 제약 충족 후보만 `ok` 이고, 불가능하면 `least_violation` + `review` 다. 추천은 `mlp_recommendation` 에 `needs_approval` 로 남는다. 10,000점 ≤ 10초 | `tests/test_optimize.py` |
| G-M14 | 비기능 | 다음 기준을 768MB · CPU 1 compose 제한 아래에서 잰다(spec §17). 단건 predict p95 ≤ 200ms, batch 500 ≤ 3초, 기동 ≤ 15초, app RSS ≤ 768MB | `make bench` |

### 2.3 오류 계약 — QA1 · QA3 가 그대로 테스트 케이스로 쓴다

| 상황 | 응답 |
|---|---|
| 모르는 키 · NaN · Infinity | 422 `invalid_input`. 입력값을 메시지에 되풀이하지 않는다 |
| 필수 변수 누락 · 보정 한도(`max_imputed`) 초과 | 422 `missing_required` |
| `min/max` 밖 (물리적으로 불가능한 값) | 422 `out_of_bounds` |
| 학습 범위 밖 (검증 범위 안) | 200 + `status: out_of_range` + 경고. 과제가 `reject` 정책이면 200 + `status: rejected` |
| `production` 모델 없음 | 503 `model_not_ready`. 대체 모델 · 기본값 응답 없음 |
| 산출물 해시 · 패키지 버전 불일치 | 503 `model_artifact_mismatch` |
| 소스 실패 (train · doctor) | 503 `source_disconnected` (doctor 는 200 + 해당 소스 `미연결`) |
| 역할 밖 | 403 `forbidden` |
| 다른 회사 · 없는 과제 · 없는 예측 ID | 404 `not_found`. 존재 여부를 숨긴다 |
| 이미 결정 · 만료된 승인 재결정 | 409 `already_decided` |
| 같은 스냅숏 · 같은 설정 학습 재요청 | 200 + 기존 `run_id` (새 학습 없음) |
| 2차 유형 경로 (review · documents · quotes) | 501 `not_implemented` |

### 2.4 범위 밖 — 실패로 보지 않는다

- 실 Data Platform · 실 MES · 실 Gateway 연결(`doctor-live` · `train-live`)은 키가 없으면 `BLOCKED (D-13)` 이다.
- 기존 6벌 원천의 결함(평창 표본 내 평가 · 원터치 문서 링크 누락 등)은 이관 보고서에 잡혀 있으면 통과다. 원천은 고치지 않는다.
- VPS 배포 · HTTPS 프록시 실구성(1차는 compose 설정 검사까지).
- 2차 범위(§10) 전부.

---

## 3. 팀 편성과 웨이브

```
Phase 0   스키마 16 · 표준 시드 · 계약 8 · 팩/등록부 골격 · 원천 조사(ks · sw) · fixture · 게이트 도구 (아키텍트 단독)
   ↓
웨이브 A0 수직 관통 (개발 3, 각자 담당 부분만 얇게)   ks.remaining_hours × sw.delta_e, API 만   → G-V01
   ↓
웨이브 A  개발 3 (병렬) 넓히기   유형 4 · 과제 8 · 감시 · 호환 라우터 · 화면 1~6   → G-S01~G-S07 · G-M01~G-M14
   ↓
웨이브 B  QA 3 (병렬)     데이터/학습/평가 · 추론/계약/보안 · 화면/최적화/승인/새 회사
   ↓
웨이브 C  결함 수정 (담당 개발 + 아키텍트)
   └──── 게이트 전건 PASS 까지 B→C 반복
```

### 3.1 Phase 0 — 아키텍트 (spec → 계약 · 골격). 여기가 가장 중요하다

1. 기본 골격을 만든다.
   - 저장소는 이미 원격과 연결되어 있다. 커밋은 로컬에만 한다.
   - `.gitignore` 에 `.env` · `var/` · `*.joblib` · `*.parquet` 를 넣는다. 단 `tests/fixtures/` 는 예외다.
   - `uv`(Python 3.12), DB `ml_db` · `ml_test_db`, `.env.example`(접두 `MLP_`), API 포트 **8200**, 웹 개발 포트 **5190**.
2. `decisions.md` — §7 의 D-01~D-20 을 옮겨 적는다.
3. `std/{task_types,statuses,metrics,split_policies,candidates,roles}.yaml` — `spec.md` §2 · §5.2 · §5.3 에서 만든다. **분류의 유일한 출처**다.
4. `contracts/` 8종 — `db-schema` · `interfaces`(`DataSource` · `Trainer` · `Registry` · `Predictor` · `Optimizer`) · `task-contract`(YAML 스키마) · `feature-contract` · `predict-contract`(JSON Schema) · `pack-contract` · `tenant-contract` · `api-contract` · `screen-map`. `spec.md` 와 대조해 모자란 시그니처를 채운다.
5. `src/mlcore/db/schema.sql`(16) · `seed_std.py`.
6. **원천 조사** — ks · sw 저장소를 **파일을 직접 열어** 센다. 결과는 `migration/source_inventory.md` 에 회사 · 파일:줄 · 수로 적는다. 이 수가 G-M02 의 분모이고 G-M12 의 대조값이다.
   - 엔드포인트, `FEATURE_META` 변수 수, 후보 모델 수, 분할, 보고 지표, 최적화 공간, 화면, 시험 함수.
   - 같은 문서에 sw `docs/*` 의 MES 테이블 대응을 적는다. `feature_map` 의 재료다.
7. 팩 · 등록부 골격과 fixture 를 만든다.
   - `packs/{press,textile,_template}` 골격: `pack.yaml` · `features.yaml` · `tasks/*.yaml`.
   - `tenants/{ks,sw,_template}.yaml` 골격. 키는 환경변수 **이름**만 적고, 확인 못 한 값은 `# 미확인` 으로 둔다.
   - `tests/fixtures/{ks,sw}/`: 합성 스냅숏 Parquet, 드리프트 fixture, CSV fixture(새 회사용), 원천 DB 사본(gateway · mes 어댑터 시험용, 행 수 diff 측정 대상), 그리고 `fixtures/README.md`(출처 · 생성 명령).
8. 앱과 콘솔 골격을 세운다.
   - 웹 골격: FastAPI · API 키 인증 · 감사 미들웨어 · `/api/v1/health`.
   - React 콘솔 골격(`web/`, 정확한 버전 고정)과 화면 1~6 `_placeholder`.
9. 게이트와 상태 파일을 만든다.
   - 게이트: `gates/{gate,check_schema,check_registry,check_routes,check_sources,check_secrets,check_tenant_bleed,check_pins,check_core_terms,check_task_cover,check_tasks,check_contract,check_leakage,check_determinism,check_no_autopromote,check_deploy,check_migration}.py` · `Makefile`(`gate` · `gate-full` · `doctor` · `train` · `run` · `tenant` · `bench` · `check-routes`).
   - `CLAUDE.md`: 기존 `## 이슈 자동 등록 규칙` 블록은 **그대로 두고** 그 위에 프로젝트 규칙을 덧붙인다.
   - `progress.md` 첫 섹션. `make gate` 가 판정표를 낸다.

Phase 0 의 끝은 G-S01 · G-S02 · G-S06 · G-S07 · G-M01 이 PASS 인 상태다. G-V01 은 FAIL 이 정상이다(웨이브 A0 의 목표).

### 3.2 개발 3명 — 엔진 3분할 (한 파일은 한 사람만 만진다)

경로는 모두 `src/mlcore/` 기준이다. 저장소 루트의 `packs/` · `tenants/` 는 데이터, `gates/` 는 검증 스크립트다.

| 담당 | 엔진 | 공용 모듈 | 화면 · API |
|---|---|---|---|
| **개발1** 데이터 · 학습 | 소스 어댑터 5 · 표준 프레임 · 시계열 결합 · 스냅숏(Parquet · SHA-256 · 학습 범위) · 전처리 공장 · 후보 사전 · 분할 정책 4 · 선정 · 재적합 · 시험 1회 · 기준선 · 예측 구간(split conformal) · 확률 보정 · 학습 보고서 · 학습 작업 큐 | `data/*` · `train/*` (**`DataSource` · `Snapshot` · `TrainResult` 를 A0 초반에 공표**) | 화면 4 모델 비교 · 검증 · API `/train` `/runs/{id}` |
| **개발2** 등록부 · 추론 · 승인 | 모델 등록부(상태 전이) · 산출물 적재/해시 대조 · 입력 검증 · 결측 보정 · 범위 판정 · 표준 예측 계약 · 예측 기록 · 실측 연결 · 추적 · 유형 `regression` · `risk` · `anomaly` 의 추론부 · `optimize` · 승인 트랜잭션 · 감사 · 인증/역할 · 호환 라우터 | `registry/models.py` · `serve/*` · `tasks/*` · `approval/` · `audit/` · `auth/` (**`Predictor.predict()` · 응답 모델을 A0 에서 가장 먼저 공표**) | 화면 2 예측 시험 · 3 조건 추천 · 5 승인 대기열 · API `/predict*` `/optimize` `/actuals` `/models*` `/approvals*` `/predictions/{id}/trace` |
| **개발3** 팩 · 회사 · 감시 · 이관 | 팩/등록부 로더 · 병합 규칙 5 · 팩 `press` · `textile` 내용 · 회사 `ks` · `sw` · 이관 도구(M1~M5) · 감시(PSI · 범위 밖 · 결측 · 실측 성능) · 스케줄러 · 재학습 후보 생성 · `make tenant` · doctor | `registry/{packs,tenants}.py` · `monitor/*` · `../../migration/*` | 화면 1 개요 · 6 감시 · API `/tasks*` `/overview` `/records` `/monitor` `/doctor` `/health` |

- **A0 (수직 관통)** — 셋이 동시에 **얇게** 만든다. 목표는 G-V01 하나다. 화면 · 최적화 · 감시 · 호환 라우터는 하지 않는다.
  - 개발1: `synthetic` · `csv` 어댑터, 스냅숏, `time_60_20_20`, 후보 2종, 기준선.
  - 개발2: 등록부 · 산출물, `predict` · 기록 · `trace`, `approval.decide()`.
  - 개발3: `press.remaining_hours` · `textile.delta_e` 정의, `features.yaml`, `ks` · `sw` 등록부, 합성 생성기 이관 2개.
- **A (넓히기)** — 공용 모듈부터 채우고 화면은 마지막에 한다.
  - 개발1: 어댑터 5 전부 · 분할 4 · 후보 사전 전부 · 보정 · 구간 · 보고서 → 화면 4.
  - 개발2: 유형 4 전부 · 범위 판정 · 배치 · 최적화(격자 · 무작위 · 위반 순위) · 경합 안전 승인 · 역할 · 호환 라우터 → 화면 2 · 3 · 5.
  - 개발3: 과제 8 전부 · 이관 대조 보고서 · 감시 · 스케줄러 · 불량 픽스처 5종 · `make tenant` → 화면 1 · 6.
- 상태 배지 · 지표 표 · 변수 폼 생성기 컴포넌트는 개발2 의 `web/src/components/` 하나만 쓴다.

### 3.3 QA 3명 — 서로 다른 관점으로 교차 검증

| 담당 | 범위 | 산출 |
|---|---|---|
| **QA1** 데이터 · 학습 · 평가 | G-V01 · G-S05 · G-M03 · G-M05 · G-M06 · G-M08 · G-M12. **누수 사냥**에 집중한다. 시험 인덱스가 보정 · 구간 · 임계값에 새는지, 같은 LOT · 설비가 구간을 넘는지, 재적합에 시험 구간이 들어가는지, 기준선 계산이 시험 구간을 보는지 본다. 결정성(스레드 수 · 정렬 순서 · dict 순서), 스냅숏 해시가 열 순서에 흔들리는지도 본다. 기존 보고 지표는 **원천 저장소 코드를 직접 읽고 자기 스크립트로** 재계산한다 | `outputs/qa1-데이터학습평가.md` |
| **QA2** 추론 · 계약 · 보안 | G-S04 · G-S06 · G-S07 · G-M01 · G-M04 · G-M07 · G-M11 · G-M14. 계약 키 누락, 유형별 `null` 규칙, NaN/Infinity/거대 수/유니코드 입력, `max_imputed` 경계, 범위 밖 판정 경계(p1/p99), 산출물 파일 바꿔치기, 다른 회사 키로 예측 · 추적, 역할 우회, 호환 라우터의 옛 키 정확성, 코어에 팩 용어가 새는지, 키 · IP 오염 검색 | `outputs/qa2-추론계약보안.md` |
| **QA3** 화면 · 최적화 · 승인 · 새 회사 | G-S02 · G-S03 · G-M02 · G-M09 · G-M10 · G-M13. 오류 계약 전수, 실제 브라우저로 화면 1~6(1024px 포함), **두 탭 동시 승인 · 승인 직후 새 후보 도착 · 되돌리기**, 최적화가 학습 범위 밖 점을 추천하는지, 불가능 제약에서 `ok` 가 나오는지, 드리프트 fixture 후 `production` 이 바뀌는지, 불량 등록부 5종 기동 거부, `make tenant` 를 빈 폴더에서 처음부터 | `outputs/qa3-화면최적화승인.md` · `outputs/e2e/` |

결함 ID 는 `DEF-QA{n}-nnn`, 등급은 치명/중대/경미다. **QA 는 고치지 않는다.** 다음 중 하나라도 나오면 **치명**이다.
- 시험 구간이 선정 · 보정에 쓰였다.
- 승인 없이 `production` 이 바뀌었다.
- 같은 승인이 두 번 결정됐다.
- 모델이 없는데 값이 나갔다.
- 합성 모델이 `live` 에서 운영됐다.
- 다른 회사 예측이 보였다.
- 원천에 쓰기가 일어났다.

---

## 4. 루프 엔지니어링 프로토콜

### 4.1 상태 파일

| 파일 | 역할 | 쓰는 사람 |
|---|---|---|
| `goal.md` | 목표 · 게이트 (이 문서). **판정 기준** | 사람만 |
| `intro.md` · `problem.md` · `spec.md` | 정본. 수치의 출처 | 사람만 |
| `progress.md` | **검증된 현황의 유일한 진실.** `\| 항목 \| 실측 \| 검증 방법 \|` 3열 + 맨 위 "지금 해야 할 것" | 루프 오케스트레이터 |
| `decisions.md` | 결정 대장 `D-nn`. 상태는 `확정` / `가설` / `차단` / **`표준 변경 요청`** / **`계약 불일치`** | 전원 |
| `progress-dev{1,2,3}.md` | 개발자별 진행 · 공표(§1) · 요청(§3) | 각 개발자 |
| `outputs/qa{1,2,3}-*.md` | QA 리포트 | 각 QA |
| `contracts/*.md` | 코드 계약. **계약이 정본이다.** 코드와 다르면 발견자가 `decisions.md` 에 `계약 불일치` 로 올리고, **아키텍트가 어느 쪽을 고칠지 정한다** | 아키텍트 |
| `packs/*` · `tenants/*` | 팩 · 등록부 · 변수 대응 | 개발3(구조 변경은 아키텍트) |
| `packs/*/baselines.yaml` | 합성 기준 지표 | 아키텍트만. **좋게 바꿀 수만 있고 나쁘게 바꿀 수 없다** |
| GitHub 이슈 (`ai-found`) | 이번 회전에 고치지 않는 결함 · 보류 TODO | `CLAUDE.md` 규칙대로 전원 (중복 확인 후 등록) |

### 4.2 한 회전에서 하는 일 (순서를 바꾸지 않는다)

1. **읽기** — `progress.md` 최신 섹션 · `decisions.md` 미결 · 직전 QA 리포트를 읽는다. `progress.md` 가 없으면 Phase 0 이다.
2. **판정** — `make gate` 를 돌린다(스키마 → 로드 → 정적 검사 → pytest → 계약 · 누수 · 결정성 → 판정). FAIL 목록을 얻는다.
3. **선택** — FAIL 중 **가장 앞선 웨이브의 항목 1개**를 고른다. 웨이브 순서는 Phase 0 → **A0(G-V01)** → A → B → C 다. G-V01 이 FAIL 인 동안에는 다른 게이트를 넓히지 않는다.
4. **기동** — §5 프롬프트로 담당 에이전트를 띄운다. 병렬 가능한 것은 한 번에 띄우고, 작은 수정은 직접 한다.
5. **검증** — 보고를 믿지 않는다. 게이트 명령을 **직접 다시 실행**한다. 분할 · 선정 · 전처리 · 산출물을 고쳤다면 반드시 `check_leakage` · `check_determinism` · `check_migration` 을 다시 돈다. 계약 · 라우터를 고쳤다면 `check_contract` 를 다시 돈다.
6. **기록 · 커밋** — `progress.md` 에 실측과 명령을, 새 결정은 `decisions.md` 에 적는다. 커밋은 `git add -A && git commit -m "<G-nn|웨이브>: <한 줄>"` 로 로컬에만 한다. 이번 회전에 고치지 않은 결함은 `CLAUDE.md` 규칙대로 GitHub 이슈로 올린다.
7. **다음 회전** — FAIL 이 남았으면 예약한다. 에이전트가 돌고 있으면 길게(20분 이상) 기다린다.

### 4.3 멈추지 않기 위한 규칙

- **막히면 우회한다.** 사람 확인이 필요한 값은 `차단` 으로 올리고, 화면에는 `미확정 (D-nn)` 으로 둔다.
- **원천이 이상해도 원천을 고치지 않는다.** 6벌의 결함 · 모순은 `docs/migration-report.md` 에 적고, 팩에는 정리된 사본만 둔다.
- **표준 변경 요청.** 팩을 만들다가 과제 유형 · 상태 · 지표 · 분할 정책 · 후보가 모자라면 코어를 바로 고치지 않는다. `decisions.md` 에 `표준 변경 요청` 을 올린다. 팩 로직을 코어로 승격하는 것은 "팩 둘 이상이 쓸 때" 만이다.
- **계약 불일치.** 기본은 코드를 계약에 맞추는 것이다. 계약이 틀렸다고 판단되면 `계약 불일치` 로 올리고, 아키텍트가 정한 뒤 계약과 코드를 함께 고친다. 코드를 근거로 계약을 조용히 바꾸지 않는다.
- **같은 실패를 2회 넘게 반복하지 않는다.** 3회째면 접근을 바꾸고, 그래도 안 되면 `차단` 으로 올린다.
- **게이트를 낮추지 않는다.** 다음은 모두 게이트를 낮추는 것이다.
  - 시험 구간을 줄이거나 바꿔서 지표 맞추기, 시드 골라 쓰기.
  - 기준선 낮추기, `baselines.yaml` 하향.
  - 허용폭(±10%) 늘리기.
  - 결정성 검사에서 열 · 단계 빼기.
  - 누수 계측 래퍼 우회.
  - 계약 스키마에서 필드를 선택 항목으로 바꾸기.
  - 자동 승격 예외 만들기.
  - fixture 를 기대값에 맞춰 손질하기.
- **한 파일은 한 사람만.** 소유권은 `screen-map.md` · §3.2 를 따른다.
- **동시에 3명 이하.** 스키마 재생성 · 전체 재학습 · 벤치마크는 한 번에 하나만 한다.
- **이 폴더 밖은 읽기만 한다.** 6벌 · 표준 MES · 허브 · Agent 플랫폼 · Data Platform 에 쓰지 않는다. 다른 사업의 포트 · DB 를 쓰지 않는다.
- **밖으로 내보내지 않는다.** push · 배포 · 외부 전송을 하지 않는다. 단, GitHub 이슈 등록(`CLAUDE.md` 규칙)은 예외다. push 는 사람이 요청할 때만 한다.

### 4.4 종료 조건 (EXIT) — 넷을 동시에 만족하면 멈춘다

1. G-V01 · G-S01~G-S07 · G-M01~G-M14 **전건 PASS**. `BLOCKED` 는 D-번호와 사유가 있어야 하며, 실연결(`doctor-live` · `train-live`)만 `BLOCKED (D-13)` 을 허용한다.
2. §1 의 1~7 을 `make gate-full` 로 확인
3. QA 리포트 3종이 있고 **치명 결함 0**
4. **연속 2회전 동안 `progress.md` 에 새 실측 변화가 없음**

멈출 때 `progress.md` 맨 위에 최종 보고를 쓴다.
- 게이트 판정표.
- 과제 8 표: 유형 · 챔피언 · 시험 지표 · 기준선 · Δ · 기존 보고값 · 차이 사유.
- 과제 대응률과 미대응 목록.
- 이관 중 발견한 원천 결함 Top 20.
- 사람이 정해야 할 D-목록, 미처리 표준 변경 요청, 열린 GitHub 이슈 목록.
- 2차 착수 전 확인 사항.

### 4.5 중단 · 재개

세션이 끊기면 `progress.md` 최신 섹션과 `decisions.md` 미결만 읽고 **4.2 의 1번부터** 시작한다. 대화 기록에 의존하지 않는다.

---

## 5. 에이전트 기동 프롬프트 (그대로 복사해 쓴다)

모든 프롬프트는 아래 **공통 서두**로 시작한다.

> 너는 표준 ML 플랫폼 개발팀의 [역할]이다. 작업 폴더는 `/Users/gerardo92/Desktop/AI Coding/Standard ML Platform`.
> 작업 전에 `CLAUDE.md` · `goal.md` · `contracts/` · `decisions.md` · `progress.md` 를 먼저 읽는다. 정본은 `intro.md` · `problem.md` · `spec.md` 이며 읽기만 한다.
> 이 시스템은 **ML 서비스를 찍어 내는 틀**이다. 코어(`src/mlcore`)에 업종 변수 · 과제 이름 · 회사명이 들어가면 실패다. 팩(`packs/`)에 회사 원천 테이블 · 열 이름이 들어가도 실패다. 회사 차이는 `tenants/<code>.yaml` 에만 둔다.
> **누수 없이 잰다.** 시계열은 시간순, 시험 구간은 1회만 쓴다. 선정 · 보정 · 구간 · 임계값 · 대기열은 검증 구간이나 운영 잔차로만 한다. 모든 지표는 기준선과 함께 낸다. 시험 구간이 새면 치명 결함이다.
> **재현된다.** 기동 시 학습하지 않는다. 모델은 등록부 + 해시 대조 산출물에서만 읽는다. 같은 스냅숏 · 시드 · 코드면 같은 예측이 나와야 한다.
> **사람만 운영 모델을 바꾼다.** `production` 으로 가는 길은 `approval.decide()` 하나다. 감시는 후보까지만 만든다.
> **지어내지 않는다.** 모델이 없으면 `503 model_not_ready`, 소스 실패는 `source_disconnected` / `미연결`, 학습 범위 밖이면 `out_of_range` 다. 기본값 · 대체 모델로 조용히 답하지 않는다.
> **원천은 읽기만 한다.** 시험은 `tests/fixtures/` 와 팩 합성 생성기로 한다. 실 Data Platform · MES · Gateway 는 부르지 않는다. fixture 는 기대값에 맞춰 손질하지 않는다.
> **계약이 정본이다.** 테이블 · 시그니처 · 과제 규격 · 예측 계약 · API 는 `contracts/` 를 따른다. 다르면 `decisions.md` 에 `계약 불일치` 로 올리고, 아키텍트 결정을 기다리는 동안 다른 항목을 한다.
> 담당 밖 파일과 이 폴더 밖은 고치지 않는다. 끝나면 실측값과 검증 명령을 [본인 진행 파일]에 적는다. 이번에 고치지 않는 결함은 `CLAUDE.md` 의 이슈 자동 등록 규칙을 따른다. 키 · IP · 호스트명은 문서 · 코드 · 등록부 · 로그 · 이슈에 적지 않는다.
> 환경: PostgreSQL 17 (unix socket `/tmp`) · DB `ml_db` · 시험 DB `ml_test_db` · API 포트 8200 · 웹 5190 · `uv` / Python 3.12 · 명령은 `uv run …` · 환경변수 접두 `MLP_` · 검증 스크립트는 `gates/` · 학습 시 `OMP_NUM_THREADS=1`.

**아키텍트 (Phase 0)**
> §3.1 의 1~9 를 순서대로 한다. `spec.md` §10.1 · §12.2 · §2.3 · §5.3 에서 테이블 16 · API 묶음 15(1차 12) · 상태 6 · 분할 정책 4 를 직접 센다. `contracts/` 의 수와 맞는지 확인해 `progress.md` 에 실측으로 적는다.
> 가장 공들일 것은 `migration/source_inventory.md` 와 `contracts/predict-contract.md` 다.
> - 인벤토리: ks · sw 의 엔드포인트 · 변수 · 모델 · 분할 · 지표 · 최적화 공간 · 화면을 **파일을 직접 열어** 센 표다.
> - 예측 계약: 유형 4 각각의 응답 예시와 JSON Schema 다. 계약을 쓰기 전에 종이 위에서 "ks 잔여수명 · ks 고장 위험 · sw 이상 탐지 · sw 인쇄 조건 추천이 같은 모양으로 들어가는가" 를 먼저 맞춰 본다.
> 골격은 `../Standard Data Hub/src/datahub/app/` 에서 구조만 이식하고, 패키지명은 `mlcore` 로 한다. `gates/check_core_terms.py` · `check_secrets.py` · `check_leakage.py`(계측 래퍼 설계)를 가장 먼저 만든다. 끝나면 `make gate` 판정표를 `progress.md` 에 붙인다.

**개발1 (데이터 · 학습 / 화면 4)**
> 담당: `data/*` · `train/*` · 화면 4 · API `/train` `/runs/{id}`.
> A0 에서는 `DataSource` · `Snapshot` · `TrainResult` 를 `progress-dev1.md` §1 에 **가장 먼저** 공표한다. 그다음 `synthetic` · `csv` 어댑터, 스냅숏(Parquet, **열 정렬 후** SHA-256, 변수별 p1/p99), `time_60_20_20`(`group_key` 경계), 후보 2종, 기준선을 만든다.
> A 에서 할 것:
> - 분할 정책 4 를 만들고, 각각 누수 시험부터 쓴다. 시험 인덱스 접근을 기록하는 래퍼를 `check_leakage` 와 공유한다.
> - 후보 사전 전부, 검증 선정 → 학습+검증 재적합 → 시험 1회 절차를 만든다.
> - 예측 구간은 split conformal, 확률 보정은 검증 구간으로 한다.
> - 순열 중요도는 시험 구간, 학습 보고서는 `report.json` 으로 낸다.
> - gateway · dataplatform · mes 어댑터는 fixture 원천 사본으로 시험한다(행 수 diff 0). 학습 작업은 회사당 동시 1개, 같은 스냅숏 · 설정이면 멱등이다.
> 화면 4: 후보별 검증 지표 · 선정 사유 · 시험 지표 대 기준선 · 중요도 · 잔차 · (risk) 보정 곡선 · 현재 `production` 과의 비교.

**개발2 (등록부 · 추론 · 승인 / 화면 2 · 3 · 5)**
> 담당: `registry/models.py` · `serve/*` · `tasks/*` · `approval/` · `audit/` · `auth/` · 화면 2 · 3 · 5 · API `/predict*` `/optimize` `/actuals` `/models*` `/approvals*` `/predictions/{id}/trace`.
> A0 에서는 `Predictor.predict()` 와 응답 모델(`contracts/predict-contract.md`)을 `progress-dev2.md` §1 에 **가장 먼저** 공표한다. 그다음 등록부 상태 전이, 산출물 저장/적재(해시 · `env.lock` 대조), predict · 기록 · trace, `approval.decide()` 를 만든다. `approval.decide()` 는 조건부 UPDATE 와 감사 INSERT 를 한 트랜잭션에서 하고, 경합 시험은 스레드 2개로 한다.
> A 에서 할 것:
> - 유형 4 의 추론부와 입력 검증 3단(형식 → `min/max` → 학습 범위), `max_imputed`, batch 500.
> - 최적화: 공간 = 학습 범위 ∩ `min/max` · `step`, `grid`/`random` 자동 선택, 제약 평가, `least_violation`, 상위 5, `mlp_recommendation`.
> - API 키 해시 · 역할 4 · 회사 범위.
> - 호환 라우터: ks · sw 옛 경로와 옛 키. 원천 저장소 응답을 그대로 재현하는지 시험한다.
> 화면 2: `features.yaml` 로 폼을 만들고 표준 응답 · 경고 · 보정 필드를 보여 준다. 화면 3: 고정 변수 입력 → 후보 5 · 제약 충족표 · 학습 범위 배지. 화면 5: 모델 · 추천 승인 카드(지표 비교 · 그림자 예측 차이 · 사유 입력).

**개발3 (팩 · 회사 · 감시 · 이관 / 화면 1 · 6)**
> 담당: `registry/{packs,tenants}.py` · `packs/{press,textile,_template}` 내용 · `tenants/{ks,sw,_template}*` · `monitor/*` · `migration/*` · 화면 1 · 6 · API `/tasks*` `/overview` `/records` `/monitor` `/doctor` `/health` · `make tenant`.
> A0: `press.remaining_hours` · `textile.delta_e` 과제 정의, 두 팩 `features.yaml`, ks · sw 등록부, 6벌 `demo_data()` → `synth/` 이관 2개(같은 시드 행 일치 시험).
> A 에서 할 것:
> - 과제 8 전부를 정의한다. ks 4 · sw 4 이고 `uses` · 제약 · 비용식(`formulas/` 순수 함수, ks 정비 비용식 이관)을 포함한다.
> - 병합 규칙 5 + 불량 픽스처 5종.
> - 이관 도구 M1~M5 → `docs/task-map.md` · `docs/migration-report.md`. 기존 지표 대조는 원천 저장소를 읽어 같은 시드로 한다.
> - 감시: PSI 10분위 · 범주 빈도, 범위 밖, 결측, 실측 성능. 손 계산 fixture 와 대조한다. 스케줄러 KST 02:00, 재학습 후보 → 승인 대기열.
> - doctor(fixture) · `make tenant`.
> 화면 1: 회사 · 과제 개요(운영 버전 · 어제 예측 수 · 경고 배지). 화면 6: 변수별 PSI · 범위 밖 · 결측 추이, 실측 성능 추이, 재학습 후보 링크.

**QA1 / QA2 / QA3 (웨이브 B, 병렬)**
> §3.3 의 담당 범위를 §2 게이트와 `contracts/` 로 검증한다. **고치지 않는다.** 결함은 `DEF-QA{n}-nnn` 으로 재현 절차 · 실측 · 기대값 · 담당을 `outputs/qa{n}-*.md` 에 적고, 통과 항목도 실측과 명령을 함께 적는다. 치명 · 중대 결함은 `CLAUDE.md` 규칙대로 GitHub 이슈로도 올린다(중복 확인 먼저).
> 검사기 출력은 `G-nn  항목  PASS|FAIL|WARN|BLOCKED  실측` 행으로 쓴다. 기대값은 개발 코드가 아니라 **원천 저장소 파일 · fixture · `spec.md`** 에서 가져온다.

---

## 6. 역할 · 권한 기본값 (`std/roles.yaml` — G-M11 의 기대값)

| 화면 · API | admin (공급기업) | approver | operator | viewer |
|---|---|---|---|---|
| 1 개요 · `GET /tasks*` · `/overview` · `/records` | ○ | ○ | ○ | ○ |
| 2 예측 시험 · `POST /predict*` · `/actuals` | ○ | ○ | ○ | ✕ |
| 3 조건 추천 · `POST /optimize` | ○ | ○ | ○ | ✕ |
| 4 모델 비교 · `POST /train` · `staging` 승격 | ○ | 조회 | ✕ | ✕ |
| 5 승인 대기열 · `POST /approvals/{id}/decide` · `promote` · `rollback` | ○ | ○ (자기 `approver_role` 과제만) | 조회만 | ✕ |
| 6 감시 · `/monitor` · `/doctor` | ○ | ○ | 조회 | ✕ |
| `GET /predictions/{id}/trace` · 감사 | ○ | ✕ | ✕ | ✕ |

`staging` 승격(ML 담당)은 1차에서 admin 이 맡는다. 별도 `ml_engineer` 역할은 `표준 변경 요청` 대상이다.

## 7. 결정 대장 — Phase 0 에서 `decisions.md` 로 옮긴다

### 7.1 열려 있는 결정 (`problem.md` §8 Q1~Q12 → D-01~D-12) — 사람이 답하기 전까지 기본값(가설)

| # | 확인 필요 | 기본값 (가설) | 바뀌어도 한 곳만 고치게 |
|---|---|---|---|
| D-01 | 배포 단위 (Q1) | 회사당 한 벌. 전 테이블에 `tenant_id` | `docker-compose.yml` |
| D-02 | 부스팅 라이브러리 (Q2) | `hist_gb` 기본, `lightgbm` 은 선택 의존성 · 기본 꺼짐 | `std/candidates.yaml` |
| D-03 | 등록부 구현 (Q3) | `mlp_*` + 파일 산출물. MLflow 없음 | `registry/models.py` 인터페이스 |
| D-04 | 승인자 (Q4) | 과제 `approver_role` 1인 | `tasks/*.yaml` · `approval/` |
| D-05 | 시계열 분할 (Q5) | `time_60_20_20`, 행 < 500 이면 `time_cv5` | `std/split_policies.yaml` |
| D-06 | 드리프트 기준 (Q6) | PSI 0.2 / 0.3 · 범위 밖 5% · 결측 +10%p · 성능 25% 악화 | `pack.yaml: monitor` |
| D-07 | 범위 밖 처리 (Q7) | `predict_with_warning`. 1차 과제 8개 모두 이 값 | `tasks/*.yaml: out_of_range` |
| D-08 | 목표 실측 원천 (Q8) | 1차는 fixture CSV · `actuals` API. 실 MES 매핑은 `차단` 가능 | `tenants/*.yaml: sources.actuals` |
| D-09 | 도면 라벨 (Q9) | 2차 | — |
| D-10 | 보존 (Q10) | 예측 · 감사 1년 · 집계 영구 · 산출물(운영 이력 있는 것) 영구 · 나머지 90일 | `monitor/retention.py` |
| D-11 | MES 예측 테이블 (Q11) | `mlp_prediction` 정본. `db/compat/sw.sql` 은 뷰 정의만(실행 안 함) | `db/compat/` |
| D-12 | 고려솔더 (Q12) | 2차, `demo` + CSV | — |

### 7.2 운영 결정

| # | 결정 | 값 | 한 곳 |
|---|---|---|---|
| D-13 | 실 원천 | 루프는 fixture · 합성만 쓴다. `doctor-live` · `train-live` 는 사람이 `.env` 에 `MLP_KS_DP_KEY` 등을 넣은 뒤 사람이 돌린다. 그 전까지 `BLOCKED (D-13)` | `Makefile` |
| D-14 | 포트 · DB | API 8200 · 웹 5190 · `ml_db` / `ml_test_db` (다른 표준 플랫폼 8100/5180 과 겹치지 않게) | `.env.example` |
| D-15 | 환경변수 접두 | `MLP_` | `.env.example` |
| D-16 | 1차 범위 | 팩 `press` · `textile`, 회사 `ks` · `sw`. 이 둘이 같은 방법론(시간순 · 재적합 · 결측 보정)을 이미 쓰므로 G-M12 대조가 의미 있다 | `goal.md` |
| D-17 | 이관 허용폭 | 같은 합성 시드 기준 기존 보고 지표 ±10%. 벗어나면 행마다 사유가 필요하다. 허용폭은 넓힐 수 없다 | `gates/check_migration.py` |
| D-18 | 호환 라우터 수명 | 1차에 ks · sw 옛 경로를 제공하고, 2차 종료 6개월 뒤 제거 | `serve/compat/` |
| D-19 | 결정성 범위 | 같은 머신 · 같은 `env.lock` · `OMP_NUM_THREADS=1` 에서 예측 차이 0. 다른 머신은 1e-9 허용 | `gates/check_determinism.py` |
| D-20 | 공개 저장소 위생 | 원격 저장소가 공개이므로 IP · 호스트명 · 회사 실데이터는 커밋하지 않는다. fixture 는 합성 또는 익명화 사본만 | `gates/check_secrets.py` |

## 8. 지켜야 할 것

- **코어는 업종을 모르고, 팩은 회사를 모른다.**
- **시험 구간은 한 번만 본다.** 누수를 막는 장치를 끄는 설정을 만들지 않는다(시험 모드 포함).
- **모델은 등록부에서만 온다.** 기동 학습 · 코드 안 버전 상수 · 등록부 밖 모델 파일을 두지 않는다.
- **운영 교체는 승인으로만 한다.** 자동 승격 경로를 만들지 않는다.
- **예측 응답은 한 모양이다.** 유형마다 키를 빼지 않는다.
- **변수 · 과제 · 제약은 YAML 이다.** 코드 안 변수 dict · 회사 테이블 이름 · 임계값 상수가 0이어야 한다.
- **실패를 보인다.** `model_not_ready` · `미연결` · `out_of_range` · `목표 없음` 을 숨기거나 합성 값으로 대체하지 않는다.
- **추천은 추천이다.** 설비 · MES 에 쓰지 않는다.
- **계약이 정본이다.** 정본(`spec.md`)의 결함 · 모순은 고치지 말고 `decisions.md` 에 적은 뒤 최종 보고에 올린다.

## 9. 실측 방법

```bash
# spec.md 와 contracts 에서 직접 센다 — 테이블 16 · 유형 7(1차 4) · 상태 6 · 분할 4 · API 15(1차 12)
grep -cE '^\| `mlp_[a-z_]+` \|' spec.md                                   # 16 (§10.1)
sed -n '/^### 2.1/,/^### 2.2/p' spec.md | grep -cE '^\| `[a-z_]+` \|'   # 7 (§2.1)
grep -cE '^\| `(ok|watch|review|out_of_range|rejected|needs_approval)` \|' spec.md          # 6 (§2.3)
grep -cE '^\| `(time_60_20_20|time_cv5|stratified_60_20_20|random_60_20_20)` \|' spec.md    # 4 (§5.3)
grep -cE '^\| `(GET|POST|PATCH) ' spec.md                                  # 15 (§12.2, 1차는 review · documents · quotes 를 뺀 12)
ls tenants/*.yaml | grep -v _template | wc -l                              # 2 (1차)
make gate          # 로드 → 정적 검사 → pytest → 계약 · 누수 · 결정성 → 판정
make gate-full     # 스키마 재생성 + 과제 8 전체 재학습 2회(결정성) + 이관 대조 + 새 회사 시험 + 승인 경합 + bench — 종료 판정은 이것으로
```

## 10. 2차 범위 (1차 종료 후 별도 루프)

| 항목 | 내용 | 2차 게이트의 핵심 |
|---|---|---|
| 유형 3 | `review_queue` · `extract` · `quote` — **2차 착수 전에 코어에 넣고 1차 게이트를 다시 돈다** | 이후 `src/mlcore/` 변경 **0줄** |
| 팩 4 | `solder` · `kimchi` · `rollform-quote` · `eto` | 팩 · 회사 파일만 추가 |
| 회사 4 | `krs` · `pc` · `ot` · `kd` | 기존 기능 대응 100% · 평창 표본 내 평가는 표준 절차로 다시 잰 값으로 대체(보고서에 이전 값과 함께) |
| 화면 4 | 7 데이터 소스 · 스냅숏 · 8 검토 대기열 · 9 도면 추출 · 견적 · 10 감사 · 예측 추적 | — |
| API 3 묶음 | `/review*` · `/documents*` · `/quotes*` | 오류 계약 · CSV 수식 주입 방지 |
| 연동 | AI Agent 플랫폼 `ml.*` 도구 계약 · 데이터 허브 `make export-hub` | spec §18-10 |
| 실데이터 | 사람이 키를 준 회사부터 `train-live` → 최소 1과제 실데이터 `production` | spec §18-7 |

1차에서 코어를 고쳐야 2차가 된다고 판명되면, 그것은 1차의 결함이다. `decisions.md` 에 올리고 1차 게이트를 다시 돈다.
