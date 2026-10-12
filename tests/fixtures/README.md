# tests/fixtures — 시험 원천 (goal §3.1-7 · D-13 · D-20)

루프는 실 Data Platform · MES · Gateway 를 부르지 않는다. 모든 시험은 이 폴더의 사본과 팩 합성 생성기로 판정한다.
**fixture 는 기대값에 맞춰 손질하지 않는다.** 바꾸려면 생성 명령을 고치고 다시 생성한 뒤, 이유를 `decisions.md` 에 남긴다.
공개 저장소이므로 회사 실데이터 · 키 · 주소를 넣지 않는다. 합성 또는 익명화 사본만.

| 폴더 | 내용 | 상태 |
|---|---|---|
| `ks/` | ks 합성 스냅숏 · 드리프트 · CSV · 원천 DB 사본 | README 만 (TODO 개발3) |
| `sw/` | sw 같은 구성 | README 만 (TODO 개발3) |
| `bad_registry/` | 병합 규칙 5 위반 불량 등록부 5종 (`contracts/tenant-contract.md` §2.1) | TODO 개발3 (A) |
| `yn/` | 새 회사 CSV fixture (G-M10) — `make tenant` 시험이 만든다 | TODO 개발3 (A) |

생성 명령은 각 폴더 README 에 적는다. 생성 스크립트는 `migration/make_fixtures.py` 하나로 모은다(개발3).
