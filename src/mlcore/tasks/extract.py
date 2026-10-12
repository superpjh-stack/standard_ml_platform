"""`extract` 유형 — 추출기 플러그인 프로토콜 · 로더 · 결과 합침 (task-contract §6.2 · progress-dev2 2차 §1.1). 소유 개발2.

코어는 도면의 뜻을 모른다: 영역 · 객체 · BOM 을 만드는 것은 팩 `extractors/<name>.py` 다. 코어는
(1) 과제 `document` 상한을 spec 상한 아래로 정하고 (2) 플러그인을 과제 정의 순서대로 부르고 (3) 결과를 계약 키로 합친다.
`model` 추출기는 그 extract 과제의 등록부 production 산출물만 받는다(호출자가 넘긴다 — 여기서 학습하지 않는다).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Literal, Protocol

from .dxf import DocumentError

__all__ = ["Extractor", "ExtractError", "limits_for", "load_extractor", "merge_results", "run_isolated", "check_result",
           "SPEC_LIMITS", "OUTPUT_KEYS"]

# spec §8.3 상한 + 결과 상한(재진입 C2 — DEF-QA22-001 · #30 코어 · D2-91): 결과 JSON 바이트 · 출력 배열(regions · objects ·
# bom_rows)당 항목 수 · 추출기 전체 실행 시간(초). 정본 = task-contract §4 `document_limits`. 팩 · 회사는 낮추기만
SPEC_LIMITS = {"max_bytes": 5 * 1024 * 1024, "max_entities": 20000, "max_result_bytes": 4 * 1024 * 1024,
               "max_items": 5000, "max_seconds": 20}
OUTPUT_KEYS = ("regions", "objects", "bom_rows")
REPLACEABLE = OUTPUT_KEYS + ("counts", "dimensions")     # 결과 `replaces` 로 앞 결과를 바꿀 수 있는 키


class ExtractError(DocumentError):
    """추출기가 올리는 문서 오류 — code invalid_document(422) | document_too_large(413), rule 은 api-contract §6.1."""


class Extractor(Protocol):
    NAME: str
    VERSION: str
    KIND: Literal["rule", "model"]

    def extract(self, raw: bytes, filename: str, *, unit: str, limits: dict, model: Any = None,
                context: dict | None = None) -> dict: ...
    # context(선택 인자 — 받는 추출기에만 넘긴다): {categories, material_aliases, params, previous}
    #   params   = 과제 extractors[].params (팩 YAML 값 — 임계값 · 허용차 · 팩 고유 상한, 코드 상수 금지)
    #   previous = 앞 추출기까지 합친 결과(None = 첫 추출기). 규칙 추출기가 찾은 객체를 모델 추출기가 분류할 때 쓴다.
    # 결과 키 `replaces: ["objects", …]` 가 있으면 합칠 때 그 배열을 이어 붙이지 않고 이 결과로 바꾼다(앞 결과를 다듬은 경우).


def limits_for(task_raw: dict) -> dict:
    """과제 document 상한(낮추기만) → {max_bytes, max_entities, max_result_bytes, max_items, max_seconds, unit_override,
    formats}. 실행 시간은 환경 `MLP_EXTRACT_MAX_SECONDS` 로도 낮출 수 있다(올릴 수 없다 — 운영 · 시험)."""
    import os
    doc = task_raw.get("document") or {}
    out = {}
    for k, cap in SPEC_LIMITS.items():
        v = doc.get(k)
        out[k] = min(int(v), cap) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else cap
    env = os.environ.get("MLP_EXTRACT_MAX_SECONDS", "")
    if env.strip().isdigit() and int(env) > 0:
        out["max_seconds"] = min(out["max_seconds"], int(env))
    out["unit_override"] = [u for u in (doc.get("unit_override") or ["mm", "inch"]) if u in ("mm", "inch")]
    out["formats"] = list(doc.get("formats") or ["dxf"])
    return out


_CACHE: dict[tuple[str, str], Any] = {}


def load_extractor(pack_path: Path, spec: dict) -> Any:
    """`extractors/<name>.py` → 모듈(NAME · VERSION · KIND · extract). 같은 파일 · 같은 내용이면 한 번만 import."""
    path = (Path(pack_path) / str(spec["module"])).resolve()
    if not path.is_file() or Path(pack_path).resolve() not in path.parents:
        raise FileNotFoundError(f"추출기 모듈 없음: {spec.get('module')}")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    key = (str(path), sha)
    if key not in _CACHE:
        name = f"mlp_extractor_{sha[:16]}_{path.stem}"
        mod_spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(mod_spec)
        sys.modules[name] = mod
        mod_spec.loader.exec_module(mod)
        for attr in ("NAME", "VERSION", "KIND", "extract"):
            if not hasattr(mod, attr):
                raise TypeError(f"추출기 {path.stem} 에 {attr} 가 없습니다")
        if mod.KIND not in ("rule", "model"):
            raise TypeError(f"추출기 {path.stem} KIND {mod.KIND!r}")
        _CACHE[key] = mod
    return _CACHE[key]


def merge_results(parts: list[tuple[Any, dict]]) -> dict:
    """[(추출기 모듈, 결과)] → 합친 결과. 배열 이어 붙임(결과 `replaces` 에 든 배열은 바꿈) · counts 키별 합 · dimensions 처음 non-null ·
    confidence = model 추출기 값 평균(규칙만이면 None) · warnings 이어 붙임."""
    out: dict[str, Any] = {k: [] for k in OUTPUT_KEYS}
    out.update(counts={}, dimensions=None, confidence=None, warnings=[])
    scores: list[float] = []
    for mod, res in parts:
        if not isinstance(res, dict):
            raise TypeError(f"추출기 {getattr(mod, 'NAME', '?')} 결과가 dict 가 아닙니다")
        replaces = res.get("replaces") or []
        if not isinstance(replaces, list) or any(k not in REPLACEABLE for k in replaces):
            raise TypeError(f"추출기 {getattr(mod, 'NAME', '?')} 의 replaces 는 {list(REPLACEABLE)} 중 이름 목록입니다")
        if "counts" in replaces:
            out["counts"] = {}
        if "dimensions" in replaces:
            out["dimensions"] = None
        for k in OUTPUT_KEYS:
            vals = res.get(k) or []
            if not isinstance(vals, list):
                raise TypeError(f"추출기 {mod.NAME} 의 {k} 가 배열이 아닙니다")
            if k in replaces:
                out[k] = list(vals)
            else:
                out[k].extend(vals)
        for k, v in (res.get("counts") or {}).items():
            out["counts"][str(k)] = int(out["counts"].get(str(k), 0)) + int(v)
        if out["dimensions"] is None and res.get("dimensions") is not None:
            out["dimensions"] = dict(res["dimensions"])
        if mod.KIND == "model" and res.get("confidence") is not None:
            scores.append(float(res["confidence"]))
        out["warnings"].extend(str(w) for w in (res.get("warnings") or []))
    if scores:
        out["confidence"] = round(sum(scores) / len(scores), 6)
    return out


# ── 격리 실행 · 결과 상한 (재진입 C2 — DEF-QA22-001 · #30 코어 · D2-91) ───────────────────────────────────
# 추출기는 팩 코드다. 상한 안 도면이라도 알고리즘에 따라 시간 · 메모리가 크게 늘 수 있어(QA2: 1.24 MB 도면 174 s · 2.26 GB)
# 코어가 실행을 **자식 프로세스**(forkserver — 스레드 없는 서버에서 fork)로 떼어 시간 상한을 넘기면 죽이고 413(rule time),
# 결과는 자식 안에서 배열 항목 수 · JSON 바이트를 재고 넘으면 413(rule items · result_bytes) — 큰 결과를 넘겨받지 않는다.
_MP_CTX = None


def _ctx():
    global _MP_CTX
    if _MP_CTX is None:
        import multiprocessing as mp
        ctx = mp.get_context("forkserver")
        ctx.set_forkserver_preload(["mlcore.tasks.extract", "mlcore.tasks.dxf", "mlcore.serve.documents", "joblib", "sklearn.pipeline",
                                    "sklearn.linear_model", "sklearn.ensemble", "sklearn.preprocessing"])
        _MP_CTX = ctx
    return _MP_CTX


def _has_nul(v, depth: int = 0) -> bool:
    if isinstance(v, str):
        return "\x00" in v
    if depth > 50:
        return False
    if isinstance(v, dict):
        return any(_has_nul(k, depth + 1) or _has_nul(x, depth + 1) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return any(_has_nul(x, depth + 1) for x in v)
    return False


def check_result(res: dict, limits: dict, name: str = "?") -> None:
    """한 추출기 결과의 상한 — 출력 배열마다 max_items, 결과 JSON(UTF-8) max_result_bytes, NUL 문자 0(jsonb 가 받지 않는다)."""
    import json
    if not isinstance(res, dict):
        raise TypeError(f"추출기 {name} 결과가 dict 가 아닙니다")
    for k in OUTPUT_KEYS:
        vals = res.get(k)
        if isinstance(vals, list) and len(vals) > limits["max_items"]:
            raise ExtractError("document_too_large", "items", f"추출 결과 {k} 가 {limits['max_items']:,}개를 넘습니다")
    text = json.dumps(res, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) > limits["max_result_bytes"]:
        raise ExtractError("document_too_large", "result_bytes",
                           f"추출 결과가 {limits['max_result_bytes']:,} 바이트를 넘습니다")
    if _has_nul(res):
        raise ExtractError("invalid_document", "nul", "도면 텍스트에 NUL 문자가 있습니다")


def _child(conn, pack_path: str, jobs: list, raw: bytes, name: str, unit: str, plugin_limits: dict, limits: dict) -> None:
    """자식 프로세스 — 추출기를 순서대로(앞 결과 previous 연결) 부르고 결과마다 상한을 잰다. → ("ok", [결과]) | ("doc", code, rule, msg)
    | ("error", 형식, 문구)."""
    try:
        from ..serve.documents import call_extractor
        results: list = []
        mods: list = []
        for es, model, ctx in jobs:
            mod = load_extractor(Path(pack_path), es)
            ctx = {**ctx, "previous": merge_results(list(zip(mods, results))) if results else None}
            try:
                res = call_extractor(mod, raw, name, unit=unit, limits=dict(plugin_limits), model=model, context=ctx)
            except ValueError as e:
                code = getattr(e, "code", None)
                if code in ("invalid_document", "document_too_large"):
                    conn.send(("doc", code, getattr(e, "rule", "parse"), getattr(e, "message", None) or str(e)))
                    return
                raise
            check_result(res, limits, getattr(mod, "NAME", "?"))
            mods.append(mod)
            results.append(res)
        conn.send(("ok", results))
    except DocumentError as e:
        conn.send(("doc", e.code, e.rule, e.message))
    except BaseException as e:                                   # noqa: BLE001 — 부모가 500 으로 그대로 보인다
        conn.send(("error", type(e).__name__, str(e)[:500]))
    finally:
        conn.close()


def run_isolated(pack_path: Path, jobs: list, raw: bytes, name: str, *, unit: str, plugin_limits: dict,
                 limits: dict) -> list[dict]:
    """jobs = [(추출기 spec, model 산출물 | None, context)] → 추출기별 결과 목록(순서 그대로).
    시간 상한 초과 · 자식 비정상 종료 → ExtractError(document_too_large, time | resources). 추출기 결함 → RuntimeError(500)."""
    ctx = _ctx()
    recv, send = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_child, args=(send, str(pack_path), jobs, raw, name, unit, plugin_limits, limits), daemon=True)
    p.start()
    send.close()
    try:
        if not recv.poll(limits["max_seconds"]):
            raise ExtractError("document_too_large", "time", f"추출이 {limits['max_seconds']}초 안에 끝나지 않았습니다")
        try:
            msg = recv.recv()
        except EOFError:
            raise ExtractError("document_too_large", "resources", "추출 프로세스가 끝까지 돌지 못했습니다(자원 한도)") from None
    finally:
        if p.is_alive():
            p.kill()
        p.join(5)
        recv.close()
    if msg[0] == "ok":
        return msg[1]
    if msg[0] == "doc":
        raise ExtractError(msg[1], msg[2], msg[3])
    raise RuntimeError(f"추출기 실행 실패: {msg[1]}: {msg[2]}")
