"""호환 라우터 (D-18 · contracts/api-contract.md §5) — `/api/v1` 밖의 옛 회사 경로. 소유 개발2.

경로는 코드에 없다: 기동한 회사 등록부의 `compat.routes` 에 있는 것만 응답하고, 나머지 `/api/*` 는 표준 404 봉투다.
`/api/v1/*` 는 앞의 표준 라우터가 먼저 잡는다(이 라우터는 app 에 **마지막**으로 붙는다).
인증: 옛 health 꼴만 키 없이, 나머지는 X-API-Key + 표준 역할 판정(std/roles.yaml) — D-59. 다른 회사 키는 404.
2차: `compat.routes` 의 객체 항목(경로 인자 · 동작 · 과제 · 회사 모양 플러그인)은 `serve/compat/phase2.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ... import auth
from ...serve.compat import Compat, CompatError, parse_body
from ...serve.compat import phase2 as p2
from ...serve.errors import ServeError
from ...serve.jsonout import DecimalJSONResponse
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
        return await _phase2(cmp, path, request)
    action, arg = hit
    try:
        if action == "health":
            return cmp.health()
        p = _auth(request, cmp, AREA[action])
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


def _auth(request: Request, cmp: Compat, area: str):
    try:
        p = auth.lookup(request.headers.get("X-API-Key"))
    except auth.AuthRequired:
        raise CompatError(401, {"detail": "API 키가 필요합니다"}) from None
    request.state.principal = p          # 감사 미들웨어가 쓰기 시도 1행을 이 주체로 남긴다(DEF-QA2-002)
    if p.tenant_id != cmp.catalog.tenant_id:
        raise CompatError(404, {"detail": "찾을 수 없습니다"})
    if not auth.allowed(p.role, area, write=request.method == "POST"):
        raise CompatError(403, {"detail": "권한이 없습니다"})
    return p


async def _read_capped(request: Request, cap: int) -> bytes | None:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return None
    return bytes(buf)


def _serve_error(e: ServeError, cmp: Compat) -> CompatError:
    """표준 오류 → 옛 오류 모양. 422 는 옛 loc/msg/type 목록, 그 밖은 {detail, code}(입력값 되풀이 없음)."""
    from ...serve.compat import old_422
    if e.status == 422:
        return old_422(e, cmp.back)
    body = {"detail": e.message, "code": e.code}
    if (e.detail or {}).get("rule"):
        body["rule"] = e.detail["rule"]
    return CompatError(e.status, body)


async def _phase2(cmp: Compat, path: str, request: Request):
    """2차 객체 경로. 설정 · 플러그인 결함은 숨기지 않고 503 으로 보인다."""
    try:
        ph = p2.Phase2(cmp)
    except p2.CompatConfigError as e:
        return JSONResponse({"detail": str(e)[:300], "code": "compat_config_error"}, status_code=503)
    hit = p2.match(ph.routes, request.method, path)
    if hit is None:
        return _std404()
    route, args = hit
    info = {"tenant": ph.tenant, "action": route.action, "method": route.method, "path": route.path, "args": args,
            "task": route.task}
    try:
        try:
            if route.action == "health":
                caller = "compat-health"
            else:
                caller = actor(_auth(request, cmp, p2.ACTIONS[route.action][1]))
            body = b""
            if request.method == "POST":
                body = await _read_capped(request, p2.UPLOAD_CAP)
                if body is None:
                    if route.action.startswith("document_"):
                        raise CompatError(413, {"detail": "업로드가 허용 상한을 넘습니다", "code": "document_too_large"})
                    raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "요청 본문이 너무 큽니다", "type": "body_size"}]})
            out = ph.run(route, args, query=dict(request.query_params), body=body,
                         content_type=request.headers.get("content-type", ""), caller=caller)
        except ServeError as e:
            raise _serve_error(e, cmp) from None
    except CompatError as e:
        try:
            status, body = ph.shape_error(e.status, e.body, info)
        except p2.PluginError as pe:
            return JSONResponse({"detail": str(pe)[:300], "code": "compat_plugin_error"}, status_code=503)
        return JSONResponse(body, status_code=status)
    except p2.PluginError as e:
        return JSONResponse({"detail": str(e)[:300], "code": "compat_plugin_error"}, status_code=503)
    if isinstance(out, p2.Raw):
        headers = {"Content-Disposition": f'attachment; filename="{out.filename}"'} if out.filename else None
        return Response(out.data, media_type=out.media_type, headers=headers)
    if isinstance(out, (bytes, bytearray)):
        return Response(bytes(out), media_type=route.params.get("media_type") or "application/octet-stream")
    status = int(route.params.get("status", 200))          # 옛 서비스는 생성도 200 이었다 — 다르면 params.status
    return DecimalJSONResponse(out, status_code=status)
