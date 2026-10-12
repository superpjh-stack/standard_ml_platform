"""QA2-1 — 대기열 · IQR · 시험 교란 불변 (krs · pc), time_cv5 폴드별 분위, 학습 구간 LOT 의 표본 내 잔차 수.

1. 같은 demo 프레임 / 시험 구간 목표 · 변수만 교란(목표 +50, 변수 극단값) 두 벌로 학습 → 챔피언 · 검증 지표 · 검증 잔차 해시 ·
   대기열 임계값 · IQR 제거 수(폴드 · 재적합) · 구간 q 가 같고, 시험 지표 · 시험 항목만 달라야 한다.
2. 검증 구간 교란(대조군) → 검증 쪽 값이 바뀌어야 한다(계측이 살아 있음).
3. pc time_cv5: 폴드별 검증 |잔차| 0.9 분위를 독립 재계산(같은 후보 · 파라미터)해 풀링 분위와 견준다.
4. production 과 같은 재적합 모델로 학습+검증 행을 채점 → 대기열 임계값 이상인 학습 구간 LOT 수(운영 경로가 막지 않으면 들어갈 수).
분할 인덱스는 이 스크립트가 split.plan 을 다시 불러 여집합으로 구한다(판정용 — 코어 경로 아님).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.train import review, split  # noqa: E402
from mlcore.train.candidates import build  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, resolve_features  # noqa: E402


def train(code, short, frame, m, t, feats, work, tag):
    s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref={"qa": tag}, synthetic=True, base_dir=work / f"snap{tag}")
    cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
    r = StandardTrainer(features=feats, frame=frame, artifact_root=work / f"art{tag}").train(cfg)
    assert r.status == "succeeded", r.report.get("error")
    return r


def summary(r, rule):
    rep = r.report
    q = rep["queue_residuals"]
    thr = review.threshold(rule, rep)["value"]
    items = review.from_run(rep, rule, task_id="x", model_version="v", origins=["test_split"], max_items=10 ** 6)
    return {"champion": r.champion, "valid": {k: round(float(v), 10) for k, v in (r.valid_metrics[r.champion]).items()
                                              if isinstance(v, (int, float))},
            "valid_sha": q["valid_sha256"], "threshold": thr, "interval_q": rep["interval"]["q"],
            "outliers": rep.get("outliers") and {"folds": rep["outliers"]["folds"], "refit": rep["outliers"]["refit"]},
            "test_mae": float(r.test_metrics["mae"].value), "items": len(items),
            "item_entities": sorted(i["entity_id"] for i in items)}


def main():
    work = Path(tempfile.mkdtemp(prefix="qa21-inv-"))
    out = {}
    for code, short in (("krs", "joint_strength"), ("pc", "sensory_score")):
        tid = f"{code}.{short}"
        m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo")
        frame = snapshot.canonical(frame)
        feats = resolve_features(t, merged=m)
        rule = m.tasks[f"{code}.residual_review"].raw["rule"]
        sp, _ = split.plan(frame, t, seed=t.raw.get("seed", 42))
        fit = set(sp.fit_idx)
        te = sorted(set(range(len(frame))) - fit)
        va = sorted(sp.valid_idx)
        base = train(code, short, frame, m, t, feats, work, "base")
        numc = [f.name for f in feats if f.numeric]
        f_test = frame.copy()
        f_test.loc[f_test.index[te], "target"] = f_test.loc[f_test.index[te], "target"] + 50
        f_test.loc[f_test.index[te[:10]], numc[0]] = 1e6           # 시험 행 극단값 — IQR 경계가 시험을 보면 제거 수가 바뀐다
        pert_test = train(code, short, f_test, m, t, feats, work, "test")
        f_val = frame.copy()
        f_val.loc[f_val.index[va[:10]], "target"] = f_val.loc[f_val.index[va[:10]], "target"] + 50
        pert_val = train(code, short, f_val, m, t, feats, work, "valid")
        b, pt, pv = summary(base, rule), summary(pert_test, rule), summary(pert_val, rule)
        same = {k: b[k] == pt[k] for k in ("champion", "valid", "valid_sha", "threshold", "interval_q", "outliers")}
        out[code] = {"policy": sp.policy, "rule": rule, "base": {k: v for k, v in b.items() if k != "item_entities"},
                     "test_perturbed_same": same, "test_perturbed_test_mae": pt["test_mae"], "test_perturbed_items": pt["items"],
                     "valid_perturbed_changed": {k: b[k] != pv[k] for k in ("valid_sha", "threshold", "interval_q")},
                     "items_subset_of_test": set(b["item_entities"]) <= set(frame["entity_id"].iloc[te].astype(str)),
                     "items_in_fit": len(set(b["item_entities"]) & set(frame["entity_id"].iloc[sorted(fit)].astype(str)))}
        # 4. 학습+검증 행의 표본 내 잔차
        model = joblib.load(ROOT / base.artifact_dir / "model.joblib") if (ROOT / base.artifact_dir / "model.joblib").exists() \
            else joblib.load(Path(base.artifact_dir) / "model.joblib")
        names = [f.name for f in feats]
        sub = frame.iloc[sorted(fit)]
        res = np.abs(sub["target"].to_numpy(float) - np.asarray(model.predict(sub[names]), float))
        out[code]["in_sample_fit_rows"] = {"n": int(len(res)), "ge_threshold": int((res >= b["threshold"]).sum()),
                                           "mae": float(res.mean())}
        if sp.policy == "time_cv5":
            ch = base.champion
            params = base.report["chosen_params"][ch]
            per = []
            for trf, vaf in sp.folds:
                mm = build(ch, "regression", feats, params, t.raw.get("seed", 42)).fit(frame.iloc[list(trf)][names], frame.iloc[list(trf)]["target"])
                r_ = np.abs(frame.iloc[list(vaf)]["target"].to_numpy(float) - mm.predict(frame.iloc[list(vaf)][names]))
                per.append({"train": len(trf), "q90": round(float(np.quantile(r_, .9)), 4), "mae": round(float(r_.mean()), 4)})
            out[code]["cv5_fold_q90"] = per
            out[code]["test_share_ge_threshold"] = round(
                float(np.mean(np.abs([x["residual"] for x in base.report["queue_residuals"]["test"]]) >= b["threshold"])), 4)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
