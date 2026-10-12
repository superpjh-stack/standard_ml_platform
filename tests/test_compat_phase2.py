"""호환 라우터 2차 장치 — 객체 경로 · 2차 동작 · 회사 모양 플러그인 (api-contract §5 · §6.3 · D-18 · D-59). 소유 개발2.

웨이브 A2 회사(krs · pc · ot · kd)의 옛 경로를 코어 수정 없이 붙이는 **일반 장치**의 시험이다. 실제 회사 · 팩 모양
(원천 응답 재현)은 A2 몫 — 여기는 시험 팩(tests/_phase2.py) + 시험 안에서 쓰는 임시 `tenants/<code>/compat.py` 플러그인.
"""

from __future__ import annotations

import io
import textwrap

import pytest
import yaml

import _dev2 as h
import _phase2 as p2
from mlcore.db.conn import connect
from mlcore.registry import tenants
from mlcore.serve.compat import phase2 as cp2

pytestmark = [pytest.mark.gate("G2-A01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

PLUGIN = '''
"""시험 회사 호환 플러그인 — 옛 키 ↔ 표준 (원천 모양 아님)."""
from mlcore.serve.compat import CompatError


def parse_quote_create(old, info):
    if "length" not in old:
        raise CompatError(422, {"detail": [{"loc": ["body", "length"], "msg": "필수 항목입니다", "type": "missing"}]})
    return {"inputs": {"x1": old["length"], "x2": old["x2"], "c1": old["grade"], "quantity": old["qty"]},
            "lines": old.get("bom") or [], "reviewed": old.get("reviewed", False), "review_note": old.get("review_note"),
            **({"doc_id": old["drawing_id"]} if old.get("drawing_id") else {})}


def shape_quote_create(q, info):
    return {"id": q["quote_id"], "total_won": int(q["total"]), "state": q["status"], "overrides": q["overrides"]}


def shape_review_list(out, info):
    return {"flagged": [{"lot_id": i["entity_id"], "absolute_error": abs(i["residual"])} for i in out["items"]],
            "review_threshold": out["rule"].get("abs_residual_ge"), "flagged_lots": out["total"]}


def shape_predict_one(out, info):
    return {"predicted": round(out["prediction"]["value"], 2), "status": out["status"]}


def shape_boom(out, info):
    raise RuntimeError("일부러 실패")


def shape_error(status, body, info):
    if status == 415:
        return 415, {"detail": "옛 415 문구", "action": info["action"]}
    return status, body
'''

DEMO_JSON = '{"manifest": {"rows": 2}, "cad": [1, 2]}'


def _routes(code: str) -> list:
    return [
        "/api/health",
        {"path": "/api/quality/overview", "method": "GET", "action": "review_list", "task": "value_review"},
        {"path": "/api/quality/predict", "method": "POST", "action": "predict_one", "task": "target_value"},
        {"path": "/api/ml/samples", "action": "samples", "task": "target_value", "params": {"limit": 5}},
        {"path": "/api/cad/analyze", "method": "POST", "action": "document_upload", "task": "drawing"},
        {"path": "/api/cad/demo", "method": "POST", "action": "document_demo", "task": "drawing",
         "params": {"file": "sample.dxf"}},
        {"path": "/api/cad/sample.dxf", "action": "pack_file", "params": {"file": "sample.dxf"}},
        {"path": "/api/data/demo", "action": "pack_file", "params": {"file": "demo.json"}},
        {"path": "/api/files/{file}", "action": "pack_file"},
        {"path": "/api/cad/{id}", "action": "document_get", "task": "drawing"},
        {"path": "/api/quotes", "method": "POST", "action": "quote_create", "task": "estimate"},
        {"path": "/api/quotes", "method": "GET", "action": "quote_list", "task": "estimate"},
        {"path": "/api/quotes/export/csv", "action": "quote_export_csv", "task": "estimate"},
        {"path": "/api/quotes/{id}", "action": "quote_get", "task": "estimate"},
        {"path": "/api/quotes/{id}/csv", "action": "quote_csv", "task": "estimate"},
        {"path": "/api/boom", "action": "quote_list", "task": "estimate", "shape": "boom"},
    ]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("compat2")
    m = p2.make_world(tmp)
    code = m.tenant.code
    tb = m.tenant.path.parent
    cfg = yaml.safe_load(m.tenant.path.read_text(encoding="utf-8"))
    cfg["compat"] = {"routes": _routes(code), "input_rename": {"len": "x1"}, "entity_prefix": "OLD-"}
    m.tenant.path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (tb / code).mkdir(exist_ok=True)
    (tb / code / "compat.py").write_text(textwrap.dedent(PLUGIN), encoding="utf-8")
    samples = tmp / "packs" / p2.PACK / "samples"
    samples.mkdir()
    (samples / "sample.dxf").write_bytes(p2.sample_dxf())
    (samples / "demo.json").write_text(DEMO_JSON, encoding="utf-8")
    (tmp / "secret.json").write_text('{"x": 1}', encoding="utf-8")       # 팩 밖 — 경로 탈출 대상
    m = tenants.load_and_merge(code, tenants_base=tb, packs_base=tmp / "packs")
    ref, _ = h.to_production(m, p2.tid(m, "target_value"))
    k = h.keys(m)
    return m, k, ref


def _tc(m):
    return h.client(m)


def test_route_parse_and_match_prefers_literal():
    routes = cp2.parse_routes(["/api/x", {"path": "/api/q/{id}", "action": "quote_get", "task": "t"},
                               {"path": "/api/q/export", "action": "quote_export_csv", "task": "t"}])
    assert [r.action for r in routes] == ["quote_get", "quote_export_csv"]
    r, args = cp2.match(routes, "GET", "/api/q/export")
    assert r.action == "quote_export_csv" and args == {}
    r, args = cp2.match(routes, "GET", "/api/q/qte_1")
    assert r.action == "quote_get" and args == {"id": "qte_1"}
    assert cp2.match(routes, "POST", "/api/q/qte_1") is None
    for bad in ({"path": "/api/v1/x", "action": "health"}, {"path": "/api/x", "action": "nope"},
                {"path": "/api/x", "action": "quote_get"}, {"path": "/api/x{id}", "action": "health"},
                {"path": "/api/x", "action": "health", "extra": 1}):
        with pytest.raises(cp2.CompatConfigError):
            cp2.parse_route(bad)


def test_health_without_key_and_unknown_path_404(world):
    m, k, ref = world
    tc = _tc(m)
    assert tc.get("/api/health").status_code == 200
    r = tc.get("/api/not/configured", headers=h.hdr(k["admin"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_key_required_role_and_other_tenant(world):
    m, k, ref = world
    tc = _tc(m)
    r = tc.get("/api/quality/overview")
    assert r.status_code == 401 and set(r.json()) == {"detail"}
    assert tc.get("/api/quality/overview", headers=h.hdr(k["viewer"])).status_code == 403    # review 조회는 operator 이상
    other = p2.make_world(m.tenant.path.parent.parent / "other")
    ko = h.keys(other)
    assert tc.get("/api/quality/overview", headers=h.hdr(ko["admin"])).status_code == 404


def test_review_list_shaped_by_plugin(world):
    m, k, ref = world
    p2.review_item(m)
    r = _tc(m).get("/api/quality/overview", headers=h.hdr(k["operator"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_threshold"] == 4.0 and body["flagged_lots"] >= 1
    assert body["flagged"][0] == {"lot_id": "LOT-1", "absolute_error": 5.5}


def test_predict_one_uses_rename_and_standard_record(world):
    m, k, ref = world
    tc = _tc(m)
    r = tc.post("/api/quality/predict", headers=h.hdr(k["operator"]), json={"len": 40, "x2": 50, "c1": "A"})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"predicted", "status"}
    with connect() as c:
        row = c.execute("SELECT channel FROM mlp_prediction WHERE tenant_id=%s ORDER BY ts DESC LIMIT 1",
                        (m.tenant.code,)).fetchone()
    assert row["channel"] == "compat"
    bad = tc.post("/api/quality/predict", headers=h.hdr(k["operator"]), json={"x1": 40, "x2": 50, "c1": "A"})
    assert bad.status_code == 422 and all(set(d) == {"loc", "msg", "type"} for d in bad.json()["detail"])
    oob = tc.post("/api/quality/predict", headers=h.hdr(k["operator"]), json={"len": 400, "x2": 50, "c1": "A"})
    assert oob.status_code == 422 and oob.json()["detail"][0]["loc"] == ["body", "len"]      # 옛 키 이름으로


def test_samples_old_paging(world):
    m, k, ref = world
    r = _tc(m).get("/api/ml/samples", headers=h.hdr(k["viewer"]), params={"offset": 2})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["limit"] == 5 and b["offset"] == 2 and len(b["items"]) == 5 and b["total"] >= 7
    assert b["items"][0]["lot_id"].startswith("OLD-") and "len" in b["items"][0] and "target_value" in b["items"][0]
    bad = _tc(m).get("/api/ml/samples", headers=h.hdr(k["viewer"]), params={"limit": 0})
    assert bad.status_code == 422


def _up(tc, k, raw, name="a.dxf"):
    return tc.post("/api/cad/analyze", headers=h.hdr(k["operator"]), files={"file": (name, raw, "application/dxf")})


def test_document_upload_get_and_error_codes(world):
    m, k, ref = world
    tc = _tc(m)
    r = _up(tc, k, p2.sample_dxf())
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["doc_id"].startswith("doc_") and doc["labels"] == "none" and doc["metrics"] is None
    g = tc.get(f"/api/cad/{doc['doc_id']}", headers=h.hdr(k["operator"]))
    assert g.status_code == 200 and g.json()["doc_id"] == doc["doc_id"]
    assert tc.get("/api/cad/doc_NOPE", headers=h.hdr(k["operator"])).status_code == 404
    r415 = _up(tc, k, b"hello", name="a.txt")
    assert r415.status_code == 415 and r415.json() == {"detail": "옛 415 문구", "action": "document_upload"}  # shape_error
    r422 = _up(tc, k, b"not a dxf at all")
    assert r422.status_code == 422 and r422.json()["detail"][0]["type"] == "invalid_document"
    big = _up(tc, k, b"0" * (cp2.UPLOAD_CAP + 10))
    assert big.status_code == 413
    r413 = _up(tc, k, p2.dxf_bytes(extra_entities=20001))
    assert r413.status_code == 413 and r413.json()["code"] == "document_too_large"
    assert tc.post("/api/cad/analyze", headers=h.hdr(k["viewer"]),
                   files={"file": ("a.dxf", p2.sample_dxf(), "application/dxf")}).status_code == 403


def test_document_demo_and_pack_files(world):
    m, k, ref = world
    tc = _tc(m)
    d = tc.post("/api/cad/demo", headers=h.hdr(k["operator"]))
    assert d.status_code == 200, d.text
    assert d.json()["filename"] == "sample.dxf"
    f = tc.get("/api/cad/sample.dxf", headers=h.hdr(k["viewer"]))
    assert f.status_code == 200 and f.content == p2.sample_dxf() and f.headers["content-type"].startswith("application/dxf")
    j = tc.get("/api/data/demo", headers=h.hdr(k["viewer"]))
    assert j.status_code == 200 and j.json() == {"manifest": {"rows": 2}, "cad": [1, 2]}
    for bad in ("..%2Fsecret.json", "%2E%2E", ".hidden", "nope.json"):
        assert tc.get(f"/api/files/{bad}", headers=h.hdr(k["viewer"])).status_code == 404, bad
    assert tc.get("/api/files/demo.json", headers=h.hdr(k["viewer"])).status_code == 200


def test_quote_create_list_get_csv_export(world):
    m, k, ref = world
    tc = _tc(m)
    doc = _up(tc, k, p2.sample_dxf()).json()
    body = {"length": 81, "x2": 12.5, "grade": "A", "qty": 3, "drawing_id": doc["doc_id"], "reviewed": True,
            "review_note": "옛 화면 검토", "bom": [{"name": "브래킷", "material": "SS400", "quantity": 2, "mass_kg": 1.5}]}
    r = tc.post("/api/quotes", headers=h.hdr(k["operator"]), json=body)
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["state"] == "draft" and q["total_won"] > 0                       # 확정은 표준 경로 · 승인으로만
    assert q["overrides"] == [{"field": "x1", "recognized": 80.0, "confirmed": 81}]
    miss = tc.post("/api/quotes", headers=h.hdr(k["operator"]), json={"x2": 1})
    assert miss.status_code == 422 and miss.json()["detail"][0]["loc"] == ["body", "length"]
    g = tc.get(f"/api/quotes/{q['id']}", headers=h.hdr(k["operator"]))
    assert g.status_code == 200 and g.json()["quote_id"] == q["id"] and isinstance(g.json()["total"], str)
    lst = tc.get("/api/quotes", headers=h.hdr(k["operator"]), params={"limit": 1, "offset": 0}).json()
    assert set(lst) == {"total", "offset", "limit", "records"} and lst["total"] >= 1 and len(lst["records"]) == 1
    c1 = tc.get(f"/api/quotes/{q['id']}/csv", headers=h.hdr(k["operator"]))
    assert c1.status_code == 200 and c1.content.startswith("﻿".encode()) and q["id"].encode() in c1.content
    ex = tc.get("/api/quotes/export/csv", headers=h.hdr(k["operator"]))
    assert ex.status_code == 200 and ex.content.startswith("﻿".encode())
    rows = ex.content.decode("utf-8-sig").splitlines()
    assert rows[0].startswith("quote_id,status") and any(q["id"] in x for x in rows[1:])
    assert tc.get("/api/quotes/qte_NOPE", headers=h.hdr(k["operator"])).status_code == 404


def test_csv_injection_in_export(world):
    m, k, ref = world
    tc = _tc(m)
    body = {"length": 80, "x2": 10, "grade": "B", "qty": 1, "reviewed": True, "review_note": "=HYPERLINK(1)"}
    assert tc.post("/api/quotes", headers=h.hdr(k["operator"]), json=body).status_code == 200
    text = tc.get("/api/quotes/export/csv", headers=h.hdr(k["operator"])).content.decode("utf-8-sig")
    assert "'=HYPERLINK(1)" in text and ",=HYPERLINK" not in text


def test_plugin_failure_is_visible(world):
    m, k, ref = world
    r = _tc(m).get("/api/boom", headers=h.hdr(k["operator"]))
    assert r.status_code == 503 and r.json()["code"] == "compat_plugin_error" and "RuntimeError" in r.json()["detail"]


def test_plugin_outside_tenants_dir_rejected(world, tmp_path):
    m, k, ref = world
    outside = tmp_path / "evil.py"
    outside.write_text("def shape_quote_list(o, i):\n    return 1\n", encoding="utf-8")
    tb = tmp_path / "tb"
    (tb / "zz").mkdir(parents=True)
    (tb / "zz" / "compat.py").symlink_to(outside)

    class T:
        path = tb / "zz.yaml"
        code = "zz"

    class M:
        tenant = T()
    with pytest.raises(cp2.PluginError):
        cp2.load_plugin(M())


BAD_ROUTES = [
    ({"path": "/api/x", "action": "nope"}, "action"),
    ({"path": "/api/v1/x", "action": "health"}, "path"),
    ({"path": "/api/x", "method": "PUT", "action": "health"}, "method"),
    ({"path": "/api/x", "action": "quote_get", "task": "not_enabled"}, "켜져 있지 않다"),
    ({"path": "/api/x", "action": "quote_get", "task": "drawing"}, "유형"),
    ({"path": "/api/x", "action": "review_list", "task": "target_value"}, "유형"),
    ({"path": "/api/x", "action": "quote_get"}, "task"),
    ({"path": "/api/x", "action": "samples", "params": {"limit": 0}}, "limit"),
    ({"path": "/api/x", "action": "samples", "params": {"bogus": 1}}, "모르는 키"),
    ({"path": "/api/x", "action": "pack_file", "params": {"file": "../secret.json"}}, "file"),
    ({"path": "/api/x", "action": "pack_file"}, "params.file"),
    ({"path": "/api/x", "action": "quote_list", "task": "estimate", "shape": "Bad-Name"}, "shape"),
    ({"path": "/api/x/{id", "action": "health"}, "인자"),
]


@pytest.mark.parametrize("item,why", BAD_ROUTES, ids=[w for _, w in BAD_ROUTES])
def test_loader_rejects_bad_compat_routes(world, tmp_path, item, why):
    m, k, ref = world
    cfg = yaml.safe_load(m.tenant.path.read_text(encoding="utf-8"))
    tb = tmp_path / "tb2"
    tb.mkdir()
    cfg["compat"]["routes"] = ["/api/health", item]
    (tb / f"{m.tenant.code}.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(tenants.RegistryRejected) as e:
        tenants.load_and_merge(m.tenant.code, tenants_base=tb, packs_base=m.pack.path.parent)
    assert e.value.rule == "T0" and why in str(e.value), str(e.value)


def test_loader_rejects_duplicate_route(world, tmp_path):
    m, k, ref = world
    cfg = yaml.safe_load(m.tenant.path.read_text(encoding="utf-8"))
    tb = tmp_path / "tb3"
    tb.mkdir()
    r = {"path": "/api/quotes", "method": "GET", "action": "quote_list", "task": "estimate"}
    cfg["compat"]["routes"] = [r, dict(r)]
    (tb / f"{m.tenant.code}.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(tenants.RegistryRejected):
        tenants.load_and_merge(m.tenant.code, tenants_base=tb, packs_base=m.pack.path.parent)


def test_unchecked_bad_config_still_visible_503(world):
    """로더를 거치지 않은 설정 결함도 숨기지 않는다(라우터 503 compat_config_error)."""
    import dataclasses
    m, k, ref = world
    cfg = {**m.tenant.config, "compat": {**m.tenant.config["compat"],
                                         "routes": ["/api/health", {"path": "/api/x", "action": "nope"}]}}
    bad = dataclasses.replace(m, tenant=dataclasses.replace(m.tenant, config=cfg))
    tc = h.client(bad)
    assert tc.get("/api/health").status_code == 200
    r = tc.get("/api/x", headers=h.hdr(k["admin"]))
    assert r.status_code == 503 and r.json()["code"] == "compat_config_error"
