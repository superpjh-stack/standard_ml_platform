"""QA2-1 — 새 회사 4 등록부의 소스 어댑터 읽기 전용: 소스 종류 · eval CSV 를 읽기 전후 SHA-256 · mtime 불변 ·
eval(CSV) 프레임 = demo(합성) 프레임(같은 행) · 원천 저장소 4 의 파일 수정 0 (읽기만)."""
import hashlib, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import pandas as pd
from mlcore.data import jobs, snapshot
from mlcore.registry import tenants

out = {}
for code in ("krs", "pc", "ot", "kd"):
    cfg = tenants.load_and_merge(code).tenant.config
    kinds = {k: v.get("kind") for k, v in cfg["sources"].items()}
    csvp = ROOT / cfg["sources"]["eval"]["path"]
    before = (hashlib.sha256(csvp.read_bytes()).hexdigest(), os.stat(csvp).st_mtime_ns)
    res = {}
    for tid, td in sorted(tenants.load_and_merge(code).tasks.items()):
        if td.type in ("regression", "extract"):
            try:
                _, _, fe, refe, _ = jobs.read_frame(code, tid, source_role="eval")
                _, _, fd, refd, _ = jobs.read_frame(code, tid, source_role="demo")
                ce, cd = snapshot.canonical(fe), snapshot.canonical(fd)
                cols = [c for c in cd.columns if c in ce.columns and not c.startswith("_")]
                res[tid] = {"rows": [len(ce), len(cd)], "same_hash": snapshot.content_sha256(ce[cols]) == snapshot.content_sha256(cd[cols])}
            except Exception as e:  # noqa: BLE001
                res[tid] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    after = (hashlib.sha256(csvp.read_bytes()).hexdigest(), os.stat(csvp).st_mtime_ns)
    out[code] = {"source_kinds": kinds, "csv_unchanged": before == after, "eval_vs_demo": res}
print(json.dumps(out, ensure_ascii=False, indent=1))
