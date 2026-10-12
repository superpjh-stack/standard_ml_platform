"""호환 라우터 (D-18 · contracts/api-contract.md §5) — `/api/v1` 밖의 옛 회사 경로. 소유 개발2.

경로는 코드에 없다: 기동한 회사 등록부의 `compat.routes` 에 있는 것만 응답하고, 나머지 `/api/*` 는 표준 404 봉투다.
`/api/v1/*` 는 앞의 표준 라우터가 먼저 잡는다(이 라우터는 app 에 **마지막**으로 붙는다).
인증: 옛 health 꼴만 키 없이, 나머지는 X-API-Key + 표준 역할 판정(std/roles.yaml) — D-59. 다른 회사 키는 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ... import auth
from ...serve.compat import Compat, CompatError, parse_body
from ._common import actor, catalog

router = APIRouter()
AREA = {"predict": "predict", "optimize": "optimize", "overview": "overview", "records": "overview", "record": "overview"}


def _std404() -> JSONResponse:
    return JSONResponse({"error": {"code": "not_found", "message": "찾을 수 없습니다", "detail": {}}}, status_code=404)


@router.api_route("/api/{rest:path}", methods=["GET", "POST"], include_in_schema=False)
async def compat(rest: str, request: Request):
    path = "/api/" + rest
    if path.startswith("/api/v1/") or getattr(request.app.state, "registry", None) is None:
        return _std404()
    cmp = Compat(catalog(request))
    hit = cmp.resolve(request.method, path)
    if hit is None:
        return _std404()
    action, arg = hit
    try:
        if action == "health":
            return cmp.health()
        try:
            p = auth.lookup(request.headers.get("X-API-Key"))
        except auth.AuthRequired:
            raise CompatError(401, {"detail": "API 키가 필요합니다"}) from None
        if p.tenant_id != cmp.catalog.tenant_id:
            raise CompatError(404, {"detail": "찾을 수 없습니다"})
        if not auth.allowed(p.role, AREA[action], write=request.method == "POST"):
            raise CompatError(403, {"detail": "권한이 없습니다"})
        if action == "predict":
            return cmp.predict(parse_body(await request.body()), caller=actor(p))
        if action == "optimize":
            return cmp.optimize(parse_body(await request.body()), caller=actor(p))
        if action == "overview":
            return cmp.overview()
        if action == "records":
            return cmp.records(dict(request.query_params))
        return cmp.record(arg)
    except CompatError as e:
        return JSONResponse(e.body, status_code=e.status)
