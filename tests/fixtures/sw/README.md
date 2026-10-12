# tests/fixtures/sw — sw 시험 원천

출처: 팩 `textile` 합성 생성기(원천 `../SongWol ML AI/api/ml_service.py:39-57 demo_data()` 이관, 시드 42 · 720행). 과제: delta_e · defect_risk · print_ood · print_setpoint.

## 있는 파일 (A0 — 개발3)

| 파일 | 내용 | sha256 (파일 바이트) |
|---|---|---|
| `snapshot.parquet` | 합성 스냅숏 720행 · 열 13 — 팩 생성기 출력 그대로(회사 `categories` 적용) | `360751ef6687c65067ee595ad2a392d53dc1d3d9264820d9c9dbf609ba3b5631` |
| `snapshot.csv` | 같은 내용 CSV (UTF-8 BOM, `ts` = `%Y-%m-%dT%H:%M:%S+09:00`) — `sources.eval` (csv 어댑터 시험) | `c3ff085a7a8b506f06ec1c7e0d108727b937cec5c42b507891534dde14d2c8a2` |

열: set_temp · set_pressure · line_speed · ink_usage · dwell_time · absorb_rate · fabric_strength · print_type · color_tone · delta_e · defect · entity_id · ts. 결측 24셀(absorb_rate · fabric_strength · ink_usage 각 8) · 불량률 31.5%. 시간 2026-08-01 부터 1시간 간격(KST).

생성 명령 (두 번 돌려 해시가 같은 것을 확인했다 — 결정적):

```
uv run python migration/make_fixtures.py --tenant sw --kind snapshot     # snapshot.parquet
uv run python migration/make_fixtures.py --tenant sw --kind csv          # snapshot.csv
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

원천 DB 사본에 넣을 테이블: PRT_PRINT_CONDS · PRT_PRINT_RESULTS · PRT_QUALITY_HISTORY · RCV_MATERIAL_LOTS (열은 migration/source_inventory.md §3) — 값은 합성, 이름만 원천과 같다.
