"""오류 계약 — {"error": {"code", "message", "detail"}} (contracts/api-contract.md §2 · goal §2.3)."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


def not_found(message: str = "찾을 수 없습니다") -> ApiError:
    return ApiError(404, "not_found", message)


def not_implemented(what: str) -> ApiError:
    return ApiError(501, "not_implemented", f"{what} 은(는) 2차 범위입니다")
