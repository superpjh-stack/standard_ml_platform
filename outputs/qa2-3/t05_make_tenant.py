"""6개 팩 각각 `make tenant NEW=<code> PACK=<pack>` 를 빈 tmp 등록부 루트(MLP_TENANTS_DIR)에서 — 코드 수정 0.
→ db-seed(그 루트만) → make doctor → 키 → 서버(8213) → 학습 전 503 → API train → 작업자 → stage → 승인 → predict / 견적 / 대기열 → 화면 1 스크린샷."""
import json, os, shutil, subprocess, sys
from pathlib import Path
from qa_lib import ROOT, SP, KEYS, Server, call, check, expect, dump, code_of
from mlcore import auth
from mlcore.db.conn import connect

PACKS = {"press": "qn1", "textile": "qn2", "solder": "qn3", "kimchi": "qn4", "rollform-quote": "qn5", "eto": "qn6"}
TRAINABLE = ("regression", "risk", "anomaly", "extract")
G = "NEW"


def sh(cmd, env):
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


for pack, code in [(p, c) for p, c in PACKS.items() if not sys.argv[1:] or p in sys.argv[1:]]:
    reg = Path(SP) / f"tenreg-{code}"
    shutil.rmtree(reg, ignore_errors=True); reg.mkdir()
    env = {**os.environ, "MLP_TENANTS_DIR": str(reg)}
    rc, out = sh(["make", "tenant", f"NEW={code}", f"PACK={pack}"], env)
    files = sorted(str(p.relative_to(reg)) for p in reg.rglob("*") if p.is_file())
    check(G, f"{pack}: make tenant NEW={code} → 등록부 1 파일", rc == 0 and files == [f"{code}.yaml"], f"rc={rc} files={files} out={out.splitlines()[-1][:160] if out else ''}")
    if rc != 0:
        # 우회(사람이 '# 미확인' 칸을 채우는 단계를 흉내): 같은 스캐폴드 문안 + 기존 회사의 categories(· ot 단가표 덮어쓰기)를 채운 뒤 병합 규칙으로 검사
        src = {"press": "ks", "solder": "krs", "kimchi": "pc", "rollform-quote": "ot", "eto": "kd"}[pack]
        rc2, out2 = sh([sys.executable, str(Path(__file__).parent / "scaffold_fill.py"), code, pack, src, str(reg)], env)
        files = sorted(str(p.relative_to(reg)) for p in reg.rglob("*") if p.is_file())
        check(G, f"{pack}: 우회 — 스캐폴드 + categories 채움(출처 {src}.yaml) → 병합 통과", rc2 == 0, f"files={files} {out2[-160:]}", warn=True)
        if rc2 != 0:
            continue
    (Path(__file__).parent / f"newtenant-{pack}.yaml").write_text((reg / f"{code}.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    rc, out = sh([sys.executable, "-m", "mlcore.db.seed_std"], env)
    check(G, f"{pack}: db-seed(그 루트만)", rc == 0, out.splitlines()[-1][:160] if out else "")
    rc, out = sh(["make", "doctor", f"TENANT={code}"], env)
    check(G, f"{pack}: make doctor", rc == 0, out.replace("\n", " ")[-200:])
    with connect() as c:
        roles = sorted({r["approver_role"] for r in c.execute("SELECT approver_role FROM mlp_task WHERE tenant_id=%s", (code,)).fetchall()})
        KEYS[code] = {}
        for role in ("viewer", "operator", "approver", "admin"):
            raw, hsh = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id,key_hash,key_prefix,role,approver_roles,consumer) VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                      (code, hsh, raw[:8], role, json.dumps(roles if role == "approver" else []), f"qa23-{role}"))
            KEYS[code][role] = raw
    json.dump(KEYS, open(f"{SP}/keys.json", "w"))
    try:
        s = Server(code, tenants_dir=reg)
    except Exception as e:  # noqa: BLE001
        check(G, f"{pack}: 서버 기동", False, f"{e} log={open(f'{SP}/server-{code}.log').read()[-300:]}")
        continue
    try:
        st, hl = call("GET", "/api/v1/health", t=code, role=None)
        check(G, f"{pack}: 기동 · model_ready 전부 false", st == 200 and not any(x["model_ready"] for x in hl["tasks"]), str([(x['task'], x['model_ready']) for x in hl['tasks']]))
        st, tl = call("GET", f"/api/v1/tenants/{code}/tasks", t=code, role="viewer")
        tasks = {x["task"]: x["type"] for x in tl["items"]}
        quote_task = next((k for k, v in tasks.items() if v == "quote"), None)
        if quote_task:
            st, e = call("POST", f"/api/v1/tenants/{code}/tasks/{quote_task}/quotes", t=code, role="operator",
                         json_body={"inputs": {"quantity": 1}, "reviewed": False})
            expect("2.1", f"{pack}: uses 운영 모델 없음 견적 → 503 model_not_ready", st, e, 503, "model_not_ready")
        for tid, ty in tasks.items():
            if ty not in TRAINABLE:
                continue
            ok = False
            for src in ("demo", "eval"):
                st, b = call("POST", f"/api/v1/tenants/{code}/tasks/{tid}/train", t=code, json_body={"source_role": src})
                if st in (200, 202):
                    ok = True; break
            if not ok:
                check(G, f"{pack}: {tid} train 접수", False, f"HTTP {st} {code_of(b)} {str(b)[:120]}", warn=(ty == "extract")); continue
            rc, out = sh([sys.executable, "-m", "mlcore.train.jobs", "--pending"], env)
            st, run = call("GET", f"/api/v1/runs/{b['run_id']}", t=code)
            v = run.get("version")
            if not v:
                check(G, f"{pack}: {tid} 학습({src})", ty == "extract", f"status={run.get('status')} err={str(run.get('error'))[:120]}", warn=True); continue
            st1, _ = call("POST", f"/api/v1/tenants/{code}/tasks/{tid}/models/{v}/stage", t=code)
            st2, pr = call("POST", f"/api/v1/tenants/{code}/tasks/{tid}/models/{v}/promote", t=code, role="approver", json_body={"reason": "새 회사"})
            st3, d = call("POST", f"/api/v1/approvals/{pr.get('approval_id')}/decide", t=code, role="approver", json_body={"decision": "approve", "reason": "새 회사 승인"})
            check(G, f"{pack}: {tid} 학습({src}) → stage → 승인 → production", st3 == 200 and d.get("production_version") == v, f"champion={run.get('champion')} beats={run.get('beats_baseline')} {st1}/{st2}/{st3}")
            if ty in ("regression", "risk", "anomaly"):
                st, info = call("GET", f"/api/v1/tenants/{code}/tasks/{tid}", t=code, role="viewer")
                X = {f["name"]: (f["default"] if f.get("default") is not None else ((f.get("values") or [None])[0] if f.get("dtype") == "category"
                     else (float(f["min"]) + float(f["max"])) / 2)) for f in info["features"]}
                st, p = call("POST", f"/api/v1/tenants/{code}/tasks/{tid}/predict", t=code, role="operator", json_body={"inputs": X})
                check(G, f"{pack}: {tid} predict 200 · 18키", st == 200 and len(p) == 18, f"HTTP {st} status={p.get('status') if isinstance(p, dict) else ''} {code_of(p) or ''}")
        if pack in ("solder", "kimchi"):
            rc, out = sh([sys.executable, "-m", "mlcore.monitor.scheduler", "--tenant", code, "--once"], env)
            rv = next(k for k, v in tasks.items() if v == "review_queue")
            st, b = call("GET", f"/api/v1/tenants/{code}/tasks/{rv}/review", t=code, role="operator")
            check(G, f"{pack}: 감시 1회 → 대기열 항목(test_split)", st == 200 and b.get("total", 0) > 0 and all(i["origin"] == "test_split" for i in b["items"]), f"rc={rc} total={b.get('total')}")
        if quote_task:
            ex = next(k for k, v in tasks.items() if v == "extract")
            sample = ROOT / "packs" / pack / "samples" / "sample.dxf"
            if not sample.exists():
                sys.path.insert(0, str(ROOT / "packs" / pack / "synth"))
                import importlib.util
                spec = importlib.util.spec_from_file_location("sdx", ROOT / "packs" / pack / "synth" / "sample_dxf.py"); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                st_, cfg = call("GET", f"/api/v1/tenants/{code}/tasks/{quote_task}", t=code, role="viewer")
                mats = next((f.get("values") for f in cfg.get("features", []) if f["name"] == "main_material"), None)
                raw = mod.sample_bytes(mats) if mats else mod.sample_bytes()
            else:
                raw = sample.read_bytes()
            st, doc = call("POST", f"/api/v1/tenants/{code}/tasks/{ex}/documents", t=code, role="operator", files={"file": ("sample.dxf", raw, "application/dxf")})
            check(G, f"{pack}: 도면 업로드", st == 201, f"HTTP {st} {code_of(doc) or ''} {str(doc)[:160] if st != 201 else 'labels=' + str(doc.get('labels'))}", warn=True)
            st, info = call("GET", f"/api/v1/tenants/{code}/tasks/{quote_task}", t=code, role="viewer")
            fe = {f["name"]: f for f in info.get("features", [])}
            inputs = {}
            for n in info.get("inputs", []):
                f = fe.get(n)
                if f is None:
                    inputs[n] = {"quantity": 1, "labor_rate": 45000, "outsource_cost": 0}.get(n, 1)
                elif f.get("dtype") == "category":
                    inputs[n] = (f.get("values") or [None])[0]
                else:
                    inputs[n] = f["default"] if f.get("default") is not None else round((float(f["min"]) + float(f["max"])) / 2)
            body = {"doc_id": doc.get("doc_id") if st == 201 else None, "inputs": inputs, "reviewed": False}
            if pack == "eto" and st == 201:
                body["lines"] = [{"name": b["name"], "material": b["material"], "quantity": b["quantity"], "mass_kg": b["mass_kg"], "price_kg": "6500"} for b in doc["bom_rows"]]
            st, q = call("POST", f"/api/v1/tenants/{code}/tasks/{quote_task}/quotes", t=code, role="operator", json_body=body)
            check(G, f"{pack}: 견적 초안", st == 201, f"HTTP {st} {code_of(q) or ''} {str(q)[:200] if st != 201 else 'total=' + q['total']}", warn=True)
        subprocess.run([sys.executable, "shots.py", "new", code, "admin", "overview", "sources", "review", "quotes"], cwd=Path(__file__).parent, capture_output=True)
    finally:
        s.close()
dump("rows_t05.txt")
