# tests/fixtures — 시험 원천 (goal §3.1-7 · D-13 · D-20)

루프는 실 Data Platform · MES · Gateway 를 부르지 않는다. 모든 시험은 이 폴더의 사본과 팩 합성 생성기로 판정한다.
**fixture 는 기대값에 맞춰 손질하지 않는다.** 바꾸려면 생성 명령을 고치고 다시 생성한 뒤, 이유를 `decisions.md` 에 남긴다.
공개 저장소이므로 회사 실데이터 · 키 · 주소를 넣지 않는다. 합성 또는 익명화 사본만.

| 폴더 | 내용 | 상태 |
|---|---|---|
| `ks/` | ks 합성 스냅숏 · 드리프트 · CSV · 원천 DB 사본 | snapshot.parquet · snapshot.csv (A0) · drift.parquet · psi_hand.json · source_db.sql (A — D-W1-10) |
| `sw/` | sw 같은 구성 | snapshot.parquet · snapshot.csv (A0) · drift.parquet · psi_hand.json · source_db.sql (A — D-W1-10) |
| `bad_registry/` | 병합 규칙 5 위반 불량 등록부 5종 (`contracts/tenant-contract.md` §2.1) | 있음 (Phase 0 · `gates/check_registry.py` 5/5) |
| `yn/` | 새 회사 CSV fixture (G-M10) — `_template` 변수. **커밋하지 않음(T4 · D-51)**: 시험이 tmp 에 만든다 `migration/make_fixtures.py --kind template_csv --out <tmp>` → `migration/make_tenant.py --new <code> --csv <tmp>/snapshot.csv` 가 tmp 등록부 루트(`MLP_TENANTS_DIR`)에 `<code>.yaml` 만 만든다(`tests/test_new_tenant.py`) | 폴더 없음이 정상 |

생성 명령은 각 폴더 README 에 적는다. 생성 스크립트는 `migration/make_fixtures.py` 하나로 모은다(개발3).
