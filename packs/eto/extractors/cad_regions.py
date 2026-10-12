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

규모(D2-101 · #30): 결과는 원천 알고리즘과 같고(`tests/test_extract_eto_scale.py` 가 1차 구현과 대조), 계산만 바꿨다 —
  사각형을 넓이 순(같으면 파일 순 — 원천 min 과 같은 선택)으로 줄 세워 키워드 텍스트 묶음을 numpy 로 한 번에 판정,
  영역 안 텍스트도 numpy 마스크 한 번. 분석(parse + 영역)은 같은 도면이면 한 번만(bom_text 가 다시 쓴다).
  영역 안 텍스트를 모두 담으면 결과가 영역 수 × 텍스트 수로 커질 수 있어, 과제 params `max_region_texts`
  (영역 texts 합계 상한, 팩 YAML)를 넘으면 413 document_too_large(rule region_texts). params 가 없으면 상한 없음(원천과 같음).
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
import types
from collections import Counter

import numpy as np

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


ARC_SEGMENTS = 48                  # 원천 원 · 호 분할 수(api/cad.py — 49점)
MIN_ARC_SEGMENTS = 8               # 점 예산으로 줄일 때의 최소 분할 수


def _arc_points(arc: tuple, segments: int, factor: float) -> list[list[float]]:
    cx, cy, r, start, end = arc
    return [_point(cx + r * math.cos(math.radians(start + (end - start) * i / segments)),
                   cy + r * math.sin(math.radians(start + (end - start) * i / segments)), factor)
            for i in range(segments + 1)]


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
            # 원천 48분할 점으로 좌표 검사 · 외곽(bbox)을 재되, 점은 들고 있지 않는다(원 · 호 2만 개 = 98만 점 — #34).
            # 미리보기 점은 _preview 가 점 예산 안에서 다시 만든다(같은 식 — 예산 안이면 원천과 같은 49점).
            arc = (cx, cy, r, start, end)
            pts = _arc_points(arc, ARC_SEGMENTS, factor)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            paths.append({"arc": arc, "layer": layer, "box": [min(xs), min(ys), max(xs), max(ys)]})
        else:
            unsupported[kind] += 1
    return {"paths": paths, "texts": texts, "rects": rects, "unsupported": unsupported,
            "entity_count": doc.entity_count, "factor": factor}


def _kinds(value: str) -> frozenset:
    up = value.upper()
    return frozenset(k for k, words in KEYWORDS.items() if any(w in up for w in words))


_BLOCK = 256                       # 키워드 텍스트 묶음 크기(묶음 × 사각형 bool 행렬)


def regions_from(texts: list[dict], rects: list[list[float]], *, max_region_texts: int | None = None) -> list[dict]:
    """R6~R8 — 키워드 텍스트를 감싸는 가장 작은 사각형 → 영역 후보 (원천과 같은 결과, 계산은 색인 — D2-101)."""
    if not texts or not rects:
        return []
    kinds = [_kinds(t["text"]) for t in texts]
    keyed = [i for i, k in enumerate(kinds) if k]
    if not keyed:
        return []
    R = np.asarray(rects, dtype=float).reshape(-1, 4)
    ok = (R[:, 2] > R[:, 0]) & (R[:, 3] > R[:, 1])
    area = (R[:, 2] - R[:, 0]) * (R[:, 3] - R[:, 1])
    order = np.argsort(area, kind="stable")                # 넓이 오름차순 · 같으면 파일 순(원천 min 의 첫 최소)
    order = order[ok[order]]
    if order.size == 0:
        return []
    Rs = R[order]
    P = np.asarray([t["point"] for t in texts], dtype=float).reshape(-1, 2)
    best: dict[int, int] = {}                              # 키워드 텍스트 번호 → 가장 작은 감싸는 사각형 번호
    for s in range(0, len(keyed), _BLOCK):
        idx = keyed[s:s + _BLOCK]
        x, y = P[idx, 0:1], P[idx, 1:2]
        m = (Rs[:, 0] <= x) & (x <= Rs[:, 2]) & (Rs[:, 1] <= y) & (y <= Rs[:, 3])
        hit = m.any(axis=1)
        first = m.argmax(axis=1)
        for j, ti in enumerate(idx):
            if hit[j]:
                best[ti] = int(order[first[j]])
    regions, seen, total = [], set(), 0
    for ti in keyed:
        if ti not in best:
            continue
        box = rects[best[ti]]
        if tuple(box) in seen:
            continue
        seen.add(tuple(box))
        mask = (box[0] <= P[:, 0]) & (P[:, 0] <= box[2]) & (box[1] <= P[:, 1]) & (P[:, 1] <= box[3])
        members = np.flatnonzero(mask)
        total += int(members.size)
        if max_region_texts is not None and total > max_region_texts:
            raise ExtractError("document_too_large", "region_texts",
                               "도면 영역 안 텍스트가 너무 많습니다(겹친 사각형). 도면을 나눠 올리세요.")
        inside = [texts[i]["text"] for i in members.tolist()]
        found = frozenset().union(*(kinds[i] for i in members.tolist()))
        label = next(iter(found)) if len(found) == 1 else "other"
        regions.append({"id": f"REG-{len(regions) + 1:03}", "label": label, "bbox": box, "texts": inside,
                        "evidence": texts[ti]["text"], "status": REVIEW})
    return regions


# 같은 도면 분석 공유 — 코어 로더 · bom_text 가 이 파일을 각자 다른 모듈 이름으로 읽어도 같은 자리를 본다(최근 1건).
_SHARED = sys.modules.setdefault("mlp_pack_eto_analysis_shared", types.ModuleType("mlp_pack_eto_analysis_shared"))
if not hasattr(_SHARED, "last"):
    _SHARED.last = None


def _cap(params: dict | None) -> int | None:
    v = (params or {}).get("max_region_texts")
    return int(v) if v is not None else None


def analyze(raw: bytes, *, unit: str, limits: dict | None = None, max_region_texts: int | None = None) -> dict:
    """parse + regions + 원천 검사(도형 없음 거부 · 경고). bom_text 도 이 함수를 쓴다 — 같은 입력이면 한 번만 계산."""
    key = (hashlib.sha256(raw).hexdigest(), unit, int((limits or {}).get("max_entities") or 20000), max_region_texts)
    last = _SHARED.last
    if last is not None and last[0] == key:
        if isinstance(last[1], ExtractError):
            raise last[1]
        return last[1]
    try:
        out = _analyze(raw, unit=unit, limits=limits, max_region_texts=max_region_texts)
    except ExtractError as e:
        _SHARED.last = (key, e)
        raise
    _SHARED.last = (key, out)
    return out


def _analyze(raw: bytes, *, unit: str, limits: dict | None, max_region_texts: int | None) -> dict:
    g = parse(raw, unit=unit, limits=limits)
    boxes = [path["box"] for path in g["paths"] if "box" in path]
    coords = [p for path in g["paths"] if "points" in path for p in path["points"]] + [t["point"] for t in g["texts"]] \
        + [[b[0], b[1]] for b in boxes] + [[b[2], b[3]] for b in boxes]
    if not coords:
        raise ExtractError("invalid_document", "parse", "지원하는 모델 공간 도형이나 텍스트가 없습니다.")
    regions = regions_from(g["texts"], g["rects"], max_region_texts=max_region_texts)
    warnings = [WARN_RULE]
    if g["unsupported"]:
        warnings.append("미지원 요소 제외: " + ", ".join(f"{k} {v}개" for k, v in g["unsupported"].items()))
    if not regions:
        warnings.append(WARN_NONE)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return {**g, "regions": regions, "warnings": warnings, "bbox": [min(xs), min(ys), max(xs), max(ys)]}


def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None, context: dict | None = None,
            **_ignored) -> dict:
    """→ 추출 결과(progress-dev2 2차 §2.1.1 모양). 원본을 쓰지 않고 외부로 보내지 않는다."""
    a = analyze(raw, unit=unit, limits=limits, max_region_texts=_cap((context or {}).get("params")))
    return {
        "regions": [dict(r, texts=list(r["texts"]), bbox=list(r["bbox"])) for r in a["regions"]], "objects": [], "bom_rows": [], "confidence": None,
        "counts": {k: sum(r["label"] == k for r in a["regions"]) for k in LABELS},
        "dimensions": None, "unit": "mm", "entity_count": a["entity_count"], "warnings": a["warnings"],
        "preview": {"bbox": a["bbox"], **_preview(a["paths"], a["factor"], _budget((context or {}).get("params"))),
                    "texts": a["texts"], "scale_to_mm": a["factor"], "source_unit": unit, "unsupported": dict(a["unsupported"])},
    }


def _budget(params: dict | None) -> int | None:
    v = (params or {}).get("preview_max_points")
    return int(v) if v is not None else None


def _preview(paths: list[dict], factor: float, budget: int | None) -> dict:
    """미리보기 경로(표시용 점) — 점 예산(과제 params `preview_max_points`, 팩 YAML) 안으로 (#34 · D2-110).
    ① 예산 안이면 원천 그대로(원 · 호 49점) ② 넘으면 원 · 호 분할 수를 예산에 맞춰 줄이고(최소 8분할)
    ③ 그래도 넘으면 파일 순서 뒤쪽 경로를 생략 — `reduced: {arc_segments, omitted_paths, max_points}` 로 줄였음을 보인다.
    params 가 없으면 예산 없음(원천과 같음). 영역 · BOM(판정용 결과)은 이 함수와 무관하다."""
    fixed = sum(len(p["points"]) for p in paths if "points" in p)
    arcs = sum(1 for p in paths if "arc" in p)
    seg = ARC_SEGMENTS
    if budget is not None and fixed + arcs * (ARC_SEGMENTS + 1) > budget:
        seg = max(MIN_ARC_SEGMENTS, min(ARC_SEGMENTS, (budget - fixed) // max(arcs, 1) - 1))
    out, used, omitted = [], 0, 0
    for p in paths:
        n = len(p["points"]) if "points" in p else seg + 1
        if budget is not None and used + n > budget:
            omitted += 1
            continue
        used += n
        out.append({"points": p["points"] if "points" in p else _arc_points(p["arc"], seg, factor), "layer": p["layer"]})
    reduced = None if seg == ARC_SEGMENTS and omitted == 0 else {"arc_segments": seg, "omitted_paths": omitted,
                                                                   "max_points": budget}
    return {"paths": out, "reduced": reduced}
