# tests/fixtures/sw — sw 시험 원천

출처: 팩 `textile` 합성 생성기(원천 `../SongWol ML AI/api/ml_service.py:39-57 demo_data()` 이관, 시드 42 · 720행). 과제: delta_e · defect_risk · print_ood · print_setpoint.

## 있는 파일 (A0 — 개발3)

| 파일 | 내용 | sha256 (파일 바이트) |
|---|---|---|
| `snapshot.parquet` | 합성 스냅숏 720행 · 열 13 — 팩 생성기 출력 그대로(회사 `categories` 적용) | `360751ef6687c65067ee595ad2a392d53dc1d3d9264820d9c9dbf609ba3b5631` |
| `snapshot.csv` | 같은 내용 CSV (UTF-8 BOM, `ts` = `%Y-%m-%dT%H:%M:%S+09:00`) — `sources.eval` (csv 어댑터 시험) | `c3ff085a7a8b506f06ec1c7e0d108727b937cec5c42b507891534dde14d2c8a2` |
| `drift.parquet` | 운영 입력 168행(7일 × 24h, 2026-09-01 부터) — 팩 생성기를 시드 20260901 로 만든 뒤 `absorb_rate` 에 학습 표준편차 × 1.5 를 더하고 [min, max] 로 자름. 목표 열 없음. PSI(absorb_rate) ≥ 0.3, 나머지 < 0.2 | `d6c45321b120b9b23dfda799b5c2689500abcebbabae14dc4e07ed3a156a7e25` |
| `psi_hand.json` | 손 계산 기대값 — 셀 수 있는 사례 3(산식 포함) · 범위 밖 · 결측 · drift 대 snapshot 변수별 PSI (mlcore 없는 순수 파이썬) | `2d02154eef2b1b0383843908904889b1ce39b9c27b7c0620a98156a0eb94c837` |
| `source_db.sql` | 원천 DB 사본(합성 · 익명 — snapshot 과 같은 720행): PRT_QUALITY_HISTORY · PRT_PRINT_CONDS · RCV_MATERIAL_LOTS. 열 = 등록부 `feature_map` · `target_map` 의 원천 열 + 결합 키 `FX_KEY`(= entity_id) · 시각 `FX_AT`(첫 테이블) — 사본 정의, 원천 결합 키 미확인. 스키마 이름 없음(`SET search_path`). gateway · mes 어댑터 시험(G-S05) | `fbb62cf339d1e38eddd09b1b16c63073372cf3cd396970b8959f47d48c8896cb` |

열: set_temp · set_pressure · line_speed · ink_usage · dwell_time · absorb_rate · fabric_strength · print_type · color_tone · delta_e · defect · entity_id · ts. 결측 24셀(absorb_rate · fabric_strength · ink_usage 각 8) · 불량률 31.5%. 시간 2026-08-01 부터 1시간 간격(KST).

생성 명령 (두 번 돌려 해시가 같은 것을 확인했다 — 결정적):

```
uv run python migration/make_fixtures.py --tenant sw --kind snapshot     # snapshot.parquet
uv run python migration/make_fixtures.py --tenant sw --kind csv          # snapshot.csv
uv run python migration/make_fixtures.py --tenant sw --kind drift        # drift.parquet
uv run python migration/make_fixtures.py --tenant sw --kind psi_hand     # psi_hand.json
uv run python migration/make_fixtures.py --tenant sw --kind source_db    # source_db.sql
```

손질 금지 — `tests/test_synth.py::test_fixture_snapshot_is_regenerated_not_edited` · `tests/test_monitor.py::test_drift_fixture_is_regenerated_not_edited` 가 생성기 출력과 같은지 본다.
해시는 pyarrow 21.0.0 · pandas 2.3.3 (D-21) 기준이다. 버전이 바뀌면 parquet 바이트 해시는 달라질 수 있고 내용 대조 시험이 정본이다.

## 웨이브 A 로 미룬 것 (TODO 개발3)

| 파일 | 용도 | 게이트 | 생성 명령 (계획) |
|---|---|---|---|
| `compat_expected.json` | 원천 옛 응답 키 목록(원천 파일을 읽어 만든다) | G-M04 | `… --kind compat` |

원천 DB 사본(위 `source_db.sql`, 등록부 `sources.actuals.tables` 중 대응 열이 있는 것)의 원래 계획 테이블: PRT_PRINT_CONDS · PRT_PRINT_RESULTS · PRT_QUALITY_HISTORY · RCV_MATERIAL_LOTS (열은 migration/source_inventory.md §3) — 값은 합성, 이름만 원천과 같다.
