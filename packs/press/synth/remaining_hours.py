"""과제 remaining_hours 의 합성 생성기 진입점 (spec §4.2 `synth/<task>.py`).

원천은 한 demo_data() 가 잔여수명 · 24h 고장 · 이상 탐지 세 과제의 데이터를 함께 만든다.
그래서 생성 규칙은 공용 모듈 `press_lots.py` 하나에 두고, 과제 진입점은 그것을 그대로 내보낸다.
"""

from .press_lots import DEFAULT_ROWS, DEFAULT_SEED, TARGETS, generate

__all__ = ["DEFAULT_ROWS", "DEFAULT_SEED", "TARGETS", "generate"]
