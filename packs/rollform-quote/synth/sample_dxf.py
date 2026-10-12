"""시험 · 데모용 합성 전개도 — ASCII DXF (pack-contract §6 · 원천 `api/cad.py:11-23 sample_bytes()` 이관).

원천은 ezdxf R2010 으로 1200 × 160 mm 외곽 1 · 지름 18 mm 홀 6 · 60 × 30 mm 캡슐 슬롯 2 를 쓴다. 여기서는 외부 의존 없이
그룹 코드를 직접 쓴다(같은 도형 · 같은 좌표 · 같은 레이어 · 같은 요소 순서 — 추출 결과 대조는 tests/test_rollform_quote_pack.py).
`samples/sample.dxf` 는 이 모듈로 만든 파일이다(손질 금지 — `uv run python packs/rollform-quote/synth/sample_dxf.py`).
"""

from __future__ import annotations

from pathlib import Path

INSUNITS_MM = 4


def _fmt(v: float) -> str:
    return repr(float(v))


def _lwpolyline(points: list[tuple[float, float, float]], layer: str, closed: bool = True) -> list[tuple[int, str]]:
    out = [(0, "LWPOLYLINE"), (8, layer), (90, str(len(points))), (70, "1" if closed else "0")]
    for x, y, b in points:
        out += [(10, _fmt(x)), (20, _fmt(y))]
        if b:
            out.append((42, _fmt(b)))
    return out


def _circle(cx: float, cy: float, r: float, layer: str) -> list[tuple[int, str]]:
    return [(0, "CIRCLE"), (8, layer), (10, _fmt(cx)), (20, _fmt(cy)), (30, "0.0"), (40, _fmt(r))]


def entities() -> list[tuple[int, str]]:
    e = _lwpolyline([(0, 0, 0), (1200, 0, 0), (1200, 160, 0), (0, 160, 0)], "OUTLINE")
    for x in (100, 600, 1100):
        for y in (40, 120):
            e += _circle(x, y, 9, "HOLES")
    for x in (320, 820):           # 캡슐: 반원 끝 둘을 평행 직선으로 잇는다 (원천 주석 그대로)
        e += _lwpolyline([(x, 65, 0), (x + 60, 65, 1), (x + 60, 95, 0), (x, 95, 1)], "SLOTS")
    return e


def dxf_bytes(ents: list[tuple[int, str]], *, insunits: int | None = INSUNITS_MM) -> bytes:
    """그룹 코드 쌍 → ASCII DXF(HEADER · ENTITIES · EOF). insunits=None 이면 단위 헤더를 쓰지 않는다."""
    pairs: list[tuple[int, str]] = [(0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1024")]
    if insunits is not None:
        pairs += [(9, "$INSUNITS"), (70, str(int(insunits)))]
    pairs += [(0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), *ents, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode("utf-8")


def sample_bytes() -> bytes:
    """원천 sample_bytes() 와 같은 도형의 합성 전개도(mm)."""
    return dxf_bytes(entities())


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "samples" / "sample.dxf"
    out.write_bytes(sample_bytes())
    print(out.name, len(sample_bytes()), "bytes")
