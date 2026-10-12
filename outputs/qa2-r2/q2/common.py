"""QA2-2 공용 — 전용 DB ml_qa2r2_db 만 쓴다(ml_db · ml_test_db 쓰기 0). 고치지 않는다.

실행: MLP_TEST_DB_DSN="dbname=ml_qa2r2_db host=/tmp" MLP_DB_DSN="dbname=ml_qa2r2_db host=/tmp" OMP_NUM_THREADS=1 \
      uv run python outputs/qa2-r2/q2/<probe>.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
assert "ml_qa2r2_db" in os.environ.get("MLP_TEST_DB_DSN", ""), "MLP_TEST_DB_DSN 은 ml_qa2r2_db 여야 한다"
os.environ["MLP_DB_DSN"] = os.environ["MLP_TEST_DB_DSN"]
os.environ.setdefault("MLP_DOCUMENT_DIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "qa22-documents"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import _dev2 as h  # noqa: E402  (MLP_DB_DSN 을 MLP_TEST_DB_DSN 으로 맞춘다)

RESULTS: list[dict] = []


def rec(gate: str, item: str, ok: bool | str, measured, expected=None):
    """ok: True=PASS · False=FAIL · 'WARN' · 'INFO'."""
    verdict = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
    row = {"gate": gate, "item": item, "verdict": verdict, "measured": measured, "expected": expected}
    RESULTS.append(row)
    print(f"{gate:8s}  {item}  {verdict}  {json.dumps(measured, ensure_ascii=False, default=str)[:300]}")
    return row


def save(name: str):
    (OUT / name).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    fails = [r for r in RESULTS if r["verdict"] == "FAIL"]
    print(f"\n== {len(RESULTS)} 검사 · FAIL {len(fails)} · WARN {sum(r['verdict'] == 'WARN' for r in RESULTS)} → {name}")


def count(table: str, where: str = "true", params=()) -> int:
    return h.count(f"SELECT count(*) AS n FROM {table} WHERE {where}", params)


# ── DXF 만들기 ──────────────────────────────────────────────────────────────
def dxf(entities: list[tuple[int, str]], *, insunits: int | None = 4, extra_sections: list[tuple[int, str]] = (),
        pad_comment: int = 0) -> bytes:
    pairs: list[tuple[int, str]] = []
    if insunits is not None:
        pairs += [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, str(insunits)), (0, "ENDSEC")]
    pairs += list(extra_sections)
    pairs += [(0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF")]
    text = "".join(f"{c}\n{v}\n" for c, v in pairs)
    raw = text.encode("utf-8")
    if pad_comment:
        raw = ("999\n" + "x" * max(0, pad_comment - 5) + "\n").encode() + raw
    return raw


def rect(x, y, w, hh, layer="L"):
    out = [(0, "LWPOLYLINE"), (8, layer), (90, "4"), (70, "1")]
    for px, py in [(x, y), (x + w, y), (x + w, y + hh), (x, y + hh)]:
        out += [(10, repr(float(px))), (20, repr(float(py)))]
    return out


def text(v, x, y, layer="T"):
    return [(0, "TEXT"), (8, layer), (10, repr(float(x))), (20, repr(float(y))), (30, "0.0"), (40, "3.0"), (1, v)]


def line(x1, y1, x2, y2, layer="L"):
    return [(0, "LINE"), (8, layer), (10, str(x1)), (20, str(y1)), (30, "0.0"), (11, str(x2)), (21, str(y2)), (31, "0.0")]


def circle(cx, cy, r, layer="C"):
    return [(0, "CIRCLE"), (8, layer), (10, str(cx)), (20, str(cy)), (30, "0.0"), (40, str(r))]


def client(m):
    """h.client 와 같되 서버 예외를 500 응답으로 받는다(500 을 결함으로 세기 위해)."""
    from fastapi.testclient import TestClient

    from mlcore.api.main import app
    tc = TestClient(app, raise_server_exceptions=False)
    tc.__enter__()
    app.state.registry = m
    app.state.catalog = None
    return tc
