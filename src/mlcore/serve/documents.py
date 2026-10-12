"""문서 · 도면 추출 서비스 — B10 `/documents*` (api-contract §6 · predict-contract §8.2 · task-contract §6.2). 소유 개발2.

순서 (source_inventory §10.5 · §11.5 의 원천 판정 순서를 표준 오류 계약으로):
  1. 파일 이름 — 경로를 떼고 150자. 확장자가 과제 `document.formats`(dxf) 가 아니면 422 invalid_document(rule format)
  2. 크기 — 과제 상한(≤ 5 MiB) 초과 413 document_too_large(rule bytes). API 는 스트림을 상한 + 1 까지만 읽는다
  3. 코어 DXF 읽개(`tasks.dxf.read`) — 바이너리 · 파싱 422, 엔티티 상한 413(rule entities)
  4. 단위 — 헤더 `$INSUNITS` 우선, 없으면 `unit_override`, 둘 다 없으면 422(rule unit)
  5. 원본 저장 `var/documents/<tenant>/<raw_sha256>.dxf`(D2-05, 커밋 금지 — .gitignore var/) — 같은 내용은 한 파일
  6. 추출기 플러그인(과제 `extractors` 순서) — model 추출기는 그 과제의 production 산출물만(없으면 503 model_not_ready)
  7. 결과 합침 → `mlp_document` 1행 · 응답 DocumentExtraction(라벨 없으면 metrics null — 지표를 만들지 않는다)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

from ..db.conn import connect
from ..settings import ROOT
from ..tasks import dxf
from ..tasks.extract import ExtractError, check_result, limits_for, load_extractor, merge_results, run_isolated
from .errors import NotFound, ServeError
from .ids import new_id

KST = timezone(timedelta(hours=9))
FILENAME_MAX = 150
DOC_ID = re.compile(r"^doc_[0-9A-Z]{26}$")


class InvalidDocument(ServeError):
    status, code, default_message = 422, "invalid_document", "읽을 수 없는 도면입니다"


class DocumentTooLarge(ServeError):
    status, code, default_message = 413, "document_too_large", "도면이 허용 상한을 넘습니다"


def as_serve_error(e: dxf.DocumentError) -> ServeError:
    cls = DocumentTooLarge if e.code == "document_too_large" else InvalidDocument
    return cls(e.message if e.message not in (e.code, "") else None, {"rule": e.rule, "field": "file"})


def doc_dir() -> Path:
    return Path(os.environ.get("MLP_DOCUMENT_DIR") or ROOT / "var" / "documents")


def clean_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1].strip().replace("\x00", "")
    return base[:FILENAME_MAX] or "upload.dxf"


def _iso(ts) -> str | None:
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


def check_type(spec: Any, want: str) -> None:
    if spec.task.type != want:
        raise NotFound(f"이 과제는 {want} 유형이 아닙니다", {"rule": "type_route", "field": None})


def _model_for(tenant_id: str, task_id: str, catalog: Any):
    """model 추출기 산출물 — 그 extract 과제의 production(해시 대조). 없으면 ModelNotReady(503) 그대로."""
    from ..registry.artifacts import load_artifacts
    from ..registry.models import Registry
    ref = Registry().get(tenant_id, task_id)
    catalog.require_servable(tenant_id, task_id, ref)
    return ref, load_artifacts(ref)


def extract_context(merged: Any) -> dict:
    """추출기에 넘기는 회사 값 (progress-dev3 2차 §1 · D2-37 요청). 코어는 뜻을 모르고 등록부 값을 그대로 넘긴다:
    `categories`(회사 범주 목록) · `material_aliases`(별칭 대문자 → 정규 값). 추출기별 `params`(과제 extractors[].params —
    임계값 · 허용차 · 팩 고유 상한 같은 YAML 값, 코드 상수 금지) · `previous`(앞 추출기까지 합친 결과 — 규칙 → 모델 순서 연결)는
    부를 때마다 더한다."""
    from ..registry.tenants import material_aliases
    cats = {str(k): [str(v) for v in (vals or [])] for k, vals in (merged.tenant.config.get("categories") or {}).items()}
    return {"categories": cats, "material_aliases": material_aliases(merged)}


def call_extractor(mod: Any, raw: bytes, name: str, *, unit: str, limits: dict, model: Any, context: dict) -> dict:
    """`context=` 를 받는 추출기(키워드 인자 context 또는 **kwargs)에만 넘긴다 — 1차 공표 모양(context 없음)도 그대로 돈다."""
    import inspect
    try:
        params = inspect.signature(mod.extract).parameters
        takes = "context" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        takes = False
    if takes:
        return mod.extract(raw, name, unit=unit, limits=limits, model=model, context=context)
    return mod.extract(raw, name, unit=unit, limits=limits, model=model)


def upload(spec: Any, catalog: Any, *, filename: str | None, raw: bytes, unit_override: str | None,
           actor: str) -> dict:
    check_type(spec, "extract")
    task = spec.task
    limits = limits_for(task.raw)
    name = clean_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in [f.lower() for f in limits["formats"]]:
        raise InvalidDocument("DXF 파일만 받습니다", {"rule": "format", "field": "file"})
    if len(raw) > limits["max_bytes"]:
        raise DocumentTooLarge(f"파일이 {limits['max_bytes']:,} 바이트를 넘습니다", {"rule": "bytes", "field": "file"})
    if unit_override is not None and unit_override not in limits["unit_override"]:
        raise InvalidDocument("unit_override 는 mm · inch 만 받습니다", {"rule": "unit", "field": "unit_override"})
    try:
        doc = dxf.read(raw, max_entities=limits["max_entities"])
        unit = dxf.resolve_unit(doc, unit_override)
    except dxf.DocumentError as e:
        raise as_serve_error(e) from None
    sha = hashlib.sha256(raw).hexdigest()
    # 추출 — 원본을 저장하기 전에 한다(거부된 문서는 남기지 않는다). 추출기는 자식 프로세스에서 시간 · 결과 상한 안에서만 돈다
    # (tasks.extract.run_isolated — DEF-QA22-001 · #30 코어 · D2-91). model 산출물(등록부 production)은 여기서 읽어 넘긴다.
    plugin_limits = {"max_bytes": limits["max_bytes"], "max_entities": limits["max_entities"],
                     "unit_override": unit_override}
    base_ctx = extract_context(catalog.merged)
    jobs, mods, used = [], [], []
    for es in task.raw.get("extractors") or []:
        mod = load_extractor(catalog.merged.pack.path, es)
        model, model_version = None, None
        if mod.KIND == "model":
            ref, model = _model_for(spec.tenant_id, task.id, catalog)
            model_version = ref.version
        jobs.append((dict(es), model, {**base_ctx, "params": dict(es.get("params") or {})}))
        mods.append(mod)
        used.append({"name": mod.NAME, "version": str(mod.VERSION), "kind": mod.KIND, "model_version": model_version})
    try:
        results = run_isolated(catalog.merged.pack.path, jobs, raw, name, unit=unit, plugin_limits=plugin_limits,
                               limits=limits)
        parts = list(zip(mods, results))
        check_result(merge_results(parts), limits, "merged")
    except dxf.DocumentError as e:                             # ExtractError 포함
        raise as_serve_error(e) from None
    merged = merge_results(parts)
    labels = task.raw.get("labels") or "none"
    path = doc_dir() / spec.tenant_id / f"{sha}.dxf"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.is_file()
    if created:
        tmp = path.with_suffix(".part")
        tmp.write_bytes(raw)
        tmp.replace(path)
    try:
        raw_path = str(path.resolve().relative_to(ROOT))
    except ValueError:
        raw_path = str(path)
    doc_id = new_id("doc")
    body = {
        "doc_id": doc_id, "task": task.id, "filename": name, "raw_sha256": sha, "unit": "mm",
        "entity_count": doc.entity_count, "regions": merged["regions"], "objects": merged["objects"],
        "bom_rows": merged["bom_rows"], "counts": merged["counts"], "dimensions": merged["dimensions"],
        "confidence": merged["confidence"], "labels": labels, "metrics": None,      # 정답 없는 도면 — 지표를 만들지 않는다
        "extractor": used, "warnings": merged["warnings"], "created_at": None,
    }
    try:
        with connect() as c:
            row = c.execute(
                "INSERT INTO mlp_document (doc_id, tenant_id, task_id, filename, raw_sha256, raw_path, result, extractor_name, "
                "extractor_version, created_by, size_bytes, entity_count, labels) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s) RETURNING created_at",
                (doc_id, spec.tenant_id, task.id, name, sha, raw_path, json.dumps(body, ensure_ascii=False),
                 ",".join(u["name"] for u in used), ",".join(u["version"] for u in used), actor, len(raw),
                 doc.entity_count, labels)).fetchone()
    except BaseException:
        if created:                                            # 행이 없으면 원본도 남기지 않는다(원자적 정리 — DEF-QA22-004)
            path.unlink(missing_ok=True)
        raise
    body["created_at"] = _iso(row["created_at"])
    return body


def _view(row: dict) -> dict:
    body = dict(row["result"] or {})
    body["created_at"] = _iso(row["created_at"])
    if body.get("labels") == "none":
        body["metrics"] = None
    return body


def get(tenant_id: str, task_id: str, doc_id: str) -> dict:
    if not DOC_ID.match(doc_id or ""):
        raise NotFound("문서를 찾을 수 없습니다")
    with connect() as c:
        row = c.execute("SELECT result, created_at FROM mlp_document WHERE tenant_id=%s AND task_id=%s AND doc_id=%s",
                        (tenant_id, task_id, doc_id)).fetchone()
    if not row:
        raise NotFound("문서를 찾을 수 없습니다")
    return _view(row)


def result_of(tenant_id: str, doc_id: str) -> dict | None:
    """견적이 인식값을 읽을 때 — 과제 무관(회사 범위만)."""
    with connect() as c:
        row = c.execute("SELECT task_id, result, created_at FROM mlp_document WHERE tenant_id=%s AND doc_id=%s",
                        (tenant_id, doc_id)).fetchone()
    return None if not row else {"task_id": row["task_id"], **_view(row)}


SUMMARY_KEYS = ("doc_id", "task", "filename", "raw_sha256", "unit", "entity_count", "counts", "labels", "confidence",
                "extractor", "warnings", "created_at")


def list_docs(tenant_id: str, task_id: str, *, search: str | None, limit: int, cursor: str | None) -> dict:
    sql = "SELECT doc_id, result, created_at FROM mlp_document WHERE tenant_id=%s AND task_id=%s"
    params: list = [tenant_id, task_id]
    if search:
        sql += " AND (filename ILIKE %s OR doc_id ILIKE %s OR raw_sha256 ILIKE %s)"
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like, like]
    count_sql, count_params = sql.replace("SELECT doc_id, result, created_at", "SELECT count(*) AS n"), list(params)
    if cursor:
        sql += " AND doc_id < %s"
        params.append(cursor)
    sql += " ORDER BY doc_id DESC LIMIT %s"
    params.append(limit + 1)
    with connect() as c:
        rows = c.execute(sql, params).fetchall()
        total = c.execute(count_sql, count_params).fetchone()["n"]
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{k: v for k, v in _view(r).items() if k in SUMMARY_KEYS} for r in rows]
    return {"items": items, "next_cursor": rows[-1]["doc_id"] if more and rows else None, "total": total}
