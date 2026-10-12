"""QA2-3 — D2-60 원터치 견적 726,484 / 726,487 재계산 (Decimal · ROUND_HALF_UP). 원천은 읽기만(SQLite mode=ro).
사용: uv run python -I outputs/qa2-r2/q3/d260_recalc.py <원천 OneTouch 폴더> <repo_root>
"""
import json, sqlite3, sys, urllib.parse, pathlib, importlib.util
from decimal import Decimal as D, ROUND_HALF_UP
src = pathlib.Path(sys.argv[1]).resolve(); repo = pathlib.Path(sys.argv[2]).resolve()
c = sqlite3.connect("file:" + urllib.parse.quote(str(src / "data/onetouch.sqlite3")) + "?mode=ro", uri=True)
q = json.loads(c.execute("select payload from quotes").fetchone()[0])
a, inp = q["assumptions"], q["input"]
W = lambda v: v.quantize(D(1), rounding=ROUND_HALF_UP)
def calc(minutes):
    qty = D(inp["quantity"]); per = D(str(a["machine_per_min"]))
    weight = D(str(inp["length"])) * D(str(inp["width"])) * D(str(inp["thickness"])) / D(10**9) * D(str(a["density"]))
    mat = W(weight * D(str(a["price_kg"])) * (1 + D(str(a["scrap_rate"]))) * qty)
    proc = W(minutes * per * qty); setup = W(D(str(a["setup_minutes"])) * per)
    base = mat + proc + setup; mk = W(base * D(str(a["markup"]))); sub = base + mk; vat = W(sub * D(str(a["vat_rate"])))
    return dict(weight=weight, material=mat, processing=proc, setup=setup, base=base, markup=mk, subtotal=sub, vat=vat, total=sub + vat)
raw = D("1.32862360")   # D2-60 이 주장하는 원천 절차 예측(반올림 전)
cur = calc(raw.quantize(D("0.0001"), rounding=ROUND_HALF_UP))   # 현행 원천 quote.py:13,18
old = calc(raw)                                                 # 반올림 전 분으로 가공비
stored = {k: q[k + "_cost"] if k + "_cost" in q else q.get(k) for k in ("material", "processing", "setup", "markup", "subtotal", "vat", "total")}
print("저장", stored)
print("현행", {k: str(v) for k, v in cur.items()})
print("반올림전", {k: str(v) for k, v in old.items()})
# 반올림 전 분의 허용 범위: processing 이 119,576 이 되는 분 구간
lo = (D("119575.5") / 90000); hi = (D("119576.5") / 90000)
print("저장 processing 119,576 이 되는 분 구간", lo, "~", hi, "· 4자리 1.3286 은", D("1.3286") * 90000)
spec = importlib.util.spec_from_file_location("qf", repo / "packs/rollform-quote/formulas/quote.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
std_in = {"quantity": D(100), "steel_grade": "SPCC", "part_length_mm": D("1200.0"), "blank_width_mm": D("160.0"), "sheet_thickness_mm": D("2.0")}
rates = {"machine_per_min": "900", "setup_minutes": "35", "scrap_rate": "0.08", "markup": "0.15", "vat_rate": "0.1",
         "density": {"SPCC": "7850"}, "price_kg": {"SPCC": "1300"}}
r = m.quote(std_in, [], {"machining_minutes": raw}, rates)
print("표준팩", {k: str(v) for k, v in r["costs"].items()}, "total", r["total"])
ok = cur["total"] == 726484 and old["total"] == 726487 == q["total"] and r["total"] == 726484
print("D2-60", "PASS" if ok else "FAIL")
