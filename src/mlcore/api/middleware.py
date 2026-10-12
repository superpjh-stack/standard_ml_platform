"""인증 · 감사 미들웨어 (spec §17 · contracts/api-contract.md). 소유 개발2.

- 인증: /api/v1/* 중 /api/v1/health 를 뺀 전부에 X-API-Key 필수 → request.state.principal.
  경로의 {t} 가 키의 회사와 다르면 404 (존재 숨김). 호환 경로(/api/… 옛 경로)는 호환 라우터가 인증하고
  같은 request.state.principal 에 주체를 둔다(D-59).
- 감사: `/api/` 아래 **모든 쓰기 시도**(POST · PATCH · PUT · DELETE)는 응답 뒤 mlp_audit 에 1행 — 성공 · 거부(401 · 403 ·
  다른 회사 404) · 실패 모두(DEF-QA2-002). 주체를 모르면 tenant '-' · actor 'anonymous'(db-schema mlp_audit).
  실패를 삼키지 않고 로그로 남긴다.
- 모든 응답에 X-Request-Id. 받은 값은 `^[A-Za-z0-9._-]{1,64}$` 일 때만 쓰고, 아니면 새로 만든다(되풀이 길이 · 문자 제한).
"""

from __future__ import annotations

import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .. import audit, auth
from ..db.conn import DbUnavailable
from .errors import ApiError

log = logging.getLogger("mlcore.api")
PUBLIC = {"/api/v1/health"}
TENANT_PATH = re.compile(r"^/api/v1/tenants/([^/]+)(/|$)")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
WRITES = ("POST", "PATCH", "PUT", "DELETE")
TARGET_MAX = 256


def _err(e: ApiError, request_id: str) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status, headers={"X-Request-Id": request_id})


def _audit(request: Request, status: int, *, rule: str | None = None) -> None:
    """쓰기 시도 1건 → mlp_audit 1행. 경로는 길이를 자른다(요청자가 정한 문자열)."""
    p = getattr(request.state, "principal", None)
    route = request.scope.get("route")
    path = request.url.path
    action = f"{request.method} {route.path if route is not None and getattr(route, 'path', None) else path}"[:TARGET_MAX]
    detail = {"status": status}
    if rule:
        detail["rule"] = rule
    try:
        audit.write(tenant_id=p.tenant_id if p else "-", actor=p.consumer if p else "anonymous", role=p.role if p else None,
                    action=action, target=path[:TARGET_MAX], detail=detail, request_id=request.state.request_id)
    except Exception as e:  # noqa: BLE001 — 감사 실패는 숨기지 않고 남긴다
        log.error("audit write failed: %s", type(e).__name__)


class AuthAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        got = request.headers.get("X-Request-Id") or ""
        request_id = got if REQUEST_ID.match(got) else uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.principal = None
        path = request.url.path
        write = request.method in WRITES and path.startswith("/api/")
        guarded = path.startswith("/api/v1/") and path not in PUBLIC
        if guarded:
            try:
                principal = auth.lookup(request.headers.get("X-API-Key"))
            except auth.AuthRequired:
                if write:
                    _audit(request, 401, rule="auth_required")
                return _err(ApiError(401, "auth_required", "API 키가 필요합니다"), request_id)
            except DbUnavailable:
                return _err(ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다"), request_id)
            request.state.principal = principal
            m = TENANT_PATH.match(path)
            if m and m.group(1) != principal.tenant_id:
                if write:                    # 거부된 회사 간 쓰기 시도 — 키의 회사 감사에 남긴다
                    _audit(request, 404, rule="tenant_scope")
                return _err(ApiError(404, "not_found", "찾을 수 없습니다"), request_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        if write:
            _audit(request, response.status_code)
        return response
