"""QA2-2 §K 예시 파일 경로 탈출 — 호환 pack_file · document_demo (samples/ 밖 · 링크 · 절대 경로). 결과 → probe_samples-result.json"""
import os, re, secrets, tempfile
from pathlib import Path
from common import ROOT, client, h, rec, save
from mlcore.registry import tenants
from mlcore.db.conn import connect

def make(routes_extra: str):
    code = "t" + secrets.token_hex(3)
    text = (ROOT / "tenants" / "ot.yaml").read_text(encoding="utf-8")
    text = re.sub(r"^code: ot\b", f"code: {code}", text, flags=re.M)
    text = re.sub(r"(?<![A-Za-z0-9_])ot\.(?=[a-z])", f"{code}.", text)
    text = text.replace("  routes:", "  routes:\n" + routes_extra, 1)
    base = Path(tempfile.mkdtemp(prefix="qa22-smp-")) / "tenants"
    (base / code / "samples").mkdir(parents=True)
    (base / f"{code}.yaml").write_text(text, encoding="utf-8")
    import shutil; shutil.copytree(ROOT / "tenants" / "ot" / "tasks", base / code / "tasks")
    secret = base / "secret.txt"; secret.write_text("QA22-SECRET-OUTSIDE")
    (base / code / "samples" / "link.dxf").symlink_to(secret)
    (base / code / "samples" / "ok.json").write_text('{"ok": 1}')
    m = tenants.load_and_merge(code, tenants_base=base)
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)", (code, "qa22", "rollform-quote", "demo"))
        for tid, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) VALUES (%s,%s,%s,%s,%s,%s)",
                      (code, tid, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    return m

import sys
cases = {"samples 안 링크 → 밖": "link.dxf", "정상 ok.json": "ok.json"}
for bad in ("../secret.txt", "/etc/passwd", "%2e%2e/secret.txt", "a/../../secret.txt"):
    try:
        make(f"    - {{path: /api/qa22/x, action: pack_file, params: {{file: \"{bad}\"}}}}\n")
        rec("G2-A01", f"등록부 params.file {bad!r}", False, "로드됨(거부 기대)")
    except Exception as e:
        rec("G2-A01", f"등록부 params.file {bad!r} → 기동 거부", True, f"{type(e).__name__}")
extra = "".join(f"    - {{path: /api/qa22/f{i}, action: pack_file, params: {{file: \"{v}\"}}}}\n" for i, v in enumerate(cases.values()))
extra += "    - {path: \"/api/qa22/dyn/{file}\", action: pack_file}\n"
try:
    m = make(extra)
except Exception as e:  # 등록부가 기동 때 거부하면 그것도 결과
    rec("G2-A01", "경로 탈출 값을 가진 등록부 로드", True, {"rejected_at_load": f"{type(e).__name__}: {str(e)[:200]}"})
    save("probe_samples-result.json"); raise SystemExit
k = h.keys(m); tc = client(m)
for i, (label, v) in enumerate(cases.items()):
    r = tc.get(f"/api/qa22/f{i}", headers=h.hdr(k["operator"]))
    leak = b"QA22-SECRET" in r.content or b"root:" in r.content or b"code: ot" in r.content
    want_ok = label.startswith("정상")
    rec("G2-A01", f"pack_file params · {label}", (r.status_code == 200 and not leak) if want_ok else (r.status_code == 404 and not leak),
        {"status": r.status_code, "leak": leak})
for v in ("..%2Fsecret.txt", "%2e%2e%2fsecret.txt", "link.dxf", "....//secret.txt", "ok.json"):
    r = tc.get(f"/api/qa22/dyn/{v}", headers=h.hdr(k["operator"]))
    leak = b"QA22-SECRET" in r.content
    rec("G2-A01", f"pack_file 경로 인자 · {v}", (r.status_code == 200) if v == "ok.json" else (r.status_code == 404 and not leak), {"status": r.status_code, "leak": leak})
r = tc.get("/api/qa22/f1"); rec("G2-A01", "pack_file 키 없음 → 401", r.status_code == 401, {"status": r.status_code})
save("probe_samples-result.json")
