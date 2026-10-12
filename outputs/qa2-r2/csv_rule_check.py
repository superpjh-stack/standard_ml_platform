"""#27-004 재검증 — eval CSV vs demo 프레임: 새 규칙 |eval − demo| ≤ 1e-12·max(1,|demo|) · 비수치 열 같음 · 결측 위치 같음 (6사)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from mlcore.data import jobs, snapshot
from mlcore.registry import tenants
out = {}
for code in ("ks", "sw", "krs", "pc", "ot", "kd"):
    m = tenants.load_and_merge(code)
    if "eval" not in m.tenant.config["sources"]:
        out[code] = "eval 소스 없음"; continue
    for tid, td in sorted(m.tasks.items()):
        if td.type not in ("regression", "classification", "extract"):
            continue
        try:
            _, _, fe, _, _ = jobs.read_frame(code, tid, source_role="eval")
            _, _, fd, _, _ = jobs.read_frame(code, tid, source_role="demo")
        except Exception as e:  # noqa: BLE001
            out[tid] = f"{type(e).__name__}: {str(e)[:120]}"; continue
        ce, cd = snapshot.canonical(fe), snapshot.canonical(fd)
        cols = [c for c in cd.columns if c in ce.columns and not c.startswith("_") and c != "ts"]
        worst, bad = 0.0, []
        for c in cols:
            a, b = ce[c], cd[c]
            if (a.isna().to_numpy() != b.isna().to_numpy()).any():
                bad.append(f"{c}:na"); continue
            if pd.api.types.is_float_dtype(b) and pd.api.types.is_numeric_dtype(a):
                x, y = a.to_numpy(float), b.to_numpy(float); ok = ~np.isnan(y)
                r = np.abs(x[ok] - y[ok]) / np.maximum(1, np.abs(y[ok]))
                worst = max(worst, float(r.max()) if r.size else 0.0)
            elif not (a.astype(str).to_numpy() == b.astype(str).to_numpy()).all():
                bad.append(c)
        out[tid] = {"rows": [len(ce), len(cd)], "max_rel": worst, "rule_ok": worst <= 1e-12 and not bad and len(ce) == len(cd), "bad": bad}
print(json.dumps(out, ensure_ascii=False, indent=1))
