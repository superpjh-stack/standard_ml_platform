# 표준 ML 플랫폼 — 프로젝트 규칙

> 작업 전에 `goal.md`(판정 기준) · `contracts/`(정본 계약) · `decisions.md` · `progress.md` 를 먼저 읽는다.
> 정본 `intro.md` · `problem.md` · `spec.md` · `goal.md` 는 사람만 고친다. 결함 · 모순은 `decisions.md` 에 적는다.

## 지켜야 할 것 (goal §8 요지)

- **코어는 업종을 모르고, 팩은 회사를 모른다.** `src/mlcore/` · `web/src/` 에 팩 변수 · 과제 이름 · 회사 코드 · 회사명 · 원천 테이블 0건, `packs/` 에 회사 · 원천 테이블 · 설비 코드 0건(G-M01). 회사 차이는 `tenants/<code>.yaml` 에만.
- **시험 구간은 한 번만 본다.** 선정 · 보정 · 구간 · 임계값 · 대기열은 검증 구간이나 운영 잔차로만. `train/guard.py` 를 끄는 설정을 만들지 않는다(시험 모드 포함).
- **모델은 등록부에서만 온다.** 기동 학습 · 코드 안 버전 상수 · 등록부 밖 모델 파일 금지. 없으면 `503 model_not_ready`.
- **운영 교체는 승인으로만.** `production` 으로 가는 코드 경로는 `approval.decide()` 하나. 감시는 후보까지만.
- **예측 응답은 한 모양.** `contracts/predict-contract.md` 18키, 유형에 없는 필드는 `null`. 키를 빼지 않는다.
- **변수 · 과제 · 제약은 YAML.** 코드 안 `FEATURE_META` · 임계값 상수 · 회사 테이블 이름 0.
- **실패를 보인다.** `model_not_ready` · `미연결` · `out_of_range` · `목표 없음` 을 숨기거나 합성 값으로 대체하지 않는다.
- **추천은 추천이다.** 설비 · MES 에 쓰지 않는다. **원천은 읽기만**(시험은 `tests/fixtures/` · 팩 합성 생성기).
- **계약이 정본이다.** 코드와 다르면 `decisions.md` 에 `계약 불일치` 로 올리고 아키텍트가 정한다.
- **게이트를 낮추지 않는다**(goal §4.3 목록). 가짜 PASS 금지 — 대상이 없으면 FAIL + 사유.
- 이 폴더 밖은 읽기만. push · 배포 · 외부 전송 금지(이슈 등록만 예외). 키 · IP · 호스트명은 어디에도 적지 않는다.

## 명령 · 환경

| 명령 | 뜻 |
|---|---|
| `make setup` | DB 생성 · 스키마 · 시드 · 의존성 |
| `make db-schema` · `make db-seed` | 스키마 재생성(데이터 삭제) · 표준 시드 |
| `make gate` | 판정표(`G-nn  항목  PASS\|FAIL\|WARN\|BLOCKED  실측`) → `outputs/gate-latest.md` |
| `make gate-full` | 스키마 재생성 + 전체 재학습 2회 · 이관 대조 · 새 회사 · 승인 경합 · bench (종료 판정) |
| `make run TENANT=<code>` | API 8200 (학습하지 않는다) |
| `make web` · `make build` | 콘솔 개발 서버 5190 · 빌드(`/app/*`) |
| `make train TENANT= TASK=` · `make doctor TENANT=` · `make tenant NEW= PACK=` · `make bench` | 웨이브 A 에서 채운다 |
| `make doctor-live` · `make train-live` | `BLOCKED (D-13)` — 사람이 키를 넣은 뒤 사람이 |
| `make check-routes` · `check-schema` · `check-registry` · `check-leakage` · `check-security` | 개별 게이트 |

환경: PostgreSQL 17 (unix socket `/tmp`) · DB `ml_db` · 시험 DB `ml_test_db` · API 포트 **8200** · 웹 **5190** · `uv` / Python 3.12 · 명령은 `uv run …` · 환경변수 접두 `MLP_` · 검증 스크립트는 `gates/` · 학습 시 `OMP_NUM_THREADS=1`.

## 소유권 (한 파일은 한 사람만 — goal §3.2 · contracts/screen-map.md)

| 담당 | 파일 |
|---|---|
| 아키텍트 | `contracts/*` · `std/*` · `src/mlcore/db/schema.sql` · `packs/*/baselines.yaml`(좋게만) · `gates/*` · 팩 · 등록부 **구조** 변경 |
| 개발1 데이터 · 학습 | `src/mlcore/data/*` · `src/mlcore/train/*`(guard.py 포함) · 화면 4 · `/train` `/runs/{id}` |
| 개발2 등록부 · 추론 · 승인 | `src/mlcore/registry/models.py` · `serve/*` · `tasks/*` · `approval/` · `audit/` · `auth/` · `api/{main,middleware,errors}.py` · 화면 2 · 3 · 5 · `web/src/components/` |
| 개발3 팩 · 회사 · 감시 · 이관 | `src/mlcore/registry/{packs,tenants}.py` · `monitor/*` · `packs/*` 내용 · `tenants/*` · `migration/*` · `tests/fixtures/*` · 화면 1 · 6 |
| QA1~3 | `outputs/qa{1,2,3}-*.md` (고치지 않는다) |

## 이슈 자동 등록 규칙

<!-- 대상: 발견했지만 이번 작업에서 해결하지 않는 것만 등록 -->
- 버그, 실패한 테스트, 임시 우회(workaround), 보류한 TODO를
  발견하면 GitHub 이슈로 등록한다.
- 이번 작업에서 바로 고친 것은 등록하지 않는다.

<!-- 중복 방지: 같은 이슈가 계속 쌓이는 것을 막는 핵심 단계 -->
- 등록 전 `gh issue list --search "<핵심 키워드>" --state open`
  으로 중복을 확인한다.
- 중복이면 새로 만들지 말고 `gh issue comment <번호>`로 추가한다.

<!-- 형식: 나중에 사람이든 에이전트든 바로 착수할 수 있게 -->
- `gh issue create --title "[auto] <요약>" --label "ai-found"
  --body "<재현 방법 / 관련 파일:라인 / 시도한 것 / 추정 원인>"`

<!-- 보안: 이슈 본문은 저장소 접근자 전원이 볼 수 있다 -->
- 이슈 본문에 토큰, 비밀번호, 개인정보, 접속 정보를 넣지 않는다.
