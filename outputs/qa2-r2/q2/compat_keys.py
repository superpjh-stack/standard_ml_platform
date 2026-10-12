"""QA2-2 — 호환 라우터 옛 키 실측 (krs · pc · ot · kd). 프로젝트 파일은 바꾸지 않는다.

실행 (프로젝트 루트에서):
  MLP_TEST_DB_DSN="dbname=ml_qa2r2_db host=/tmp" MLP_DB_DSN="dbname=ml_qa2r2_db host=/tmp" OMP_NUM_THREADS=1 \
    .venv/bin/python outputs/qa2-r2/q2/compat_keys.py
결과: outputs/qa2-r2/q2/compat_keys-result.json
방식: tests/test_compat.py 의 2차 4개사 fixture 와 같다(make_tenant → tenants/<code>/compat.py · samples 복사 →
use_tenants_dir 안에서 real_production → keys → client). 서버 기동 없음(TestClient in-process).
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

import _dev2 as h  # noqa: E402

EXP = yaml.safe_load((ROOT / "tests" / "compat_expected.yaml").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent / "compat_keys-result.json"
TMP = Path(tempfile.mkdtemp(prefix="qa22-compat-"))
RESULT: dict = {"errors_500": [], "companies": {}}


def _copy_tenant_files(source: str, m) -> None:
    d = h.tenants_base(m) / m.tenant.code
    d.mkdir(exist_ok=True)
    shutil.copy(ROOT / "tenants" / source / "compat.py", d / "compat.py")
    if (ROOT / "tenants" / source / "samples").is_dir():
        shutil.copytree(ROOT / "tenants" / source / "samples", d / "samples", dirs_exist_ok=True)


def _types(d: dict) -> dict:
    return {k: type(v).__name__ for k, v in d.items()}


def _first_keys(v):
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return list(v[0])
    if isinstance(v, dict):
        return list(v)
    return None


def _scalar_sample(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:120]
    return out


class Rec:
    def __init__(self, code: str):
        self.code = code
        self.routes: dict = {}
        RESULT["companies"][code] = self.routes

    def add(self, name: str, r, nested: tuple = (), keep: bool = False) -> dict | None:
        ent = {"status": r.status_code, "content_type": r.headers.get("content-type", "")}
        if r.status_code >= 500:
            RESULT["errors_500"].append({"company": self.code, "route": name, "status": r.status_code, "body": r.text[:300]})
        body = None
        if "json" in ent["content_type"]:
            body = r.json()
            if isinstance(body, dict):
                ent["keys"] = list(body)
                ent["types"] = _types(body)
                ent["scalars"] = _scalar_sample(body)
                for n in nested:
                    cur = body
                    for part in n.split("."):
                        cur = cur.get(part) if isinstance(cur, dict) else None
                    ent[f"{n}.keys"] = _first_keys(cur)
                    if isinstance(cur, list) and cur and isinstance(cur[0], dict):
                        ent[f"{n}[0].types"] = _types(cur[0])
                        ent[f"{n}[0].scalars"] = _scalar_sample(cur[0])
                        ent[f"{n}.len"] = len(cur)
                    elif isinstance(cur, dict):
                        ent[f"{n}.types"] = _types(cur)
                        ent[f"{n}.scalars"] = _scalar_sample(cur)
                if keep or r.status_code >= 400:
                    ent["body"] = json.loads(json.dumps(body, ensure_ascii=False)[:1500]) if len(json.dumps(body)) < 1500 else str(body)[:1500]
            else:
                ent["body"] = str(body)[:600]
        elif "csv" in ent["content_type"]:
            text = r.content.decode("utf-8-sig")
            ent["bom"] = r.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(io.StringIO(text)))
            ent["csv_first_col"] = [x[0] if x else "" for x in rows][:60]
            ent["csv_rows"] = rows[:3]
            ent["content_disposition"] = r.headers.get("content-disposition")
        else:
            ent["len"] = len(r.content)
            ent["content_disposition"] = r.headers.get("content-disposition")
        self.routes.setdefault(name, []).append(ent)
        return body


def auth_checks(rec: Rec, tc, method: str, url: str, other_key: str, **kw):
    """키 없음 → 401 옛 모양, 다른 회사 키 → 404."""
    f = tc.get if method == "GET" else tc.post
    rec.add(f"AUTH nokey {method} {url}", f(url, **kw))
    rec.add(f"AUTH otherco {method} {url}", f(url, headers=h.hdr(other_key), **kw))


# ── 다른 회사(키 범위 시험용) ─────────────────────────────────────────────
OTHER = h.make_tenant("pc", TMP / "other")
OTHER_KEY = h.keys(OTHER)["admin"]


def run_krs():
    e = EXP["krs"]
    m = h.make_tenant("krs", TMP / "krs")
    _copy_tenant_files("krs", m)
    rec = Rec("krs")
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        rec.add("GET /api/health (before production)", tc.get("/api/health"), keep=True)
        ref, _ = h.real_production(m, f"{m.tenant.code}.joint_strength")
        RESULT.setdefault("models", {})["krs"] = {"version": ref.version, "algo": ref.algo}
        rec.add("GET /api/health", tc.get("/api/health"), keep=True)
        rec.add("GET /api/ml/overview", tc.get("/api/ml/overview", headers=h.hdr(k["viewer"])),
                nested=("quality", "models", "features", "target"))
        rec.add("GET /api/ml/samples", tc.get("/api/ml/samples", headers=h.hdr(k["viewer"])), nested=("items",))
        rec.add("GET /api/ml/samples?limit=0", tc.get("/api/ml/samples?limit=0", headers=h.hdr(k["viewer"])))
        rec.add("POST /api/ml/optimize", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]), json=e["optimize_payload"]),
                nested=("composition", "process"), keep=True)
        rec.add("POST /api/ml/optimize {}", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]), json={}), keep=True)
        rec.add("POST /api/ml/optimize target 500", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]),
                                                           json={"target_strength": 500}))
        rec.add("POST /api/quality/predict", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]), json=e["predict_record"]), keep=True)
        rec.add("POST /api/quality/predict temp262", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                             json={**e["predict_record"], "temperature_c": 262}), keep=True)
        rec.add("POST /api/quality/predict unbalanced", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                                json={**e["predict_record"], **e["predict_unbalanced"]}))
        rec.add("POST /api/quality/predict missing sn_pct", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                json={kk: v for kk, v in e["predict_record"].items() if kk != "sn_pct"}))
        rec.add("POST /api/quality/predict supplier D", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                                json={**e["predict_record"], "supplier": "D"}))
        from mlcore.monitor import review as job
        rec.add("GET /api/quality/overview (empty)", tc.get("/api/quality/overview", headers=h.hdr(k["operator"])), keep=True)
        job.run_review(m.tenant.code, date(2026, 10, 4), merged=m)
        rec.add("GET /api/quality/overview", tc.get("/api/quality/overview", headers=h.hdr(k["operator"])), nested=("flagged",))
        rec.add("GET /api/data/records", tc.get("/api/data/records", headers=h.hdr(k["viewer"])), nested=("items", "summary"))
        rec.add("GET /api/data/records?supplier=B&state=결측", tc.get("/api/data/records", headers=h.hdr(k["viewer"]),
                                                               params={"supplier": "B", "state": "결측", "limit": 5}),
                nested=("items", "summary"))
        for q in e["records_bad_queries"]:
            rec.add(f"GET /api/data/records?{q}", tc.get(f"/api/data/records?{q}", headers=h.hdr(k["viewer"])))
        for meth, url in [("GET", "/api/ml/overview"), ("GET", "/api/ml/samples"), ("GET", "/api/quality/overview"),
                          ("GET", "/api/data/records")]:
            auth_checks(rec, tc, meth, url, OTHER_KEY)
        auth_checks(rec, tc, "POST", "/api/quality/predict", OTHER_KEY, json=e["predict_record"])
        auth_checks(rec, tc, "POST", "/api/ml/optimize", OTHER_KEY, json=e["optimize_payload"])


def run_pc():
    e = EXP["pc"]
    m = h.make_tenant("pc", TMP / "pc")
    _copy_tenant_files("pc", m)
    rec = Rec("pc")
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        rec.add("GET /api/health (before production)", tc.get("/api/health"), keep=True)
        ref, _ = h.real_production(m, f"{m.tenant.code}.sensory_score")
        RESULT.setdefault("models", {})["pc"] = {"version": ref.version, "algo": ref.algo}
        rec.add("GET /api/health", tc.get("/api/health"), keep=True)
        rec.add("GET /api/ml/overview", tc.get("/api/ml/overview", headers=h.hdr(k["viewer"])), nested=("metrics", "target"))
        rec.add("POST /api/ml/optimize", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]), json=e["optimize_payload"]),
                nested=("settings", "context"), keep=True)
        rec.add("POST /api/ml/optimize infeasible", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]),
                                                             json=e["optimize_infeasible"]), keep=True)
        rec.add("POST /api/ml/optimize missing target", tc.post("/api/ml/optimize", headers=h.hdr(k["operator"]),
                                                                json={"max_material_cost": 85}))
        rec.add("POST /api/quality/predict", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]), json=e["valid_record"]), keep=True)
        rec.add("POST /api/quality/predict warn", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                          json={**e["valid_record"], **e["recipe_warn"]}), keep=True)
        rec.add("POST /api/quality/predict reject", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                            json={**e["valid_record"], **e["recipe_reject"]}))
        rec.add("POST /api/quality/predict line K3", tc.post("/api/quality/predict", headers=h.hdr(k["operator"]),
                                                             json={**e["valid_record"], "line": "K3"}))
        from mlcore.monitor import review as job
        rec.add("GET /api/quality/overview (empty)", tc.get("/api/quality/overview", headers=h.hdr(k["operator"])), keep=True)
        job.run_review(m.tenant.code, date(2026, 10, 3), merged=m)
        rec.add("GET /api/quality/overview", tc.get("/api/quality/overview", headers=h.hdr(k["operator"])), nested=("priority_queue",))
        rec.add("GET /api/data/records", tc.get("/api/data/records", headers=h.hdr(k["viewer"])), nested=("records",))
        rec.add("GET /api/data/records?filters", tc.get(f"/api/data/records?{e['records_query']}", headers=h.hdr(k["viewer"])),
                nested=("records",))
        for q in e["records_bad_queries"] + ["search=" + "x" * 31]:
            rec.add(f"GET /api/data/records?{q[:40]}", tc.get(f"/api/data/records?{q}", headers=h.hdr(k["viewer"])))
        for meth, url in [("GET", "/api/ml/overview"), ("GET", "/api/quality/overview"), ("GET", "/api/data/records")]:
            auth_checks(rec, tc, meth, url, OTHER_KEY)
        auth_checks(rec, tc, "POST", "/api/quality/predict", OTHER_KEY, json=e["valid_record"])
        auth_checks(rec, tc, "POST", "/api/ml/optimize", OTHER_KEY, json=e["optimize_payload"])


def run_ot():
    e = EXP["ot"]
    overrides = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
                 for p in sorted((ROOT / "tenants" / "ot" / "tasks").glob("*.yaml"))}
    m = h.make_tenant("ot", TMP / "ot", overrides=overrides)
    _copy_tenant_files("ot", m)
    rec = Rec("ot")
    other_ot = h.make_tenant("kd", TMP / "ot-other")
    other_key = h.keys(other_ot)["admin"]
    with h.use_tenants_dir(m):
        ref, _ = h.real_production(m, f"{m.tenant.code}.machining_minutes")
        h.real_production(m, f"{m.tenant.code}.cad_objects")
        RESULT.setdefault("models", {})["ot"] = {"version": ref.version, "algo": ref.algo}
        k, tc = h.keys(m), h.client(m)
        op = h.hdr(k["operator"])
        rec.add("GET /api/health", tc.get("/api/health"), keep=True)
        rec.add("GET /api/ml/overview", tc.get("/api/ml/overview", headers=h.hdr(k["viewer"])),
                nested=("metrics", "test_metrics", "split", "features", "features.length"))
        rec.add("GET /api/data/demo", tc.get("/api/data/demo", headers=h.hdr(k["viewer"])), nested=("manifest", "cad", "quotes"))
        s = tc.get("/api/cad/sample.dxf", headers=h.hdr(k["viewer"]))
        rec.add("GET /api/cad/sample.dxf", s)
        d = rec.add("POST /api/cad/demo", tc.post("/api/cad/demo", headers=op), nested=("objects", "counts", "dimensions"))
        rec.add("GET /api/cad/{id}", tc.get(f"/api/cad/{d['id']}", headers=op), nested=("objects",))
        rec.add("GET /api/cad/{unknown}", tc.get("/api/cad/unknown", headers=op))
        rec.add("POST /api/cad/analyze", tc.post("/api/cad/analyze", headers=op, files={"file": ("../../part.dxf", s.content)}),
                nested=("objects",), keep=False)
        rec.add("POST /api/cad/analyze a.dwg", tc.post("/api/cad/analyze", headers=op, files={"file": ("a.dwg", s.content)}))
        rec.add("POST /api/cad/analyze bad.dxf", tc.post("/api/cad/analyze", headers=op, files={"file": ("bad.dxf", b"not DXF")}))
        rec.add("POST /api/cad/analyze big", tc.post("/api/cad/analyze", headers=op,
                                                     files={"file": ("large.dxf", b"0" * (5 * 1024 * 1024 + 1))}))
        payload = {**e["quote_payload"], "drawing_id": d["id"], "holes": 7}
        q = rec.add("POST /api/quotes", tc.post("/api/quotes", headers=op, json=payload), nested=("input", "assumptions", "overrides"))
        rec.add("POST /api/quotes review_note 5 spaces", tc.post("/api/quotes", headers=op, json={**payload, "review_note": "     "}))
        rec.add("POST /api/quotes extra", tc.post("/api/quotes", headers=op, json={**payload, "extra": 1}))
        rec.add("POST /api/quotes unknown drawing", tc.post("/api/quotes", headers=op,
                                                             json={**payload, "drawing_id": "doc_01M4RNXVMPYNZGXXNWJZ6CP01R"}))
        rec.add("POST /api/quotes malformed drawing id", tc.post("/api/quotes", headers=op, json={**payload, "drawing_id": "CAD-0123456789ab"}))
        rec.add("GET /api/quotes", tc.get("/api/quotes", headers=op), nested=("records",))
        rec.add("GET /api/quotes?limit=101", tc.get("/api/quotes?limit=101", headers=op))
        rec.add("GET /api/quotes/{id}", tc.get(f"/api/quotes/{q['id']}", headers=op), nested=("input",))
        rec.add("GET /api/quotes/{unknown}", tc.get("/api/quotes/unknown", headers=op))
        rec.add("GET /api/quotes/{id}/csv", tc.get(f"/api/quotes/{q['id']}/csv", headers=op))
        rec.add("GET /api/quotes/{unknown}/csv", tc.get("/api/quotes/unknown/csv", headers=op))
        for meth, url in [("GET", "/api/ml/overview"), ("GET", "/api/data/demo"), ("GET", "/api/cad/sample.dxf"),
                          ("POST", "/api/cad/demo"), ("GET", f"/api/cad/{d['id']}"), ("GET", "/api/quotes"),
                          ("GET", f"/api/quotes/{q['id']}"), ("GET", f"/api/quotes/{q['id']}/csv")]:
            auth_checks(rec, tc, meth, url, other_key)
        auth_checks(rec, tc, "POST", "/api/quotes", other_key, json=payload)
        auth_checks(rec, tc, "POST", "/api/cad/analyze", other_key, files={"file": ("a.dxf", s.content)})


def run_kd():
    e = EXP["kd"]
    m = h.make_tenant("kd", TMP / "kd")
    _copy_tenant_files("kd", m)
    rec = Rec("kd")
    with h.use_tenants_dir(m):
        ref, _ = h.real_production(m, f"{m.tenant.code}.labor_hours")
        RESULT.setdefault("models", {})["kd"] = {"version": ref.version, "algo": ref.algo}
        k, tc = h.keys(m), h.client(m)
        op = h.hdr(k["operator"])
        rec.add("GET /api/health", tc.get("/api/health"), keep=True)
        rec.add("GET /api/ml/overview", tc.get("/api/ml/overview", headers=h.hdr(k["viewer"])),
                nested=("metrics", "test_metrics", "features", "features.mass_kg", "recognition"))
        s = tc.get("/api/cad/sample.dxf", headers=h.hdr(k["viewer"]))
        rec.add("GET /api/cad/sample.dxf", s)
        demo = rec.add("POST /api/cad/demo", tc.post("/api/cad/demo", headers=op), nested=("objects", "bom", "counts"))
        d = rec.add("POST /api/cad/analyze", tc.post("/api/cad/analyze", headers=op, files={"file": ("KD-demo-reactor.dxf", s.content)}),
                    nested=("objects", "bom", "counts"))
        rec.add("GET /api/cad/{id}", tc.get(f"/api/cad/{d['id']}", headers=op), nested=("objects", "bom"))
        rec.add("GET /api/cad/{demo id}", tc.get(f"/api/cad/{demo['id']}", headers=op), keep=False)
        rec.add("GET /api/cad/{unknown}", tc.get("/api/cad/doc_NOPE", headers=op))
        rec.add("POST /api/cad/analyze x.dwg", tc.post("/api/cad/analyze", headers=op, files={"file": ("x.dwg", b"bad")}))
        rec.add("POST /api/cad/analyze bad.dxf", tc.post("/api/cad/analyze", headers=op, files={"file": ("x.dxf", b"bad")}))
        rec.add("POST /api/cad/analyze big", tc.post("/api/cad/analyze", headers=op,
                                                     files={"file": ("x.dxf", b"x" * (5 * 1024 * 1024 + 1))}))
        data = {**e["quote_input"], "drawing_id": d["id"],
                "bom": [{**{kk: r[kk] for kk in ("name", "material", "quantity", "mass_kg")}, "price_kg": e["price_kg"][r["material"]]}
                        for r in d["bom"]]}
        q = rec.add("POST /api/quotes", tc.post("/api/quotes", headers=op, json=data),
                    nested=("lines", "features", "cost_snapshot", "input", "source_bom"))
        rec.add("POST /api/quotes material not in bom", tc.post("/api/quotes", headers=op, json={**data, "material": "AL6061"}))
        rec.add("POST /api/quotes review_note spaces", tc.post("/api/quotes", headers=op, json={**data, "review_note": "     "}))
        rec.add("POST /api/quotes unknown drawing", tc.post("/api/quotes", headers=op, json={**data, "drawing_id": "doc_NOPE"}))
        rec.add("POST /api/quotes wellformed unknown drawing", tc.post("/api/quotes", headers=op,
                json={**data, "drawing_id": "doc_01M4RNXVMPYNZGXXNWJZ6CP01R"}))
        rec.add("POST /api/quotes CAD-style drawing id", tc.post("/api/quotes", headers=op, json={**data, "drawing_id": "CAD-0123456789ab"}))
        rec.add("GET /api/quotes", tc.get("/api/quotes", headers=op), nested=("records",))
        rec.add("GET /api/quotes?offset=-1", tc.get("/api/quotes?offset=-1", headers=op))
        rec.add("GET /api/quotes/export/csv", tc.get("/api/quotes/export/csv", headers=op))
        rec.add("GET /api/quotes/{id}", tc.get(f"/api/quotes/{q['id']}", headers=op), nested=("lines",))
        rec.add("GET /api/quotes/{unknown}", tc.get("/api/quotes/missing", headers=op))
        rec.add("GET /api/quotes/{id}/csv", tc.get(f"/api/quotes/{q['id']}/csv", headers=op))
        for meth, url in [("GET", "/api/ml/overview"), ("GET", "/api/cad/sample.dxf"), ("POST", "/api/cad/demo"),
                          ("GET", f"/api/cad/{d['id']}"), ("GET", "/api/quotes"), ("GET", "/api/quotes/export/csv"),
                          ("GET", f"/api/quotes/{q['id']}"), ("GET", f"/api/quotes/{q['id']}/csv")]:
            auth_checks(rec, tc, meth, url, OTHER_KEY)
        auth_checks(rec, tc, "POST", "/api/quotes", OTHER_KEY, json=data)
        auth_checks(rec, tc, "POST", "/api/cad/analyze", OTHER_KEY, files={"file": ("a.dxf", s.content)})


if __name__ == "__main__":
    assert h.db_ok(), "DB 없음"
    for fn in (run_krs, run_pc, run_ot, run_kd):
        try:
            fn()
        except Exception:  # noqa: BLE001
            RESULT.setdefault("script_errors", []).append({"fn": fn.__name__, "tb": traceback.format_exc()[-2000:]})
        OUT.write_text(json.dumps(RESULT, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote", OUT, "500s:", len(RESULT["errors_500"]), "script_errors:", len(RESULT.get("script_errors", [])))
