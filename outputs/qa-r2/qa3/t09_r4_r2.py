"""QA-R2 — R4 실경로 두 갈래 (DEF-QA3-001 #17 재검증).
사용: t09_r4_r2.py setup <base> <code> <task_short>...   → demo 등록부 생성 · DB 행 · 합성 학습 → 승인 → production
      t09_r4_r2.py live <base> <code>                    → 같은 폴더의 YAML 을 live 로(합성 소스 제거 · 미대응 변수 대응표 추가)
      t09_r4_r2.py approve <base> <code> <task_short>... → (기동 뒤) 합성 학습 → 승인 → production"""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
cmd, base, code = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
shorts = sys.argv[4:]
y = base / f"{code}.yaml"
if cmd == "setup":
    base.mkdir(parents=True, exist_ok=True)
    t = (ROOT / "tenants" / "sw.yaml").read_text(encoding="utf-8")
    t = re.sub(r"^code: sw\b", f"code: {code}", t, flags=re.M)
    t = re.sub(r"(?<![A-Za-z0-9_])sw\.(?=[a-z])", f"{code}.", t)
    t = re.sub(r"^  enable: \[.*\]", "  enable: [" + ", ".join(f"{code}.{s}" for s in shorts) + "]", t, flags=re.M)
    y.write_text(t, encoding="utf-8")
if cmd == "live":
    t = y.read_text(encoding="utf-8")
    t = re.sub(r"^mode: \w+", "mode: live", t, flags=re.M)
    t = re.sub(r"^  demo: .*\n", "", t, flags=re.M)
    t = t.replace("feature_map:", "feature_map:\n  PRT_PRINT_CONDS.DWELL_SEC: dwell_time\n  PRT_PRINT_CONDS.COLOR_TONE: color_tone", 1)
    y.write_text(t, encoding="utf-8"); print("live yaml 작성"); sys.exit(0)
if cmd in ("setup", "approve"):
    os.environ["MLP_TENANTS_DIR"] = str(base)
    from mlcore.db.conn import connect
    from mlcore.registry import tenants
    from mlcore.registry.models import Registry
    from mlcore.serve import training
    from mlcore import approval
    if cmd == "setup":
        m = tenants.load_and_merge(code, tenants_base=base)
        with connect() as c:
            c.execute("INSERT INTO mlp_tenant (tenant_id,name,pack,mode) VALUES (%s,'QA-R2 R4','textile','demo') ON CONFLICT DO NOTHING", (code,))
            for tid, td in m.tasks.items():
                c.execute("INSERT INTO mlp_task (tenant_id,task_id,pack_task_id,type,def_hash,approver_role) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (code, tid, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
        if code.endswith("b"):      # 갈래 B: 기동 전에는 production 을 만들지 않는다
            print("setup only"); sys.exit(0)
    else:
        # live YAML 에는 합성 소스가 없다 → 학습용으로만 demo YAML 을 잠시 다른 폴더에 둔다
        import shutil, tempfile
        tb = Path(tempfile.mkdtemp()); shutil.copy(base.parent / f"{code}-demo.yaml", tb / f"{code}.yaml")
        os.environ["MLP_TENANTS_DIR"] = str(tb)
    reg = Registry()
    for s in shorts:
        rid = training.submit(code, f"{code}.{s}", actor="qar2", source_role="demo", seed=None)["run_id"]
        res, ref = training.run_and_register(rid)
        reg.stage(code, f"{code}.{s}", ref.version, actor="qar2")
        aid = reg.request_promotion(code, f"{code}.{s}", ref.version, actor="qar2", action="promote", reason=None)
        print(s, approval.decide(aid, actor="qar2", actor_role="approver", approve=True, reason="qar2 R4"), "synthetic", reg.get(code, f"{code}.{s}").synthetic)
