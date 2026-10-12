"""QA1 결정성 — 스레드 수 · 행 순서 · 열 순서 · 해시 시드(dict/set 순서) 를 흔들어 시험 예측 해시를 비교한다.
실행: source outputs/qa1/env.sh && uv run python outputs/qa1/determinism_probe.py   (자식 프로세스로 변형 실행)"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
TASKS = [("ks", "ks.remaining_hours"), ("ks", "ks.failure_24h"), ("ks", "ks.sensor_ood"),
         ("sw", "sw.delta_e"), ("sw", "sw.defect_risk"), ("sw", "sw.print_ood")]

CHILD = r'''
import json, sys, tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0, sys.argv[1])
from mlcore.data import jobs, snapshot
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features
shuffle = sys.argv[2] == "1"
out = {}
for tenant, tid in json.loads(sys.argv[3]):
    m, t, frame, ref, syn = jobs.read_frame(tenant, tid)
    if shuffle:
        frame = frame.sample(frac=1, random_state=99)[list(reversed(frame.columns))]
    with tempfile.TemporaryDirectory() as d:
        s = snapshot.freeze(frame, tenant_id=tenant, task=t, source_ref=ref, synthetic=syn, base_dir=Path(d) / "s")
        cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
        r = StandardTrainer(artifact_root=Path(d) / "a", snapshot_dir=Path(d) / "s").train(cfg)
    out[tid] = {"snap": s.snapshot_id, "pred": r.report["test_predictions_sha256"], "champion": r.champion,
                "art": r.artifact_sha256, "imp": json.dumps(r.report["test"].get("permutation_importance"), sort_keys=True)[:0] or
                __import__("hashlib").sha256(json.dumps(r.report["test"].get("permutation_importance"), sort_keys=True).encode()).hexdigest()[:12]}
print("JSON" + json.dumps(out))
'''

def run(env_extra, shuffle):
    env = {**os.environ, **env_extra}
    p = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), "1" if shuffle else "0", json.dumps(TASKS)],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    line = [l for l in p.stdout.splitlines() if l.startswith("JSON")]
    if not line:
        raise SystemExit(p.stderr[-2000:])
    return json.loads(line[0][4:])

variants = [
    ("기준 OMP=1 HASHSEED=0", {"OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}, False),
    ("재실행 OMP=1 HASHSEED=0", {"OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}, False),
    ("HASHSEED=12345", {"OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "12345"}, False),
    ("OMP=4 · OPENBLAS=4 · HASHSEED=7", {"OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "PYTHONHASHSEED": "7"}, False),
    ("행 섞기 + 열 역순", {"OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}, True),
]
res = [(n, run(e, s)) for n, e, s in variants]
base = res[0][1]
for n, r in res:
    for tid in base:
        same = {k: r[tid][k] == base[tid][k] for k in ("snap", "pred", "champion", "art", "imp")}
        st = "PASS" if all(same.values()) else ("WARN" if same["pred"] else "FAIL")
        diff = [k for k, v in same.items() if not v]
        print(f"G-M06  결정성 {n:32s} {tid:20s} {st:5s} 다른 항목={diff or '없음'} pred={r[tid]['pred'][:12]} snap={r[tid]['snap']}")
