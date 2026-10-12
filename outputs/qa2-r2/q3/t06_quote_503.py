"""§2.1 견적의 uses 과제 production 없음 → 503 model_not_ready (초안 0 · 대체 금액 0) — 새 회사(eto · rollform-quote) 학습 전, 입력은 완전하게.
+ 새 회사 solder predict 422 원인 확인."""
import json, os, subprocess, sys
from pathlib import Path
from qa_lib import ROOT, SP, KEYS, Server, call, check, expect, dump, code_of
from mlcore import auth
from mlcore.db.conn import connect
for pack, code, src in (("eto", "qn7", "kd"), ("rollform-quote", "qn8", "ot")):
    reg = Path(SP) / f"tenreg-{code}"
    import shutil; shutil.rmtree(reg, ignore_errors=True); reg.mkdir()
    env = {**os.environ, "MLP_TENANTS_DIR": str(reg)}
    subprocess.run([sys.executable, "scaffold_fill.py", code, pack, src, str(reg)], env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "mlcore.db.seed_std"], env=env, cwd=ROOT, check=True, capture_output=True)
    with connect() as c:
        KEYS[code] = {}
        for role in ("operator", "admin"):
            raw, hsh = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,%s,'[]'::jsonb,'qa23')", (code, hsh, raw[:8], role))
            KEYS[code][role] = raw
    s = Server(code, tenants_dir=reg)
    try:
        q = f"/api/v1/tenants/{code}/tasks/{code}.quote/quotes"
        if pack == "eto":
            body = {"inputs": {"cut_m": 24, "weld_m": 18, "thickness_mm": 6, "complexity": 3, "main_material": "STS304", "product_family": "반응기",
                               "quantity": 1, "labor_rate": 45000, "outsource_cost": 0},
                    "lines": [{"name": "SHELL", "material": "STS304", "quantity": 2, "mass_kg": "320", "price_kg": "6500"}], "reviewed": False}
        else:
            body = {"inputs": {"part_length_mm": 1200, "blank_width_mm": 160, "sheet_thickness_mm": 2, "hole_count": 6, "slot_count": 2,
                               "bend_count": 2, "steel_grade": "SPCC", "section_profile": "잔넬", "quantity": 100}, "reviewed": False}
        st, e = call("POST", q, t=code, role="operator", json_body=body)
        expect("2.1", f"{pack}: uses production 없음 견적(완전한 입력) → 503 model_not_ready", st, e, 503, "model_not_ready", extra=str(e)[:160] if st != 503 else "")
        st, lst = call("GET", q, t=code, role="operator")
        check("2.1", f"{pack}: 503 뒤 견적 초안 0", st == 200 and lst.get("total", len(lst.get("items", []))) == 0, f"total={lst.get('total')}")
    finally:
        s.close()
dump("rows_t06.txt")
