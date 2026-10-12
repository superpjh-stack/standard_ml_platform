"""2차 유형 코어 시험 도우미 — 시험용 팩(임시 폴더) · 회사 · DXF (개발2).

원천 팩(eto · rollform-quote)은 개발3 웨이브 A2 몫이라, 코어 시험은 `_template` 팩을 임시 폴더에 복사해
2차 유형 과제 3개(review_queue · extract · quote) + **시험용 추출기 · 시험용 견적식**을 더한 팩으로 한다.
견적식은 원천 식이 아니다(원천 대조는 팩이 생긴 뒤 G2-Q01 fixture) — Decimal · ROUND_HALF_UP 만 쓰는 시험용 식.
실제 로더(registry.packs.load_pack · tenants.load_and_merge)를 그대로 지난다.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import textwrap
from pathlib import Path

import os
import tempfile

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.registry import tenants

PACK = "coretest"
DOC_DIR = Path(os.environ.setdefault("MLP_DOCUMENT_DIR", tempfile.mkdtemp(prefix="mlp-docs-")))   # 원본 저장 — 저장소 밖

EXTRACTOR = '''
"""시험용 규칙 추출기 — 닫힌 LWPOLYLINE 사각형 · TEXT. 코어 DXF 읽개를 쓴다."""
from mlcore.tasks import dxf
from mlcore.tasks.extract import ExtractError

NAME = "test_rects"
VERSION = "1.0.0"
KIND = "rule"


def extract(raw, filename, *, unit, limits, model=None):
    doc = dxf.read(raw, max_entities=limits["max_entities"])
    k = dxf.SCALE_TO_MM[unit]
    rects, texts, warnings = [], [], []
    for e in doc.entities:
        if e.type == "LWPOLYLINE":
            xs = [float(v) * k for v in e.all(10)]
            ys = [float(v) * k for v in e.all(20)]
            if len(xs) > 50:
                raise ExtractError("document_too_large", "vertices", "꼭짓점이 너무 많습니다")
            if xs:
                rects.append([min(xs), min(ys), max(xs), max(ys)])
        elif e.type == "TEXT":
            texts.append((float(e.get(10, 0)) * k, float(e.get(20, 0)) * k, e.get(1, "")))
    regions, bom = [], []
    def area(r):
        return (r[2] - r[0]) * (r[3] - r[1])
    home = {}
    for t in texts:                     # 텍스트는 그것을 품는 가장 작은 사각형에 속한다
        owners = [i for i, r in enumerate(rects) if r[0] <= t[0] <= r[2] and r[1] <= t[1] <= r[3]]
        if owners:
            home.setdefault(min(owners, key=lambda i: area(rects[i])), []).append(t)
    for i, r in enumerate(rects):
        inside = home.get(i, [])
        if not inside:
            continue
        label = "bom_table" if any("BOM" in t[2].upper() for t in inside) else "other"
        regions.append({"id": f"R{i + 1}", "label": label, "bbox": r, "texts": [t[2] for t in inside],
                        "evidence": "키워드", "status": "확인" if label != "other" else "검토 필요"})
        if label == "bom_table":
            for t in inside:
                parts = [p.strip() for p in t[2].split("|")]
                if len(parts) == 4 and parts[2].isdigit():
                    bom.append({"name": parts[0], "material": parts[1], "quantity": int(parts[2]),
                                "mass_kg": float(parts[3]), "source": f"R{i + 1}"})
    dims = None
    if rects:
        big = max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        dims = {"length": round(big[2] - big[0], 3), "width": round(big[3] - big[1], 3)}
    if not texts:
        warnings.append("텍스트 없음")
    return {"regions": regions, "objects": [], "bom_rows": bom, "confidence": None,
            "counts": {"rect": len(rects), "text": len(texts)}, "dimensions": dims, "warnings": warnings}
'''

FORMULA = '''
"""시험용 견적식 — Decimal · ROUND_HALF_UP 만 (원천 식 아님)."""
from decimal import ROUND_HALF_UP, Decimal

ONE = Decimal(1)
H4 = Decimal("0.0001")


def prepare(inputs, lines):
    total = Decimal(0)
    for ln in lines:
        total += Decimal(str(ln["mass_kg"])) * Decimal(ln["quantity"])
    return {"bom_mass": total} if lines else {}


def quote(inputs, lines, predicted, rates):
    hours = abs(predicted["target_value"]).quantize(H4, rounding=ROUND_HALF_UP)
    qty = Decimal(inputs["quantity"])
    out_lines = []
    material = Decimal(0)
    for ln in lines:
        amt = (Decimal(str(ln["mass_kg"])) * Decimal(ln["quantity"]) * rates["price_kg"] * qty).quantize(ONE, rounding=ROUND_HALF_UP)
        material += amt
        out_lines.append({"name": ln["name"], "material": ln["material"], "quantity": ln["quantity"], "amount": amt})
    labor = (hours * rates["unit_rate"] * qty).quantize(ONE, rounding=ROUND_HALF_UP)
    markup = ((material + labor) * rates["markup"]).quantize(ONE, rounding=ROUND_HALF_UP)
    subtotal = material + labor + markup
    vat = (subtotal * rates["vat"]).quantize(ONE, rounding=ROUND_HALF_UP)
    return {"lines": out_lines, "costs": {"material": material, "labor": labor, "markup": markup,
                                          "subtotal": subtotal, "vat": vat},
            "total": subtotal + vat, "predicted": {"target_value": hours}}
'''

TASKS = {
    "value_review": {
        "id": f"{PACK}.value_review", "type": "review_queue", "title": "잔차 검토", "entity": "lot",
        "out_of_range": "predict_with_warning", "approver_role": "quality", "uses": [f"{PACK}.target_value"],
        "rule": {"abs_residual_ge": 4.0}, "origins": ["test_split", "live_residual"], "max_items": 50,
    },
    "drawing": {
        "id": f"{PACK}.drawing", "type": "extract", "title": "도면 추출", "entity": "drawing",
        "out_of_range": "predict_with_warning", "approver_role": "quality",
        "document": {"formats": ["dxf"], "max_bytes": 5242880, "max_entities": 20000, "unit_override": ["mm", "inch"]},
        "extractors": [{"name": "test_rects", "kind": "rule", "module": "extractors/test_rects.py", "version": "1.0.0"}],
        "labels": "none", "outputs": ["regions", "bom_rows"],
    },
    "estimate": {
        "id": f"{PACK}.estimate", "type": "quote", "title": "견적", "entity": "job",
        "out_of_range": "predict_with_warning", "approver_role": "quality", "uses": [f"{PACK}.target_value"],
        "from_extract": f"{PACK}.drawing", "recognized": {"x1": "dimensions.width", "tolerance": "0.001"},
        "inputs": ["x1", "x2", "c1", "quantity"], "formula": "formulas/quote.py",
        "rates": {"unit_rate": "45000", "price_kg": "1200", "markup": "0.15", "vat": "0.10"},
        "rounding": "ROUND_HALF_UP", "currency": "KRW",
        "confirm": {"requires": ["reviewed", "review_note"], "review_note_min": 5, "approver_role": "quality"},
    },
}


def make_pack(tmp: Path) -> Path:
    import yaml
    base = tmp / "packs"
    dst = base / PACK
    shutil.copytree(h.ROOT / "packs" / "_template", dst, ignore=shutil.ignore_patterns("__pycache__"))
    meta = yaml.safe_load((dst / "pack.yaml").read_text(encoding="utf-8"))
    meta["code"] = PACK
    meta["name"] = "코어 시험 팩"
    meta["tasks"] = sorted(["target_value", "target_risk", *TASKS])
    (dst / "pack.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    for n in ("target_value", "target_risk"):
        p = dst / "tasks" / f"{n}.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("_template.", f"{PACK}."), encoding="utf-8")
    for n, t in TASKS.items():
        (dst / "tasks" / f"{n}.yaml").write_text(yaml.safe_dump(t, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (dst / "extractors").mkdir(exist_ok=True)
    (dst / "extractors" / "test_rects.py").write_text(textwrap.dedent(EXTRACTOR), encoding="utf-8")
    (dst / "formulas").mkdir(exist_ok=True)
    (dst / "formulas" / "quote.py").write_text(textwrap.dedent(FORMULA), encoding="utf-8")
    return base


def make_world(tmp: Path, *, overrides: dict | None = None):
    """→ Merged(시험 팩 · 새 회사 코드). mlp_tenant · mlp_task 행을 넣는다."""
    import yaml
    packs_base = make_pack(tmp)
    code = "t" + secrets.token_hex(3)
    tb = tmp / f"tenants-{code}"
    tb.mkdir()
    text = (h.ROOT / "tenants" / "_template.yaml").read_text(encoding="utf-8").replace("__code__", code)
    text = text.replace("__name__", "코어 시험 회사").replace("pack: _template", f"pack: {PACK}")
    cfg = yaml.safe_load(text)
    cfg["tasks"]["enable"] = [f"{code}.{n}" for n in ["target_value", "target_risk", *TASKS]]
    cfg["sources"] = {"demo": {"kind": "synthetic", "seed": 42}}
    (tb / f"{code}.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    for short, over in (overrides or {}).items():
        d = tb / code / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{short}.yaml").write_text(yaml.safe_dump(over, allow_unicode=True), encoding="utf-8")
    m = tenants.load_and_merge(code, tenants_base=tb, packs_base=packs_base)
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)",
                  (code, "코어 시험 회사", PACK, m.tenant.config["mode"]))
        for task_id, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                      "VALUES (%s,%s,%s,%s,%s,%s)", (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    return m


def tid(m, short: str) -> str:
    return f"{m.tenant.code}.{short}"


# ── DXF ────────────────────────────────────────────────────────────────────────────────
def dxf_bytes(*, insunits: int | None = 4, rects=((0, 0, 100, 40),), texts=(("BOM", 10, 30),),
              extra_entities: int = 0, encoding: str = "utf-8") -> bytes:
    out = ["0", "SECTION", "2", "HEADER"]
    if insunits is not None:
        out += ["9", "$INSUNITS", "70", str(insunits)]
    out += ["0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for x0, y0, x1, y1 in rects:
        out += ["0", "LWPOLYLINE", "8", "0", "90", "4", "70", "1"]
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            out += ["10", str(x), "20", str(y)]
    for text, x, y in texts:
        out += ["0", "TEXT", "8", "0", "10", str(x), "20", str(y), "40", "2.5", "1", text]
    for i in range(extra_entities):
        out += ["0", "LINE", "8", "0", "10", "0", "20", str(i), "11", "1", "21", str(i)]
    out += ["0", "ENDSEC", "0", "EOF"]
    return ("\n".join(out) + "\n").encode(encoding)


def sample_dxf() -> bytes:
    """사각형 2(외곽 200×80 · BOM 표) · BOM 행 2 · 단위 mm."""
    return dxf_bytes(rects=((0, 0, 200, 80), (10, 10, 90, 60)),
                     texts=(("BOM", 20, 50), ("브래킷 | SS400 | 2 | 1.5", 20, 40), ("볼트 | SUS304 | 4 | 0.25", 20, 30)))


def upload(tc, m, key, raw: bytes, *, filename: str = "sample.dxf", unit_override: str | None = None):
    data = {"unit_override": unit_override} if unit_override else None
    return tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{tid(m, 'drawing')}/documents", headers=h.hdr(key),
                   files={"file": (filename, raw, "application/dxf")}, data=data)


def schema(name: str) -> dict:
    text = (h.ROOT / "contracts" / "predict-contract.md").read_text(encoding="utf-8")
    return json.loads(re.search(rf"```json {name}\n(.*?)```", text, re.S).group(1))


def review_item(m, *, origin: str = "test_split", state: str = "open", prediction_id: str | None = None) -> str:
    """대기열 항목 1행(항목 생성은 개발1 · 개발3 — 여기는 B09 조회 · 판정 시험용)."""
    from mlcore.serve.ids import new_id
    iid = new_id("rvw")
    with connect() as c:
        c.execute("INSERT INTO mlp_review_item (item_id, tenant_id, task_id, entity_id, prediction_id, predicted, actual, "
                  "residual, reason, origin, state, version, rule, threshold) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (iid, m.tenant.code, tid(m, "value_review"), "LOT-1", prediction_id, 10.0, 15.5, 5.5,
                   "|잔차| 5.50 ≥ 4.0", origin, state, "v1", "abs_residual_ge", 4.0))
    return iid
