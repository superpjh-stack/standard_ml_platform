"""호환 라우터 2차 — 객체 경로 · 2차 유형 동작 · 회사 모양 플러그인 (api-contract §5 · §6.3 · predict-contract §7). 소유 개발2.

코어 동결(core-freeze-2) 뒤 회사 4(웨이브 A2)의 옛 경로를 **코어 수정 없이** 붙이기 위한 일반 장치다.

등록부 `tenants/<code>.yaml compat.routes` 의 항목은 두 꼴이다.
  - 문자열(1차 그대로) — 접미사로 동작을 추론(`…/predict` · `…/optimize` · `…/overview` · `…/records` · `…/health`).
  - 객체 `{path, method, action, task?, shape?, params?}` — 이 모듈. `path` 에 `{이름}` 경로 인자(한 마디, `/` 없음).
    같은 요청에 여러 객체가 맞으면 **경로 인자가 적은 것**(글자 그대로 맞는 것)이 먼저, 같으면 적힌 순서.

동작(ACTIONS)은 표준 서비스를 그대로 부른다 — 계산 · 저장 · 승인 규칙은 표준 경로와 같고, 여기는 요청 · 응답 모양만 바꾼다.
회사 고유 모양은 `tenants/<code>/compat.py`(있으면)의 함수:
  `parse_<동작>(old_body, info) -> 표준 본문` · `shape_<동작>(표준 결과, info) -> 옛 본문` (route.shape 가 있으면 `shape_<shape>`)
  · `shape_error(status, body, info) -> (status, body)` — 없으면 표준 결과 그대로(+ compat.input_rename 은 요청 입력에 적용).
  재진입 보강(D2-70): `parse_optimize` 가 `{fixed, params}` 를 돌려주면 현재값 없는 표준 최적화(D2-A2-02) ·
  `parse_records(query, info)` · `records_frame(frame, n_all, info)` (D2-A2-05) · 예시 파일은 `tenants/<code>/samples/` 먼저(D2-A2-04).
  info = {tenant, action, method, path, args, query, task, params}. 플러그인은 `CompatError` 를 올려 옛 오류를 낼 수 있다.
플러그인 파일은 회사 등록부 폴더(`tenants/`) 안의 것만, 내용 해시로 한 번만 읽는다. 읽기 · 실행 실패는 숨기지 않고
503 `compat_plugin_error`(사유 포함)로 돌려준다 — 표준 결과로 조용히 대신하지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ServeError

# 경로 표 · 해석은 `serve/compat_routes.py` 한 곳(등록부 로더도 같은 표로 기동 때 검사 — import 순환 없이)
from ..compat_routes import (ACTIONS, ARG, SAFE_FILE, CompatConfigError, Route, match,  # noqa: F401
                             parse_route, parse_routes)

LIST_CAP = 1000          # 옛 offset 목록이 한 번에 훑는 최대 견적 수
UPLOAD_CAP = 5 * 1024 * 1024 + 64 * 1024     # spec 문서 상한 + multipart 머리 여유 (과제 상한은 표준 서비스가 다시 본다)


# ── 회사 플러그인 ──────────────────────────────────────────────────────────────────────
_PLUGINS: dict[tuple[str, str], Any] = {}


class PluginError(Exception):
    pass


def plugin_path(merged: Any) -> Path:
    return merged.tenant.path.parent / merged.tenant.code / "compat.py"


def load_plugin(merged: Any) -> Any | None:
    """`tenants/<code>/compat.py` → 모듈(없으면 None). 등록부 폴더 밖(심볼릭 링크 포함)은 거부."""
    p = plugin_path(merged)
    if not p.is_file():
        return None
    base = merged.tenant.path.parent.resolve()
    real = p.resolve()
    if base not in real.parents:
        raise PluginError(f"호환 플러그인이 회사 등록부 폴더 밖입니다: {p.name}")
    data = real.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    key = (str(real), sha)
    if key not in _PLUGINS:
        name = f"mlp_compat_{sha[:16]}"
        spec = importlib.util.spec_from_file_location(name, real)
        mod = importlib.util.module_from_spec(spec)
        try:
            sys.modules[name] = mod
            spec.loader.exec_module(mod)          # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001 — 숨기지 않는다
            sys.modules.pop(name, None)
            raise PluginError(f"호환 플러그인을 읽을 수 없습니다: {type(e).__name__}: {str(e)[:200]}") from None
        _PLUGINS[key] = mod
    return _PLUGINS[key]


# ── 동작 실행 ─────────────────────────────────────────────────────────────────────────
@dataclass
class Raw:
    """동작이 JSON 이 아닌 본문(CSV · DXF)을 돌려줄 때."""
    data: bytes
    media_type: str
    filename: str | None = None


class Phase2:
    """한 회사의 객체 경로. cmp = serve.compat.Compat(1차 장치 — rename · 회사 설정 · 묶음 동작을 같이 쓴다)."""

    def __init__(self, cmp: Any):
        from . import CompatError
        self.cmp = cmp
        self.CompatError = CompatError
        self.catalog, self.merged = cmp.catalog, cmp.merged
        self.tenant = cmp.catalog.tenant_id
        self.routes = parse_routes(cmp.routes())

    # 플러그인 호출 — 플러그인이 올린 CompatError · ServeError 는 그대로, 그 밖은 PluginError
    def _call(self, name: str, *args):
        mod = load_plugin(self.merged)
        fn = getattr(mod, name, None) if mod is not None else None
        if fn is None:
            return False, None
        try:
            return True, fn(*args)
        except (self.CompatError, ServeError):
            raise
        except Exception as e:  # noqa: BLE001
            raise PluginError(f"호환 플러그인 {name} 실패: {type(e).__name__}: {str(e)[:200]}") from None

    def parse(self, route: Route, body: Any, info: dict) -> Any:
        found, out = self._call(f"parse_{route.shape or route.action}", body, info)
        return out if found else body

    def _frame_hook(self, info: dict):
        """플러그인 `records_frame(frame, n_all, info) -> frame`(있으면) — 옛 행 상태 열 · 옛 필터(D2-A2-05)."""
        mod = load_plugin(self.merged)
        if mod is None or not callable(getattr(mod, "records_frame", None)):
            return None

        def hook(df, n_all):
            import pandas as pd
            _, out = self._call("records_frame", df, n_all, info)
            if not isinstance(out, pd.DataFrame):
                raise PluginError("호환 플러그인 records_frame 은 프레임을 돌려줘야 합니다")
            return out
        return hook

    def shape(self, route: Route, result: Any, info: dict) -> Any:
        found, out = self._call(f"shape_{route.shape or route.action}", result, info)
        return out if found else result

    def shape_error(self, status: int, body: Any, info: dict) -> tuple[int, Any]:
        found, out = self._call("shape_error", status, body, info)
        if found and isinstance(out, tuple) and len(out) == 2:
            return int(out[0]), out[1]
        return status, body

    def spec(self, route: Route):
        short = route.task
        if short is None:                       # samples 만 — 묶음 회귀 과제
            return self.cmp._need("regression")
        from ..errors import NotFound
        tid = f"{self.tenant}.{short}"
        if tid not in self.catalog.ids():
            if tid in (getattr(self.merged, "disabled", None) or {}):
                raise self.CompatError(503, {"detail": "이 과제는 꺼져 있어 쓸 수 없습니다", "code": "model_not_ready"})
            raise self.CompatError(404, {"detail": "이 회사에는 해당 과제가 켜져 있지 않습니다"})
        s = self.catalog.get(self.tenant, tid)
        want = ACTIONS[route.action][2]
        if want is not None and s.task.type not in want:
            raise NotFound("이 과제는 이 동작의 유형이 아닙니다", {"rule": "type_route", "field": None})
        return s

    def _rename_inputs(self, inputs: Any) -> Any:
        if not isinstance(inputs, dict):
            return inputs
        return {self.cmp.rename.get(k, k): v for k, v in inputs.items()}

    def run(self, route: Route, args: dict, *, query: dict, body: bytes, content_type: str, caller: str) -> Any:
        info = {"tenant": self.tenant, "action": route.action, "method": route.method, "path": route.path,
                "args": dict(args), "query": dict(query), "task": route.task, "params": dict(route.params)}
        act = route.action
        cmp = self.cmp
        if act in ("health", "overview", "predict", "optimize", "records", "record"):
            from . import parse_body
            if act == "health":
                res = cmp.health()
            elif act == "overview":
                # 옛 지표 소수 자리 — 플러그인 상수 OVERVIEW_METRIC_DIGITS(원천 ml_service 의 round 자리, 없으면 1차 그대로 3)
                mod = load_plugin(self.merged)
                digits = getattr(mod, "OVERVIEW_METRIC_DIGITS", None) if mod is not None else None
                res = cmp.overview(metric_digits=digits if isinstance(digits, int) and 0 <= digits <= 8 else 3)
            elif act == "predict":
                res = cmp.predict(self.parse(route, parse_body(body), info), caller=caller)
            elif act == "optimize":
                res = cmp.optimize(self.parse(route, parse_body(body), info), caller=caller)
            elif act == "records":
                q = self.parse(route, dict(query), info)            # parse_records(query, info) — 옛 쿼리 → 표준 쿼리
                if not isinstance(q, dict):
                    raise PluginError("호환 플러그인 parse_records 는 쿼리 dict 를 돌려줘야 합니다")
                res = cmp.records(q, frame_hook=self._frame_hook(info))
            else:
                res = cmp.record(next(iter(args.values()), ""))
            return self.shape(route, res, info)
        if act == "pack_file":
            return self.shape(route, self._pack_file(route, args), info)
        spec = self.spec(route)
        handler = getattr(self, f"_{act}")
        res = handler(spec, route, args, query, body, content_type, caller, info)
        return self.shape(route, res, info)

    # ── 동작별 ─────────────────────────────────────────────────────────────────
    def _predict_one(self, spec, route, args, query, body, ctype, caller, info):
        from ..predict import PredictRequest, Predictor
        from . import old_422, parse_body
        old = self.parse(route, parse_body(body), info)
        if isinstance(old, dict) and "inputs" in old and set(old) <= {"inputs", "entity_id"}:
            std_body = old                                      # 플러그인이 이미 표준 본문으로 바꿨다
        else:
            std_body = {"inputs": self.cmp._to_inputs(old, spec)}
        try:
            return Predictor(self.catalog, self.cmp.registry).predict(
                self.tenant, spec.task.id,
                PredictRequest(inputs=std_body["inputs"], entity_id=std_body.get("entity_id")),
                caller=caller, channel="compat")
        except ServeError as e:
            if e.status == 422:
                raise old_422(e, self.cmp.back) from None
            raise

    def _int(self, query: dict, name: str, default: int, lo: int, hi: int | None) -> int:
        v = query.get(name)
        if v is None:
            return default
        try:
            x = int(v)
        except ValueError:
            raise self.CompatError(422, {"detail": [{"loc": ["query", name], "msg": "정수여야 합니다",
                                                     "type": "int_parsing"}]}) from None
        if x < lo or (hi is not None and x > hi):
            raise self.CompatError(422, {"detail": [{"loc": ["query", name], "msg": "범위 밖입니다", "type": "range"}]})
        return x

    def _samples(self, spec, route, args, query, body, ctype, caller, info):
        from ...api.routers.ops import _frame
        p = route.params
        limit = self._int(query, "limit", int(p.get("limit", 12)), 1, int(p.get("max_limit", 100)))
        offset = self._int(query, "offset", 0, 0, None)
        frame = _frame(self.merged, self.merged.tasks[spec.task.id])
        rows = []
        key = self.cmp._target_key(spec)
        for _, r in frame.iloc[offset:offset + limit].iterrows():
            row = {self.cmp.back.get(f.name, f.name): _plain(r.get(f.name)) for f in spec.defs}
            if "target" in frame.columns:
                row[key] = _plain(r.get("target"))
            row["lot_id"] = self.cmp.lot_id(str(r["entity_id"]))
            rows.append(row)
        return {"total": int(len(frame)), "offset": offset, "limit": limit, "items": rows}

    def _review_list(self, spec, route, args, query, body, ctype, caller, info):
        from .. import review
        p = route.params
        limit = self._int(query, "limit", int(p.get("limit", 12)), 1, int(p.get("max_limit", 50)))
        state = query.get("state", p.get("state", "open"))
        if state not in (None, "open", "confirmed_issue", "false_alarm"):
            raise self.CompatError(422, {"detail": [{"loc": ["query", "state"], "msg": "허용된 값이 아닙니다",
                                                     "type": "literal_error"}]})
        out = review.list_items(self.tenant, spec.task.id, state=state, limit=limit, cursor=None)
        out["rule"] = dict(spec.task.raw.get("rule") or {})
        return out

    def _upload(self, spec, filename: str | None, raw: bytes, unit: str | None, caller: str) -> dict:
        from .. import documents
        limits = documents.limits_for(spec.task.raw)
        name = documents.clean_filename(filename)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in [f.lower() for f in limits["formats"]]:     # 옛 서비스는 확장자 오류를 415 로 냈다(api-contract §6.1)
            raise self.CompatError(415, {"detail": "DXF 파일만 받습니다"})
        return documents.upload(spec, self.catalog, filename=name, raw=raw, unit_override=unit, actor=caller)

    def _document_upload(self, spec, route, args, query, body, ctype, caller, info):
        from ...api.routers.phase2 import _multipart
        from .. import documents
        limits = documents.limits_for(spec.task.raw)
        if len(body) > limits["max_bytes"] + 64 * 1024:
            raise documents.DocumentTooLarge("업로드가 허용 상한을 넘습니다", {"rule": "bytes", "field": "file"})
        form = _multipart(ctype, body)
        f = form.get(route.params.get("file_field", "file"))
        if f is None or f["filename"] is None:
            raise documents.InvalidDocument("file 칸이 없습니다", {"rule": "format", "field": "file"})
        unit = form.get("unit_override")
        unit_override = unit["data"].decode("utf-8", "replace").strip() if unit else None
        if unit_override is None and query.get("unit_override"):
            unit_override = query["unit_override"]
        return self._upload(spec, f["filename"], f["data"], unit_override or None, caller)

    def _sample_file(self, name: Any) -> Path:
        """예시 파일 — 회사 폴더 `tenants/<code>/samples/` 가 먼저(회사 값이 든 샘플 — 회사 재질 · 회사 참조 데이터, D2-A2-04),
        없으면 팩 `samples/`. 두 폴더 밖(경로 탈출 · 심볼릭 링크)은 404."""
        if not isinstance(name, str) or not SAFE_FILE.match(name) or ".." in name:
            raise self.CompatError(404, {"detail": "파일을 찾을 수 없습니다"})
        tbase = self.merged.tenant.path.parent
        for base in (tbase / self.merged.tenant.code / "samples", self.merged.pack.path / "samples"):
            base = base.resolve()
            p = (base / name).resolve()
            if base in p.parents and p.is_file():
                return p
        raise self.CompatError(404, {"detail": "파일을 찾을 수 없습니다"})

    def _document_demo(self, spec, route, args, query, body, ctype, caller, info):
        p = self._sample_file(route.params.get("file"))
        return self._upload(spec, p.name, p.read_bytes(), route.params.get("unit_override"), caller)

    def _document_get(self, spec, route, args, query, body, ctype, caller, info):
        from .. import documents
        return documents.get(self.tenant, spec.task.id, next(iter(args.values()), ""))

    def _pack_file(self, route: Route, args: dict) -> Any:
        name = args.get("file", route.params.get("file"))
        p = self._sample_file(name)
        if p.suffix.lower() == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        media = route.params.get("media_type") or {".dxf": "application/dxf", ".csv": "text/csv; charset=utf-8"}.get(
            p.suffix.lower(), "application/octet-stream")
        return Raw(p.read_bytes(), media, p.name)

    def _qc(self, spec):
        from .. import quotes
        return quotes.QuoteContext(spec, self.catalog)

    def _quote_create(self, spec, route, args, query, body, ctype, caller, info):
        from .. import quotes
        from ..jsonout import loads
        try:
            old = loads(body or b"{}")
        except (ValueError, RecursionError):
            raise self.CompatError(422, {"detail": [{"loc": ["body"], "msg": "JSON 형식이 아닙니다",
                                                     "type": "json_invalid"}]}) from None
        from . import check_nul
        check_nul(old)                                                   # NUL → 옛 422 (D2-111)
        std = self.parse(route, old, info)
        if isinstance(std, dict) and isinstance(std.get("inputs"), dict):
            std = {**std, "inputs": self._rename_inputs(std["inputs"])}
        from . import old_422
        try:
            return quotes.create(self._qc(spec), std, actor=caller)    # 초안(draft)만 — 확정은 표준 경로 · 승인으로만
        except ServeError as e:
            if e.status == 422:
                raise old_422(e, self.cmp.back) from None
            raise

    def _all_quotes(self, spec, search: str | None) -> list[dict]:
        from .. import quotes
        items, cursor = [], None
        while len(items) < LIST_CAP:
            page = quotes.list_quotes(self.tenant, spec.task.id, spec.notice, search=search, limit=100, cursor=cursor)
            items += page["items"]
            cursor = page["next_cursor"]
            if not cursor:
                break
        return items[:LIST_CAP]

    def _quote_list(self, spec, route, args, query, body, ctype, caller, info):
        p = route.params
        limit = self._int(query, "limit", int(p.get("limit", 10)), 1, int(p.get("max_limit", 100)))
        offset = self._int(query, "offset", 0, 0, None)
        search = query.get("search")
        if search is not None and len(search) > int(p.get("search_max", 80)):
            raise self.CompatError(422, {"detail": [{"loc": ["query", "search"], "msg": "너무 깁니다",
                                                     "type": "string_too_long"}]})
        items = self._all_quotes(spec, search or None)
        return {"total": len(items), "offset": offset, "limit": limit, "records": items[offset:offset + limit]}

    def _quote_get(self, spec, route, args, query, body, ctype, caller, info):
        from .. import quotes
        return quotes.get(self.tenant, spec.task.id, next(iter(args.values()), ""), spec.notice)

    def _quote_csv(self, spec, route, args, query, body, ctype, caller, info):
        from .. import quotes
        q = quotes.get(self.tenant, spec.task.id, next(iter(args.values()), ""), spec.notice)
        data = quotes.to_csv(q, list(spec.task.raw.get("csv") or []) or None)
        safe = re.sub(r"[^A-Za-z0-9_]", "", q["quote_id"])
        return Raw(data, "text/csv; charset=utf-8", f"{safe}.csv")

    def _quote_export_csv(self, spec, route, args, query, body, ctype, caller, info):
        from .. import quotes
        cols = list(route.params.get("columns") or ["quote_id", "status", "revision", "total", "currency", "doc_id",
                                                    "review_note", "created_at"])
        items = self._all_quotes(spec, query.get("search") or None)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow([quotes.safe_cell(c) for c in cols])
        for q in items:
            w.writerow([quotes.safe_cell(_cell(q, c)) for c in cols])
        return Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "quotes.csv")


def _cell(q: dict, col: str) -> Any:
    cur: Any = q
    for part in col.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _plain(v: Any) -> Any:
    try:
        import pandas as pd
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return v.item()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v
