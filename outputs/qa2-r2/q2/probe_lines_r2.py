"""[r2 원본 머리] QA2-2 §C 견적 float 경로(런타임) · §D 확정 뒤 금액 변경 · §E input_limits 경계 · §F CSV 수식 주입 · §G 역할 · 회사 범위 · 감사.
고치지 않는다. 결과 → probe_quote-result.json"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from common import ROOT, client, count, h, rec, save

D = Decimal


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def floats_in(v, path="$"):
    out = []
    if type(v).__name__ == "float" or (hasattr(v, "dtype") and "float" in str(getattr(v, "dtype", ""))):
        out.append(path)
    elif isinstance(v, dict):
        for k, x in v.items():
            out += floats_in(x, f"{path}.{k}")
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            out += floats_in(x, f"{path}[{i}]")
    return out


def main():
    base = Path(tempfile.mkdtemp(prefix="qa22-quote-"))
    m = h.make_tenant("kd", base / "a")
    t = m.tenant.code
    import shutil
    tdir = m.tenant.path.parent / t
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "tenants" / "kd" / "compat.py", tdir / "compat.py")       # 옛 경로 플러그인(시험 회사 폴더로 복사)
    shutil.copytree(ROOT / "tenants" / "kd" / "samples", tdir / "samples")
    k = h.keys(m)
    tc = client(m)
    with h.use_tenants_dir(m):
        h.real_production(m, f"{t}.labor_hours")
    mats = m.tenant.config["categories"]["main_material"]
    sample = load("packs/eto/synth/sample_dxf.py", "qa22q_sample").sample_bytes(mats)
    r = tc.post(f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": ("sample.dxf", sample, "application/dxf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    Q = f"/api/v1/tenants/{t}/tasks/{t}.quote"

    def jpost(url, key, body, raw=None):
        return tc.post(url, headers={**h.hdr(k[key] if key in k else key), "Content-Type": "application/json"},
                       content=raw if raw is not None else json.dumps(body, ensure_ascii=False))

    def lines(price="6500"):
        return [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"],
                 "price_kg": price} for b in doc["bom_rows"]]

    def body(ls=None, **kw):
        inputs = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": doc["bom_rows"][0]["material"],
                  "product_family": "반응기", "quantity": 1, "labor_rate": 45000, "outsource_cost": 0}
        inputs.update(kw)
        return {"doc_id": doc["doc_id"], "inputs": inputs, "lines": lines() if ls is None else ls,
                "reviewed": True, "review_note": "QA 검토 견적"}

    def err(r):
        try:
            e = r.json().get("error") or {}
        except ValueError:
            return (r.status_code, None, None)
        return (r.status_code, e.get("code"), (e.get("detail") or {}).get("field") or (e.get("detail") or {}).get("rule"))


    old = {"drawing_id": doc["doc_id"], "product": "반응기", "material": doc["bom_rows"][0]["material"],
           "bom": [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"], "price_kg": 6500}
                   for b in doc["bom_rows"]],
           "quantity": 1, "cut_m": 24.5, "weld_m": 18.25, "thickness_mm": 6.0, "complexity": 3.0, "labor_rate": 45000,
           "outsource_cost": 0, "reviewed": True, "review_note": "옛 경로 검토"}
    L = lines()
    one = lambda **kw: [{**L[0], **kw}] + L[1:]
    C = [
        ("name 80자", body(one(name="가" * 80)), 201), ("name 81자", body(one(name="가" * 81)), 422),
        ("name 빈 문자열", body(one(name="")), 422), ("name 공백만", body(one(name="   ")), 422),
        ("name 숫자형", body(one(name=123)), 422), ("name null", body(one(name=None)), 422),
        ("quantity 1000", body(one(quantity=1000)), 201), ("quantity 1001", body(one(quantity=1001)), 422),
        ("quantity 1.0", body(one(quantity=1.0)), None), ("quantity '5'", body(one(quantity="5")), None),
        ("quantity true", body(one(quantity=True)), 422), ("quantity 리스트", body(one(quantity=[1])), 422),
        ("mass_kg 0.01", body(one(mass_kg=0.01)), 201), ("mass_kg 0.009", body(one(mass_kg=0.009)), 422),
        ("mass_kg 10000", body(one(mass_kg=10000)), 201), ("mass_kg 10000.01", body(one(mass_kg=10000.01)), 422),
        ("mass_kg -0.0", body(one(mass_kg=-0.0)), 422),
        ("price_kg 1000000", body(one(price_kg=1000000)), 201), ("price_kg 1000000.01", body(one(price_kg=1000000.01)), 422),
        ("price_kg 'NaN'", body(one(price_kg="NaN")), 422), ("price_kg 'Infinity'", body(one(price_kg="Infinity")), 422),
        ("price_kg '1e3'", body(one(price_kg="1e3")), None), ("price_kg '-0'", body(one(price_kg="-0")), None),
        ("price_kg ' 6500 '", body(one(price_kg=" 6500 ")), None),
        ("material 별칭(소문자 sts304)", body(one(material="sts304")), None), ("material 별칭 키", body(one(material=next(iter(m.tenant.config.get("material_aliases") or {"x": 1})))), 201),
        ("material null", body(one(material=None)), 422), ("material 빈", body(one(material="")), 422),
        ("품목 100행", body((L * 100)[:100]), 201), ("품목 101행", body((L * 101)[:101]), 422),
        ("품목 lines null", {**body(), "lines": None}, None), ("품목 lines 객체", {**body(), "lines": {"a": 1}}, 422),
        ("품목 행이 문자열", body(["x"]), 422), ("품목 amount 키(금액 직접)", body(one(amount="-1000000")), 422),
        ("품목 weight_total 키", body(one(weight_total="0")), 422), ("품목 키 대소문자 Price_kg", body([{**{k2: v for k2, v in L[0].items() if k2 != "price_kg"}, "Price_kg": "1"}] + L[1:]), 422),
        ("품목 중첩 객체 값", body(one(price_kg={"v": 1})), 422),
        ("품목 이름 NUL", body(one(name="a\u0000b")), None),
        ("inputs 모르는 키(discount)", body(discount=-99999), None),
    ]
    for label, b, want in C:
        r = jpost(f"{Q}/quotes", "operator", b)
        got = err(r)
        js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        tot = js.get("total") if r.status_code == 201 else None
        saved = None
        if r.status_code == 201:
            saved = [(x.get("name", "")[:6], x.get("material"), x.get("quantity"), x.get("price_kg"), x.get("amount")) for x in (js.get("lines") or [])[:1]]
        ok = (r.status_code == want) if want else ("INFO" if r.status_code in (201, 422) else False)
        rec("r2-Q", f"create · {label}", ok, {"status": r.status_code, "code": got[1], "field": got[2], "total": tot, "saved": saved}, want)
    # 수정(revision) 경로도 같은 검사인가
    base = jpost(f"{Q}/quotes", "operator", body()).json()
    qid = base["quote_id"]
    for label, b, want in [("rev 음수 단가", body(one(price_kg="-6500")), 422), ("rev 단가 1e12", body(one(price_kg="1000000000000")), 422),
                           ("rev 수량 1.5", body(one(quantity=1.5)), 422), ("rev 모르는 키", body(one(discount="1")), 422),
                           ("rev 재질 목록 밖", body(one(material="UNOBTAINIUM")), 422), ("rev 0행", body([]), 422),
                           ("rev 정상", body(one(price_kg="7000")), 201)]:
        r = jpost(f"{Q}/quotes/{qid}/revisions", "operator", b)
        rec("r2-Q", f"revision · {label}", r.status_code == want, {"status": r.status_code, "err": err(r)[1:]}, want)
    # 옛 경로 POST /api/quotes (kd) — 원천 BomRow 와 같은 422 인가
    for label, mut, want in [("old 음수 단가", {"price_kg": -6500}, 422), ("old 단가 1e12", {"price_kg": 1e12}, 422),
                             ("old 수량 1.5", {"quantity": 1.5}, 422), ("old 재질 목록 밖", {"material": "UNOBTAINIUM"}, 422),
                             ("old 모르는 키", {"discount": 1}, 422), ("old 이름 81자", {"name": "가" * 81}, 422),
                             ("old 정상", {}, 200)]:
        o2 = {**old, "bom": [{**old["bom"][0], **mut}] + old["bom"][1:]}
        r = tc.post("/api/quotes", headers={**h.hdr(k["operator"]), "Content-Type": "application/json"}, content=json.dumps(o2))
        try:
            jj = r.json()
        except ValueError:
            jj = r.text[:120]
        rec("r2-Q", f"old · {label}", r.status_code == want, {"status": r.status_code, "body": str(jj)[:200]}, want)
    # 음수 금액 — 회사 단가표 덮어쓰기로 할인(markup 음수)일 때
    save("probe_lines_r2-result.json")


if __name__ == "__main__":
    main()
