"""G2-R01 — 검토 대기열 누수 (goal2 §2 · task-contract §6.1 · std/split_policies.yaml `queue_scoring` · D2-11).

대기열 항목은 (1) uses 과제 run 의 **시험 구간 잔차**(학습기 final_eval 안에서 1회 계산된 것만 — 새 시험 접근 0) 또는
(2) **실측이 붙은 운영 예측 잔차**로만 만든다. 학습 · 검증 구간 잔차 · 전체 재적합 후 같은 데이터 채점(평창식)은 거부하고
guard ledger 에 남긴다. 상위 q% 임계값은 **검증 구간 잔차**(학습 구간 모델의 표본 밖 잔차) 분위, 절대 기준 |잔차| ≥ x 도 지원.
기대값은 개발 코드가 아니라 이 시험이 분할을 다시 만들어 독립으로 계산한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from mlcore.data import snapshot
from mlcore.train import guard, review, split
from mlcore.train.candidates import build
from mlcore.train.trainer import StandardTrainer, TrainConfig

from tests._dev1 import FEATS, raw_rows, std_frame, task

SEED = 7


def _train(t, f, tmp_path):
    sid = "snp_" + snapshot.content_sha256(snapshot.canonical(f))[:16]
    return StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path).train(TrainConfig.from_task(t, sid, seed=SEED))


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    t = task(time_key=None, split="random_60_20_20", candidates=["ridge"])
    f = snapshot.canonical(std_frame(t, raw_rows(600, 21)))
    r = _train(t, f, tmp_path_factory.mktemp("rq"))
    assert r.status == "succeeded", r.report
    sp, _ = split.plan(f, t, seed=SEED)
    te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))   # 시험 코드는 판정용으로 여집합을 쓴다
    return t, f, r, sp, te


def _report(r):
    return json.loads(json.dumps(r.report))          # DB(jsonb) 를 거친 것과 같은 모양


# ── 학습기 쪽: 잔차는 final_eval 안에서만 ─────────────────────────────────
def test_test_residuals_come_from_final_eval_only(trained):
    t, f, r, sp, te = trained
    q = r.report["queue_residuals"]
    assert q["origin"] == "test_split" and q["source"] == "final_eval"
    assert [row["entity_id"] for row in q["test"]] == f["entity_id"].iloc[te].tolist()
    assert len(q["test"]) == r.report["split"]["boundaries"]["sizes"]["test"]
    for row in q["test"]:
        assert row["residual"] == pytest.approx(row["actual"] - row["predicted"])
    # 대기열 재료를 만들면서 시험 구간을 더 보지 않았다 — ledger 는 final_eval 1회 + report 뿐
    assert [e["purpose"] for e in r.ledger] == ["final_eval", "report"] and not [e for e in r.ledger if not e["ok"]]


def test_valid_residuals_are_out_of_sample_from_train_segment_model(trained):
    t, f, r, sp, te = trained
    m = build("ridge", "regression", FEATS, {}, SEED)
    tr, va = list(sp.train_idx), list(sp.valid_idx)
    m.fit(f[[x.name for x in FEATS]].iloc[tr], f["target"].iloc[tr].to_numpy(float))
    expect = np.sort(np.abs(f["target"].iloc[va].to_numpy(float) - m.predict(f[[x.name for x in FEATS]].iloc[va])))
    got = r.report["queue_residuals"]["valid_abs"]
    assert got == pytest.approx(expect.tolist())
    assert r.report["queue_residuals"]["valid_rows"] == len(va)


# ── 규칙 ─────────────────────────────────────────────────────────────
def test_abs_residual_rule_from_test_split(trained):
    t, f, r, sp, te = trained
    items = review.from_run(_report(r), {"abs_residual_ge": 4.0}, task_id="tt.residual_review",
                            model_version="v1", origins=["test_split"], max_items=50)
    rows = r.report["queue_residuals"]["test"]
    expect = sorted((x for x in rows if abs(x["residual"]) >= 4.0), key=lambda x: (-abs(x["residual"]), x["entity_id"]))[:50]
    assert [i["entity_id"] for i in items] == [x["entity_id"] for x in expect] and items
    test_entities = set(f["entity_id"].iloc[te])
    for i in items:
        assert i["entity_id"] in test_entities
        assert i["origin"] == "test_split" and i["prediction_id"] is None and i["rule"] == "abs_residual_ge"
        assert i["threshold"] == 4.0 and abs(i["residual"]) >= 4.0 and i["model_version"] == "v1"
        assert i["reason"].startswith("|잔차| ")
    assert set(items[0]) == set(review.ITEM_KEYS)


def test_abs_rule_boundary_is_inclusive_and_capped():
    pairs = [{"prediction_id": f"prd_{i}", "entity_id": f"E{i}", "predicted": 10.0, "actual": 10.0 + d,
              "model_version": "v2"} for i, d in enumerate([4.0, -4.0, 3.999, 7.5, -0.1])]
    items = review.from_live(pairs, {"abs_residual_ge": 4.0}, task_id="tt.rq", origins=["live_residual"], max_items=2)
    assert [i["entity_id"] for i in items] == ["E3", "E0"]           # |잔차| ↓, 동률은 entity_id 순 · 상한 2
    allv = review.from_live(pairs, {"abs_residual_ge": 4.0}, task_id="tt.rq", origins=["live_residual"], max_items=50)
    assert sorted(i["entity_id"] for i in allv) == ["E0", "E1", "E3"]  # 4.0 은 포함(≥), 3.999 는 제외


def test_top_quantile_threshold_is_valid_residual_quantile(trained):
    t, f, r, sp, te = trained
    rep = _report(r)
    items = review.from_run(rep, {"top_quantile": 0.10}, task_id="tt.rq", model_version="v1",
                            origins=["test_split"], quantile_from="valid", max_items=500)
    valid_abs = np.asarray(rep["queue_residuals"]["valid_abs"])
    thr = float(np.quantile(valid_abs, 0.90))
    test_abs = np.abs([x["residual"] for x in rep["queue_residuals"]["test"]])
    assert thr != pytest.approx(float(np.quantile(test_abs, 0.90)))   # 시험 잔차 분위가 아니다
    assert all(i["threshold"] == pytest.approx(thr) and i["rule"] == "top_quantile" for i in items)
    assert len(items) == int((test_abs >= thr).sum())
    info = review.threshold({"top_quantile": 0.10}, rep, quantile_from="valid")
    assert info["value"] == pytest.approx(thr) and info["from"] == "valid" and info["n"] == len(valid_abs)


def test_threshold_does_not_move_when_test_segment_changes(trained, tmp_path):
    t, f, r, sp, te = trained
    g = f.copy()
    g.loc[te, "target"] = g.loc[te, "target"] * 5 + 50
    r2 = _train(t, g, tmp_path)
    a = review.threshold({"top_quantile": 0.1}, _report(r), quantile_from="valid")
    b = review.threshold({"top_quantile": 0.1}, _report(r2), quantile_from="valid")
    assert a == b                                                     # 임계값은 검증 잔차만 본다


# ── 거부 (guard 계측) ───────────────────────────────────────────────────
@pytest.mark.parametrize("origin", ["train", "valid", "train_split", "valid_split", "in_sample", "all"])
def test_train_or_valid_residual_origins_are_refused_and_recorded(origin):
    led = guard.AccessLedger()
    with pytest.raises(review.QueueLeak):
        review.build_items([{"entity_id": "E1", "predicted": 1.0, "actual": 9.0, "prediction_id": None}],
                           {"abs_residual_ge": 1.0}, origin=origin, task_id="tt.rq", model_version="v1",
                           origins=["test_split", "live_residual"], ledger=led)
    v = led.violations()
    assert v and v[-1]["purpose"] == "queue_scoring"
    assert issubclass(review.QueueLeak, guard.TestLeak)


@pytest.mark.parametrize("qf", ["test", "train", "all", "in_sample", None])
def test_quantile_must_come_from_valid(trained, qf):
    t, f, r, sp, te = trained
    with pytest.raises(review.QueueLeak):
        review.threshold({"top_quantile": 0.1}, _report(r), quantile_from=qf)


def test_origin_not_enabled_for_task_is_refused(trained):
    t, f, r, sp, te = trained
    with pytest.raises(review.QueueLeak):
        review.from_run(_report(r), {"abs_residual_ge": 4.0}, task_id="tt.rq", model_version="v1", origins=["live_residual"])


@pytest.mark.parametrize("rule", [{}, {"abs_residual_ge": -1}, {"top_quantile": 0}, {"top_quantile": 1.0},
                                  {"abs_residual_ge": 1, "top_quantile": 0.1}, {"bogus": 1}])
def test_bad_rules_are_refused(rule):
    with pytest.raises(ValueError):
        review.parse_rule(rule)


def _pc_style(f):
    """평창식(source_inventory §9.3 · §9.6 · P2): 전체 행으로 재적합한 모델로 **같은 데이터**를 채점해 잔차 · 0.9 분위를 낸다."""
    X = f[[x.name for x in FEATS]]
    y = f["target"].to_numpy(float)
    m = build("ridge", "regression", FEATS, {}, SEED).fit(X, y)
    resid = y - m.predict(X)
    return m, resid


def test_pyeongchang_full_refit_same_data_scoring_is_refused(trained):
    t, f, r, sp, te = trained
    m, resid = _pc_style(f)
    led = guard.AccessLedger()
    # (a) 재적합 구간 = 채점 구간 → InSampleEvaluation, ledger 기록
    with pytest.raises(guard.InSampleEvaluation):
        review.residuals(m.predict, f, fit_idx=range(len(f)), score_idx=range(len(f)), ledger=led)
    assert led.violations()[-1]["purpose"] == "queue_scoring"
    # (b) 학습+검증으로 재적합한 모델이 학습 · 검증 행을 채점 → 같은 거부
    with pytest.raises(guard.InSampleEvaluation):
        review.residuals(m.predict, f, fit_idx=sp.fit_idx, score_idx=sp.valid_idx, ledger=guard.AccessLedger())
    # (c) 평창식 잔차를 run 보고서 모양으로 꾸며 넣어도 거부(행 수 · 예측 해시 · ledger 증거가 맞지 않는다)
    rep = _report(r)
    rep["queue_residuals"]["test"] = [{"entity_id": e, "actual": float(a), "predicted": float(a - d), "residual": float(d)}
                                      for e, a, d in zip(f["entity_id"], f["target"], resid)]
    with pytest.raises(guard.InSampleEvaluation):
        review.from_run(rep, {"top_quantile": 0.1}, task_id="tt.rq", model_version="v1", origins=["test_split"],
                        quantile_from="valid")
    rep2 = _report(r)
    rep2["queue_residuals"]["valid_abs"] = sorted(np.abs(resid).tolist())     # 표본 내 잔차로 분위
    with pytest.raises(guard.InSampleEvaluation):
        review.from_run(rep2, {"top_quantile": 0.1}, task_id="tt.rq", model_version="v1", origins=["test_split"],
                        quantile_from="valid")
    rep3 = _report(r)
    rep3["ledger"] = []                                                        # 시험 1회 평가 증거 없음
    with pytest.raises(guard.InSampleEvaluation):
        review.from_run(rep3, {"abs_residual_ge": 4.0}, task_id="tt.rq", model_version="v1", origins=["test_split"])
    rep4 = _report(r)
    rep4["queue_residuals"]["source"] = "refit_all"
    with pytest.raises(guard.InSampleEvaluation):
        review.from_run(rep4, {"abs_residual_ge": 4.0}, task_id="tt.rq", model_version="v1", origins=["test_split"])


def test_out_of_sample_scoring_is_allowed(trained):
    t, f, r, sp, te = trained
    m = build("ridge", "regression", FEATS, {}, SEED)
    m.fit(f[[x.name for x in FEATS]].iloc[list(sp.train_idx)], f["target"].iloc[list(sp.train_idx)].to_numpy(float))
    rows = review.residuals(m.predict, f, fit_idx=sp.train_idx, score_idx=sp.valid_idx, ledger=guard.AccessLedger())
    assert len(rows) == len(sp.valid_idx)          # 검증 잔차(임계값 재료)는 만들 수 있다 — 항목으로는 못 쓴다


def test_guard_refuses_queue_purposes():
    import pandas as pd
    frame = pd.DataFrame({"y": range(10)})
    for p in ("queue", "queue_scoring"):
        led = guard.AccessLedger()
        with pytest.raises(guard.TestLeak):
            guard.GuardedTest(range(8, 10), led).take(frame, p)
        assert led.violations()[-1]["purpose"] == p


# ── 운영 잔차 ──────────────────────────────────────────────────────────
def test_live_residual_items_need_prediction_id_and_actual():
    pairs = [{"prediction_id": "prd_A", "entity_id": "E1", "predicted": 5.0, "actual": 12.0, "model_version": "v3"},
             {"prediction_id": "prd_B", "entity_id": "E2", "predicted": 5.0, "actual": None, "model_version": "v3"}]
    items = review.from_live(pairs, {"abs_residual_ge": 4.0}, task_id="tt.rq", origins=["live_residual"])
    assert len(items) == 1 and items[0]["prediction_id"] == "prd_A" and items[0]["origin"] == "live_residual"
    assert items[0]["residual"] == 7.0 and items[0]["model_version"] == "v3"
    with pytest.raises(ValueError):
        review.from_live([{**pairs[0], "prediction_id": None}], {"abs_residual_ge": 4.0}, task_id="tt.rq",
                         origins=["live_residual"])


def test_live_top_quantile_uses_run_valid_threshold(trained):
    t, f, r, sp, te = trained
    rep = _report(r)
    thr = review.threshold({"top_quantile": 0.1}, rep, quantile_from="valid")["value"]
    pairs = [{"prediction_id": "prd_X", "entity_id": "E9", "predicted": 0.0, "actual": thr + 0.01, "model_version": "v1"},
             {"prediction_id": "prd_Y", "entity_id": "E8", "predicted": 0.0, "actual": thr - 0.01, "model_version": "v1"}]
    items = review.from_live(pairs, {"top_quantile": 0.1}, task_id="tt.rq", origins=["live_residual"], run_report=rep,
                             quantile_from="valid")
    assert [i["entity_id"] for i in items] == ["E9"] and items[0]["threshold"] == pytest.approx(thr)
    with pytest.raises(ValueError):           # 운영 묶음만으로 분위를 재지 않는다 — run 보고서(검증 잔차)가 필요
        review.from_live(pairs, {"top_quantile": 0.1}, task_id="tt.rq", origins=["live_residual"])


def test_risk_task_residuals_are_captured(tmp_path):
    t = task("risk", time_key=None, split="stratified_60_20_20", candidates=["logreg"])
    f = snapshot.canonical(std_frame(t, raw_rows(600, 5, "risk")))
    r = _train(t, f, tmp_path)
    q = r.report["queue_residuals"]
    assert r.status == "succeeded" and len(q["test"]) == r.report["split"]["boundaries"]["sizes"]["test"]
    assert all(0.0 <= abs(x["residual"]) <= 1.0 for x in q["test"])


# ── 끝까지: 실제 학습 → 운영 → 예측 + 실측 → 운영 잔차 대기열 (시험 DB) ───────────────────────
def test_end_to_end_run_report_and_live_pairs_from_db(tmp_path):
    import _dev2 as h
    from mlcore.db.conn import connect

    if not h.db_ok():
        pytest.fail("시험 DB(ml_test_db) 에 연결할 수 없다 — make setup")
    m = h.make_tenant("ks", tmp_path)
    task_id = f"{m.tenant.code}.remaining_hours"
    ref, result = h.real_production(m, task_id)
    with connect() as c:
        rep = c.execute("SELECT report FROM mlp_train_run WHERE run_id=%s", (ref.run_id,)).fetchone()["report"]
    # DB(jsonb) 를 거친 보고서로도 증거 대조가 맞는다 — test_split 항목
    items = review.from_run(rep, {"top_quantile": 0.10}, task_id=f"{m.tenant.code}.rq", model_version=ref.version,
                            origins=["test_split", "live_residual"], quantile_from="valid")
    n_test = rep["split"]["boundaries"]["sizes"]["test"]
    assert 0 < len(items) <= min(50, n_test) and all(i["origin"] == "test_split" for i in items)
    test_ids = {r["entity_id"] for r in rep["queue_residuals"]["test"]}
    assert {i["entity_id"] for i in items} <= test_ids
    # 운영 예측 2건 + 실측 1건 → 짝 1건
    tc = h.client(m)
    keys = h.keys(m)
    inputs = h.mid_inputs(h.lock_of(ref), h.lock_of(ref)["order"])
    pids = []
    for eid in ("LIVE-1", "LIVE-2"):
        r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task_id}/predict", headers=h.hdr(keys["operator"]),
                    json={"inputs": inputs, "entity_id": eid})
        assert r.status_code == 200, r.text
        pids.append(r.json()["prediction_id"])
    pred = r.json()["prediction"]["value"]
    r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{task_id}/actuals", headers=h.hdr(keys["operator"]),
                json={"entity_id": "LIVE-1", "value": pred + 1000.0, "observed_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})   # 예측 뒤 실측(D2-80)
    assert r.status_code in (200, 201), r.text
    with connect() as c:
        pairs = review.live_pairs(c, m.tenant.code, task_id, version=ref.version)
    assert [p["prediction_id"] for p in pairs] == [pids[0]] and pairs[0]["actual"] == pred + 1000.0
    live = review.from_live(pairs, {"top_quantile": 0.10}, task_id=f"{m.tenant.code}.rq", origins=["live_residual"],
                            run_report=rep, quantile_from="valid")
    assert len(live) == 1 and live[0]["prediction_id"] == pids[0] and live[0]["model_version"] == ref.version
