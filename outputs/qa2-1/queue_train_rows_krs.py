"""QA2-1 — krs: 학습 구간 LOT 의 표본 내 잔차가 운영 경로(live_residual)로 대기열에 들어가는지 (API 그대로).

krs.joint_strength 학습 → 승인 → production. 학습 스냅숏의 재적합 구간(학습+검증) 행 중 production 모델 |잔차| ≥ 4 MPa 인
LOT 을 이 스크립트가 고른다(판정용). 그 LOT 의 실측(학습 목표값)을 **먼저**(과거 시각, MES 이력처럼) 올리고, 같은 입력 · entity_id
로 운영 예측 → 대기열 일정 작업. 기대(G2-R01): 학습 · 검증 구간 잔차로 항목을 만들지 않는다(거부 또는 표시).
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
import _dev2 as h  # noqa: E402
from mlcore.db.conn import connect  # noqa: E402
from mlcore.monitor import review as job  # noqa: E402
from mlcore.train import split  # noqa: E402
from test_vertical_slice_2 import _promote_via_api  # noqa: E402

KST = timezone(timedelta(hours=9))


def main():
    out = {}
    m = h.make_tenant("krs", Path(tempfile.mkdtemp(prefix="qa21-krs-")))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        t = m.tenant.code
        uses, queue = f"{t}.joint_strength", f"{t}.residual_review"
        ub = f"/api/v1/tenants/{t}/tasks/{uses}"
        version = _promote_via_api(tc, k, t, uses)
        with connect() as c:
            row = c.execute("SELECT s.path, mv.artifact_path, r.report FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                            "JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                            (t, uses, version)).fetchone()
        p = Path(row["path"]); p = p if p.is_absolute() else ROOT / p
        frame = pd.read_parquet(p)
        task = m.tasks[uses]
        sp, _ = split.plan(frame, task, seed=row["report"]["config"]["seed"])
        fit = frame.iloc[sorted(sp.fit_idx)]
        art = Path(row["artifact_path"]); art = art if art.is_absolute() else ROOT / art
        model = joblib.load(art / "model.joblib")
        feats = [f for f in task.raw["features"]]
        res = fit["target"].to_numpy(float) - np.asarray(model.predict(fit[feats]), float)
        pick = fit[np.abs(res) >= 4.0].dropna(subset=feats)
        out["fit_rows"] = len(fit)
        out["fit_rows_ge4"] = int((np.abs(res) >= 4.0).sum())
        out["picked_complete_rows"] = len(pick)
        sent = []
        for _, r in pick.iterrows():
            e = str(r["entity_id"])
            a = tc.post(f"{ub}/actuals", headers=h.hdr(k["operator"]),
                        json={"entity_id": e, "value": float(r["target"]), "observed_at": datetime(2025, 1, 1, 9, tzinfo=KST).isoformat()})
            inp = {f: (str(r[f]) if f == "supplier" else float(r[f])) for f in feats}
            pr = tc.post(f"{ub}/predict", headers=h.hdr(k["operator"]), json={"inputs": inp, "entity_id": e})
            sent.append({"entity": e, "actual_status": a.status_code, "predict_status": pr.status_code,
                         "warn": (pr.json().get("warnings") if pr.status_code == 200 else pr.text[:160])})
        out["sent"] = sent[:3]
        out["predict_ok"] = sum(1 for s in sent if s["predict_status"] == 200)
        summ = [x for x in job.run_review(t, date(2026, 10, 3), merged=m) if x["task_id"] == queue]
        out["run_review"] = json.loads(json.dumps(summ, default=str))
        with connect() as c:
            items = c.execute("SELECT entity_id, origin, residual FROM mlp_review_item WHERE tenant_id=%s AND task_id=%s",
                              (t, queue)).fetchall()
        fit_ids = set(fit["entity_id"].astype(str))
        live = [i for i in items if i["origin"] == "live_residual"]
        out["items"] = {"total": len(items), "live": len(live),
                        "live_from_fit_segment": sum(1 for i in live if i["entity_id"] in fit_ids),
                        "example": [dict(i) for i in live[:3]]}
        r = tc.get(f"/api/v1/tenants/{t}/tasks/{queue}/review", headers=h.hdr(k["approver"]), params={"limit": 5})
        out["api_review_first"] = (r.json().get("items") or [None])[0] if r.status_code == 200 else r.text[:200]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
