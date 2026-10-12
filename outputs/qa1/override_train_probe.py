"""QA1 — 덮어쓰기로 목표 열을 변수에 넣거나 목표를 변수로 바꾸면 학습이 막히는가 (임시 등록부 · 임시 산출물).
실행: source outputs/qa1/env.sh && uv run python outputs/qa1/override_train_probe.py"""
import os, shutil, sys, tempfile
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features
base_feats = ["press_force", "vibration", "motor_current", "equip_temp", "mold_temp", "cycle_time", "shot_count", "machine_code", "product_type"]
for name, over in [("목표 열을 변수로", {"features": base_feats + ["remaining_hours"]}),
                   ("목표를 변수 shot_count 로", {"target": {"name": "shot_count"}})]:
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "tenants" / "ks.yaml", d / "ks.yaml")
    (d / "ks" / "tasks").mkdir(parents=True)
    (d / "ks" / "tasks" / "remaining_hours.yaml").write_text(yaml.safe_dump(over, allow_unicode=True))
    os.environ["MLP_TENANTS_DIR"] = str(d)
    try:
        m, t, frame, ref, syn = jobs.read_frame("ks", "ks.remaining_hours")
        s = snapshot.freeze(frame, tenant_id="ks", task=t, source_ref=ref, synthetic=syn, base_dir=d / "s")
        r = StandardTrainer(artifact_root=d / "a", snapshot_dir=d / "s").train(TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta))
        tm = r.test_metrics.get("mae")
        print(f"G-M03  덮어쓰기 학습 {name:22s} {'FAIL' if r.status == 'succeeded' else 'PASS'} status={r.status} 시험 MAE={tm.value if tm else None} 기준선={tm.baseline if tm else None} 사유={r.selection_reason[:100]}")
    except Exception as e:
        print(f"G-M03  덮어쓰기 학습 {name:22s} PASS 거부 {type(e).__name__}: {str(e)[:100]}")
    shutil.rmtree(d)
