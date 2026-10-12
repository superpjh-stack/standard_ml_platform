# press 합성 생성기 (M2 — A0 이관 완료)

| 파일 | 역할 |
|---|---|
| `press_lots.py` | 공용 생성 규칙 — 원천 `api/ml_service.py:20-38 demo_data()` 이관. `pack.yaml synth.module` |
| `remaining_hours.py` | 과제 진입점(spec §4.2 `synth/<task>.py`) — 공용 모듈을 그대로 내보낸다 |
| `__init__.py` | `mlcore.registry.packs.load_synth()` 가 이 폴더를 패키지로 읽는다 |

`generate(rows=720, seed=42, *, categories=None) -> DataFrame` — 열: `entity_id` · `ts` · 변수 9 · `remaining_hours` · `failure_24h`.
원천 세 과제(잔여수명 · 24h 고장 · 이상)가 한 `demo_data()` 를 공유하므로 failure_24h · sensor_ood 도 같은 프레임을 쓴다(진입점이 없으면 공용 모듈로 해석).
범주 `machine_code` · `product_type` 값은 `categories` 인자(회사 등록부 `categories`)로 받는다. 없으면 팩 중립 `M1~M4` · `P1~P3` — 길이가 같아 같은 행이 나온다.
행 일치 근거: `tests/test_synth.py` (원천 보고 시험 지표 6개 · 검증 지표 2개를 자리수까지 재현).
