# textile 합성 생성기 (M2 — A0 이관 완료)

| 파일 | 역할 |
|---|---|
| `print_lots.py` | 공용 생성 규칙 — 원천 `api/ml_service.py:22-57` (`true_delta_e` · `demo_data()`) 이관. `pack.yaml synth.module` |
| `delta_e.py` | 과제 진입점(spec §4.2 `synth/<task>.py`) — 공용 모듈을 그대로 내보낸다 |
| `__init__.py` | `load_synth()` 가 패키지로 읽는다 |

`generate(rows=720, seed=42, *, categories=None) -> DataFrame` — 열: `entity_id` · `ts` · 변수 9 · `delta_e` · `defect`.
원천의 설비 코드 열(난수 소비 없음)은 회사 값이라 만들지 않는다. 반올림(수치 2 · ΔE 3)은 원천 그대로.
행 일치 근거: `tests/test_synth.py` (ΔE 시험 · 검증 지표, 불량률 31.5%, DTF/연한 색상 41건 재현. 불량 분류 지표는 ≤0.0013 차이 — D-52).
