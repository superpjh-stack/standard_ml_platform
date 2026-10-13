# 2차 QA 재검증 (r3) — 수정 커밋 25ea206 (#34 · DEF-QA2R2-002~004)

> 기준 커밋 140bd38 (HEAD). 수정 커밋 25ea206 이후 `src` · `packs` 변경은 0줄이다(`git diff 25ea206 HEAD -- src packs`) · 2026-10-14. **고치지 않았다.** `src packs tenants std contracts web/src gates migration tests` 613 파일의 SHA-256 은 전후 같다(`.pyc` 캐시 2개만 다르다). 작업 트리에서 새로 생긴 것은 `outputs/qa2-r3/` 와 이 리포트뿐이다. QA 도중 `goal.md` 가 바뀌었다(01:38, 로컬 경로 → `./` 2줄 — #33 사람 몫). 이 변경은 QA 가 한 것이 아니다.
>
> 환경:
> - 전용 DB `ml_qa2r3_db` 를 썼고 끝난 뒤 dropdb 했다. 만들기 순서: `createdb` → `schema.sql` → `seed_std`(6사 · 20과제).
> - 서버는 실서버 uvicorn 포트 8215, 산출물 · 스냅숏 · 문서 폴더는 저장소 밖 임시 폴더(`<scratch>`)를 썼다. kd.labor_hours · krs.joint_strength 는 API 학습 → 작업자 → stage → promote → 승인으로 운영에 올렸다(`t01_train_r3`).
> - PostgreSQL 17 · uv/Python 3.12 · `OMP_NUM_THREADS=1`.
>
> 실행 0: ml_db 쓰기, `make gate` · `gate2` · `gate-full` · `bench` · `db-reset` · `db-schema`. ml_test_db 는 `pytest` 1회만 썼다.
>
> r2 재현 스크립트는 복사해서 DB · 포트만 바꿔 돌렸다(이름에 `_r3`). 실서버 경계 · 회귀용 스크립트는 새로 만들었다.
> - 복사: `q2/probe_nul_r3` · `q2/probe_lines_r3` · `q2/probe_quote_r3` · `queue_regress_r3` · `q3/server_extract_r3`(기본 · `MLP_EXTRACT_MAX_SECONDS=1`) · `q3/t01_train_r3` · `q3/qa_lib` · `q3/mkkeys`
> - 새로: `q3/server_extract_bound_r3`(엔티티 · 바이트 경계, 미리보기 줄임) · `q3/server_api_r3`(NUL · 미래 실측 · 1:1 · 정규형 · #31 실서버) · `q3/nul_extra_r3`(본문 밖 NUL) · `q3/nul_deep_r3`(64단 밖 NUL)
>
> 환경 설정은 `source outputs/qa2-r3/env.sh` 로 한다. 이 파일은 `QA_SP` 가 임시 폴더를 가리킨다고 가정한다.

## 1. 결함 재검증

| 이슈 | 결함 | 판정 | 실측 (r3) |
|---|---|---|---|
| #34 | DEF-QA2R2-001 결과 4 MiB 상한이 미리보기까지 재서 원 5,000개 이상 도면 413 (중대) | **해결** | 실서버(`server_extract_r3`)에서 원 3,000 · **5,000 · 19,000 → 201**(r2 는 5,000 · 19,000 이 413 `result_bytes`)이고 응답은 1.1 KB 다. 경계(`server_extract_bound_r3`): 원만 20,000 → 201 · **20,001 → 413 `entities`**, 원 19,998 + 틀 2 = 20,000 → 201 · 19,999 + 2 = 20,001 → 413 `entities`, 호만 20,000 → 201(0.96 s), 원 10,000 + 호 10,000 → 201. 파일 정확히 5 MiB(5,242,880 B · 원 19,000) → 201, **5 MiB + 1 B → 413 `bytes`**. 거부된 문서는 모두 mlp_document 행 · 원본 파일이 0 이다. DoS 방어는 그대로다: 판정용 결과가 4 MiB 를 넘는 도면(긴 BOM 텍스트 2,200 영역 · 4.4 MB)은 여전히 413 `result_bytes`(0.19 s)다. 미리보기는 팩 점 예산(10만 점) 안으로 줄어든다(직접 호출): 원 3,000 → 분할 32 · 생략 0, 원 5,000 → 분할 18 · 생략 0, 원/호 20,000 → 분할 8 · 경로 8,889 생략, `reduced` 표시 있음, 미리보기 2.1~2.4 MB · 판정용 결과 약 0.5 KB. 서버 + 자식 RSS 최고 644 MB(5 MiB 패딩 도면)다. 서버 로그에 500 · Traceback 은 0 이다 |
| #30 | (회귀 확인) region_texts · items · time 방어 | **유지** | 겹친 2만 엔티티 → 413 `region_texts` **0.42 s · RSS 587 MB**(r2 0.41 s · 587 MB)다. 영역 6,666개 → 413 `items`, 4,999개 → 201(0.35 s)이다. `MLP_EXTRACT_MAX_SECONDS=1` 로 돌리면 모든 경우가 1 s 안에 끝난다. r2 에서 413 `time` 이 났던 원 19,000 도 이번에는 0.89 s 에 201 이 됐다(미리보기 점을 줄여서다). 그래서 time 규칙은 이번에 다시 걸리지 않았다. 서버는 살아 있고 health 200 이며, 남은 자식은 forkserver 2개뿐이다 |
| — | DEF-QA2R2-002 JSON 본문 NUL → 500 (경미) | **해결** | r2 재현(`probe_nul_r3`) 13건이 모두 422 다(r2 는 500 이 9건). 실서버(`server_api_r3` N) 결과: 결함에 적힌 경로 전부(견적 품목 이름 · 메모 · 수정 · 확정 요청, 실측 · 예측 entity_id, 옛 `/api/quotes` 품목 이름 · 메모)가 422 `rule nul` 이다. field 는 `lines.0.name` · `review_note` · `entity_id` 다. 그 밖에 다음도 모두 422 다. ① 견적 inputs 값 · 키 · doc_id · 최상위 모르는 키 · 품목 키 ② 예측 inputs 값 · 키 · model_version ③ 실측 observed_at ④ 학습 source_role ⑤ 승격 reason ⑥ 승인 결정 reason ⑦ krs 대기열 note · state ⑧ krs 표준 최적화 fixed ⑨ 옛 경로 kd 견적 product · drawing_id · 키, krs `/api/quality/predict` · `/api/ml/optimize` 의 값 · 키(옛 422 모양 `type: nul`). 배치 2건 중 1건만 NUL 이면 200 이고 그 건만 `items.1.entity_id` nul 이다. 날 NUL 바이트(이스케이프 없음)는 422 `json_invalid` 다. 키 이름은 `*` 로만 보이고 입력값은 되풀이하지 않는다. 부분 상태도 없다: NUL 요청 뒤 정상 확정 요청 202 · 정상 결정 200 · 정상 검토 200 이고, mlp_actual 증가는 0, mlp_quote · mlp_prediction 은 정상 요청분만 늘었다. 64단보다 깊은 NUL(`find_nul` 은 그 아래를 보지 않는다)은 다른 형 검사가 먼저 422 로 막는다(`nul_deep_r3` — 표준 예측 · 대기열 · 옛 예측 65 · 80단, 견적 70단 `depth`). **본문 밖 NUL 은 아래 새 결함 DEF-QA2R3-001 로 따로 적었다** |
| — | DEF-QA2R2-003 미래 실측 수락 · linked_prediction_ids 1:1 아님 (경미) | **해결** | 실서버(F): 관측 시각 **+4분 · +4분50초 → 200**, **+5분10초 · +6분 · +30일 → 422 `observed_at` `future`** 이다. 표기 시간대를 바꿔도(KST +6분 · −12:00 +6분 → 422, +14:00 +4분 → 200) 판정이 같다. 시간대 없는 값은 422, 과거 1일은 200 이다. 거부된 실측의 행은 0 이다(통과 4건만 늘었다). r2 재현(`queue_regress_r3` U)에서 R2-FUTURE 30일 실측은 422 이고, 짝 `U_future_actual_paired` 는 **false** 다(r2 true · pc · krs). 1:1(P) 결과: 같은 entity 로 예측 2 → 실측 1 이면 링크는 **뒤 예측 1개**다. 새 예측 없이 이어진 둘째 실측은 링크 0, 새 예측 → 실측은 그 예측만이다(r2 는 앞 예측까지 같이 나왔다). 같은 (entity, observed_at) 를 다시 등록하면 같은 actual_id · 같은 링크가 나온다. 관측 시각이 예측 전이면 링크 0 이다. 최종 응답 링크 4쌍은 짝 규칙 SQL(`pairs_cte`, 대기열 `live_pairs` 와 같다) 결과와 차이가 0 이다. 대기열 회귀(`queue_regress_r3`)는 N · T · M(뒤) · A1 · A2 짝, F(재적합 entity) 짝 0, 스냅숏 없음 fail closed 로 r2 와 같다 |
| — | DEF-QA2R2-004 품목 값 정규화 불일치 (경미) | **해결** | 실서버(Z)에서 저장값(DB jsonb)과 응답이 같은 정규형이다. 품목 `" 6500 "` · `"6500.0"` → **6500(숫자)**, `"6500.50"` · 6500.50 → 6500.5, mass `" 1.50 "` → 1.5, name `" SHELL "` → `SHELL` 이다. 입력은 `quantity "1"` → **201** · 1(r2 422), `" 2 "` → 2, cut_m `" 24.50 "` → 24.5, labor_rate `"45000"` → 45000, 범주 `" 반응기 "` → `반응기` 다. 같은 뜻이면 같은 금액이다: 품목 quantity 5 · `"5"` · `" 5 "` · `"5.0"` → 모두 20,955,891, 입력 quantity 1 · `"1"` · `" 1 "` · `"1.0"` → 모두 9,035,689. 지수 · 문자 · 소수 수량(`"1e3"` · `"1e0"` · `"abc"` · 1.5)은 품목 · 입력 모두 422 `number` / `integer` 다. r2 재현(`probe_lines_r3`)도 저장 단가가 `"6500"`(문자열) → `6500`(숫자)로 바뀐 것 말고는 판정이 같다 |
| #31 | (회귀 확인) 견적 품목 검증 422 | **유지** | 실서버(Q)에서 음수 단가 · 1e12 · 수량 1.5 · 1001 · `amount` 키 · 재질 목록 밖 · 0행 · 101행 · `"NaN"` · 이름 81자가 생성 · 수정 두 경로 모두 422 다(20/20). `probe_lines_r3` 53건과 `probe_quote_r3` 90건은 r2 와 판정이 같다. 다만 `probe_quote_r3` 의 `경계 · quantity '1'` 은 422 → 201 로 바뀌었다. D2-113 의 의도된 변경이라 결함이 아니다. 나머지 FAIL 은 r2 관찰 ①(`total_mass_kg` out_of_bounds 3건)과 ⑤(감사 행 종류 기대값)이다 |

**닫아도 되는 이슈: #34** (닫지 않았다). DEF-QA2R2-002~004 는 리포트에만 있던 경미 결함이고, 모두 해결이다.

## 2. 새 결함

| ID | 등급 | 요약 | 담당 | 이슈 |
|---|---|---|---|---|
| DEF-QA2R3-001 | 경미 | 조회 문자열(`search`)에 NUL(`%00`)이 있으면 500 이 난다. 원인은 `psycopg.DataError: PostgreSQL text fields cannot contain NUL`이다. 해당 경로는 표준 견적 목록 `GET …/kd.quote/quotes?search=` (`serve/quotes.py:742` `list_quotes`), 표준 문서 목록 `GET …/kd.drawing_regions/documents?search=` (`serve/documents.py:222` `list_docs`), 옛 `GET /api/quotes?search=` · `/api/quotes/export/csv?search=` (`serve/compat/phase2.py:356` → `list_quotes`) 이다. D2-111 은 JSON 본문만 막았다. 읽기 경로라 상태 변화 · 노출은 없다. 응답 본문은 `Internal Server Error` 뿐이다. 같은 꼴의 경로 인자(견적 · 문서 · 옛 도면 id → 404), cursor(422), 업로드 파일 이름(`a%00b.dxf` 로 바뀌어 201)은 500 이 아니다. r2 커밋에서도 이 코드는 같았다. 따라서 25ea206 회귀가 아니라 이번에 처음 찾은 것이다 | 개발2(`serve/quotes.list_quotes` · `serve/documents.list_docs` 또는 라우터 `search` 검증 — `find_nul` 공통) | — |

재현:
`GET /api/v1/tenants/kd/tasks/kd.quote/quotes?search=a%00b` 를 operator 키로 호출한다 → 500. `q3/nul_extra_r3.py` 의 5건이다(`rows_nul_extra_r3.txt`).

관찰(결함 아님):
- ① 미리보기는 판정용 결과 · 문서 행 · 응답에 들지 않는다(predict-contract §8.2 그대로). 그래서 `preview.reduced` · `omitted` 표시는 API 로는 보이지 않는다. 원 3,000개 도면부터 분할이 48 → 32 로 줄어든다. 화면 1 의 SVG 는 영역 bbox 만 그리므로 영향은 없다.
- ② 실측 응답의 `linked_prediction_ids` 는 등록 시점 값이다. 관측 시각이 더 이른 실측이 늦게 들어오면 짝은 그 실측으로 옮겨 간다. 그래도 앞 응답은 바뀌지 않는다(QA-R3-P4: +3 s 실측 링크 1 → 뒤에 온 +1 s 실측 링크 1). 대기열은 짝 규칙 SQL 을 매번 다시 계산하므로 1:1 은 지켜진다.
- ③ 추출은 서버 + forkserver + 자식을 합친 RSS 가 최대 644 MB 다. 자식 단독 수치(D2-110 의 163 MB)와는 재는 범위가 다르다. r2 관찰 ② 와 같은 설계(메모리 rlimit 없음)다.
- ④ `MLP_EXTRACT_MAX_SECONDS` 는 정수 초만 받는다. 이번 도면은 모두 1 s 안에 끝나서 time 413 은 다시 재지 못했다.

## 3. pytest

`OMP_NUM_THREADS=1 uv run pytest -q -x` (ml_test_db): **1135 passed · 3 skipped** · 146.9 s (rc 0). 수정 커밋 메시지에 적힌 수는 1112 passed 인데 이번에는 1135 다. 25ea206 이후 `tests` 변경은 0 이라 차이의 원인은 확인하지 못했다(실패 0). pytest 는 `var/snapshots/` 에 시험 스냅숏을 남긴다(.gitignore)

## 4. 결론

- **치명 0 · 중대 0.** #34(중대)는 해결이다. 상한 안 도면(엔티티 ≤ 20,000 · ≤ 5 MiB)은 201 이고, 상한 밖 도면은 413 `entities` · `bytes` 다. 판정용 결과 4 MiB 방어도 유지된다.
- DEF-QA2R2-002 · 003 · 004 는 해결이다.
- 남은 것:
  - 새 경미 결함 DEF-QA2R3-001(조회 문자열 NUL 500 — 리포트에만)
  - #33 goal.md 로컬 경로(사람 몫)
