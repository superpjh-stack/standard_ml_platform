"""표준 ML 플랫폼 API — `uv run uvicorn mlcore.api.main:app --port 8200` (make run TENANT=<code>).

기동 시 학습하지 않는다(G-M06). 기동은 등록부 로드 · 병합 규칙 검사만 하고, 위반이면 기동을 거부한다(G-S02).
모델은 요청 시 등록부의 production 버전 산출물(해시 대조)에서만 읽는다 — 없으면 503 model_not_ready.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..db.conn import DbUnavailable
from ..registry import tenants
from ..settings import ROOT, get_settings
from .errors import ApiError
from .middleware import AuthAuditMiddleware
from .routers import v1

log = logging.getLogger("mlcore.api")
VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    code = get_settings().tenant
    # 등록부 병합만 한다. 학습 함수는 여기서 부르지 않는다.
    app.state.registry = tenants.load_and_merge(code) if code else None
    yield


app = FastAPI(title="표준 ML 플랫폼", version=VERSION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

_origins = list(get_settings().cors_origins)
if _origins:  # CORS 는 설정 목록만 (spec §17). 비어 있으면 붙이지 않는다
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["X-API-Key", "Content-Type", "X-Request-Id"])
app.add_middleware(AuthAuditMiddleware)


def _err(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "detail": detail or {}}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(request: Request, exc: ApiError):
    return JSONResponse(exc.body(), status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    # 입력값을 되풀이하지 않는다 — 위치와 규칙 이름만 (goal §2.3)
    detail = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "rule": e.get("type")} for e in exc.errors()]
    return _err(422, "invalid_input", "입력 값이 올바르지 않습니다", {"errors": detail})


@app.exception_handler(StarletteHTTPException)
async def _http(request: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    message = {404: "찾을 수 없습니다", 405: "허용되지 않는 메서드입니다"}.get(exc.status_code, "요청을 처리할 수 없습니다")
    return _err(exc.status_code, code, message)


@app.exception_handler(DbUnavailable)
async def _db_down(request: Request, exc):
    return _err(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다")


app.include_router(v1.router)

# 콘솔 — web/dist 가 있으면 /app/* 로 제공 (contracts/screen-map.md)
DIST: Path = ROOT / "web" / "dist"
if (DIST / "assets").is_dir():
    app.mount("/app/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/app/{rest:path}", include_in_schema=False)
def console(rest: str = ""):
    index = DIST / "index.html"
    if not index.is_file():
        return _err(503, "console_not_built", "먼저 web 에서 npm run build 를 실행하세요")
    return FileResponse(index)
