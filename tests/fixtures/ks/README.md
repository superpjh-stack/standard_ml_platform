# tests/fixtures/ks — ks 시험 원천

출처: 팩 `press` 합성 생성기(원천 `../KwangSung ML AI/api/ml_service.py:20-38 demo_data()` 이관, 시드 42 · 720행). 과제: remaining_hours · failure_24h · sensor_ood · maintenance_timing.

## 만들 파일 (TODO — 개발3 담당, 웨이브 A0/A)

| 파일 | 용도 | 게이트 | 생성 명령 (계획) |
|---|---|---|---|
| `snapshot.parquet` | 합성 스냅숏(표준 프레임). 해시 고정 | G-V01 · G-M06 | `uv run python migration/make_fixtures.py --tenant ks --kind snapshot --seed 42 --rows 720` |
| `snapshot.csv` | 같은 내용 CSV(UTF-8 BOM) — csv 어댑터 시험 | G-S05 · G-M08 | `… --kind csv` |
| `drift.parquet` | 일부 변수 분포를 옮긴 운영 입력 7일분 — PSI ≥ 0.3 이 나와야 한다 | G-M09 | `… --kind drift --shift <변수>=<σ배수>` (손 계산 PSI 를 README 에 함께 적는다) |
| `psi_hand.json` | 손 계산 PSI · 범위 밖 · 결측 기대값 | G-M09 | 손 계산(스크립트 아님) |
| `source_db.sql` | gateway · mes 어댑터 시험용 원천 DB 사본(익명 합성) — 행 수 diff 0 측정 대상 | G-S05 | `… --kind source_db` → `createdb ml_src_ks` 에 적재 |
| `compat_expected.json` | 원천 옛 응답 키 목록(원천 저장소 파일에서 읽은 것) | G-M04 | `… --kind compat` (원천 코드를 실행하지 않고 파일을 읽어 만든다) |

## 원천 DB 사본에 넣을 테이블

PRS_PROCESS_DATA · PRS_MOLD_SHOTS · BAS_EQUIPMENTS (열은 migration/source_inventory.md §4) — 값은 합성, 이름만 원천과 같다.

## 상태

Phase 0: 이 README 만 있다. fixture 가 없으므로 G-V01 · G-S05 · G-M08 · G-M09 는 FAIL 이 정상이다.
