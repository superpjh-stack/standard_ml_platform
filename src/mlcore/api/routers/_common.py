"""라우터 공용 — 주체 · 과제 목록 · 과제 경로 정규화 (개발2)."""

from __future__ import annotations

from fastapi import Request

from ... import auth
from ...serve.catalog import TaskCatalog
from ...serve.errors import NotFound


def principal(request: Request) -> auth.Principal:
    p = getattr(request.state, "principal", None)
    if p is None:
        raise auth.AuthRequired()
    return p


def catalog(request: Request) -> TaskCatalog:
    """기동 때 병합한 회사 등록부(app.state.registry)로 만든다. 등록부가 없으면 과제도 없다(404)."""
    reg = getattr(request.app.state, "registry", None)
    if reg is None:
        raise NotFound("과제를 찾을 수 없습니다")
    cat = getattr(request.app.state, "catalog", None)
    if cat is None or cat.merged is not reg:
        cat = TaskCatalog(reg)
        request.app.state.catalog = cat
    return cat


def task_id(t: str, task: str) -> str:
    """경로의 {task} 는 `<tenant>.<task>`(정본) — 짧은 이름도 받는다."""
    return task if "." in task else f"{t}.{task}"


def actor(p: auth.Principal) -> str:
    return f"{p.consumer}#{p.key_id}"
