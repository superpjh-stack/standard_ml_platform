# tests/fixtures/ks — ks 시험 원천

출처: 팩 `press` 합성 생성기(원천 `../KwangSung ML AI/api/ml_service.py:20-38 demo_data()` 이관, 시드 42 · 720행). 과제: remaining_hours · failure_24h · sensor_ood · maintenance_timing.

## 있는 파일 (A0 — 개발3)

| 파일 | 내용 | sha256 (파일 바이트) |
|---|---|---|
| `snapshot.parquet` | 합성 스냅숏 720행 · 열 13 — 팩 생성기 출력 그대로(회사 `categories` 적용) | `bc49ed49cf771bd978790a7226d940f1d7b18bda40d2689f5402ced3942fb890` |
| `snapshot.csv` | 같은 내용 CSV (UTF-8 BOM, `ts` = `%Y-%m-%dT%H:%M:%S+09:00`) — `sources.eval` (csv 어댑터 시험) | `3f6a10ceb842f21cfe138da2ec47054193b47cbd2dde1e10b04f648fb98f219e` |

열: press_force · vibration · motor_current · equip_temp · mold_temp · cycle_time · shot_count · machine_code · product_type · remaining_hours · failure_24h · entity_id · ts. 결측 24셀(vibration · motor_current · mold_temp 각 8). 시간 2026-08-01 부터 1시간 간격(KST).

생성 명령 (두 번 돌려 해시가 같은 것을 확인했다 — 결정적):

```
uv run python migration/make_fixtures.py --tenant ks --kind snapshot     # snapshot.parquet
uv run python migration/make_fixtures.py --tenant ks --kind csv          # snapshot.csv
```

손질 금지 — `tests/test_synth.py::test_fixture_snapshot_is_regenerated_not_edited` 가 생성기 출력과 같은지 본다.
해시는 pyarrow 21.0.0 · pandas 2.3.3 (D-21) 기준이다. 버전이 바뀌면 parquet 바이트 해시는 달라질 수 있고 내용 대조 시험이 정본이다.

## 웨이브 A 로 미룬 것 (TODO 개발3)

| 파일 | 용도 | 게이트 | 생성 명령 (계획) |
|---|---|---|---|
| `drift.parquet` | 일부 변수 분포를 옮긴 운영 입력 7일분 — PSI ≥ 0.3 | G-M09 | `… --kind drift --shift <변수>=<σ배수>` |
| `psi_hand.json` | 손 계산 PSI · 범위 밖 · 결측 기대값 | G-M09 | 손 계산 |
| `source_db.sql` | gateway · mes 어댑터 시험용 원천 DB 사본(익명 합성) | G-S05 | `… --kind source_db` |
| `compat_expected.json` | 원천 옛 응답 키 목록(원천 파일을 읽어 만든다) | G-M04 | `… --kind compat` |

원천 DB 사본에 넣을 테이블: PRS_PROCESS_DATA · PRS_MOLD_SHOTS · BAS_EQUIPMENTS (열은 migration/source_inventory.md §4) — 값은 합성, 이름만 원천과 같다.
