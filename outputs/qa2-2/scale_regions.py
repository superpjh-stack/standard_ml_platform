"""cad_regions 최악 꼴 실측(상한 절반 10,000 엔티티) + ot geometry contains 최악 꼴 — 직접 호출(서버 없음)."""
import json, math, sys, time, tracemalloc
from common import ROOT, circle, dxf, rect, text
import importlib.util
def load(rel, name):
    s = importlib.util.spec_from_file_location(name, ROOT / rel); m = importlib.util.module_from_spec(s); sys.modules[name] = m; s.loader.exec_module(m); return m
out = {}
reg = load("packs/eto/extractors/cad_regions.py", "q_reg"); bom = load("packs/eto/extractors/bom_text.py", "q_bom")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
ents = []
for i in range(n): ents += rect(-i - 1, -i - 1, 2 * i + 2, 2 * i + 2, "BOM")
for i in range(n): ents += text("BOM", i + 0.5, 0, "BOM")
raw = dxf(ents)
t0 = time.perf_counter(); res = reg.extract(raw, "x.dxf", unit="mm", limits={"max_entities": 20000}); t1 = time.perf_counter()
js = len(json.dumps(res["regions"], ensure_ascii=False)); t2 = time.perf_counter()
bom.extract(raw, "x.dxf", unit="mm", limits={"max_entities": 20000}, context={}); t3 = time.perf_counter()
out["cad_regions"] = {"entities": 2 * n, "file_MB": round(len(raw) / 2**20, 2), "cad_regions_sec": round(t1 - t0, 1), "bom_text_sec": round(t3 - t2, 1),
                      "regions": len(res["regions"]), "regions_json_MB": round(js / 2**20, 1)}
geo = load("packs/rollform-quote/extractors/geometry_objects.py", "q_geo")
prm = {"max_vertices": 500, "flatten_mm": 0.2, "flatten_segments": 8, "max_points_entity": 2000, "max_points": 60000, "coord_limit": 10000000, "aspect_cap": 1000}
ents = [(0, "LWPOLYLINE"), (8, "O"), (90, "500"), (70, "1")]
for i in range(500):
    a = 2 * math.pi * i / 500
    ents += [(10, repr(500 * math.cos(a))), (20, repr(500 * math.sin(a))), ]
for i in range(1999):
    ents += [(0, "LWPOLYLINE"), (8, "H"), (90, "27"), (70, "1")]
    cx, cy = -300 + (i % 45) * 13, -300 + (i // 45) * 13
    for j in range(27):
        a = 2 * math.pi * j / 27
        ents += [(10, repr(cx + 3 * math.cos(a))), (20, repr(cy + 3 * math.sin(a)))]
raw = dxf(ents)
t0 = time.perf_counter()
try:
    r = geo.extract(raw, "x.dxf", unit="mm", limits={"max_entities": 2000}, context={"params": prm})
    info = {"objects": len(r["objects"]), "outer_pts": max(len(o["points"]) for o in r["objects"]), "total_pts": sum(len(o["points"]) for o in r["objects"])}
except Exception as e:
    info = {"error": f"{type(e).__name__} {getattr(e,'rule','')}"}
out["ot_geometry"] = {**info, "sec": round(time.perf_counter() - t0, 1), "file_MB": round(len(raw) / 2**20, 2)}
print(json.dumps(out, ensure_ascii=False))
(ROOT / "outputs/qa2-2/scale_regions-result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
