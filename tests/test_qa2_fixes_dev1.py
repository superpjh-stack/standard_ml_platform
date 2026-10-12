"""2차 QA 결함 회귀 시험 — 개발1 (웨이브 C2 · 코어 재진입). QA 재현 스크립트(outputs/qa2-1 · qa2-3)를 옮겼다.

- DEF-QA21-001 (#26): live_residual 짝은 **예측 이후 관측된 실측**만, production 모델 학습 스냅숏의 재적합 구간
  (학습 + 검증) entity 는 제외 — guard ledger `queue_scoring` 에 남긴다 (task-contract §6.1 · D2-80).
- DEF-QA21-002 (#27): 같은 entity 예측 여러 건 × 실측 1건 → 예측마다 그 뒤의 가장 이른 실측 1건, 실측 하나는 예측
  하나(그 실측 직전의 마지막 예측)에만 (D2-81).
- DEF-QA21-003 (#27): time_cv5 top_quantile 임계값 = 마지막(시험 직전) 검증 블록 잔차 분위 — 폴드 풀링 아님 (D2-80).
- DEF-QA23-007 (#29): 학습 대상이 아닌 과제(review_queue · 규칙 extract · quote · optimize) train 요청 → 접수 시점 422,
  실패 학습 기록 0 (D2-82).
기대값은 이 시험이 분할 · 스냅숏을 다시 읽어 독립으로 계산한다.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mlcore.data import snapshot
from mlcore.train import guard, review, split
from mlcore.train.candidates import build
from mlcore.train.trainer import StandardTrainer, TrainConfig

from tests._dev1 import FEATS, raw_rows, std_frame, task

KST = timezone(timedelta(hours=9))
SEED = 7


# ── DEF-QA21-003: time_cv5 검증 잔차 = 마지막 검증 블록 ─────────────────────────────────────────────
def test_cv5_valid_residuals_are_last_validation_block_only(tmp_path):
    t = task(candidates=["ridge"])                        # time_key 있음 · 행 300 < 500 → time_cv5
    f = snapshot.canonical(std_frame(t, raw_rows(300, 11)))
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    r = StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path).train(TrainConfig.from_task(t, sid, seed=SEED))
    assert r.status == "succeeded", r.report
    sp, _ = split.plan(f, t, seed=SEED)
    assert sp.policy == "time_cv5" and len(sp.folds) == 5
    tr, va = list(sp.folds[-1][0]), list(sp.folds[-1][1])
    m = build("ridge", "regression", FEATS, {}, SEED)
    X = f[[x.name for x in FEATS]]
    m.fit(X.iloc[tr], f["target"].iloc[tr].to_numpy(float))
    expect = np.sort(np.abs(f["target"].iloc[va].to_numpy(float) - m.predict(X.iloc[va])))
    q = r.report["queue_residuals"]
    assert q["valid_rows"] == len(va) == r.report["split"]["boundaries"]["folds"][-1]["valid"]
    assert q["valid_abs"] == pytest.approx(expect.tolist())
    assert q.get("valid_block") == "last"
    thr = review.threshold({"top_quantile": 0.10}, json.loads(json.dumps(r.report)))
    assert thr["value"] == pytest.approx(float(np.quantile(expect, 0.9))) and thr["n"] == len(va)


def test_cv5_threshold_ignores_test_segment(tmp_path):
    """누수 없음 유지 — 시험 구간 목표를 바꿔도 임계값 그대로."""
    t = task(candidates=["ridge"])
    f = snapshot.canonical(std_frame(t, raw_rows(300, 11)))
    sp, _ = split.plan(f, t, seed=SEED)
    te = sorted(set(range(len(f))) - set(sp.fit_idx))
    g = f.copy()
    g.loc[te, "target"] = g.loc[te, "target"] * 5 + 50
    out = []
    for i, fr in enumerate((f, g)):
        sid = "snp_" + snapshot.content_sha256(fr)[:16]
        r = StandardTrainer(features=FEATS, frame=fr, artifact_root=tmp_path / str(i)).train(TrainConfig.from_task(t, sid, seed=SEED))
        out.append(review.threshold({"top_quantile": 0.1}, json.loads(json.dumps(r.report))))
    assert out[0] == out[1]


# ── DB 세계: pc 학습 → production ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import _dev3 as h

    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    base = tmp_path_factory.mktemp("tenants")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLP_TENANTS_DIR", str(base))
        code = h.copy_tenant("pc", base)
        m = h.register_db(code)
        uses = f"{code}.sensory_score"
        version = h.train_to_production(code, uses)
        from mlcore.db.conn import connect

        with connect() as c:
            row = c.execute("SELECT s.path, r.report FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                            "JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id WHERE mv.tenant_id=%s AND mv.task_id=%s "
                            "AND mv.version=%s", (code, uses, version)).fetchone()
        p = Path(row["path"])
        p = p if p.is_absolute() else h.ROOT / p
        frame = pd.read_parquet(p)
        test_cnt = Counter(str(x["entity_id"]) for x in row["report"]["queue_residuals"]["test"])
        all_cnt = Counter(str(e) for e in frame.loc[frame["target"].notna(), "entity_id"])
        fit_ids = sorted(e for e, n in all_cnt.items() if n > test_cnt.get(e, 0))
        test_only = sorted(e for e in test_cnt if all_cnt[e] == test_cnt[e])
        yield {"code": code, "uses": uses, "version": version, "m": m, "fit_ids": fit_ids, "test_only": test_only,
               "queue": f"{code}.residual_review", "base": base}


_N = [0]


def _pred(world, entity: str, ts: datetime, value: float = 50.0) -> str:
    from mlcore.db.conn import connect

    import secrets

    _N[0] += 1
    pid = f"prd_c2{secrets.token_hex(8)}{_N[0]:04d}"
    with connect() as c:
        c.execute("INSERT INTO mlp_prediction (prediction_id, tenant_id, task_id, version, entity_id, inputs, outputs, status, "
                  "caller, channel, synthetic, ts) VALUES (%s,%s,%s,%s,%s,'{}',%s,'ok','test','api',true,%s)",
                  (pid, world["code"], world["uses"], world["version"], entity,
                   json.dumps({"prediction": {"value": value}}), ts))
    return pid


def _act(world, entity: str, value: float, observed: datetime) -> None:
    from mlcore.db.conn import connect

    with connect() as c:
        c.execute("INSERT INTO mlp_actual (tenant_id, task_id, entity_id, value, observed_at, source) VALUES (%s,%s,%s,%s,%s,'api')",
                  (world["code"], world["uses"], entity, value, observed))


def _pairs(world, **kw):
    from mlcore.db.conn import connect

    with connect() as c:
        return review.live_pairs(c, world["code"], world["uses"], version=world["version"], **kw)


T0 = datetime(2031, 3, 1, 9, tzinfo=KST)        # 다른 시험 행과 섞이지 않게 먼 시각


def test_actual_observed_before_prediction_is_not_paired(world):
    """QA queue_leak_probe B — 예측보다 6년 앞선 실측도 짝이 되던 결함."""
    e = "C2-PRE-ACTUAL"
    _act(world, e, 40.0, T0 - timedelta(days=6 * 365))
    pid = _pred(world, e, T0)
    assert pid not in {p["prediction_id"] for p in _pairs(world)}
    _act(world, e, 41.0, T0 + timedelta(hours=2))          # 예측 뒤 실측이 오면 그것과 짝
    (p,) = [p for p in _pairs(world) if p["prediction_id"] == pid]
    assert p["actual"] == 41.0


def test_fit_segment_entities_are_excluded_and_logged(world):
    """QA queue_train_rows_krs · queue_leak_probe A — 학습 스냅숏 재적합 구간 LOT 재예측 + 학습 목표 실측."""
    fit = world["fit_ids"][:5]
    test_e = world["test_only"][:2]
    assert len(fit) == 5 and len(test_e) == 2
    pids = {e: _pred(world, e, T0 + timedelta(days=1)) for e in fit + test_e}
    for e in fit + test_e:
        _act(world, e, 90.0, T0 + timedelta(days=1, hours=3))
    led = guard.AccessLedger()
    got = {p["entity_id"] for p in _pairs(world, ledger=led)}
    assert not got & set(fit)                                # 표본 내 잔차 0
    assert set(test_e) <= got                                # 시험 구간 entity 의 운영 예측은 그대로
    ev = [x for x in led.events() if x["purpose"] == "queue_scoring"]
    assert ev and not ev[-1]["ok"] and ev[-1]["n_rows"] >= 5 and "재적합" in ev[-1]["reason"]


def test_monitor_review_creates_no_fit_segment_items(world):
    from mlcore.db.conn import connect
    from mlcore.monitor import review as job

    job.run_review(world["code"], date(2031, 3, 5), merged=world["m"])
    with connect() as c:
        ids = {r["entity_id"] for r in c.execute(
            "SELECT entity_id FROM mlp_review_item WHERE tenant_id=%s AND task_id=%s AND origin='live_residual'",
            (world["code"], world["queue"])).fetchall()}
    assert not ids & set(world["fit_ids"])


def test_one_actual_pairs_with_one_prediction(world):
    """QA queue_leak_probe C — 같은 entity 예측 2건이 실측 1건과 둘 다 짝이 되던 결함."""
    e = "C2-DUP"
    p1 = _pred(world, e, T0 + timedelta(days=2))
    p2 = _pred(world, e, T0 + timedelta(days=2, hours=1), value=55.0)
    _act(world, e, 60.0, T0 + timedelta(days=2, hours=5))
    mine = [p for p in _pairs(world) if p["entity_id"] == e]
    assert [p["prediction_id"] for p in mine] == [p2] and mine[0]["predicted"] == 55.0
    # 예측 → 실측 → 예측 → 실측: 각자 그 뒤 가장 이른 실측
    p3 = _pred(world, e, T0 + timedelta(days=3))
    _act(world, e, 70.0, T0 + timedelta(days=3, hours=1))
    _act(world, e, 75.0, T0 + timedelta(days=3, hours=9))    # 더 늦은 실측은 p3 와 짝이 아니다
    mine = {p["prediction_id"]: p["actual"] for p in _pairs(world) if p["entity_id"] == e}
    assert mine == {p2: 60.0, p3: 70.0} and p1 not in mine


# ── DEF-QA23-007: 학습 대상이 아닌 과제 → 접수 시점 422 ─────────────────────────────────────────────
def test_non_trainable_task_train_request_rejected_at_submit(world):
    import _dev3 as h
    from mlcore.data import jobs
    from mlcore.db.conn import connect

    code, queue = world["code"], world["queue"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLP_TENANTS_DIR", str(world["base"]))
        with pytest.raises(jobs.NotTrainable) as ei:
            jobs.submit(code, queue, actor="test-admin")
        assert ei.value.status == 422 and ei.value.detail["rule"] == "not_trainable"
        tc = h.client(code)
        try:
            k = h.keys(world["m"])
            r = tc.post(f"/api/v1/tenants/{code}/tasks/residual_review/train", headers=h.hdr(k["admin"]), json={})
            assert r.status_code == 422, r.text
            assert r.json()["error"]["detail"]["rule"] == "not_trainable"
        finally:
            tc.__exit__(None, None, None)
    with connect() as c:
        n = c.execute("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s", (code, queue)).fetchone()["n"]
    assert n == 0


def test_trainable_rule_by_type():
    from mlcore.data.taskview import trainable
    from mlcore.registry.tenants import TaskDef

    assert trainable(task("regression")) and trainable(task("risk")) and trainable(task("anomaly"))
    for ty in ("review_queue", "quote", "optimize"):
        assert not trainable(TaskDef(f"tt.{ty}", f"tmpl.{ty}", ty, {"type": ty}, "h"))
    assert not trainable(TaskDef("tt.ex", "tmpl.ex", "extract", {"type": "extract", "extractors": []}, "h"))
    assert trainable(TaskDef("tt.ex", "tmpl.ex", "extract", {"type": "extract", "model": {"features": ["x1"]}}, "h"))
