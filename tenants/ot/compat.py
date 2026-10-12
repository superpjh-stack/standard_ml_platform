"""ot 호환 모양 플러그인 — 옛 경로 응답 키 (api-contract §5 · §6.3 · predict-contract §7.1). 소유 개발2.

원천 `../OneTouch ML AI/api/{main,quote,cad,storage,ml_service}.py` 를 **읽어** 옛 응답 모양만 옮겼다(원천 실행 0).
계산 · 저장 · 승인은 표준 서비스 그대로다 — 금액은 표준 Decimal 견적식(팩 rollform-quote) 결과, 인식은 팩 추출기(기하 규칙 +
객체 분류 모델), 사람 수정 이력은 표준 overrides(옛 키 이름으로만 바꿈), 견적은 draft 만(확정은 표준 경로 · 승인).
표준이 다르게 정해 내지 않는 키는 `tests/compat_expected.yaml ot.differs`.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from mlcore.serve.compat import CompatError

MSG_415 = "ASCII DXF만 지원합니다. DWG·PDF는 자동 인식하지 않습니다. 원본 CAD에서 DXF 전개도로 내보내세요."   # main.py:86
MSG_413 = "도면 파일은 5MB 이하만 지원합니다."                                                       # main.py:88
MSG_DRAWING_404 = "도면 분석을 찾을 수 없습니다."                                                    # main.py:97
MSG_NO_DRAWING = "먼저 CAD 도면을 분석하세요."                                                       # main.py:104
MSG_QUOTE_404 = "견적을 찾을 수 없습니다."                                                           # main.py:117
SCOPE = "재료 + 통합 가공시간 + 준비비. 금형 제작·도금·열처리·포장·운송·외주 특수공정 비용은 별도입니다."   # quote.py:35
STATUS = {"draft": "검토용 초안", "pending_confirm": "확정 대기", "confirmed": "확정"}               # quote.py:28 (원천은 초안만)
QUOTE_KEYS = ["drawing_id", "material", "profile", "length", "width", "thickness", "holes", "slots", "bends", "quantity",
              "reviewed", "review_note"]                                                           # main.py:31-44
OLD = {"part_length_mm": "length", "blank_width_mm": "width", "sheet_thickness_mm": "thickness", "hole_count": "holes",
       "slot_count": "slots", "bend_count": "bends", "steel_grade": "material", "section_profile": "profile",
       "quantity": "quantity"}                                                                     # 표준 견적 입력 → 옛 QuoteInput 키
COST_KEYS = ["machine_per_min", "setup_minutes", "scrap_rate", "markup", "vat_rate"]                # config.py:21 COST 순서
COUNT_KEYS = ["outer", "hole", "slot", "other"]                                                    # cad.py:132


def _tenant_name(info: dict) -> str:
    from pathlib import Path

    import yaml
    p = Path(__file__).resolve().parent.parent / f"{info['tenant']}.yaml"
    try:
        return str((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("name") or "")
    except OSError:
        return ""


def _err(field: str, msg: str, typ: str) -> CompatError:
    return CompatError(422, {"detail": [{"loc": ["body", field], "msg": msg, "type": typ}]})


def _won(v: Any) -> int:
    return int(Decimal(str(v)))


# ── health · overview ────────────────────────────────────────────────────────────────────
def shape_health(res: dict, info: dict) -> dict:
    return {"status": res["status"], "model_ready": res["model_ready"], "version": res["version"],   # main.py:49
            "mode": res["data_mode"]}


def shape_overview(o: dict, info: dict) -> dict:
    """ml_service.py:28-38 (가공시간 회귀 부분). 객체 분류 지표(recognition_*) · 객체 설명자 행 수 · 시험 구간 행 단위
    예측(trend) · 예시 단가표(materials) · 견적 계수(cost)는 내지 않는다(differs)."""
    sp = o.get("split") or {}
    return {"version": o["version"], "mode": o["data_mode"], "job_rows": o["rows"], "missing_cells": o["missing_cells"],
            "champion": o["champion"],
            "metrics": [{"model": m["model"], "mae": m["mae"], "rmse": m["rmse"], "r2": m["r2"]} for m in o["metrics"]],
            "test_metrics": o["test_metrics"], "split": {"jobs": [sp.get("train"), sp.get("validation"), sp.get("test")]},
            "features": o["features"], "profiles": o.get("profiles"), "warning": o["warning"]}


# ── 도면 ─────────────────────────────────────────────────────────────────────────────────
def _drawing(doc: dict, mode: str) -> dict:
    """cad.py:136 + storage.py:25 — 옛 도면 분석 키. 좌표는 mm(원본 단위는 source_unit)."""
    objs = doc["objects"]
    boxes = [o["bbox"] for o in objs if isinstance(o.get("bbox"), list) and len(o["bbox"]) == 4]
    bbox = ([min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
            if boxes else None)                                                                     # cad.py:133
    return {"filename": doc["filename"], "unit": "mm", "source_unit": doc["unit"], "objects": objs,
            "counts": {k: int((doc.get("counts") or {}).get(k, 0)) for k in COUNT_KEYS}, "bbox": bbox,
            "dimensions": doc.get("dimensions"), "warnings": doc["warnings"], "entity_count": doc["entity_count"],
            "data_mode": mode, "id": doc["doc_id"], "created_at": doc["created_at"]}


def shape_document_upload(doc: dict, info: dict) -> dict:
    return _drawing(doc, "uploaded_geometry_synthetic_model")                                      # cad.py:137


def shape_document_demo(doc: dict, info: dict) -> dict:
    return _drawing(doc, "synthetic_demo")                                                         # main.py:78


def shape_document_get(doc: dict, info: dict) -> dict:
    return _drawing(doc, "uploaded_geometry_synthetic_model")


# ── 견적 ─────────────────────────────────────────────────────────────────────────────────
def parse_quote_create(old: Any, info: dict) -> dict:
    """옛 QuoteInput(main.py:31-44) → 표준 본문. 모양 검사만(키 · 필수 · reviewed true · 메모 5자 · 수량 1~10,000 정수) —
    값 범위 · 재질 · 형상은 표준 입력 검증(팩 features · 회사 범주)이 한다."""
    if not isinstance(old, dict):
        raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "객체여야 합니다", "type": "model_attributes_type"}]})
    errs = [{"loc": ["body", k if isinstance(k, str) and k.isidentifier() else "?"], "msg": "알 수 없는 입력입니다",
             "type": "extra_forbidden"} for k in old if k not in QUOTE_KEYS]
    errs += [{"loc": ["body", k], "msg": "필수 항목입니다", "type": "missing"} for k in QUOTE_KEYS if k not in old]
    if errs:
        raise CompatError(422, {"detail": errs})
    if old["reviewed"] is not True:
        raise _err("reviewed", "검토 확인(true)이 필요합니다", "literal_error")                        # :43
    note = old["review_note"]
    if not isinstance(note, str) or not 5 <= len(note) <= 500:
        raise _err("review_note", "5자 이상 500자 이하", "string_too_short")                            # :44
    if len(note.strip()) < 5:
        raise CompatError(422, {"detail": "확인 내용을 5자 이상 입력하세요."})                           # :105
    q = old["quantity"]
    if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 10000:
        raise _err("quantity", "1~10,000 정수입니다", "greater_than_equal")                              # :42
    std = {"doc_id": old["drawing_id"], "inputs": {s: old[o] for s, o in OLD.items()}, "lines": [], "reviewed": True,
           "review_note": note}
    return std


def _doc(info: dict, doc_id: str | None) -> dict | None:
    if not doc_id:
        return None
    from mlcore.serve import documents
    return documents.result_of(info["tenant"], doc_id)


def _quote(q: dict, info: dict) -> dict:
    """quote.py:28-35 + storage.py:37 — 옛 견적 키. 금액은 표준 Decimal 견적식 결과(원 단위 정수)."""
    inp = q["inputs"]
    doc = _doc(info, q["doc_id"])
    line = (q["lines"] or [{}])[0]
    rates = q["rates"]
    grade = inp.get("steel_grade")
    old_input = {"drawing_id": q["doc_id"], **{o: inp.get(s) for s, o in OLD.items()},
                 "reviewed": q["reviewed"], "review_note": q["review_note"]}
    old_input = {k: old_input.get(k) for k in QUOTE_KEYS}
    c = q["costs"]
    return {"drawing_id": q["doc_id"], "filename": doc["filename"] if doc else None,
            "status": STATUS.get(q["status"], q["status"]), "input": old_input,
            "minutes_per_piece": line.get("minutes_per_piece"), "total_minutes": line.get("total_minutes"),
            "weight_per_piece": line.get("weight_per_piece"), "material_cost": _won(c["material"]),
            "processing_cost": _won(c["processing"]), "setup_cost": _won(c["setup"]), "markup_cost": _won(c["markup"]),
            "subtotal": _won(c["subtotal"]), "vat": _won(c["vat"]), "total": _won(q["total"]),
            "unit_price": line.get("unit_price"),
            "model_version": q["model_versions"][0]["version"] if q["model_versions"] else None,
            "assumptions": {**{k: Decimal(rates[k]) for k in COST_KEYS if k in rates},
                            "price_kg": Decimal((rates.get("price_kg") or {}).get(grade, "0")) if grade else None,
                            "density": Decimal((rates.get("density") or {}).get(grade, "0")) if grade else None},
            "overrides": [{"field": OLD.get(o["field"], o["field"]), "recognized": o["recognized"], "confirmed": o["confirmed"]}
                          for o in q["overrides"]],
            "notice": q["notice"], "recognition_warnings": doc["warnings"] if doc else [], "scope": SCOPE,
            "id": q["quote_id"], "created_at": q["created_at"]}


def shape_quote_create(q: dict, info: dict) -> dict:
    return _quote(q, info)


def shape_quote_get(q: dict, info: dict) -> dict:
    return _quote(q, info)


def shape_quote_list(out: dict, info: dict) -> dict:
    return {"total": out["total"], "offset": out["offset"], "limit": out["limit"],
            "records": [_quote(q, info) for q in out["records"]]}                                  # storage.py:54


def shape_old_quote_csv(q: dict, info: dict):
    """main.py:126-139 — 견적 1건 CSV (경로 /api/quotes/{id}/csv · 동작 quote_get + 이 모양)."""
    from mlcore.serve.compat.phase2 import Raw
    from mlcore.serve.quotes import safe_cell
    o = _quote(q, info)
    i = o["input"]
    rows = [[f"{_tenant_name(info)} 견적 초안".strip(), o["id"]], ["상태", o["status"]], ["도면", o["filename"]],
            ["생성 시각", o["created_at"]], ["재질", i["material"]], ["제품", i["profile"]], ["수량", i["quantity"]],
            ["길이(mm)", i["length"]], ["전개 폭(mm)", i["width"]], ["두께(mm)", i["thickness"]], ["홀 수", i["holes"]],
            ["슬롯 수", i["slots"]], ["굽힘 수", i["bends"]], ["개당 예측 가공시간(분)", o["minutes_per_piece"]],
            ["재료비(원)", o["material_cost"]], ["가공비(원)", o["processing_cost"]], ["준비비(원)", o["setup_cost"]],
            ["원가 가산액(원)", o["markup_cost"]], ["공급가액(원)", o["subtotal"]], ["부가세(원)", o["vat"]],
            ["합계(원)", o["total"]], ["확인 내용", i["review_note"]], ["버전", o["model_version"]],
            ["주의", o["notice"]], ["범위", o["scope"]]]
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in rows:
        w.writerow([safe_cell("" if v is None else v if isinstance(v, str) else str(v)) for v in row])
    return Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{o['id']}.csv")


# ── 오류 ─────────────────────────────────────────────────────────────────────────────────
def shape_error(status: int, body: Any, info: dict) -> tuple[int, Any]:
    """옛 HTTPException 모양 `{"detail": 문구}` (main.py:86-117). 입력 검증 422 는 옛 목록 모양 그대로(main.py:26-28)."""
    act = info.get("action", "")
    if status == 415:
        return 415, {"detail": MSG_415}
    if status == 413 and act.startswith("document_"):
        return 413, {"detail": MSG_413}
    if status == 422 and act.startswith("document_") and isinstance(body, dict) and isinstance(body.get("detail"), list):
        return 422, {"detail": "; ".join(str(d.get("msg")) for d in body["detail"])}               # main.py:90 str(e)
    if status == 404 and act == "document_get":
        return 404, {"detail": MSG_DRAWING_404}
    if status == 404 and act == "quote_create":
        return 404, {"detail": MSG_NO_DRAWING}
    if status == 404 and act.startswith("quote_"):
        return 404, {"detail": MSG_QUOTE_404}
    return status, body
