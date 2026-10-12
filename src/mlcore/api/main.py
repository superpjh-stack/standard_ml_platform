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

from .. import auth
from ..db.conn import DbUnavailable
from ..serve.contract import safe_errors
from ..serve.errors import ServeError
from ..settings import ROOT, get_settings
from .errors import ApiError
from .middleware import AuthAuditMiddleware
from .routers import compat, models, ops, phase2, predict, train, v1

log = logging.getLogger("mlcore.api")
VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    code = get_settings().tenant
    # 등록부 병합만 한다. 학습 함수는 여기서 부르지 않는다. 등록부 루트는 학습 작업자와 같은 규칙
    # (mlcore.data.jobs.tenants_base_for = registry.tenants.tenant_base: MLP_TENANTS_DIR → 기본 tenants/, D-65).
    # R4: live 회사는 등록부 DB 의 production 스냅숏 synthetic 을 읽어 합성 모델 과제를 끈다(DEF-QA3-001 · D-120).
    if code:
        from ..data.jobs import tenants_base_for
        from ..registry.tenants import load_for_serving
        app.state.registry = load_for_serving(code, tenants_base=tenants_base_for(code))
    else:
        app.state.registry = None
    yield


app = FastAPI(title="표준 ML 플랫폼", version=VERSION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

_origins = [o for o in get_settings().cors_origins if o != "*"]   # 와일드카드는 설정에 있어도 받지 않는다
if _origins:  # CORS 는 설정 목록(MLP_CORS_ORIGINS)만 (spec §17 · G-M11). 비어 있으면 붙이지 않는다
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["X-API-Key", "Content-Type", "X-Request-Id"], allow_credentials=False)
app.add_middleware(AuthAuditMiddleware)


def _err(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "detail": detail or {}}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(request: Request, exc: ApiError):
    return JSONResponse(exc.body(), status_code=exc.status)


@app.exception_handler(ServeError)
async def _serve_error(request: Request, exc: ServeError):
    # 추론 · 등록부 · 승인 오류 — model_not_ready · model_artifact_mismatch · invalid_input · already_decided …
    return JSONResponse(exc.body(), status_code=exc.status)


@app.exception_handler(auth.AuthRequired)
async def _auth_required(request: Request, exc):
    return _err(401, "auth_required", "API 키가 필요합니다")


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    # 입력값 · 요청 키 문자열을 되풀이하지 않는다 — 계약 필드 위치와 규칙 이름만 (goal §2.3)
    errs = safe_errors(exc.errors(), skip=1)
    nul = next((e for e in errs if e["rule"] == "nul"), None)
    if nul is not None:              # NUL 은 공통 검증(D2-111) — 견적 · 대기열 경로와 같은 {field, rule: nul} 모양으로도
        return _err(422, "invalid_input", "문자열에 NUL 문자(U+0000)가 있습니다", {**nul, "errors": [nul]})
    return _err(422, "invalid_input", "입력 값이 올바르지 않습니다", {"errors": errs})


@app.exception_handler(StarletteHTTPException)
async def _http(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 400:
        # FastAPI 는 JSON 해석 중 JSONDecodeError 밖의 오류(예: 4300자리 넘는 정수 리터럴)를 400 으로 낸다 —
        # 오류 계약에는 400 이 없다. 형식 오류이므로 422 invalid_input (DEF-QA2-006)
        return _err(422, "invalid_input", "입력 값이 올바르지 않습니다", {"errors": [{"field": None, "rule": "json_invalid"}]})
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    message = {404: "찾을 수 없습니다", 405: "허용되지 않는 메서드입니다"}.get(exc.status_code, "요청을 처리할 수 없습니다")
    return _err(exc.status_code, code, message)


@app.exception_handler(DbUnavailable)
async def _db_down(request: Request, exc):
    return _err(503, "db_unavailable", "데이터베이스에 연결할 수 없습니다")


app.include_router(v1.router)
app.include_router(predict.router)
app.include_router(models.router)
app.include_router(train.router)
app.include_router(ops.router)       # 개발3 B02 · B06 · B12 · B14 (progress-dev3 §3 요청)
app.include_router(phase2.router)    # 2차 B09 · B10 · B11 (api-contract §6)


def include_compat() -> None:
    """호환 라우터(`/api/{rest}` 잡이)는 **맨 마지막**에 둔다 — 다른 담당 라우터가 붙은 뒤에도 끝으로 옮긴다."""
    routes = app.router.routes
    mine = [r for r in routes if getattr(r, "endpoint", None) is compat.compat]
    for r in mine:
        routes.remove(r)
    if not mine:
        app.include_router(compat.router)
    else:
        routes.extend(mine)

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


include_compat()
