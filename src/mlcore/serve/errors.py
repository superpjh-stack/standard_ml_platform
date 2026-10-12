"""추론 · 등록부 · 승인 공용 오류 — 상태 코드 · 오류 코드는 std/statuses.yaml error_codes (goal §2.3).

각 예외는 `status` · `code` 를 갖고 API 계층(`api/main.py`)이 `{"error": {code, message, detail}}` 로 바꾼다.
`detail` 에는 입력값을 되풀이하지 않는다 — `field` · `rule` 만.
"""

from __future__ import annotations


class ServeError(Exception):
    status = 500
    code = "internal"
    default_message = "요청을 처리할 수 없습니다"

    def __init__(self, message: str | None = None, detail: dict | None = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.detail = detail or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class InvalidInput(ServeError):
    status, code, default_message = 422, "invalid_input", "입력 값이 올바르지 않습니다"


class MissingRequired(ServeError):
    status, code, default_message = 422, "missing_required", "필수 입력이 없거나 보정 한도를 넘었습니다"


class OutOfBounds(ServeError):
    status, code, default_message = 422, "out_of_bounds", "입력 값이 허용 범위(min/max) 밖입니다"


class NotFound(ServeError):
    status, code, default_message = 404, "not_found", "찾을 수 없습니다"


class NotImplementedTaskType(ServeError):
    status, code, default_message = 501, "not_implemented", "이 과제 유형의 추론은 아직 구현되지 않았습니다"
