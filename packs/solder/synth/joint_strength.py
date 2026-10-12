"""과제 joint_strength 의 합성 생성기 진입점 (spec §4.2 `synth/<task>.py`) — 공용 모듈을 그대로 내보낸다."""

from .solder_lots import DEFAULT_ROWS, DEFAULT_SEED, TARGETS, generate

__all__ = ["DEFAULT_ROWS", "DEFAULT_SEED", "TARGETS", "generate"]
