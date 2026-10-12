"""kd 호환 모양 플러그인 — 옛 경로 응답 키 (api-contract §5 · §6.3 · predict-contract §7.1). 소유 개발2.

원천 `../KyungDong ML AI/api/{main,quote,cad,storage,ml_service}.py` 를 **읽어** 옛 응답 모양만 옮겼다(원천 실행 0).
계산 · 저장 · 승인은 표준 서비스 그대로다 — 금액은 표준 Decimal 견적식 결과, 추출은 팩 추출기, 견적은 draft 만(확정은
표준 경로 · 승인). 여기는 키 이름 · 순서 · 문구만 바꾼다. 표준이 다르게 정해 내지 않는 키는 `tests/compat_expected.yaml kd.differs`.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from mlcore.serve.compat import CompatError

# 원천 문구 (회사 화면 문구 — 원천 그대로)
MSG_415 = "ASCII DXF만 지원합니다. DWG·CAD·PDF는 DXF로 변환 후 업로드하세요."         # main.py:92
MSG_413 = "도면 파일은 5 MiB 이하만 지원합니다."                                       # main.py:94
MSG_DRAWING_404 = "도면 분석을 찾을 수 없습니다."                                      # main.py:103
MSG_QUOTE_404 = "견적을 찾을 수 없습니다."                                             # main.py:138
SCOPE = ("사용자가 입력한 BOM 소재·통합 제조공수·외주비 기준입니다. 운송·인증·설계비 등 미입력 비용은 포함하지 않습니다. "
         "공수는 납기 예측이 아닙니다.")                                                # quote.py:23
STATUS = {"draft": "검토용 초안", "pending_confirm": "확정 대기", "confirmed": "확정"}  # quote.py:18 (원천은 초안만)
RECOGNITION = {"method": "DXF 텍스트·폐합 사각형 기반 규칙 후보 추출", "labels": ["title_block", "bom_table", "rev_table"],
               "measured_accuracy": None, "reason": "3종 영역 정답 라벨 미확보. 실제 객체 인식 정확도 측정 불가."}   # ml_service.py:64
QUOTE_KEYS = ["drawing_id", "product", "material", "bom", "quantity", "cut_m", "weld_m", "thickness_mm", "complexity",
              "labor_rate", "outsource_cost", "reviewed", "review_note"]                                   # main.py:47-60
BOM_KEYS = ["name", "material", "quantity", "mass_kg", "price_kg"]                                         # main.py:34-39
INPUTS = {"cut_m": "cut_m", "weld_m": "weld_m", "thickness_mm": "thickness_mm", "complexity": "complexity",
          "main_material": "material", "product_family": "product", "quantity": "quantity", "labor_rate": "labor_rate",
          "outsource_cost": "outsource_cost"}                                        # 표준 견적 입력 → 옛 QuoteInput 키
EXPORT_FILENAME = "kyungdong-visible-quotes"                                         # main.py:132 (DEF-QA22-008)
EXPORT_HEAD = ["견적번호", "도면명", "제품", "상태", "합계(원)", "모델버전"]            # main.py:132


def _tenant_name(info: dict) -> str:
    """회사 이름 — 같은 등록부 폴더의 `<code>.yaml` name (원천 CSV 머리 main.py:145 의 회사명을 코드에 두지 않는다)."""
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
    return {"status": res["status"], "model_ready": res["model_ready"], "version": res["version"],   # main.py:71
            "mode": res["data_mode"]}


OLD_WARNING = "합성 작업 900건으로 학습한 공수 예측입니다. 실측 견적 정확도·객체 인식률·납기 정확도를 의미하지 않습니다."   # 원천 ml_service.py:66 — 합성 모델일 때만(실데이터 모델이면 표준 문구 그대로, DEF-QA22-007)
OVERVIEW_METRIC_DIGITS = 4   # 원천 ml_service.py:41 metrics() round(…, 4) — 옛 개요 mae · rmse 소수 자리(DEF-QA22-007)

def shape_overview(o: dict, info: dict) -> dict:
    """ml_service.py:59-66. 시험 구간 행 단위 예측(trend) · 예시 단가표(materials) · 견적 계수(cost) · 특성 중복(duplicates)은
    내지 않는다(differs)."""
    sp = o.get("split") or {}
    return {"version": o["version"], "mode": o["data_mode"], "job_rows": o["rows"], "missing_cells": o["missing_cells"],
            "champion": o["champion"],
            "metrics": [{"model": m["model"], "mae": m["mae"], "rmse": m["rmse"], "r2": m["r2"]} for m in o["metrics"]],
            "test_metrics": o["test_metrics"], "split": [sp.get("train"), sp.get("validation"), sp.get("test")],
            "features": o["features"], "products": o.get("products"), "recognition": dict(RECOGNITION),
            "warning": OLD_WARNING if o["data_mode"] in ("synthetic_demo", "demo") else o["warning"]}


# ── 도면 ─────────────────────────────────────────────────────────────────────────────────
def _drawing(doc: dict, mode: str) -> dict:
    """cad.py:123 + storage.py:25 — 옛 도면 분석 키. 영역 = 원천 objects 와 같은 키(id · label · bbox · texts · evidence · status)."""
    from mlcore.tasks.dxf import SCALE_TO_MM
    counts = {k: int((doc.get("counts") or {}).get(k, 0)) for k in ("title_block", "bom_table", "rev_table", "other")}
    return {"filename": doc["filename"], "sha256": doc["raw_sha256"], "unit": doc["unit"],
            "scale_to_mm": SCALE_TO_MM.get(doc["unit"]), "mode": mode, "objects": doc["regions"],
            "bom": doc["bom_rows"], "counts": counts, "warnings": doc["warnings"], "entity_count": doc["entity_count"],
            "id": doc["doc_id"], "created_at": doc["created_at"]}


def shape_document_upload(doc: dict, info: dict) -> dict:
    return _drawing(doc, "uploaded_dxf")


def shape_document_demo(doc: dict, info: dict) -> dict:
    return _drawing(doc, "synthetic_demo")                                            # main.py:85


def shape_document_get(doc: dict, info: dict) -> dict:
    return _drawing(doc, "uploaded_dxf")


# ── 견적 ─────────────────────────────────────────────────────────────────────────────────
def parse_quote_create(old: Any, info: dict) -> dict:
    """옛 QuoteInput(main.py:47-60) → 표준 본문. 모양 검사만(키 · 필수 · reviewed true · 메모 5자 · BOM 1~100행) —
    값 범위 · 재질 · 제품군 · 총중량은 표준 입력 검증(팩 features · 회사 범주)이 한다."""
    if not isinstance(old, dict):
        raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "객체여야 합니다", "type": "model_attributes_type"}]})
    errs = [{"loc": ["body", k if isinstance(k, str) and k.isidentifier() else "?"], "msg": "알 수 없는 입력입니다",
             "type": "extra_forbidden"} for k in old if k not in QUOTE_KEYS]
    errs += [{"loc": ["body", k], "msg": "필수 항목입니다", "type": "missing"} for k in QUOTE_KEYS if k not in old]
    if errs:
        raise CompatError(422, {"detail": errs})
    if old["reviewed"] is not True:
        raise _err("reviewed", "검토 확인(true)이 필요합니다", "literal_error")                # :59 Literal[True]
    note = old["review_note"]
    if not isinstance(note, str) or not 5 <= len(note.strip()) <= 500:
        raise _err("review_note", "5자 이상 500자 이하", "string_too_short")                    # :60 (str_strip_whitespace)
    bom = old["bom"]
    if not isinstance(bom, list) or not 1 <= len(bom) <= 100:
        raise _err("bom", "BOM 은 1~100행입니다", "too_short" if isinstance(bom, list) and not bom else "list_type")   # :51
    for i, row in enumerate(bom):
        if not isinstance(row, dict) or set(row) != set(BOM_KEYS):
            raise CompatError(422, {"detail": [{"loc": ["body", "bom", i], "msg": "BOM 행 키는 " + ", ".join(BOM_KEYS),
                                                "type": "model_attributes_type"}]})
    q = old["quantity"]
    if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 1000:
        raise _err("quantity", "1~1000 정수입니다", "int_type" if not isinstance(q, int) else "greater_than_equal")   # :52
    lr = old["labor_rate"]
    if isinstance(lr, bool) or not isinstance(lr, (int, Decimal)) or not 1 <= lr <= 1000000:
        raise _err("labor_rate", "1~1,000,000 입니다", "greater_than_equal")            # :57 (표준 견적 입력은 0 이상만 본다)
    _drawing_or_404(info, old["drawing_id"], MSG_DRAWING_404)                     # :103 · :109
    inputs = {std: old[o] for std, o in INPUTS.items()}
    return {"doc_id": old["drawing_id"].strip(), "inputs": inputs, "lines": [{k: r[k] for k in BOM_KEYS} for r in bom],
            "reviewed": True, "review_note": note.strip()}


def _doc(info: dict, doc_id: str | None) -> dict | None:
    if not doc_id:
        return None
    from mlcore.serve import documents
    return documents.result_of(info["tenant"], doc_id)

def _drawing_or_404(info: dict, drawing_id: Any, message: str) -> None:
    """원천 순서 — 모양 검사(pydantic, drawing_id 1~60자) 뒤 도면 조회 404(DEF-QA22-006: 표준 꼴이 아닌 id 도 422 · loc doc_id 가
    아니라 원천 404 문구). 표준 doc_id 꼴이 아니면 없는 도면이다."""
    if not isinstance(drawing_id, str) or not 1 <= len(drawing_id.strip()) <= 60:
        raise _err("drawing_id", "1~60자 문자열입니다", "string_too_short")
    from mlcore.serve import documents
    if not documents.DOC_ID.match(drawing_id.strip()) or _doc(info, drawing_id.strip()) is None:
        raise CompatError(404, {"detail": message})


def _quote(q: dict, info: dict) -> dict:
    """quote.py:18-23 + storage.py:37 — 옛 견적 키. 금액은 표준 Decimal 견적식 결과(원 단위 정수)."""
    inp = q["inputs"]
    doc = _doc(info, q["doc_id"])
    bom = [{k: ln.get(k) for k in BOM_KEYS} for ln in q["lines"]]
    old_input = {"drawing_id": q["doc_id"], "product": inp.get("product_family"), "material": inp.get("main_material"),
                 "bom": bom, "quantity": inp.get("quantity"), "cut_m": inp.get("cut_m"), "weld_m": inp.get("weld_m"),
                 "thickness_mm": inp.get("thickness_mm"), "complexity": inp.get("complexity"),
                 "labor_rate": inp.get("labor_rate"), "outsource_cost": inp.get("outsource_cost"),
                 "reviewed": q["reviewed"], "review_note": q["review_note"]}
    c = q["costs"]
    hours = Decimal(q["predictions"][0]["value"]) if q["predictions"] else None
    rates = q["rates"]
    return {"drawing_id": q["doc_id"], "filename": doc["filename"] if doc else None, "status": STATUS.get(q["status"], q["status"]),
            "input": old_input, "source_bom": doc["bom_rows"] if doc else None,
            "source_sha256": doc["raw_sha256"] if doc else None,
            "lines": [{**{k: ln.get(k) for k in BOM_KEYS}, "weight_total": ln.get("weight_total"), "cost": _won(ln["amount"])}
                      for ln in q["lines"]],
            "features": {"cut_m": inp.get("cut_m"), "weld_m": inp.get("weld_m"), "thickness_mm": inp.get("thickness_mm"),
                         "complexity": inp.get("complexity"), "material": inp.get("main_material"),
                         "product": inp.get("product_family"), "mass_kg": inp.get("total_mass_kg")},
            "mass_kg": inp.get("total_mass_kg"), "hours_per_unit": hours,
            "material_cost": _won(c["material"]), "labor_cost": _won(c["labor"]), "outsource_cost": _won(c["outsource"]),
            "markup_cost": _won(c["markup"]), "subtotal": _won(c["subtotal"]), "vat": _won(c["vat"]), "total": _won(q["total"]),
            "model_version": q["model_versions"][0]["version"] if q["model_versions"] else None,
            "cost_snapshot": {"labor_per_hour": inp.get("labor_rate", rates.get("labor_per_hour")),
                              "scrap_rate": Decimal(rates["scrap_rate"]), "markup": Decimal(rates["markup"]),
                              "vat_rate": Decimal(rates["vat_rate"])},
            "notice": q["notice"], "scope": SCOPE, "id": q["quote_id"], "created_at": q["created_at"]}


def shape_quote_create(q: dict, info: dict) -> dict:
    return _quote(q, info)


def shape_quote_get(q: dict, info: dict) -> dict:
    return _quote(q, info)


def shape_quote_list(out: dict, info: dict) -> dict:
    return {"total": out["total"], "offset": out["offset"], "limit": out["limit"],
            "records": [_quote(q, info) for q in out["records"]]}                     # storage.py:54


def _csv(rows: list[list], filename: str):
    from mlcore.serve.compat.phase2 import Raw
    from mlcore.serve.quotes import safe_cell
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in rows:
        w.writerow([safe_cell("" if v is None else v if isinstance(v, str) else str(v)) for v in row])
    return Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{filename}.csv")   # main.py:123-126


def shape_old_quote_csv(q: dict, info: dict):
    """main.py:142-150 — 견적 1건 CSV (경로 /api/quotes/{id}/csv · 동작 quote_get + 이 모양)."""
    o = _quote(q, info)
    head = _tenant_name(info)
    rows = [[f"{head} 견적 초안".strip(), o["id"]], ["도면", o["filename"]], ["원본 SHA256", o["source_sha256"]],
            ["제품", o["input"]["product"]], ["대수", o["input"]["quantity"]], ["예측 공수(h/대)", o["hours_per_unit"]],
            ["소재비(원)", o["material_cost"]], ["가공비(원)", o["labor_cost"]], ["외주비(원)", o["outsource_cost"]],
            ["원가 가산액(원)", o["markup_cost"]], ["공급가액(원)", o["subtotal"]], ["부가세(원)", o["vat"]],
            ["합계(원)", o["total"]], ["버전", o["model_version"]], ["확인 메모", o["input"]["review_note"]],
            ["주의", o["notice"]], ["범위", o["scope"]], [],
            ["품명", "재질", "수량/대", "개당 중량kg", "단가 원/kg", "금액 원"]]
    rows += [[r["name"], r["material"], r["quantity"], r["mass_kg"], r["price_kg"], r["cost"]] for r in o["lines"]]
    return _csv(rows, o["id"])


def shape_old_quote_export(out: dict, info: dict):
    """main.py:129-132 — 보이는 쪽(search · offset · limit) 견적 목록 CSV (동작 quote_list + 이 모양)."""
    rows = [EXPORT_HEAD]
    for q in out["records"]:
        o = _quote(q, info)
        rows.append([o["id"], o["filename"], o["input"]["product"], o["status"], o["total"], o["model_version"]])
    return _csv(rows, EXPORT_FILENAME)


# ── 오류 ─────────────────────────────────────────────────────────────────────────────────
def shape_error(status: int, body: Any, info: dict) -> tuple[int, Any]:
    """옛 HTTPException 모양 `{"detail": 문구}` (main.py:92-103 · :138). 입력 검증 422 는 옛 목록 모양 그대로(main.py:25-27)."""
    act = info.get("action", "")
    if status == 415:
        return 415, {"detail": MSG_415}
    if status == 413 and act.startswith("document_"):
        return 413, {"detail": MSG_413}
    if status == 422 and act.startswith("document_") and isinstance(body, dict) and isinstance(body.get("detail"), list):
        return 422, {"detail": "; ".join(str(d.get("msg")) for d in body["detail"])}               # main.py:96 str(exc)
    if status == 404 and act == "document_get":
        return 404, {"detail": MSG_DRAWING_404}
    if status == 404 and act.startswith("quote_") and body != {"detail": MSG_DRAWING_404}:   # 견적 생성의 없는 도면은 원천 문구(:103)
        return 404, {"detail": MSG_QUOTE_404}
    return status, body
