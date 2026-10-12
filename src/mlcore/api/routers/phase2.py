"""B09 review · B10 documents · B11 quotes (api-contract §6 · goal2 §2.1 · §6). 소유 개발2.

- 역할: std/roles.yaml `review`(조회 operator · 판정 approver own_task) · `quotes`(operator 이상, 확정 **결정**은 B13 decide —
  approver 이상, D2-04). 과제 유형이 경로와 다르면 404 not_found(detail.rule `type_route`).
- 업로드는 multipart 를 스트림으로 상한 + 머리 여유까지만 읽는다(source_inventory §11.1). 외부 multipart 의존 없이 표준 email 파서.
- 견적 본문은 `jsonout.loads`(parse_float=Decimal) — JSON 실수가 float 를 거치지 않는다. 응답도 Decimal 그대로(금액은 문자열).
"""

from __future__ import annotations

import re
from email.parser import BytesParser
from email.policy import HTTP

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ... import auth
from ...serve import documents, quotes, review
from ...serve.errors import InvalidInput
from ...serve.jsonout import DecimalJSONResponse, loads
from ._common import actor, catalog, principal, task_id

router = APIRouter(prefix="/api/v1")
FORM_SLACK = 64 * 1024          # multipart 머리 · 다른 칸 여유
JSON_MAX = 1024 * 1024
CURSOR = r"^[A-Za-z0-9_]{1,64}$"


def _spec(request: Request, t: str, task: str):
    return catalog(request).get(t, task_id(t, task))


# ── B09 review ─────────────────────────────────────────────────────────────────────────
@router.get("/tenants/{t}/tasks/{task}/review")
def list_review(t: str, task: str, request: Request,
                state: str | None = Query(default=None, pattern="^(open|confirmed_issue|false_alarm)$"),
                limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None, pattern=CURSOR)):
    p = auth.require(principal(request), "review", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "review_queue")
    out = review.list_items(t, spec.task.id, state=state, limit=limit, cursor=cursor)
    try:                       # 화면 8 이 결정 버튼을 보일지 — PATCH 와 같은 판정(C2 D2-93 · DEF-QA23-004). 서버 판정은 그대로 PATCH 가 한다
        auth.require(p, "review")
        auth.require_own_task(p, "review", spec.task.raw["approver_role"])
        out["can_decide"] = True
    except auth.Forbidden:
        out["can_decide"] = False
    return out


@router.patch("/tenants/{t}/tasks/{task}/review/{item_id}")
async def decide_review(t: str, task: str, item_id: str, request: Request):
    p = auth.require(principal(request), "review")
    spec = _spec(request, t, task)
    documents.check_type(spec, "review_queue")
    auth.require_own_task(p, "review", spec.task.raw["approver_role"])
    body = await _json(request)
    if not isinstance(body, dict) or set(body) - {"state", "note"}:
        raise InvalidInput("요청은 {state, note} 입니다", {"field": None, "rule": "extra_forbidden"})
    return review.close_item(t, spec.task.id, item_id, state=body.get("state"), note=body.get("note"), actor=actor(p),
                         role=p.role, request_id=request.state.request_id)


# ── B10 documents ──────────────────────────────────────────────────────────────────────
async def _read_capped(request: Request, cap: int) -> bytes:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            raise documents.DocumentTooLarge("업로드가 허용 상한을 넘습니다", {"rule": "bytes", "field": "file"})
    return bytes(buf)


def _multipart(content_type: str, body: bytes) -> dict:
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type:
        raise documents.InvalidDocument("multipart/form-data 의 file 칸으로 보내세요", {"rule": "format", "field": "file"})
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body)
    out: dict = {}
    if not msg.is_multipart():
        raise documents.InvalidDocument("multipart 본문을 읽을 수 없습니다", {"rule": "format", "field": "file"})
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name or name in out:
            continue
        out[name] = {"filename": part.get_filename(), "data": part.get_payload(decode=True) or b""}
    return out


@router.post("/tenants/{t}/tasks/{task}/documents")
async def upload_document(t: str, task: str, request: Request):
    p = auth.require(principal(request), "quotes")
    cat = catalog(request)
    spec = cat.get(t, task_id(t, task))
    documents.check_type(spec, "extract")
    limits = documents.limits_for(spec.task.raw)
    raw = await _read_capped(request, limits["max_bytes"] + FORM_SLACK)
    form = _multipart(request.headers.get("content-type", ""), raw)
    f = form.get("file")
    if f is None or f["filename"] is None:
        raise documents.InvalidDocument("file 칸이 없습니다", {"rule": "format", "field": "file"})
    unit = form.get("unit_override")
    unit_override = unit["data"].decode("utf-8", "replace").strip() if unit else None
    body = documents.upload(spec, cat, filename=f["filename"], raw=f["data"], unit_override=unit_override or None,
                            actor=actor(p))
    return JSONResponse(body, status_code=201)


@router.get("/tenants/{t}/tasks/{task}/documents")
def list_documents(t: str, task: str, request: Request, search: str | None = Query(default=None, max_length=80),
                   limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None, pattern=CURSOR)):
    auth.require(principal(request), "quotes", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "extract")
    return documents.list_docs(t, spec.task.id, search=search, limit=limit, cursor=cursor)


@router.get("/tenants/{t}/tasks/{task}/documents/{doc_id}")
def get_document(t: str, task: str, doc_id: str, request: Request):
    auth.require(principal(request), "quotes", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "extract")
    return documents.get(t, spec.task.id, doc_id)


# ── B11 quotes ─────────────────────────────────────────────────────────────────────────
async def _json(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > JSON_MAX:
            raise InvalidInput("요청 본문이 너무 큽니다", {"field": None, "rule": "body_size"})
    if not raw:
        return {}
    try:
        return loads(bytes(raw))
    except (ValueError, RecursionError):
        raise InvalidInput("JSON 본문을 읽을 수 없습니다", {"field": None, "rule": "json_invalid"}) from None


def _qc(request: Request, t: str, task: str) -> quotes.QuoteContext:
    return quotes.QuoteContext(_spec(request, t, task), catalog(request))


@router.post("/tenants/{t}/tasks/{task}/quotes")
async def create_quote(t: str, task: str, request: Request):
    p = auth.require(principal(request), "quotes")
    qc = _qc(request, t, task)
    return DecimalJSONResponse(quotes.create(qc, await _json(request), actor=actor(p)), status_code=201)


@router.get("/tenants/{t}/tasks/{task}/quotes")
def list_quotes(t: str, task: str, request: Request, search: str | None = Query(default=None, max_length=80),
                status: str | None = Query(default=None, pattern="^(draft|pending_confirm|confirmed)$"),
                limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None, pattern=CURSOR)):
    auth.require(principal(request), "quotes", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "quote")
    return DecimalJSONResponse(quotes.list_quotes(t, spec.task.id, spec.notice, search=search, limit=limit,
                                                  cursor=cursor, status=status))


@router.get("/tenants/{t}/tasks/{task}/quotes/{quote_id}.csv")
def quote_csv(t: str, task: str, quote_id: str, request: Request):
    auth.require(principal(request), "quotes", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "quote")
    q = quotes.get(t, spec.task.id, quote_id, spec.notice)
    data = quotes.to_csv(q, list(spec.task.raw.get("csv") or []) or None)
    safe = re.sub(r"[^A-Za-z0-9_]", "", q["quote_id"])
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})


@router.get("/tenants/{t}/tasks/{task}/quotes/{quote_id}")
def get_quote(t: str, task: str, quote_id: str, request: Request):
    auth.require(principal(request), "quotes", write=False)
    spec = _spec(request, t, task)
    documents.check_type(spec, "quote")
    return DecimalJSONResponse(quotes.get(t, spec.task.id, quote_id, spec.notice))


@router.post("/tenants/{t}/tasks/{task}/quotes/{quote_id}/revisions")
async def revise_quote(t: str, task: str, quote_id: str, request: Request):
    p = auth.require(principal(request), "quotes")
    qc = _qc(request, t, task)
    return DecimalJSONResponse(quotes.revise(qc, quote_id, await _json(request), actor=actor(p)), status_code=201)


@router.post("/tenants/{t}/tasks/{task}/quotes/{quote_id}/confirm")
async def confirm_quote(t: str, task: str, quote_id: str, request: Request):
    p = auth.require(principal(request), "quotes")            # 요청은 operator 이상 — 결정은 B13 decide(approver 이상)
    qc = _qc(request, t, task)
    out = quotes.request_confirm(qc, quote_id, await _json(request), actor=actor(p), role=p.role,
                                 request_id=request.state.request_id)
    return JSONResponse(out, status_code=202)
