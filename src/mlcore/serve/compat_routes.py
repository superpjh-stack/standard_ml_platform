"""호환 경로 표 — `compat.routes` 객체 항목의 동작 · 모양 검사 · 경로 맞추기 (api-contract §5). 소유 개발2.

표는 여기 한 곳이다: 호환 라우터(`serve/compat/phase2.py`)와 등록부 로더(`registry/tenants.py` — 기동 때 T0 검사)가
같은 표를 읽는다. 이 모듈은 표준 라이브러리만 import 한다(로더와 순환 없음).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 동작 → (메서드, std/roles.yaml 권한 영역, 과제 유형(필요하면))
ACTIONS: dict[str, tuple[str, str, tuple[str, ...] | None]] = {
    "health": ("GET", "overview", None),
    "overview": ("GET", "overview", None),
    "predict": ("POST", "predict", None),
    "optimize": ("POST", "optimize", None),
    "records": ("GET", "overview", None),
    "record": ("GET", "overview", None),
    "predict_one": ("POST", "predict", ("regression", "risk", "anomaly")),
    "samples": ("GET", "overview", ("regression", "risk", "anomaly", "optimize")),
    "review_list": ("GET", "review", ("review_queue",)),
    "document_upload": ("POST", "quotes", ("extract",)),
    "document_demo": ("POST", "quotes", ("extract",)),
    "document_get": ("GET", "quotes", ("extract",)),
    "pack_file": ("GET", "overview", None),
    "quote_create": ("POST", "quotes", ("quote",)),
    "quote_list": ("GET", "quotes", ("quote",)),
    "quote_get": ("GET", "quotes", ("quote",)),
    "quote_csv": ("GET", "quotes", ("quote",)),
    "quote_export_csv": ("GET", "quotes", ("quote",)),
}
ARG = re.compile(r"\{([a-z_][a-z0-9_]{0,30})\}")
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")
LIST_CAP = 1000
UPLOAD_CAP = 5 * 1024 * 1024 + 64 * 1024     # spec 문서 상한 + multipart 머리 여유 (과제 상한은 표준 서비스가 다시 본다)          # 옛 offset 목록이 한 번에 훑는 최대 견적 수


class CompatConfigError(ValueError):
    """등록부 compat.routes 객체가 틀렸다 — 기동한 회사 설정 결함(503 compat_config_error)."""


@dataclass(frozen=True)
class Route:
    path: str
    method: str
    action: str
    task: str | None = None
    shape: str | None = None
    params: dict = field(default_factory=dict)
    regex: re.Pattern = field(default=re.compile(""), compare=False)
    n_args: int = 0


def parse_route(item: dict) -> Route:
    if not isinstance(item, dict):
        raise CompatConfigError(f"compat.routes 항목은 문자열 또는 객체입니다: {item!r}")
    unknown = set(item) - {"path", "method", "action", "task", "shape", "params"}
    if unknown:
        raise CompatConfigError(f"compat.routes 모르는 키 {sorted(unknown)}")
    path, action = item.get("path"), item.get("action")
    if not isinstance(path, str) or not path.startswith("/api/") or path.startswith("/api/v1/"):
        raise CompatConfigError(f"compat.routes path 는 /api/ 아래(/api/v1 제외) — {path!r}")
    if action not in ACTIONS:
        raise CompatConfigError(f"compat.routes action {action!r} — {sorted(ACTIONS)} 만")
    method = str(item.get("method") or ACTIONS[action][0]).upper()
    if method not in ("GET", "POST"):
        raise CompatConfigError(f"compat.routes method {method!r} — GET · POST 만")
    task = item.get("task")
    if ACTIONS[action][2] is not None and action != "samples" and not task:
        raise CompatConfigError(f"compat.routes {path}: action {action} 에는 task(과제 짧은 이름)가 필요합니다")
    if task is not None and not (isinstance(task, str) and re.match(r"^[a-z][a-z0-9_]{0,40}$", task)):
        raise CompatConfigError(f"compat.routes task {task!r}")
    shape = item.get("shape")
    if shape is not None and not (isinstance(shape, str) and re.match(r"^[a-z][a-z0-9_]{0,40}$", shape)):
        raise CompatConfigError(f"compat.routes shape {shape!r}")
    params = item.get("params") or {}
    if not isinstance(params, dict):
        raise CompatConfigError("compat.routes params 는 객체")
    check_params(params)
    parts, names = [], []
    for seg in path.split("/"):
        m = ARG.fullmatch(seg)
        if m:
            names.append(m.group(1))
            parts.append(f"(?P<{m.group(1)}>[^/]+)")
        elif "{" in seg or "}" in seg:
            raise CompatConfigError(f"compat.routes path 인자는 한 마디 전체 {{이름}} — {path!r}")
        else:
            parts.append(re.escape(seg))
    if len(set(names)) != len(names):
        raise CompatConfigError(f"compat.routes path 인자 이름 중복 — {path!r}")
    return Route(path, method, action, task, shape, dict(params), re.compile("^" + "/".join(parts) + "$"), len(names))


def parse_routes(items: list) -> list[Route]:
    return [parse_route(x) for x in items or [] if not isinstance(x, str)]


def match(routes: list[Route], method: str, path: str) -> tuple[Route, dict] | None:
    hits = []
    for i, r in enumerate(routes):
        if r.method != method:
            continue
        m = r.regex.match(path)
        if m:
            hits.append((r.n_args, i, r, m.groupdict()))
    if not hits:
        return None
    _, _, r, args = min(hits, key=lambda x: (x[0], x[1]))
    return r, args


PARAM_KEYS = {"limit", "max_limit", "state", "file", "file_field", "unit_override", "media_type", "columns", "status",
              "search_max"}


def check_params(params: dict) -> None:
    """params 모양 — 아는 키만 · 값 모양(정수 · 파일 이름 · 열 목록 · 상태 코드)."""
    unknown = set(params) - PARAM_KEYS
    if unknown:
        raise CompatConfigError(f"compat.routes params 모르는 키 {sorted(unknown)}")
    for k in ("limit", "max_limit", "search_max"):
        if k in params and not (isinstance(params[k], int) and not isinstance(params[k], bool) and 0 < params[k] <= 1000):
            raise CompatConfigError(f"compat.routes params.{k} 는 1~1000 정수")
    if "status" in params and not (isinstance(params["status"], int) and 200 <= params["status"] <= 299):
        raise CompatConfigError("compat.routes params.status 는 2xx 정수")
    if "file" in params and not (isinstance(params["file"], str) and SAFE_FILE.match(params["file"]) and ".." not in params["file"]):
        raise CompatConfigError(f"compat.routes params.file {params['file']!r} — 회사 · 팩 samples/ 의 파일 이름만")
    if "columns" in params and not (isinstance(params["columns"], list) and params["columns"]
                                    and all(isinstance(c, str) and re.match(r"^[a-z_][a-z0-9_.]{0,60}$", c) for c in params["columns"])):
        raise CompatConfigError("compat.routes params.columns 는 이름 목록")
    for k in ("state", "file_field", "unit_override", "media_type"):
        if k in params and not (isinstance(params[k], str) and re.match(r"^[A-Za-z0-9_./;= -]{1,80}$", params[k])):
            raise CompatConfigError(f"compat.routes params.{k} 는 짧은 문자열")


def check_routes(items: list, task_types: dict[str, str]) -> None:
    """등록부 기동 검사 — 객체 항목 전부. task_types = {켜진 과제 짧은 이름: 유형}. 틀리면 CompatConfigError."""
    if items is None:
        return
    if not isinstance(items, list):
        raise CompatConfigError("compat.routes 는 목록")
    seen = set()
    for x in items:
        if isinstance(x, str):
            continue
        r = parse_route(x)
        key = (r.method, r.path)
        if key in seen:
            raise CompatConfigError(f"compat.routes 같은 경로 두 번 {r.method} {r.path}")
        seen.add(key)
        want = ACTIONS[r.action][2]
        if r.task is not None:
            if r.task not in task_types:
                raise CompatConfigError(f"compat.routes {r.path}: 과제 {r.task!r} 가 켜져 있지 않다")
            if want is not None and task_types[r.task] not in want:
                raise CompatConfigError(f"compat.routes {r.path}: 과제 {r.task} 유형 {task_types[r.task]} — "
                                        f"동작 {r.action} 은 {list(want)} 만")
        if r.action in ("pack_file", "document_demo") and "file" not in r.params and "{file}" not in r.path:
            raise CompatConfigError(f"compat.routes {r.path}: {r.action} 에는 params.file 또는 경로 인자 {{file}}")
