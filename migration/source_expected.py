"""원천 저장 결과 → 대조 기대값 fixture (G2-E01 · G2-Q01 · goal2 §0.2 "원천을 읽어 기대값 작성, 실행 금지").

원천 저장소의 SQLite 를 **읽기 전용(URI mode=ro)** 으로 열어, 원천 앱이 저장해 둔 도면 분석 · 견적 결과를 그대로 옮긴다.
원천 코드는 import · 실행하지 않는다. 값은 손질하지 않는다 — 바꾸려면 이 스크립트를 고치고 다시 만든다.
옮기는 것은 합성 데모 결과뿐이다(원천 mode=synthetic_demo · 예시 단가 — 실데이터 0). 도면 원본 바이트(raw)는 옮기지 않는다.

    uv run python migration/source_expected.py --tenant kd     # → tests/fixtures/kd/source_drawing.json · source_quotes.json
    uv run python migration/source_expected.py --tenant ot     # → tests/fixtures/ot/source_drawing.json · source_quotes.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"kd": ROOT.parent / "KyungDong ML AI" / "data" / "kyungdong.sqlite3",
           "ot": ROOT.parent / "OneTouch ML AI" / "data" / "onetouch.sqlite3"}
DRAWING_KEYS = {
    "kd": ("filename", "mode", "unit", "scale_to_mm", "unit_source", "entity_count", "bbox", "counts", "unsupported",
           "objects", "bom", "warnings"),
    "ot": ("filename", "unit", "source_unit", "objects", "counts", "bbox", "dimensions", "skipped", "warnings",
           "entity_count", "data_mode"),
}
QUOTE_KEYS = {
    "kd": ("input", "source_bom", "lines", "features", "mass_kg", "hours_per_unit", "material_cost", "labor_cost",
           "outsource_cost", "markup_cost", "subtotal", "vat", "total", "model", "model_version", "cost_snapshot"),
    "ot": ("input", "status", "minutes_per_piece", "total_minutes", "weight_per_piece", "material_cost", "processing_cost",
           "setup_cost", "markup_cost", "subtotal", "vat", "total", "unit_price", "model", "model_version", "test_mae",
           "assumptions", "overrides"),
}


def _ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"원천 파일 없음: {path.name}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def drawings(conn, keys) -> list[dict]:
    out = []
    for did, created, payload in conn.execute("SELECT id, created_at, payload FROM drawings ORDER BY created_at, id"):
        d = json.loads(payload)
        out.append({"ref": f"drawings/{did}", "created_at": created, **{k: d.get(k) for k in keys},
                    "paths_count": len(d.get("paths") or []), "texts_count": len(d.get("texts") or [])})
    return out


def quotes(conn, keys) -> list[dict]:
    out = []
    for qid, created, payload in conn.execute("SELECT id, created_at, payload FROM quotes ORDER BY created_at, id"):
        q = json.loads(payload)
        out.append({"ref": f"quotes/{qid}", "created_at": created, **{k: q.get(k) for k in keys}})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", required=True, choices=sorted(SOURCES))
    a = ap.parse_args(argv)
    conn = _ro(SOURCES[a.tenant])
    out_dir = ROOT / "tests" / "fixtures" / a.tenant
    out_dir.mkdir(parents=True, exist_ok=True)
    note = ("원천 앱이 저장한 합성 데모 결과(읽기 전용 사본). 생성: migration/source_expected.py — 손질 금지")
    for name, rows in (("source_drawing.json", drawings(conn, DRAWING_KEYS[a.tenant])),
                       ("source_quotes.json", quotes(conn, QUOTE_KEYS[a.tenant]))):
        (out_dir / name).write_text(json.dumps({"note": note, "source": f"data/{SOURCES[a.tenant].name}", "rows": rows},
                                               ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{a.tenant}/{name}: {len(rows)} 행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
