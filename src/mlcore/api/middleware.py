"""인증 · 감사 미들웨어 골격 (spec §17 · contracts/api-contract.md).

- 인증: /api/v1/* 중 /api/v1/health 를 뺀 전부에 X-API-Key 필수 → request.state.principal.
  경로의 {t} 가 키의 회사와 다르면 404 (존재 숨김).
- 감사: 쓰기 요청(POST · PATCH · PUT · DELETE)은 응답 후 mlp_audit 에 1행. 실패를 삼키지 않고 로그로 남긴다.
- 모든 응답에 X-Request-Id.
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


def _err(e: ApiError, request_id: str) -> JSONResponse:
    return JSONResponse(e.body(), status_code=e.status, headers={"X-Request-Id": request_id})


class AuthAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.principal = None
        path = request.url.path
        guarded = path.startswith("/api/v1/") and path not in PUBLIC
        if guarded:
            try:
                principal = auth.lookup(request.headers.get("X-API-Key"))
            except auth.AuthRequired:
                return _err(ApiError(401, "auth_required", "API 키가 필요합니다"), request_id)
            except DbUnavailable:
                return _err(ApiError(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다"), request_id)
            m = TENANT_PATH.match(path)
            if m and m.group(1) != principal.tenant_id:
                return _err(ApiError(404, "not_found", "찾을 수 없습니다"), request_id)
            request.state.principal = principal
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        if guarded and request.method in ("POST", "PATCH", "PUT", "DELETE"):
            p = request.state.principal
            try:
                audit.write(tenant_id=p.tenant_id, actor=p.consumer, role=p.role,
                            action=f"{request.method} {request.scope.get('route').path if request.scope.get('route') else path}",
                            target=path, detail={"status": response.status_code}, request_id=request_id)
            except Exception as e:  # noqa: BLE001 — 감사 실패는 숨기지 않고 남긴다
                log.error("audit write failed: %s", type(e).__name__)
        return response
