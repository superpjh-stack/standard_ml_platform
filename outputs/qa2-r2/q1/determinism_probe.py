"""QA2-1 — 결정성 (6사 · 학습 과제 전부, 새 과제 포함). 프로세스 하나가 과제마다
(원본, 행 섞기 + 열 역순) 두 벌을 학습해 스냅숏 ID · 챔피언 · 시험 예측 해시 · 산출물 SHA-256 · 대기열 재료 해시를 낸다.
`run_determinism.sh` 가 이 스크립트를 환경을 바꿔(PYTHONHASHSEED · 스레드 수) 여러 번 돌리고 결과를 견준다.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.data.taskview import has_model  # noqa: E402
from mlcore.registry import tenants  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features  # noqa: E402

LEARN = ("regression", "risk", "anomaly")


def one(code, tid, frame, m, t, work, tag):
    s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref={"qa": "det"}, synthetic=True, base_dir=work / f"s{tag}")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
    r = StandardTrainer(features=resolve_features(t, merged=m), frame=frame, artifact_root=work / f"a{tag}").train(cfg)
    q = (r.report or {}).get("queue_residuals") or {}
    return {"snapshot": s.snapshot_id, "status": r.status, "champion": r.champion,
            "test_pred": r.report.get("test_predictions_sha256"), "artifact": r.artifact_sha256,
            "queue": hashlib.sha256(json.dumps(q, sort_keys=True, default=str).encode()).hexdigest()[:16],
            "imp": hashlib.sha256(json.dumps((r.report.get("test") or {}).get("importance"), sort_keys=True, default=str).encode()).hexdigest()[:16]}


def main():
    work = Path(tempfile.mkdtemp(prefix="qa21-det-"))
    res = {}
    for code in ("ks", "sw", "krs", "pc", "ot", "kd"):
        mg = tenants.load_and_merge(code)
        for tid, td in sorted(mg.tasks.items()):
            if td.type not in LEARN and not (td.type == "extract" and has_model(td)):
                continue
            m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo")
            a = one(code, tid, frame, m, t, work, f"{tid}-a")
            rng = np.random.default_rng(7)
            f2 = frame.iloc[rng.permutation(len(frame))][list(frame.columns)[::-1]].reset_index(drop=True)
            b = one(code, tid, f2, m, t, work, f"{tid}-b")
            res[tid] = {"orig": a, "shuffled_same": {k: a[k] == b[k] for k in a}}
    print(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
