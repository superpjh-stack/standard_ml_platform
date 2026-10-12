# 계약 — 콘솔 화면 지도 (Screen Map)

> **정본.** 출처: `spec.md` §12.1 · goal §3.2 · §6. 검사: `make check-routes` · `tests/e2e/`(G-S03).
> 콘솔은 `web/`(Vite + React 19 + TS). 개발 서버 5190, 빌드는 API(8200)가 `/app/*` 로 제공. **회사 화면 코드는 0** — 입력 폼은 `GET .../tasks/{task}` 의 `features` 메타로 만든다.
> 공용 컴포넌트(상태 배지 · 지표 표 · 변수 폼 생성기 · 2차: 문서 뷰어 · 금액 표)는 `web/src/components/` 하나, 개발2 소유.
> **2차(goal2 §3.2):** 화면 7~10 의 파일 · 소유자를 정했다. 웨이브 P 끝(동결 전) 아키텍트가 마지막 열을 `2차` → `○` 로 바꾸면 G-S03(화면 10 · e2e 6개사)이 이 행들을 판정한다. 그 전에는 `check_routes` 가 1차 6 만 본다.

| # | 화면 | 경로 | 파일 | 소유 | API | 역할 | 1차 |
|---|---|---|---|---|---|---|---|
| 1 | 회사 · 과제 개요 | `/app/overview` | `web/src/screens/Overview.tsx` | 개발3 | B02 · B06 · B01 | 전원 | ○ |
| 2 | 예측 시험 | `/app/predict` | `web/src/screens/Predict.tsx` | 개발2 | B02 · B03 | operator 이상 | ○ (1024px 가로 스크롤 0) |
| 3 | 조건 추천 | `/app/optimize` | `web/src/screens/Optimize.tsx` | 개발2 | B02 · B04 | operator 이상 | ○ (1024px 가로 스크롤 0) |
| 4 | 모델 비교 · 검증 | `/app/models` | `web/src/screens/Models.tsx` | 개발1 | B07 · B08 | admin · approver(조회) | ○ |
| 5 | 승인 대기열 | `/app/approvals` | `web/src/screens/Approvals.tsx` | 개발2 | B13 · B07 | approver · admin · operator(조회) | ○ |
| 6 | 감시 | `/app/monitor` | `web/src/screens/Monitor.tsx` | 개발3 | B14 | admin · approver · operator(조회) | ○ |
| 7 | 데이터 소스 · 스냅숏 | `/app/sources` | `web/src/screens/Sources.tsx` | 개발1 | B14 doctor · B08 · B12 | admin · approver(조회) | 2차 |
| 8 | 검토 대기열 | `/app/review` | `web/src/screens/Review.tsx` | 개발2 | B09 · B02 | admin · approver(자기 과제) · operator(조회) | 2차 |
| 9 | 도면 추출 · 견적 | `/app/quotes` | `web/src/screens/Quotes.tsx` | 개발2 | B10 · B11 · B13 | admin · approver · operator(확정 ✕) | 2차 |
| 10 | 감사 · 예측 추적 | `/app/trace` | `web/src/screens/Trace.tsx` | 개발2 | B15 · 감사 조회 | admin | 2차 |

## 화면별 필수 요소 (G-S03 판정에 쓴다)

| # | 반드시 보이는 것 | 지어내지 않기 |
|---|---|---|
| 1 | 과제별 운영 버전 · 어제 예측 수 · 경고 배지 · 합성 배지 | production 없으면 "운영 모델 없음 (model_not_ready)" |
| 2 | 과제 선택 → features.yaml 폼 → 표준 응답 18키 중 값 · 상태 · 경고 · 보정 필드 · 모델 버전 | 503 은 그대로 "운영 모델 없음" |
| 3 | 고정 변수 입력 → 후보 5 · 제약 충족표 · 학습 범위 배지 · "추천은 설비로 내려가지 않음" | infeasible 은 `least_violation` + 검토 필요 |
| 4 | 후보별 검증 지표 · 선정 사유 · 시험 지표 대 기준선 · 중요도 · 잔차 · (risk) 보정 곡선 · production 과의 비교 | 기준선 못 이김 표시 |
| 5 | 모델 · 추천 승인 카드(지표 비교 · 그림자 예측 차이 · 사유 입력) · 409 처리 | — |
| 6 | 변수별 PSI · 범위 밖 · 결측 추이 · 실측 성능 추이 · 재학습 후보 링크 | 실측 없으면 "실측 없음" |
| 7 | 소스별 doctor 결과(연결 · 미연결 · 대응률 · 목표 없음 · 기간) · 스냅숏 목록(행 · 기간 · sha256 · 합성 배지) · CSV 업로드 소스 | 미연결 · `live 불가`(krs D2-01) · 목표 없음을 그대로 |
| 8 | 과제별 open 대기열(\|잔차\| · 규칙 · 임계값 · 출처 test_split/live_residual) · 항목 상세(예측 ID 링크 → 화면 10) · 확인/오탐 + 메모 · 409 처리 | 대기열 0 이면 "검토할 항목 없음", 학습 구간 잔차 항목은 존재할 수 없다 |
| 9 | DXF 업로드(상한 표시) · 영역/객체/BOM 표 + 미리보기 · 인식값 수정(수정 칸 표시 = overrides) · 견적 초안 구성 금액 · 확정 요청 · 확정 배지(잠금) · 이력 · CSV | 라벨 없으면 "정답 라벨 없음 — 지표 없음 (labels: none)", 금액은 서버 문자열 그대로(브라우저 계산 0) |
| 10 | 예측 ID 입력 → 모델 버전 → run → 스냅숏 → 원천 소스 · 실측 · 감사 행 | 추적 끊김은 "원천 기록 없음" 으로 |

`_placeholder` 표지: Phase 0 골격 화면은 `data-placeholder="true"` 와 문구 `_placeholder` 를 가진다. G-S03 은 이 표지가 0건이어야 PASS 다.
