# tests/fixtures/ks — ks 시험 원천

출처: 팩 `press` 합성 생성기(원천 `../KwangSung ML AI/api/ml_service.py:20-38 demo_data()` 이관, 시드 42 · 720행). 과제: remaining_hours · failure_24h · sensor_ood · maintenance_timing.

## 있는 파일 (A0 — 개발3)

| 파일 | 내용 | sha256 (파일 바이트) |
|---|---|---|
| `snapshot.parquet` | 합성 스냅숏 720행 · 열 13 — 팩 생성기 출력 그대로(회사 `categories` 적용) | `bc49ed49cf771bd978790a7226d940f1d7b18bda40d2689f5402ced3942fb890` |
| `snapshot.csv` | 같은 내용 CSV (UTF-8 BOM, `ts` = `%Y-%m-%dT%H:%M:%S+09:00`) — `sources.eval` (csv 어댑터 시험) | `3f6a10ceb842f21cfe138da2ec47054193b47cbd2dde1e10b04f648fb98f219e` |
| `drift.parquet` | 운영 입력 168행(7일 × 24h, 2026-09-01 부터) — 팩 생성기를 시드 20260901 로 만든 뒤 `vibration` 에 학습 표준편차 × 1.5 를 더하고 [min, max] 로 자름. 목표 열 없음. PSI(vibration) ≥ 0.3, 나머지 < 0.2 | `34252f30aefa743772204252560b26d8300ef849dc20e34af46c8c13c8be40fc` |
| `psi_hand.json` | 손 계산 기대값 — 셀 수 있는 사례 3(산식 포함) · 범위 밖 · 결측 · drift 대 snapshot 변수별 PSI (mlcore 없는 순수 파이썬) | `33619b53731ef1608ccb071d055c68e84f8b25ee1adcd4e3d642be1a426fc827` |
| `source_db.sql` | 원천 DB 사본(합성 · 익명 — snapshot 과 같은 720행): PRS_PROCESS_DATA · PRS_MOLD_SHOTS · BAS_EQUIPMENTS. 열 = 등록부 `feature_map` · `target_map` 의 원천 열 + 결합 키 `FX_KEY`(= entity_id) · 시각 `FX_AT`(첫 테이블) — 사본 정의, 원천 결합 키 미확인. 스키마 이름 없음(`SET search_path`). gateway · mes 어댑터 시험(G-S05) | `1ed5b4e19c3d15b44c48a1b4c4b3754ffdb2226ab9eca82dc26cf6f06e502145` |

열: press_force · vibration · motor_current · equip_temp · mold_temp · cycle_time · shot_count · machine_code · product_type · remaining_hours · failure_24h · entity_id · ts. 결측 24셀(vibration · motor_current · mold_temp 각 8). 시간 2026-08-01 부터 1시간 간격(KST).

생성 명령 (두 번 돌려 해시가 같은 것을 확인했다 — 결정적):

```
uv run python migration/make_fixtures.py --tenant ks --kind snapshot     # snapshot.parquet
uv run python migration/make_fixtures.py --tenant ks --kind csv          # snapshot.csv
uv run python migration/make_fixtures.py --tenant ks --kind drift        # drift.parquet
uv run python migration/make_fixtures.py --tenant ks --kind psi_hand     # psi_hand.json
uv run python migration/make_fixtures.py --tenant ks --kind source_db    # source_db.sql
```

손질 금지 — `tests/test_synth.py::test_fixture_snapshot_is_regenerated_not_edited` · `tests/test_monitor.py::test_drift_fixture_is_regenerated_not_edited` 가 생성기 출력과 같은지 본다.
해시는 pyarrow 21.0.0 · pandas 2.3.3 (D-21) 기준이다. 버전이 바뀌면 parquet 바이트 해시는 달라질 수 있고 내용 대조 시험이 정본이다.

## 웨이브 A 로 미룬 것 (TODO 개발3)

| 파일 | 용도 | 게이트 | 생성 명령 (계획) |
|---|---|---|---|
| `compat_expected.json` | 원천 옛 응답 키 목록(원천 파일을 읽어 만든다) | G-M04 | `… --kind compat` |

원천 DB 사본(위 `source_db.sql`, 등록부 `sources.actuals.tables` 중 대응 열이 있는 것)의 원래 계획 테이블: PRS_PROCESS_DATA · PRS_MOLD_SHOTS · BAS_EQUIPMENTS (열은 migration/source_inventory.md §4) — 값은 합성, 이름만 원천과 같다.
