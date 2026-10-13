"""QA2 재검증(r2) — 대기열 짝짓기 회귀 사냥 (D2-80 · D2-81 변경 뒤 정상 운영 잔차를 빼먹지 않는가).

pc.sensory_score(top_quantile) · krs.joint_strength(abs ≥ 4) 를 API 로 학습 → 승인한 뒤:
  N  새 entity 예측 → 그 뒤 실측(잔차 큼)              → 짝 1 · live 항목 1 (기대)
  T  시험 구간 entity 재예측 → 그 뒤 실측               → 짝 1 (재적합 구간이 아니라 빼지 않음)
  F  재적합 구간 entity 예측 → 그 뒤 실측               → 짝 0 · ledger queue_scoring
  M  같은 entity 예측 2 → 실측 1                        → 짝 1 (뒤 예측)
  A  예측 → 실측 → 예측 → 실측                          → 짝 2
  U  실측(관측 시각 미래)을 먼저 등록 → 예측            → 관찰(관측 시각만 본다)
  X  스냅숏 파일 없음                                   → live 항목 0 + 요약 error (fail closed), test_split 은?
전용 DB(ml_qa2r3_db) · 임시 등록부 폴더만 쓴다. 고치지 않는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
import _dev2 as h  # noqa: E402
from mlcore.db.conn import connect  # noqa: E402
from mlcore.monitor import review as job  # noqa: E402
from mlcore.train import review as tr  # noqa: E402
from test_vertical_slice_2 import _promote_via_api  # noqa: E402

KST = timezone(timedelta(hours=9))


def run(src: str, uses_name: str, feats_cat: tuple[str, ...]):
    out: dict = {"tenant_src": src}
    m = h.make_tenant(src, Path(tempfile.mkdtemp(prefix=f"r2q-{src}-")))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        t = m.tenant.code
        uses, queue = f"{t}.{uses_name}", f"{t}.residual_review"
        ub = f"/api/v1/tenants/{t}/tasks/{uses}"
        version = _promote_via_api(tc, k, t, uses)
        with connect() as c:
            row = c.execute("SELECT s.path, r.report FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                            "JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id WHERE mv.tenant_id=%s AND mv.task_id=%s "
                            "AND mv.version=%s", (t, uses, version)).fetchone()
        rep = row["report"]
        p = Path(row["path"]); p = p if p.is_absolute() else ROOT / p
        frame = pd.read_parquet(p)
        feats = [f for f in h.task_features(m, uses)]
        test_ids = [str(r["entity_id"]) for r in rep["queue_residuals"]["test"]]
        with connect() as c:
            fitset = tr.fit_entities(c, t, uses, version)
        test_only = [e for e in test_ids if e not in fitset]
        out["fit_entities"] = len(fitset)
        out["test_entities_not_fit"] = len(test_only)
        good = frame.dropna(subset=feats)
        good = good[good["target"].notna()]

        def inputs_of(eid=None):
            r = good[good["entity_id"].astype(str) == eid].iloc[0] if eid else good.iloc[len(good) // 2]
            return {f: (str(r[f]) if (f in feats_cat or not pd.api.types.is_numeric_dtype(good[f])) else float(r[f])) for f in feats}

        def predict(eid, inp):
            r = tc.post(f"{ub}/predict", headers=h.hdr(k["operator"]), json={"inputs": inp, "entity_id": eid})
            return r.status_code, (r.json().get("prediction") or {}).get("value") if r.status_code == 200 else r.text[:200], \
                (r.json().get("prediction_id") if r.status_code == 200 else None)

        def actual(eid, value, when):
            r = tc.post(f"{ub}/actuals", headers=h.hdr(k["operator"]),
                        json={"entity_id": eid, "value": value, "observed_at": when.isoformat()})
            return r.status_code, r.text[:200]

        def soon(sec=2):
            return datetime.now(KST) + timedelta(seconds=sec)

        cases: dict = {}
        # N — 새 entity
        inp = inputs_of()
        s, v, pid_n = predict("R2-NEW-1", inp)
        cases["N_predict"] = s
        time.sleep(0.05)
        cases["N_actual"] = actual("R2-NEW-1", float(v) + 12.0, soon(1))
        # T — 시험 구간(재적합 구간 아님) entity
        te = test_only[0] if test_only else None
        if te and te in set(good["entity_id"].astype(str)):
            s, v, pid_t = predict(te, inputs_of(te))
            cases["T_predict"] = [te, s]
            cases["T_actual"] = actual(te, float(v) + 12.0, soon(1))
        else:
            pid_t = None
            cases["T_predict"] = "시험 entity 없음/입력 불완전"
        # F — 재적합 구간 entity
        fe = next(e for e in good["entity_id"].astype(str) if e in fitset)
        s, v, pid_f = predict(fe, inputs_of(fe))
        cases["F_predict"] = [fe, s]
        cases["F_actual"] = actual(fe, float(v) + 12.0, soon(1))
        # M — 같은 entity 예측 2 → 실측 1
        s1, v1, pid_m1 = predict("R2-MULTI", inp)
        inp2 = dict(inp)
        s2, v2, pid_m2 = predict("R2-MULTI", inp2)
        cases["M_predict"] = [s1, s2]
        cases["M_actual"] = actual("R2-MULTI", float(v2) + 12.0, soon(1))
        # U — 미래 관측 시각 실측을 먼저 등록
        cases["U_actual_first"] = actual("R2-FUTURE", 999.0, datetime.now(KST) + timedelta(days=30))
        s, v, pid_u = predict("R2-FUTURE", inp)
        cases["U_predict"] = s
        time.sleep(1.5)
        # A — 예측 → 실측 → 예측 → 실측
        s, va, pid_a1 = predict("R2-ALT", inp)
        cases["A_actual1"] = actual("R2-ALT", float(va) + 12.0, soon(1))
        time.sleep(1.5)
        s, vb, pid_a2 = predict("R2-ALT", inp)
        cases["A_actual2"] = actual("R2-ALT", float(vb) + 13.0, soon(1))
        time.sleep(1.5)
        out["cases"] = cases

        with connect() as c:
            pairs = tr.live_pairs(c, t, uses, version=version)
        pp = {p_["prediction_id"]: p_["entity_id"] for p_ in pairs}
        out["pairs"] = {"n": len(pairs), "entities": sorted(pp.values()),
                        "N": pid_n in pp, "T": (pid_t in pp) if pid_t else None, "F": pid_f in pp,
                        "M_first": pid_m1 in pp, "M_second": pid_m2 in pp, "A1": pid_a1 in pp, "A2": pid_a2 in pp,
                        "U_future_actual_paired": pid_u in pp}
        summ = [x for x in job.run_review(t, date.today(), merged=m) if x["task_id"] == queue]
        out["run_review"] = json.loads(json.dumps(summ, default=str))
        with connect() as c:
            items = c.execute("SELECT entity_id, prediction_id, origin, residual FROM mlp_review_item WHERE tenant_id=%s "
                              "AND task_id=%s AND origin='live_residual'", (t, queue)).fetchall()
        out["live_items"] = sorted(i["entity_id"] for i in items)
        out["live_items_in_fit"] = [i["entity_id"] for i in items if i["entity_id"] in fitset]
        r = tc.get(f"/api/v1/tenants/{t}/tasks/{queue}/review", headers=h.hdr(k["admin"]))
        out["api_review_live"] = sum(1 for i in r.json()["items"] if i["origin"] == "live_residual")
        # X — 스냅숏 파일을 잠시 치운 뒤 새 짝 → fail closed
        s, v, pid_x = predict("R2-NEW-X", inp)
        actual("R2-NEW-X", float(v) + 12.0, soon(1))
        time.sleep(1.5)
        moved = p.with_suffix(".r2moved")
        p.rename(moved)
        try:
            summ2 = [x for x in job.run_review(t, date.today(), merged=m) if x["task_id"] == queue]
        finally:
            moved.rename(p)
        out["X_run_review"] = json.loads(json.dumps(summ2, default=str))
        with connect() as c:
            out["X_item_made"] = c.execute("SELECT count(*) AS n FROM mlp_review_item WHERE tenant_id=%s AND prediction_id=%s",
                                           (t, pid_x)).fetchone()["n"]
    return out


def main():
    res = [run("pc", "sensory_score", ("cabbage_origin", "prod_line")),
           run("krs", "joint_strength", ())]
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
