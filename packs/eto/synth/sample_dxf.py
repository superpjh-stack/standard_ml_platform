"""시험용 합성 도면 — ASCII DXF (pack-contract §6 `synth/sample_dxf.py`).

원천 `api/cad.py:16-39 sample_bytes()` 의 도형 · 텍스트 · 좌표를 그대로 옮겼다(원천은 ezdxf R2010 으로 쓰고, 여기서는
외부 의존 없이 그룹 코드를 직접 쓴다 — 추출 결과가 같은지는 tests/test_extract_eto.py).
  표제란(TITLE 사각형 + 텍스트 4) · BOM표(BOM 사각형 + 머리 2 + 품목 4) · 리비전표(REV 사각형 + 2) · 장비 외형(사각형 · 호 2 · 선 2) · 도곽.
도면 번호의 회사 접두어는 옮기지 않는다(`DEMO-R1000`). 재질 이름은 회사 값이라 `materials`(회사 재질 목록, 원천 순서)로 받는다 —
품목 재질은 원천과 같은 목록 위치(몸통 · 경판 = 둘째, 재킷 = 첫째, 지지대 = 넷째)를 쓴다. 없으면 팩 중립 M1…M8.
"""

from __future__ import annotations

NEUTRAL_MATERIALS = [f"M{i}" for i in range(1, 9)]
INSUNITS_MM = 4


def _fmt(v: float) -> str:
    return repr(float(v))


def _rect(x: float, y: float, w: float, h: float, layer: str) -> list[tuple[int, str]]:
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    out = [(0, "LWPOLYLINE"), (8, layer), (90, "4"), (70, "1")]
    for px, py in pts:
        out += [(10, _fmt(px)), (20, _fmt(py))]
    return out


def _text(value: str, x: float, y: float, layer: str) -> list[tuple[int, str]]:
    return [(0, "TEXT"), (8, layer), (10, _fmt(x)), (20, _fmt(y)), (30, "0.0"), (40, "3.0"), (1, value)]


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, layer: str) -> list[tuple[int, str]]:
    return [(0, "ARC"), (8, layer), (10, _fmt(cx)), (20, _fmt(cy)), (30, "0.0"), (40, _fmt(r)), (50, _fmt(a0)), (51, _fmt(a1))]


def _line(p: tuple[float, float], q: tuple[float, float], layer: str) -> list[tuple[int, str]]:
    return [(0, "LINE"), (8, layer), (10, _fmt(p[0])), (20, _fmt(p[1])), (30, "0.0"), (11, _fmt(q[0])), (21, _fmt(q[1])), (31, "0.0")]


def entities(materials: list[str] | None = None) -> list[tuple[int, str]]:
    m = list(materials or NEUTRAL_MATERIALS)
    if len(m) < 4:
        raise ValueError("재질 목록은 4개 이상(원천 목록 위치를 쓴다)")
    e: list[tuple[int, str]] = []
    e += _rect(0, 0, 420, 297, "FRAME")
    e += _rect(260, 15, 150, 48, "TITLE")
    for i, t in enumerate(["DRAWING NO: DEMO-R1000", "TITLE: REACTOR ASSEMBLY", f"MATERIAL: {m[1]}", "DEMO / NOT FOR FABRICATION"]):
        e += _text(t, 265, 54 - i * 10, "TITLE")
    e += _rect(235, 170, 175, 110, "BOM")
    rows = ["BILL OF MATERIALS (DEMO)", "NAME | MATERIAL | QTY | MASS_KG", f"SHELL | {m[1]} | 1 | 320", f"HEAD | {m[1]} | 2 | 90",
            f"JACKET | {m[0]} | 1 | 110", f"SUPPORT | {m[3]} | 4 | 10"]
    for i, t in enumerate(rows):
        e += _text(t, 239, 269 - i * 15, "BOM")
    e += _rect(260, 85, 150, 60, "REV")
    for i, t in enumerate(["REVISION HISTORY", "A | 2026-09-19 | DEMO ONLY"]):
        e += _text(t, 265, 132 - i * 14, "REV")
    e += _rect(65, 90, 110, 110, "EQUIPMENT")
    e += _arc(120, 200, 55, 0, 180, "EQUIPMENT")
    e += _arc(120, 90, 55, 180, 360, "EQUIPMENT")
    e += _line((120, 55), (120, 245), "EQUIPMENT")
    e += _line((92, 143), (148, 143), "EQUIPMENT")
    return e


def dxf_bytes(ents: list[tuple[int, str]], *, insunits: int | None = INSUNITS_MM) -> bytes:
    """그룹 코드 쌍 → ASCII DXF(HEADER · ENTITIES · EOF). insunits=None 이면 단위 헤더를 쓰지 않는다."""
    pairs: list[tuple[int, str]] = [(0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1024")]
    if insunits is not None:
        pairs += [(9, "$INSUNITS"), (70, str(int(insunits)))]
    pairs += [(0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), *ents, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode("utf-8")


def sample_bytes(materials: list[str] | None = None) -> bytes:
    """원천 sample_bytes() 와 같은 도형의 합성 도면(mm)."""
    return dxf_bytes(entities(materials))
