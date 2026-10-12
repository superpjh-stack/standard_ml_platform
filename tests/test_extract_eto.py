"""팩 eto 규칙 추출기(cad_regions · bom_text) — 원천 결과 일치 (G2-E01 일부 · task-contract §6.2 · D2-06).

기대값 = 원천 앱이 저장한 샘플 도면 분석 결과 `tests/fixtures/kd/source_drawing.json`(migration/source_expected.py 가
원천 SQLite 를 읽기 전용으로 옮긴 것) + 원천 시험 `tests/test_api.py:30-35 · :70-88` 의 단정. 원천 코드는 실행하지 않는다.
도면은 팩 `synth/sample_dxf.py`(원천 sample_bytes 도형 이관)로 만든다 — 도면 번호의 회사 접두어만 다르다(팩에 회사 코드 0).
코어 쪽 상한 · 단위 판정(`mlcore.tasks.dxf`)은 개발2 시험이 본다 — 여기서는 플러그인이 그 위에서 원천과 같은 결과를 내는지.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mlcore.registry import tenants
from mlcore.tasks import dxf
from mlcore.tasks.extract import ExtractError, limits_for, load_extractor, merge_results

pytestmark = [pytest.mark.gate("G2-E01")]

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packs" / "eto"
SOURCE = json.loads((ROOT / "tests" / "fixtures" / "kd" / "source_drawing.json").read_text(encoding="utf-8"))["rows"]
SOURCE_PREFIX = "KD-DEMO-R1000"          # 원천 샘플 도면 번호 — 팩 샘플은 DEMO-R1000 (회사 접두어를 옮기지 않는다)


def _sample():
    spec = importlib.util.spec_from_file_location("eto_sample_dxf", PACK / "synth" / "sample_dxf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE = _sample()


@pytest.fixture(scope="module")
def kd():
    return tenants.load_and_merge("kd")


def context(m) -> dict:
    return {"categories": m.tenant.config.get("categories") or {}, "material_aliases": tenants.material_aliases(m)}


def run(m, raw: bytes, *, override: str | None = None, ctx: dict | None = None) -> dict:
    """코어와 같은 순서: 상한 → dxf.read(형식 · 엔티티 수) → 단위 → 과제 extractors 순서대로 → 합침."""
    task = m.tasks["kd.drawing_regions"].raw
    limits = limits_for(task)
    doc = dxf.read(raw, max_entities=limits["max_entities"])
    unit = dxf.resolve_unit(doc, override)
    parts = []
    for spec in task["extractors"]:
        mod = load_extractor(m.pack.path, spec)
        kw = {"context": ctx} if ctx is not None else {}
        parts.append((mod, mod.extract(raw, "sample.dxf", unit=unit, limits=limits, **kw)))
    return {"parts": parts, "merged": merge_results(parts)}


def test_plugins_declare_contract_attributes(kd):
    for spec in kd.tasks["kd.drawing_regions"].raw["extractors"]:
        mod = load_extractor(kd.pack.path, spec)
        assert (mod.NAME, mod.VERSION, mod.KIND) == (spec["name"], spec["version"], spec["kind"]) == (spec["name"], "1.0.0", "rule")


def test_sample_regions_and_bom_match_source(kd):
    src = SOURCE[-1]                                             # 원천 최신 저장 분석(두 행은 같은 결과)
    assert src["mode"] == "synthetic_demo" and all(r["objects"] == src["objects"] for r in SOURCE)
    out = run(kd, SAMPLE.sample_bytes(kd.tenant.config["categories"]["main_material"]), ctx=context(kd))
    merged = out["merged"]
    want_regions = json.loads(json.dumps(src["objects"]).replace(SOURCE_PREFIX, "DEMO-R1000"))
    assert merged["regions"] == want_regions                      # id · label · bbox · texts · evidence · status 전부
    assert merged["bom_rows"] == src["bom"]                       # 4 행 · source REG-002
    assert sum(r["quantity"] * r["mass_kg"] for r in merged["bom_rows"]) == 650     # 원천 시험 :34
    cad = out["parts"][0][1]
    assert cad["counts"] == src["counts"] == {"title_block": 1, "bom_table": 1, "rev_table": 1, "other": 0}
    assert cad["entity_count"] == src["entity_count"] == 21
    assert cad["preview"]["bbox"] == src["bbox"] and cad["preview"]["unsupported"] == src["unsupported"]
    assert len(cad["preview"]["paths"]) == src["paths_count"] and len(cad["preview"]["texts"]) == src["texts_count"]
    assert merged["warnings"] == src["warnings"]                  # 규칙 후보 경고 + BOM 형식 경고(원천 문구 그대로)
    assert merged["confidence"] is None and merged["objects"] == [] and merged["counts"]["bom_rows"] == 4


def test_regions_are_not_duplicated_by_bom_plugin(kd):
    out = run(kd, SAMPLE.sample_bytes(kd.tenant.config["categories"]["main_material"]), ctx=context(kd))
    assert [p[1]["regions"] for p in out["parts"]][1] == []      # 영역은 cad_regions 한 번만
    assert len(out["merged"]["regions"]) == 3


def test_without_context_no_material_check_but_same_rows(kd):
    out = run(kd, SAMPLE.sample_bytes(kd.tenant.config["categories"]["main_material"]))
    assert out["merged"]["bom_rows"] == SOURCE[-1]["bom"]
    assert any("재질 목록을 받지 못해" in w for w in out["merged"]["warnings"])   # 검사하지 않았음을 숨기지 않는다


def test_material_alias_and_unknown_material(kd):
    """원천 :112-113 — 대문자 + 별칭 통합, 회사 재질 목록 밖은 버린다."""
    mats = kd.tenant.config["categories"]["main_material"]
    ents = SAMPLE.entities(mats)
    ents = [(c, v.replace(f"JACKET | {mats[0]}", "JACKET | sus304").replace(f"SUPPORT | {mats[3]}", "SUPPORT | UNOBTAINIUM"))
            for c, v in ents]
    out = run(kd, SAMPLE.dxf_bytes(ents), ctx=context(kd))["merged"]["bom_rows"]
    assert [(r["name"], r["material"]) for r in out] == [("SHELL", mats[1]), ("HEAD", mats[1]), ("JACKET", mats[0])]


@pytest.mark.parametrize("row, kept", [
    ("A | {m} | 0 | 10", False), ("A | {m} | 1001 | 10", False), ("A | {m} | 1.5 | 10", False),
    ("A | {m} | 2 | 0.001", False), ("A | {m} | 2 | 10001", False), ("A | {m} | 2 | nan", False),
    ("A | {m} | 2 | ten", False), ("A | {m} | 2", False), ("A | {m} | 1000 | 10000", True), ("A | {m} | 3.0 | 0.01", True),
])
def test_bom_row_bounds(kd, row, kept):
    m0 = kd.tenant.config["categories"]["main_material"][0]
    ents = [(c, v) for c, v in SAMPLE.entities(kd.tenant.config["categories"]["main_material"])]
    ents = [(c, row.format(m=m0) if v.startswith("SHELL |") else v) for c, v in ents]
    names = [r["name"] for r in run(kd, SAMPLE.dxf_bytes(ents), ctx=context(kd))["merged"]["bom_rows"]]
    assert ("A" in names) is kept


def _line_only(insunits):
    return SAMPLE.dxf_bytes([(0, "LINE"), (8, "0"), (10, "0.0"), (20, "0.0"), (30, "0.0"), (11, "10.0"), (21, "10.0"), (31, "0.0")],
                            insunits=insunits)


def test_unit_confirmation_and_header_precedence(kd):
    """원천 시험 :70-80 — 단위 없으면 사람이 고른다(inch → 25.4), 헤더가 있으면 헤더가 이긴다."""
    with pytest.raises(dxf.DocumentError) as e:
        run(kd, _line_only(0))
    assert (e.value.code, e.value.rule) == ("invalid_document", "unit")
    out = run(kd, _line_only(0), override="inch")
    cad = out["parts"][0][1]
    assert cad["preview"]["scale_to_mm"] == 25.4 and cad["preview"]["bbox"] == [0, 0, 254, 254]
    assert not out["merged"]["regions"] and not out["merged"]["bom_rows"]
    assert run(kd, _line_only(1), override="mm")["parts"][0][1]["preview"]["source_unit"] == "inch"


def test_no_text_does_not_invent_regions_and_blocks_disclosed(kd):
    """원천 시험 :83-88 — 블록 참조(INSERT)는 미지원으로 공개, 영역을 지어내지 않는다."""
    blocks = [(0, "SECTION"), (2, "BLOCKS"), (0, "BLOCK"), (2, "test"), (8, "0"), (10, "0.0"), (20, "0.0"),
              (0, "CIRCLE"), (8, "0"), (10, "0.0"), (20, "0.0"), (40, "5.0"), (0, "ENDBLK"), (0, "ENDSEC")]
    raw = SAMPLE.dxf_bytes([(0, "INSERT"), (8, "0"), (2, "test"), (10, "0.0"), (20, "0.0"),
                            (0, "LINE"), (8, "0"), (10, "0.0"), (20, "0.0"), (11, "10.0"), (21, "10.0")])
    raw = raw.replace(b"0\nSECTION\n2\nENTITIES\n", "".join(f"{c}\n{v}\n" for c, v in blocks).encode() + b"0\nSECTION\n2\nENTITIES\n")
    out = run(kd, raw)
    cad = out["parts"][0][1]
    assert not out["merged"]["regions"] and cad["preview"]["unsupported"] == {"INSERT": 1} and cad["entity_count"] == 2
    assert any("후보를 찾지 못했습니다" in w for w in out["merged"]["warnings"])


def test_bulge_polyline_unsupported_and_vertex_cap(kd):
    m = kd.tenant.config["categories"]["main_material"]
    bulge = [(0, "LWPOLYLINE"), (8, "0"), (90, "2"), (70, "0"), (10, "0.0"), (20, "0.0"), (42, "0.5"), (10, "5.0"), (20, "0.0")]
    out = run(kd, SAMPLE.dxf_bytes(SAMPLE.entities(m) + bulge))
    assert out["parts"][0][1]["preview"]["unsupported"] == {"곡선 폴리라인": 1} and len(out["merged"]["regions"]) == 3
    many = [(0, "LWPOLYLINE"), (8, "0"), (90, "4001"), (70, "0")]
    for i in range(4001):
        many += [(10, f"{i}.0"), (20, "0.0")]
    with pytest.raises(ExtractError) as e:
        run(kd, SAMPLE.dxf_bytes(many))
    assert (e.value.code, e.value.rule) == ("document_too_large", "vertices")


def test_coordinates_out_of_range_rejected(kd):
    raw = SAMPLE.dxf_bytes([(0, "LINE"), (8, "0"), (10, "0.0"), (20, "0.0"), (11, "200000000.0"), (21, "0.0")])
    with pytest.raises(ExtractError) as e:
        run(kd, raw)
    assert e.value.code == "invalid_document"


def test_no_geometry_rejected(kd):
    with pytest.raises(ExtractError) as e:
        run(kd, SAMPLE.dxf_bytes([]))
    assert e.value.code == "invalid_document"


def test_entity_limit_from_task_document(kd, tmp_path):
    """과제 document.max_entities(회사가 낮출 수 있다)를 넘으면 413 — 코어 읽개가 판정한다."""
    m = kd.tenant.config["categories"]["main_material"]
    raw = SAMPLE.sample_bytes(m)
    with pytest.raises(dxf.DocumentError) as e:
        dxf.read(raw, max_entities=20)
    assert (e.value.code, e.value.rule) == ("document_too_large", "entities")
    assert dxf.read(raw, max_entities=21).entity_count == 21


def test_extractors_are_pure(kd):
    """원본을 쓰지 않고(바이트 불변) 같은 입력이면 같은 결과, 네트워크 · 파일 쓰기 import 0."""
    raw = SAMPLE.sample_bytes(kd.tenant.config["categories"]["main_material"])
    before = bytes(raw)
    a = run(kd, raw, ctx=context(kd))["merged"]
    b = run(kd, raw, ctx=context(kd))["merged"]
    assert a == b and raw == before
    for f in (PACK / "extractors").glob("*.py"):
        txt = f.read_text(encoding="utf-8")
        for bad in ("import socket", "import requests", "urllib", "httpx", "open(", "write_bytes", "write_text"):
            assert bad not in txt, (f.name, bad)
