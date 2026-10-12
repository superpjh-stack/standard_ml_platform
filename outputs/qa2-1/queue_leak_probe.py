"""QA2-1 — 대기열 누수 사냥 (G2-R01 · goal2 §3.3 치명 '대기열이 학습 구간 잔차로 채워짐').

A. 운영 경로(API 그대로): pc.sensory_score 학습 → 승인 → production. 그 뒤 운영 예측을 **학습 스냅숏의 학습 구간 LOT**
   (entity_id · 입력 그대로)로 보내고 실측(POST actuals)을 그 LOT 의 학습 목표값으로 붙인다 → 대기열 일정 작업.
   live_residual 항목이 학습 구간 잔차(표본 내 잔차)로 채워지는지, 거부 · 표시가 있는지 본다.
B. 실측 짝짓기: 실측 시각이 예측보다 **앞선** 실측(예측 전에 이미 알던 값)도 짝이 되는지.
C. 같은 entity 로 예측 2회 · 실측 1회 → 두 예측이 같은 실측과 짝이 되는지(중복 잔차).
D. top_quantile 임계값 = 검증 잔차 분위인지 · time_cv5 에서 폴드별 분위(작은 앞 폴드가 분위를 키우는지).
전용 DB(ml_qa21_db) · 임시 등록부 폴더만 쓴다.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
import tempfile  # noqa: E402

import _dev2 as h  # noqa: E402
from mlcore.db.conn import connect  # noqa: E402
from mlcore.monitor import review as job  # noqa: E402
from mlcore.train import review as tr  # noqa: E402
from test_vertical_slice_2 import _promote_via_api  # noqa: E402

KST = timezone(timedelta(hours=9))
FEATS = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct", "brine_salinity_pct", "brining_hours", "fermentation_temp_c",
         "fermentation_hours", "storage_temp_c", "cabbage_origin", "prod_line"]


def main():
    out: dict = {}
    m = h.make_tenant("pc", Path(tempfile.mkdtemp(prefix="qa21-pc-")))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        t = m.tenant.code
        uses, queue = f"{t}.sensory_score", f"{t}.residual_review"
        ub = f"/api/v1/tenants/{t}/tasks/{uses}"
        version = _promote_via_api(tc, k, t, uses)
        with connect() as c:
            snap = c.execute("SELECT s.path, r.report FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                             "JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id WHERE mv.tenant_id=%s AND mv.task_id=%s AND mv.version=%s",
                             (t, uses, version)).fetchone()
        rep = snap["report"]
        p = Path(snap["path"]); p = p if p.is_absolute() else ROOT / p
        frame = pd.read_parquet(p).sort_values(["ts", "entity_id"], kind="mergesort").reset_index(drop=True)
        n_test = rep["split"]["boundaries"]["sizes"]["test"]
        fit = frame.iloc[: len(frame) - n_test]
        out["split"] = {"policy": rep["split"]["policy"], "sizes": rep["split"]["boundaries"]["sizes"],
                        "folds": rep["split"]["boundaries"].get("folds")}
        thr = tr.threshold({"top_quantile": 0.10}, rep)
        out["threshold"] = thr
        va = np.asarray(rep["queue_residuals"]["valid_abs"])
        # D. 폴드별 검증 잔차 분위 — 분위는 폴드 묶음 전체에서
        out["valid_abs_quantiles"] = {"q90_pooled": float(np.quantile(va, .9)), "n": len(va)}
        test_abs = np.abs([r["residual"] for r in rep["queue_residuals"]["test"]])
        out["test_share_over_thr"] = float((test_abs >= thr["value"]).mean())

        # A. 학습 구간 LOT 을 그대로 운영 예측 + 그 학습 목표를 실측으로
        rows = fit.dropna(subset=FEATS).head(20)
        pids = {}
        for _, r in rows.iterrows():
            inp = {f: (float(r[f]) if f not in ("cabbage_origin", "prod_line") else str(r[f])) for f in FEATS}
            res = tc.post(f"{ub}/predict", headers=h.hdr(k["operator"]), json={"inputs": inp, "entity_id": str(r["entity_id"])})
            if res.status_code != 200:
                out.setdefault("predict_errors", []).append([res.status_code, res.text[:200]])
                continue
            pids[str(r["entity_id"])] = (res.json()["prediction_id"], res.json()["prediction"]["value"], float(r["target"]))
            a = tc.post(f"{ub}/actuals", headers=h.hdr(k["operator"]),
                        json={"entity_id": str(r["entity_id"]), "value": float(r["target"]),
                              "observed_at": datetime(2026, 10, 2, 9, tzinfo=KST).isoformat()})
            out.setdefault("actual_status", []).append(a.status_code)
        out["A_train_rows_predicted"] = len(pids)
        out["A_in_sample_abs_resid"] = sorted(round(abs(v[2] - v[1]), 4) for v in pids.values())
        # C. 같은 entity 로 두 번째 예측(실측 추가 없음)
        e0 = next(iter(pids))
        r0 = rows[rows["entity_id"].astype(str) == e0].iloc[0]
        inp = {f: (float(r0[f]) if f not in ("cabbage_origin", "prod_line") else str(r0[f])) for f in FEATS}
        inp["fermentation_hours"] = float(inp["fermentation_hours"]) + 5
        r2 = tc.post(f"{ub}/predict", headers=h.hdr(k["operator"]), json={"inputs": inp, "entity_id": e0})
        out["C_second_prediction"] = r2.status_code
        # B. 실측을 먼저(예측 전 시각) 올리고 그 뒤 예측
        eb = "QA21-PRE-ACTUAL"
        a = tc.post(f"{ub}/actuals", headers=h.hdr(k["operator"]),
                    json={"entity_id": eb, "value": 40.0, "observed_at": datetime(2020, 1, 1, 9, tzinfo=KST).isoformat()})
        out["B_actual_first_status"] = a.status_code
        rb = tc.post(f"{ub}/predict", headers=h.hdr(k["operator"]), json={"inputs": inp, "entity_id": eb})
        out["B_predict_status"] = rb.status_code

        summ = [x for x in job.run_review(t, date(2026, 10, 3), merged=m) if x["task_id"] == queue]
        out["run_review"] = json.loads(json.dumps(summ, default=str))
        with connect() as c:
            items = c.execute("SELECT entity_id, prediction_id, origin, residual, threshold FROM mlp_review_item "
                              "WHERE tenant_id=%s AND task_id=%s", (t, queue)).fetchall()
        fit_ids = set(fit["entity_id"].astype(str))
        live = [i for i in items if i["origin"] == "live_residual"]
        out["items"] = {"total": len(items), "live": len(live), "test_split": len(items) - len(live),
                        "live_from_train_segment_entities": sorted(i["entity_id"] for i in live if i["entity_id"] in fit_ids),
                        "live_pre_actual": [i["entity_id"] for i in live if i["entity_id"] == eb],
                        "live_same_entity_count": sum(1 for i in live if i["entity_id"] == e0)}
        pairs = None
        with connect() as c:
            pairs = tr.live_pairs(c, t, uses, version=version)
        out["pairs"] = {"n": len(pairs), "train_segment_pairs": sum(1 for p_ in pairs if p_["entity_id"] in fit_ids),
                        "pre_actual_paired": any(p_["entity_id"] == eb for p_ in pairs),
                        "same_entity_pairs": sum(1 for p_ in pairs if p_["entity_id"] == e0)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
