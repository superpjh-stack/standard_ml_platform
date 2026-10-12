"""규칙 추출기 — 도면 영역 3종 후보(표제란 · BOM표 · 리비전표) (task-contract §6.2 · D2-06 · source_inventory §11.5 R1~R9).

원천 `api/cad.py:50-123 analyze()` 를 **읽어** 이관했다(실행하지 않는다). 원천은 ezdxf 로 읽고, 표준은 코어 DXF 읽개
`mlcore.tasks.dxf.read`(그룹 코드 쌍, 외부 의존 0)를 쓴다 — 같은 도면에서 같은 영역 · 같은 텍스트가 나오는지는
`tests/test_extract_eto.py` 가 원천 시험(`tests/test_api.py:30-35 · :83-88`)의 기대값으로 본다.

규칙(원천 그대로):
  R3 단위 — 코어가 정한 원본 단위(`unit`)를 mm 로 환산(inch 25.4 · cm 10 · m 1000).
  R4 좌표 유한 · |v| ≤ 1e8, TEXT/MTEXT 2,000자(코어 읽개가 자름), LWPOLYLINE 꼭짓점 ≤ 4,000, bulge 있는 폴리라인은 미지원.
  R5 사각형 후보 = 닫힌 4점 축 정렬 LWPOLYLINE.
  R6 키워드(대문자 부분 일치) — 아래 KEYWORDS(도면 공통 어휘).
  R7 키워드 텍스트 삽입점을 포함하는 가장 작은 사각형 하나, 같은 사각형은 한 번만.
  R8 영역 안 텍스트의 키워드 종류가 하나면 그 라벨, 둘 이상이면 other. 상태는 언제나 '검토 필요'.
  R9 텍스트 · 사각형이 없으면 영역을 만들지 않는다(가짜 후보 0). INSERT 등 다른 요소는 미지원 개수로 공개.
정답 라벨이 없으므로 지표를 만들지 않는다(과제 labels: none — 코어가 metrics: null).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from mlcore.tasks.dxf import SCALE_TO_MM, read
from mlcore.tasks.extract import ExtractError

NAME = "cad_regions"
VERSION = "1.0.0"
KIND = "rule"

KEYWORDS = {"title_block": ["DRAWING NO", "DRAWING NUMBER", "DWG NO", "도면번호", "도면명"],
            "bom_table": ["BILL OF MATERIAL", "PARTS LIST", "BOM", "부품표", "자재명세"],
            "rev_table": ["REVISION", "REV.", "리비전", "개정이력"]}
LABELS = ("title_block", "bom_table", "rev_table", "other")
MAX_VERTICES = 4000
COORD_LIMIT = 1e8
REVIEW = "검토 필요"
WARN_RULE = ("텍스트 키워드가 포함된 폐합 사각형을 후보로 제시합니다. 학습된 영역 탐지·OCR 결과가 아니며, 담당자 검토가 필요합니다.")
WARN_NONE = "표제란·BOM표·리비전표 후보를 찾지 못했습니다. DXF 텍스트와 폐합 사각형을 확인하세요."
_UNICODE_ESC = re.compile(r"\\U\+([0-9A-Fa-f]{4})")
_MTEXT_FMT = re.compile(r"\\[ACcFfHhQqTtWw][^;]*;|\\[LlOoKk]")


def _decode_text(s: str) -> str:
    """DXF 유니코드 표기 `\\U+XXXX` → 문자 (원천 ezdxf decode_dxf_unicode 와 같은 뜻)."""
    return _UNICODE_ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def _mtext_plain(s: str) -> str:
    s = s.replace("\\P", "\n").replace("\\~", " ")
    s = _MTEXT_FMT.sub("", s)
    return s.replace("{", "").replace("}", "").replace("\\\\", "\\")


def _point(x: float, y: float, factor: float) -> list[float]:
    a = [round(float(x) * factor, 4), round(float(y) * factor, 4)]
    if not all(math.isfinite(v) and abs(v) <= COORD_LIMIT for v in a):
        raise ExtractError("invalid_document", "parse", "도면 좌표 범위를 확인하세요.")
    return a


def _lw_vertices(ent) -> list[tuple[float, float, float]]:
    """LWPOLYLINE 꼭짓점 (x, y, bulge) — 10/20 이 꼭짓점을 열고 42 가 그 꼭짓점의 bulge."""
    out: list[list[float]] = []
    for code, value in ent.codes:
        if code == 10:
            out.append([float(value), 0.0, 0.0])
        elif code == 20 and out:
            out[-1][1] = float(value)
        elif code == 42 and out:
            out[-1][2] = float(value)
    return [(x, y, b) for x, y, b in out]


def parse(raw: bytes, *, unit: str, limits: dict | None = None) -> dict:
    """도면 → {paths, texts, rects, unsupported, entity_count, factor} (원천 analyze 의 앞부분)."""
    limits = limits or {}
    doc = read(raw, max_entities=int(limits.get("max_entities") or 20000))
    if unit not in SCALE_TO_MM:
        raise ExtractError("invalid_document", "unit", "단위가 없거나 지원하지 않는 단위입니다. mm 또는 inch를 직접 선택하세요.")
    factor = SCALE_TO_MM[unit]
    paths, texts, rects, unsupported = [], [], [], Counter()
    for ent in doc.entities:
        kind, layer = ent.type, ent.layer
        if kind in ("TEXT", "MTEXT"):
            if kind == "TEXT":
                value = _decode_text(ent.get(1, "") or "")
            else:
                value = _mtext_plain(_decode_text("".join(ent.all(3)) + (ent.get(1, "") or "")))
            texts.append({"text": value[:2000], "point": _point(ent.num(10, 0.0), ent.num(20, 0.0), factor), "layer": layer})
        elif kind == "LINE":
            paths.append({"points": [_point(ent.num(10, 0.0), ent.num(20, 0.0), factor),
                                     _point(ent.num(11, 0.0), ent.num(21, 0.0), factor)], "layer": layer})
        elif kind == "LWPOLYLINE":
            vertices = _lw_vertices(ent)
            if len(vertices) > MAX_VERTICES:
                raise ExtractError("document_too_large", "vertices", "폴리라인 꼭짓점 수가 너무 많습니다.")
            if any(abs(b) > 1e-9 for _, _, b in vertices):
                unsupported["곡선 폴리라인"] += 1
                continue
            pts = [_point(x, y, factor) for x, y, _ in vertices]
            if not pts:
                continue
            closed = bool(int(ent.get(70, "0") or 0) & 1)
            paths.append({"points": pts + ([pts[0]] if closed else []), "layer": layer})
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            box = [min(xs), min(ys), max(xs), max(ys)]
            if closed and len(pts) == 4 and all((p[0] in (box[0], box[2]) and p[1] in (box[1], box[3])) for p in pts):
                rects.append(box)
        elif kind in ("CIRCLE", "ARC"):
            start = 0.0 if kind == "CIRCLE" else ent.num(50, 0.0)
            end = 360.0 if kind == "CIRCLE" else ent.num(51, 0.0)
            if end <= start:
                end += 360
            cx, cy, r = ent.num(10, 0.0), ent.num(20, 0.0), ent.num(40, 0.0)
            paths.append({"points": [_point(cx + r * math.cos(math.radians(start + (end - start) * i / 48)),
                                            cy + r * math.sin(math.radians(start + (end - start) * i / 48)), factor)
                                     for i in range(49)], "layer": layer})
        else:
            unsupported[kind] += 1
    return {"paths": paths, "texts": texts, "rects": rects, "unsupported": unsupported,
            "entity_count": doc.entity_count, "factor": factor}


def regions_from(texts: list[dict], rects: list[list[float]]) -> list[dict]:
    """R6~R8 — 키워드 텍스트를 감싸는 가장 작은 사각형 → 영역 후보."""
    regions, seen = [], set()
    for text in texts:
        value = text["text"].upper()
        if not any(any(w in value for w in words) for words in KEYWORDS.values()):
            continue
        x, y = text["point"]
        enclosing = [r for r in rects if r[0] <= x <= r[2] and r[1] <= y <= r[3] and r[2] > r[0] and r[3] > r[1]]
        if not enclosing:
            continue
        box = min(enclosing, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        if tuple(box) in seen:
            continue
        seen.add(tuple(box))
        inside = [t["text"] for t in texts if box[0] <= t["point"][0] <= box[2] and box[1] <= t["point"][1] <= box[3]]
        kinds = {k for k, words in KEYWORDS.items() if any(any(w in t.upper() for w in words) for t in inside)}
        label = next(iter(kinds)) if len(kinds) == 1 else "other"
        regions.append({"id": f"REG-{len(regions) + 1:03}", "label": label, "bbox": box, "texts": inside,
                        "evidence": text["text"], "status": REVIEW})
    return regions


def analyze(raw: bytes, *, unit: str, limits: dict | None = None) -> dict:
    """parse + regions + 원천 검사(도형 없음 거부 · 경고). bom_text 도 이 함수를 쓴다."""
    g = parse(raw, unit=unit, limits=limits)
    coords = [p for path in g["paths"] for p in path["points"]] + [t["point"] for t in g["texts"]]
    if not coords:
        raise ExtractError("invalid_document", "parse", "지원하는 모델 공간 도형이나 텍스트가 없습니다.")
    regions = regions_from(g["texts"], g["rects"])
    warnings = [WARN_RULE]
    if g["unsupported"]:
        warnings.append("미지원 요소 제외: " + ", ".join(f"{k} {v}개" for k, v in g["unsupported"].items()))
    if not regions:
        warnings.append(WARN_NONE)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return {**g, "regions": regions, "warnings": warnings, "bbox": [min(xs), min(ys), max(xs), max(ys)]}


def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None, **_context) -> dict:
    """→ 추출 결과(progress-dev2 2차 §2.1.1 모양). 원본을 쓰지 않고 외부로 보내지 않는다."""
    a = analyze(raw, unit=unit, limits=limits)
    return {
        "regions": a["regions"], "objects": [], "bom_rows": [], "confidence": None,
        "counts": {k: sum(r["label"] == k for r in a["regions"]) for k in LABELS},
        "dimensions": None, "unit": "mm", "entity_count": a["entity_count"], "warnings": a["warnings"],
        "preview": {"bbox": a["bbox"], "paths": a["paths"], "texts": a["texts"], "scale_to_mm": a["factor"],
                    "source_unit": unit, "unsupported": dict(a["unsupported"])},
    }
