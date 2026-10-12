"""G2-E01 — 추출 (서비스 부분, 웨이브 P 개발2). goal2 §2 · §2.1 · api-contract §6.1 · predict-contract §8.2.

코어가 지는 것: 업로드 상한(5 MiB · 20,000 엔티티 → 413 document_too_large) · 잘못된 DXF(422 invalid_document, rule
format · binary · parse · unit) · 단위(헤더 우선, unit_override) · `mlp_document`(raw_sha256 · size · entity_count · labels) ·
원본 `var/documents/<tenant>/<sha>.dxf` · 추출기 플러그인 호출 · 결과 합침 · 라벨 없으면 지표 null.
**원천 추출기 결과 일치(kd 영역 3종 · BOM · ot 객체 분류)는 팩(eto · rollform-quote — 개발3 A2)이 생긴 뒤 이 파일에 더한다.**
시험용 추출기는 tests/_phase2.py(시험 팩, 원천 규칙 아님).
"""

from __future__ import annotations

import hashlib

import jsonschema
import pytest

import _dev2 as h
import _phase2 as p2
from mlcore.db.conn import connect
from mlcore.tasks import dxf

pytestmark = [pytest.mark.gate("G2-E01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]
DOC_SCHEMA = p2.schema("document-schema")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = p2.make_world(tmp_path_factory.mktemp("extract"))
    other = p2.make_world(tmp_path_factory.mktemp("extract-other"))
    return m, h.keys(m), h.keys(other), other


def _err(r, status, code, rule=None):
    assert r.status_code == status, (r.status_code, r.text)
    e = r.json()["error"]
    assert e["code"] == code, e
    if rule:
        assert e["detail"].get("rule") == rule, e
    return e


# ── 코어 DXF 읽개 ──────────────────────────────────────────────────────────────────────
def test_dxf_reader_counts_model_space_entities_and_units():
    doc = dxf.read(p2.dxf_bytes(extra_entities=5))
    assert doc.entity_count == 1 + 1 + 5 and doc.insunits() == 4
    assert dxf.resolve_unit(doc, None) == "mm"
    inch = dxf.read(p2.dxf_bytes(insunits=1))
    assert dxf.resolve_unit(inch, "mm") == "inch"                  # 헤더가 있으면 헤더 우선(원천 kd R3)
    none = dxf.read(p2.dxf_bytes(insunits=None))
    assert dxf.resolve_unit(none, "inch") == "inch"
    with pytest.raises(dxf.DocumentError) as e:
        dxf.resolve_unit(none, None)
    assert (e.value.code, e.value.rule) == ("invalid_document", "unit")


@pytest.mark.parametrize("raw,rule", [
    (b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 40, "binary"),
    (b"not a dxf at all\n", "parse"),
    (b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\nabc\n0\nENDSEC\n0\nEOF\n", "parse"),     # 좌표가 숫자 아님
    (b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\nnan\n0\nENDSEC\n0\nEOF\n", "parse"),     # 유한하지 않음
    (b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n1\n", "parse"),                        # 닫히지 않은 구간
])
def test_dxf_reader_rejects_broken(raw, rule):
    with pytest.raises(dxf.DocumentError) as e:
        dxf.read(raw)
    assert (e.value.code, e.value.rule) == ("invalid_document", rule)


def test_dxf_reader_entity_limit_and_cp949():
    with pytest.raises(dxf.DocumentError) as e:
        dxf.read(p2.dxf_bytes(extra_entities=30), max_entities=20)
    assert (e.value.code, e.value.rule) == ("document_too_large", "entities")
    doc = dxf.read(p2.dxf_bytes(texts=(("부품표 BOM", 1, 1),), encoding="cp949"))
    assert doc.encoding == "cp949" and doc.entities[-1].get(1) == "부품표 BOM"


# ── 업로드 API ─────────────────────────────────────────────────────────────────────────
def test_upload_returns_contract_and_stores_document(world):
    m, k, ko, other = world
    tc = h.client(m)
    raw = p2.sample_dxf()
    r = p2.upload(tc, m, k["operator"], raw)
    assert r.status_code == 201, r.text
    body = r.json()
    jsonschema.validate(body, DOC_SCHEMA)
    sha = hashlib.sha256(raw).hexdigest()
    assert body["raw_sha256"] == sha and body["unit"] == "mm" and body["entity_count"] == 5
    assert body["labels"] == "none" and body["metrics"] is None and body["confidence"] is None   # 라벨 없음 → 지표 없음
    assert body["extractor"] == [{"name": "test_rects", "version": "1.0.0", "kind": "rule", "model_version": None}]
    assert [b["name"] for b in body["bom_rows"]] == ["브래킷", "볼트"] and body["counts"] == {"rect": 2, "text": 3}
    assert body["dimensions"] == {"length": 200.0, "width": 80.0}
    assert "raw" not in body and "content" not in body                  # 원본 바이트는 응답에 없다
    with connect() as c:
        row = c.execute("SELECT raw_sha256, raw_path, size_bytes, entity_count, labels, created_by FROM mlp_document "
                        "WHERE doc_id = %s", (body["doc_id"],)).fetchone()
    assert row["raw_sha256"] == sha and row["size_bytes"] == len(raw) and row["entity_count"] == 5
    assert row["labels"] == "none" and row["created_by"].startswith("test-operator")
    stored = p2.DOC_DIR / m.tenant.code / f"{sha}.dxf"
    assert stored.read_bytes() == raw and row["raw_path"].endswith(f"{m.tenant.code}/{sha}.dxf")
    got = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'drawing')}/documents/{body['doc_id']}",
                 headers=h.hdr(k["operator"]))
    assert got.status_code == 200 and got.json() == body
    lst = tc.get(f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'drawing')}/documents?limit=1",
                 headers=h.hdr(k["operator"])).json()
    assert set(lst) == {"items", "next_cursor", "total"} and lst["items"][0]["doc_id"] == body["doc_id"]


def test_upload_size_and_entity_limits_413(world):
    m, k, ko, other = world
    tc = h.client(m)
    big = p2.dxf_bytes() + b"999\n" + b"x" * (5 * 1024 * 1024) + b"\n"
    _err(p2.upload(tc, m, k["operator"], big), 413, "document_too_large", "bytes")
    _err(p2.upload(tc, m, k["operator"], p2.dxf_bytes(extra_entities=20001)), 413, "document_too_large", "entities")


def test_upload_lowered_limit_from_override(tmp_path):
    m = p2.make_world(tmp_path, overrides={"drawing": {"document": {"formats": ["dxf"], "max_bytes": 4096,
                                                                   "max_entities": 10, "unit_override": ["mm"]}}})
    k = h.keys(m)
    tc = h.client(m)
    _err(p2.upload(tc, m, k["operator"], p2.dxf_bytes(extra_entities=11)), 413, "document_too_large", "entities")
    padded = p2.dxf_bytes(extra_entities=2).replace(b"0\nEOF", b"999\n" + b"x" * 5000 + b"\n0\nEOF")
    _err(p2.upload(tc, m, k["operator"], padded), 413, "document_too_large", "bytes")
    assert p2.upload(tc, m, k["operator"], p2.dxf_bytes(extra_entities=5)).status_code == 201


@pytest.mark.parametrize("filename,raw,rule", [
    ("drawing.pdf", b"%PDF-1.7", "format"),
    ("drawing.dxf", b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 64, "binary"),
    ("drawing.dxf", b"garbage\ncontent\nwith odd", "parse"),
])
def test_upload_invalid_document_422(world, filename, raw, rule):
    m, k, ko, other = world
    _err(p2.upload(h.client(m), m, k["operator"], raw, filename=filename), 422, "invalid_document", rule)


def test_upload_unit_rules(world):
    m, k, ko, other = world
    tc = h.client(m)
    raw = p2.dxf_bytes(insunits=None, rects=((0, 0, 4, 2),), texts=(("A", 1, 1),))
    _err(p2.upload(tc, m, k["operator"], raw), 422, "invalid_document", "unit")
    r = p2.upload(tc, m, k["operator"], raw, unit_override="inch")
    assert r.status_code == 201 and r.json()["dimensions"] == {"length": 101.6, "width": 50.8}   # inch → mm
    _err(p2.upload(tc, m, k["operator"], raw, unit_override="furlong"), 422, "invalid_document", "unit")


def test_upload_extractor_limit_error_and_no_store(world):
    m, k, ko, other = world
    rect = tuple((i, i, i + 1, i + 1) for i in range(1))
    many = p2.dxf_bytes(rects=rect)
    many = many.replace(b"90\n4\n", b"90\n60\n").replace(b"10\n0\n20\n1\n", b"10\n0\n20\n1\n" + b"10\n0\n20\n0\n" * 60)
    raw_sha = hashlib.sha256(many).hexdigest()
    _err(p2.upload(h.client(m), m, k["operator"], many), 413, "document_too_large", "vertices")
    assert not (p2.DOC_DIR / m.tenant.code / f"{raw_sha}.dxf").exists()                  # 거부된 문서는 남기지 않는다


def test_upload_roles_tenant_scope_and_type_route(world):
    m, k, ko, other = world
    tc = h.client(m)
    raw = p2.sample_dxf()
    _err(p2.upload(tc, m, k["viewer"], raw), 403, "forbidden")
    _err(p2.upload(tc, m, ko["operator"], raw), 404, "not_found")                       # 다른 회사 키
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'estimate')}/documents", headers=h.hdr(k["operator"]),
                files={"file": ("a.dxf", raw, "application/dxf")})
    _err(r, 404, "not_found", "type_route")
    doc = p2.upload(tc, m, k["operator"], raw).json()
    tco = h.client(other)
    _err(tco.get(f"/api/v1/tenants/{other.tenant.code}/tasks/{p2.tid(other, 'drawing')}/documents/{doc['doc_id']}",
                 headers=h.hdr(ko["operator"])), 404, "not_found")                       # 다른 회사의 문서 ID
    tc = h.client(m)
    _err(tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{p2.tid(m, 'drawing')}/documents", headers=h.hdr(k["operator"]),
                 json={"file": "x"}), 422, "invalid_document", "format")                 # multipart 아님
