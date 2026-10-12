# _template 합성 생성기

`template_rows.py::generate(rows=600, seed=42)` — 단순 선형 자리표시(x1 · x2 · c1 → target_value · target_risk). 원천 이관 대상 없음.
새 업종 팩은 이 파일을 원천 `demo_data()` 이관으로 바꾸고, 과제가 생성기를 공유하면 공용 모듈 + `synth/<task>.py` 진입점으로 둔다.
