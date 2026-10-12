# 2차 QA 재검증 (r2) — QA1 · 2 · 3 관점 통합

> 기준 커밋 c18af0f (태그 `core-freeze-2` → c18af0f) · 2026-10-13. **고치지 않았다.** `src packs tenants std contracts web/src gates migration tests` 373 파일의 SHA-256 은 전후 같다. 작업 트리 변경은 `outputs/bench-compose-latest.json` 1개(QA 전부터 있었다)와 `outputs/qa2-r2/` 뿐이다.
>
> 환경:
> - 전용 DB `ml_qa2r2_db` 를 썼고 끝난 뒤 dropdb 했다. 만들기 순서: `createdb` → `schema.sql` → `seed_std`.
> - 서버는 포트 8214, 산출물 · 스냅숏 · 문서 폴더는 저장소 밖 임시 폴더(`<scratch>`)를 썼다.
> - PostgreSQL 17 · uv/Python 3.12 · Playwright chromium 1024px · `OMP_NUM_THREADS=1`.
>
> 실행 0: ml_db · ml_test_db 쓰기, `make gate` · `gate2` · `bench`.
>
> 원천 6 저장소(4사 + Agent · 허브)는 읽기만 했다. 시작 표식 이후 수정된 파일은 0개다(`find -newer`).
>
> 개발 회귀 시험은 돌리지 않았다. 2차 QA 재현 스크립트를 복사해 DB · 포트만 바꿔 직접 돌렸다.
> - QA1 → `outputs/qa2-r2/q1/`, QA2 → `q2/`, QA3 → `q3/`
> - r2 에서 새로 만든 스크립트는 이름에 `_r2` 를 붙였다. `queue_regress.py` 와 `csv_rule_check.py` 도 새로 만든 것이다.
>
> 환경 설정은 `source outputs/qa2-r2/env.sh` 로 한다. 이 파일은 `QA_SP` 가 임시 폴더를 가리킨다고 가정한다.

## 1. 결함 재검증

| 이슈 | 결함 | 판정 | 실측 (r2) |
|---|---|---|---|
| #26 | DEF-QA21-001 대기열이 학습 구간 잔차 · 선행 실측을 받음 (중대) | **해결** | 재현 스크립트 2개를 다시 돌렸다. `queue_train_rows_krs`: krs 재적합 LOT 의 재예측 10건(200)에서 live 항목 **0**(이전 10/10). `queue_leak_probe`: pc 학습 구간 LOT 20건 + 예측보다 6년 앞선 실측의 짝이 **0**(이전 21/22 · 1). 회귀 없음 확인(`queue_regress`, pc · krs 같음): 새 entity · 시험 구간 entity · 예측 → 실측 → 예측 → 실측은 **짝이 유지**되고 live 항목 6건이 생긴다. 재적합 구간 entity 는 빠진다. 스냅숏 파일이 없으면 InSampleEvaluation 이 나고 항목 0(fail closed) |
| #27 | DEF-QA21-002 같은 실측에 예측 여럿이 짝 | **해결** | 같은 entity 로 예측 2건 → 실측 1건이면 짝 1건(뒤 예측)이다. `same_entity_pairs` 2 → 0 |
| #27 | DEF-QA21-003 time_cv5 풀링 분위 | **해결** | 임계값은 마지막 검증 블록(n 56)에서 3.5984 이고, 시험 대기열은 6/84(7.1%)다. 폴드 q90 은 6.016 · 3.826 · 4.802 · 4.356 · **3.598** 이다. 시험을 교란해도 챔피언 · 검증 해시 · 임계값 · 구간 q · IQR 이 모두 그대로다(`queue_invariance_probe`). 검증을 교란하면 임계값이 바뀐다. MAE 1.5375 는 그대로다 |
| #27 | DEF-QA21-004 eval CSV ↔ demo 미세 차이 | **해결(규칙)** | 스냅숏 해시는 여전히 다르다. 다만 바뀐 규칙(D2-102)을 6사 회귀 과제 7개에 직접 재 보니 최대 상대 차이가 2.2e-16 으로 ≤ 1e-12 이고, 행 · 범주 · 결측 위치가 같다(`csv_rule_check`) |
| #28 | DEF-QA23-001 `make tenant` 5/6 팩 거부 · 스캐폴드 삭제 (중대) | **해결** | 빈 등록부 루트에서 6팩 모두 확인했다(`t05` r2). `CATEGORIES` 없이 돌리면 거부되고 **`<code>.yaml.draft` 만** 남으며 채울 칸을 안내한다. 이 상태로 seed 해도 회사 행은 0이다. 채움 파일에 모르는 키 · 팩 범주가 아닌 키가 있으면 T0 로 거부되고 파일은 그대로다. `CATEGORIES=` 로 다시 돌리면 통과하고 초안이 지워진다(ot 단가표 덮어쓰기 포함). 그 뒤 seed · doctor · 학습 · 승인 · predict 18키 · 대기열 15 · 6 · 견적 46,650 이 돈다. textile 은 범주 없이 통과한다 |
| #29 | DEF-QA23-002 "운영 모델 없음" 오표시 | **해결** | health 항목에 `type · model_required · uses` 가 들어간다. model_required false 는 규칙 extract · quote · review_queue · optimize 다. overview 의 `uses` 는 v2 를 보인다. 화면 1(kd)은 "모델 불필요 (규칙)" · "의존 kd.labor_hours" 로 표시한다 |
| #29 | 003 records NaT | **해결** | kd · krs records 의 ts 가 null 50/50 이다. "NaT" 문자열 0 · 화면 1 표시 0 |
| #29 | 004 화면 8 operator 버튼 | **해결** | `can_decide`: operator false · approver true · approver_other false · admin true · viewer 403. 화면 8 operator 는 결정 버튼 0개에 "조회 전용" 안내가 나온다. approver 는 버튼 30개. 가로 스크롤 0 |
| #29 | 005 409 문구 | **해결** | 두 탭에서 뒤 탭은 "이미 검토가 끝난 항목입니다 — 다른 사람이 먼저 결정했습니다" 를 보인다. "이미 결정된 승인" 은 0 |
| #29 | 006 doctor 권한 | **해결** | `GET /doctor`: viewer · operator 403, approver · admin 200 (kd · krs). 화면 6 operator 는 표 없이 안내가 나온다 |
| #29 | 007 비학습 과제 train | **해결** | extract(규칙) · quote · optimize · review_queue 4종 모두 422 `invalid_input` rule `not_trainable` 이고, mlp_train_run 은 0 → 0 이다 |
| #30 | DEF-QA22-001 도면 영역 제곱 · 174 s · 2.26 GB (중대) | **해결** (회귀 → DEF-QA2R2-001) | 실서버에서 잰 값(`server_extract_r2`)이다. RSS 는 서버와 자식 프로세스를 합한 값이다. 겹친 2만 엔티티는 **413 `region_texts` · 0.41 s · RSS 587 MB** 다(이전 174 s · 2.26 GB · 500). 결과 항목 6,666개는 413 `items`, 4,999개는 201 이다. `MLP_EXTRACT_MAX_SECONDS=1` 로 무거운 도면을 올리면 413 `time` 이 나고 자식이 정리된다. 서버는 살아 있고 health 200 이다. 거부된 문서는 모두 원본 파일 · mlp_document 행이 0 이다 |
| #31 | DEF-QA22-002 견적 품목 검증 없음 (중대) | **해결** | QA2 원래 경우 14개가 모두 422 다(`probe_quote` §E). r2 경계(`probe_lines_r2`): name 80/81자 · 빈 값 · 공백 · 숫자형, quantity 1001 · 1.5 · true, mass 0.009 · 10000.01, price 1,000,000.01 · NaN · Infinity, 101행, `amount` · `weight_total` · 대소문자 키 → 422. 수정(revision) 경로 7종과 옛 `/api/quotes` 7종도 같은 검사를 받는다 |
| #32 | 003 CSV 앞 공백 수식 | **해결** | 표준 · 옛 CSV 2경로에서 `lstrip` 뒤 위험 칸이 0이다. 옛 경로의 `' =1+1'` → `'=1+1` |
| #32 | 004 DXF NUL 500 | **해결** | 422 `invalid_document` rule `nul`(앞 4 KiB 밖 · `\U+0000`). 원본은 남지 않는다. JSON 본문 NUL 은 다른 경로라 새 결함으로 따로 적었다(DEF-QA2R2-002) |
| #32 | 005 허브 api_usage 키 | **해결** | 오늘 날짜로 export-hub 를 임시 폴더에 냈다. kd documents 36/19 · quotes 25/12, krs review 10/8, pc review 8/7, ot 이 모두 mlp_audit 집계와 같다. 다른 회사 경로(`krs` 아래 `pc.…`)는 셈하지 않는다 |
| #32 | 006~008 호환 차이 | **해결** | 옛 견적의 없는 도면 · 원천 꼴 id → 404 원천 문구(`doc_id` 노출 0). kd · ot 개요 mae/rmse 4자리 · warning 원천 문구. krs 조성 합 422 문자열 · pc 배합 합 pydantic 모양. kd 내보내기 파일 이름. 500 은 0이다 |
| #32 | 009 커밋된 로컬 경로 | **해결**(outputs) | `check_secrets` 가 홈 경로를 FAIL 로 잡는다(r2 산출물 정리 전 5건 → 정리 뒤 0). 남은 것은 goal.md 2곳(사람 몫 — #33, WARN) |

**닫아도 되는 이슈: #26 · #27 · #28 · #29 · #30 · #31 · #32** (닫지 않았다). #30 수정의 회귀는 #34 로 따로 열었다.

## 2. 새 결함

| ID | 등급 | 요약 | 담당 | 이슈 |
|---|---|---|---|---|
| DEF-QA2R2-001 | **중대** | 결과 4 MiB 상한(`max_result_bytes`)이 미리보기(원 · 호 1개당 49점)까지 잰다. 그래서 상한 안 정상 도면을 413 `result_bytes` 로 거부한다. 원 3,000개(108 KB)는 201, 5,000개(181 KB) · 19,000개는 413 이다. 원천 KyungDong `api/cad.py:54,87` 은 엔티티 20,000 상한만 둔다. goal2 §2.1 의 413 은 5 MiB · 20,000 초과일 때다 | 개발2(`tasks/extract.check_result`) · 개발3(`cad_regions` 미리보기) · 아키텍트(task-contract §4 ↔ goal2 §2.1) | #34 |
| DEF-QA2R2-002 | 경미 | JSON 본문의 NUL(`\u0000`)이 500 이 된다. 해당 경로: 견적 품목 이름 · 메모 · 수정 · 확정 요청 메모, 실측 entity_id, 예측 entity_id(입력 완전), 옛 `/api/quotes` 품목 이름 · 메모. 부분 상태는 없다(행 0, 다음 확정 요청 202, 수정 사슬 1 · 2 · 3 연속) | 개발2(`serve/quotes.py` · `serve/actuals.py` · predict) | — |
| DEF-QA2R2-003 | 경미 | 실측 API 가 관측 시각이 30일 뒤인 실측을 받는다. 그 실측을 예측 **전에** 등록해도 "예측 뒤 관측" 으로 짝이 되어 live 항목이 생긴다(R2-FUTURE, pc · krs). 또 실측 응답의 `linked_prediction_ids` 에 앞 실측과 이미 짝이 된 예측이 함께 나온다. 이는 D2-81 의 1:1 과 다르다. 학습 구간 누수는 아니다 | 개발1 · 개발2(`serve/actuals.py`) | — |
| DEF-QA2R2-004 | 경미 | 품목 값 정규화가 일정하지 않다. `price_kg " 6500 "` 은 공백 그대로 저장되고(금액은 맞다), 숫자형 · 문자열형이 섞여 저장된다(1000000 vs "6500"). 품목 quantity `"5"` 는 201 인데, `inputs.quantity "1"` 은 422 다 | 개발2(`serve/quotes.validate_line_limits`) | — |

관찰(결함 아님):
- ① 품목 상한 안 값(quantity 1000 · mass 10000 · 100행)이 회귀 입력 `total_mass_kg` 범위에 걸려 422 `out_of_bounds` 가 난다. 2차 QA 의 "우연한 방어" 와 같은 동작이다.
- ② 추출은 자식 프로세스에서 순서대로 돌고 메모리 rlimit 은 없다(D2-91 설계). 서버와 자식을 합한 RSS 는 최대 738 MB 였다.
- ③ 합성 production 회사(qn4)를 `mode: live` 로 바꾸면 R2(live 원천 없음)에서 기동이 거부된다. 그래서 합성 모델 운영은 0이다. R4 단독 경로는 이번에 따로 보지 못했다.
- ④ `make monitor` 가 저장소 `var/export/hub/2026-10-12.json` 을 다시 썼다. var/ 는 .gitignore 이고, 2차 QA3 와 같은 부수 효과다.
- ⑤ 원래 스크립트의 기대값 때문에 생긴 FAIL 은 2차 QA 와 같은 이유로 다시 판정했다. 파일 이름 3 · 감사 목록 · 업로드 감사 doc_id · Agent 추천 needs_approval · ot labels synthetic · 견적 503 의 입력 불완전이다.

## 3. 새 치명 사냥 (goal §3.3 · goal2 §3.3 — 기준마다 공격 ≥ 1)

```
§3.3 시험 구간 선정·보정    PASS  krs·pc 시험 교란(목표 +50 · 변수 1e6): 챔피언·검증·임계값(마지막 블록)·구간 q·IQR 불변 (queue_invariance_probe)
§3.3 승인 없는 production   PASS  채움 파일 tasks 로 approver_role · confirm · line_limits · input_limits · rounding · 모르는 키 덮어쓰기 6종 → R1 거부, 초안만 (crit_r2 C)
§3.3 같은 승인 두 번         PASS  견적 두 탭 동시 확정 200/409 · 동시 확정 요청 202/409 · 대기열 두 탭 200/409 · 화면 8 409 (t02 · t03 · ui_api_r2)
§3.3 모델 없이 값           PASS  새 회사 eto · rollform-quote uses production 없음 → 503 model_not_ready · 초안 0 (t06)
§3.3 합성 모델 live 운영     PASS  합성 production 회사 mode: live → 기동 거부(rc 3) · 예측 0 (crit_r2 B)
§3.3 다른 회사 예측          PASS  kd admin 키로 pc 대기열 PATCH/GET · ot 견적 GET/CSV/옛 GET · ot 문서 GET/옛 cad → 404, 수정 · 견적 생성은 422(내용 노출 0) (xtenant_r2) · 허브 api_usage 다른 회사 경로 0
§3.3 원천 쓰기              PASS  원천 6 저장소 find -newer 0 파일
goal2 확정 견적 금액 변경    PASS  확정 뒤 회사 단가표 ×3 + 재기동 → 확정 46,650 · CSV 바이트 불변(새 초안 57,357) (crit_r2 A) · 모델 v1→v2 교체 불변 kd 14,995,787 · ot 727,395 (t02)
goal2 사람 수정 이력 소실    PASS  NUL 500 수정 뒤 revision 1·2·3 연속 · overrides 유지 · 반려/만료/확정 뒤 overrides 유지 (crit_r2 A2 · t02)
goal2 라벨 없이 IoU/F1       PASS  kd · 새 회사 eto 업로드 labels none · metrics null
goal2 대기열 학습 구간 잔차   PASS  재적합 entity 재예측 + 뒤 실측 → 짝 0 · 스냅숏 없음 → fail closed 0 (queue_regress F · X)
goal2 A2 이후 코어 변경      PASS  git diff core-freeze-2 -- src/mlcore web/src/components std contracts 0줄 · 태그 = HEAD
```

## 4. 결론

- **치명 0. 중대 1**(DEF-QA2R2-001 #34 — #30 수정의 회귀로, 상한 안 정상 도면을 거부한다). 따라서 "치명 0 · 중대 0" 은 아니다.
- 남은 미해결:
  - #34 (중대)
  - 경미 DEF-QA2R2-002~004 (리포트에만)
  - #33 goal.md 로컬 경로 (사람 몫)
