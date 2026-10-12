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
    NUL = "a\u0000b"
    n0 = count("mlp_quote", "tenant_id=%s", (t,))
    a0 = count("mlp_audit", "tenant_id=%s", (t,))
    tests = [("quote line name", "POST", f"{Q}/quotes", body(one(name=NUL))),
             ("quote review_note", "POST", f"{Q}/quotes", {**body(), "review_note": "검토 " + NUL}),
             ("quote inputs product_family", "POST", f"{Q}/quotes", body(product_family=NUL)),
             ("quote line material", "POST", f"{Q}/quotes", body(one(material=NUL))),
             ("quote 키 이름 NUL", "POST", f"{Q}/quotes", body([{**L[0], NUL: 1}] + L[1:])),
             ]
    base = jpost(f"{Q}/quotes", "operator", body()).json()
    tests += [("revision line name", "POST", f"{Q}/quotes/{base['quote_id']}/revisions", body(one(name=NUL))),
              ("confirm review_note", "POST", f"{Q}/quotes/{base['quote_id']}/confirm", {"reviewed": True, "review_note": "확정 요청 " + NUL})]
    U = f"/api/v1/tenants/{t}/tasks/{t}.labor_hours"
    tests += [("predict entity_id", "POST", f"{U}/predict", {"inputs": {}, "entity_id": NUL}),
              ("actuals entity_id", "POST", f"{U}/actuals", {"entity_id": NUL, "value": 1.0, "observed_at": "2026-10-13T10:00:00+09:00"}),
              ("old quote bom name", "POST", "/api/quotes", {**old, "bom": [{**old["bom"][0], "name": NUL}] + old["bom"][1:]}),
              ("old quote review_note", "POST", "/api/quotes", {**old, "review_note": "옛 검토 " + NUL})]
    for label, meth, url, b in tests:
        r = jpost(url, "operator", b)
        rec("r2-NUL", label, r.status_code == 422 or r.status_code == 403, {"status": r.status_code, "err": err(r)[1:]}, 422)
    r = jpost(f"{Q}/quotes/{base['quote_id']}/confirm", "operator", {"reviewed": True, "review_note": "확정 요청 정상"})
    rec("r2-NUL", "NUL 500 뒤 정상 확정 요청(부분 상태 없음)", r.status_code == 202, {"status": r.status_code, "err": err(r)[1:]}, 202)
    good = {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": "STS304", "product_family": "반응기", "total_mass_kg": 300}
    r = jpost(f"{U}/predict", "operator", {"inputs": good, "entity_id": NUL})
    rec("r2-NUL", "predict entity_id(완전한 입력)", r.status_code == 422, {"status": r.status_code, "err": err(r)[1:]}, 422)
    rec("r2-NUL", "quote 행 증가(정상 1건 외)", "INFO", {"delta": count("mlp_quote", "tenant_id=%s", (t,)) - n0})
    # 대기열 검토 메모 NUL 은 krs 과제가 필요 — 별도
    save("probe_nul_r2-result.json")


if __name__ == "__main__":
    main()
