"""G-M05 C · D — 분할 · 누수 (spec §5.3 · contracts/interfaces.md §3 · gates/check_leakage.py).

- 시계열은 시간순 · group_key 경계 교집합 0 · time_key 가 있으면 비시간순 split 설정을 무시한다.
- 시험 인덱스는 SplitPlan 에 없다(GuardedTest 만).
- 켜진 학습 과제 6(ks 3 · sw 3)을 팩 합성 스냅숏으로 래퍼 아래에서 학습: 위반 0 · final_eval 정확히 1회 ·
  report 는 그 뒤 · 모든 결과에 기준선 비교. 합성 과제(optimize 2)는 학습하지 않는다(NotTrainable).
- 표본 내 평가(평창식: 전체 재적합 후 같은 데이터 채점)는 InSampleEvaluation.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mlcore.data import jobs, snapshot
from mlcore.train import guard, split
from mlcore.train.evaluate import final_evaluation
from mlcore.train.trainer import NotTrainable, StandardTrainer, TrainConfig
from tests._dev1 import FEATS, raw_rows, std_frame, task

ROOT = Path(__file__).resolve().parents[1]
LEARNED = [("ks", "ks.remaining_hours"), ("ks", "ks.failure_24h"), ("ks", "ks.sensor_ood"),
           ("sw", "sw.delta_e"), ("sw", "sw.defect_risk"), ("sw", "sw.print_ood")]
COMPOSITE = [("ks", "ks.maintenance_timing"), ("sw", "sw.print_setpoint")]


def _test_idx(frame, sp):
    return sorted(set(range(len(frame))) - set(sp.train_idx) - set(sp.valid_idx))


# ── 분할 ───────────────────────────────────────────────
def test_time_split_is_chronological_60_20_20():
    t = task()
    f = std_frame(t, raw_rows(1000, 1).sample(frac=1, random_state=3))   # 섞어서 넣어도
    f = f.sample(frac=1, random_state=4).reset_index(drop=True)
    sp, test = split.plan(f, t, seed=1)
    te = _test_idx(f, sp)
    assert sp.policy == "time_60_20_20"
    assert (len(sp.train_idx), len(sp.valid_idx), len(test)) == (600, 200, 200) and len(te) == 200
    assert f["ts"].iloc[list(sp.train_idx)].max() < f["ts"].iloc[list(sp.valid_idx)].min()
    assert f["ts"].iloc[list(sp.valid_idx)].max() < f["ts"].iloc[te].min()
    assert not set(sp.train_idx) & set(sp.valid_idx)


def test_time_key_forces_time_order_even_if_split_says_random():
    t = task(split="random_60_20_20")
    assert split.choose_policy(t, 1000) == "time_60_20_20"
    assert split.choose_policy(task(time_key=None, split="random_60_20_20"), 1000) == "random_60_20_20"
    assert split.choose_policy(task("risk", time_key=None, split="stratified_60_20_20"), 1000) == "stratified_60_20_20"


def test_small_rows_use_time_cv5_and_folds_are_expanding_and_before_test():
    t = task()
    f = std_frame(t, raw_rows(300, 2))
    sp, test = split.plan(f, t, seed=1)
    assert sp.policy == "time_cv5" and len(sp.folds) == 5 and len(test) == 60
    te_min = f["ts"].iloc[_test_idx(f, sp)].min()
    prev = 0
    for tr, va in sp.folds:
        assert len(tr) > prev
        prev = len(tr)
        assert f["ts"].iloc[list(tr)].max() < f["ts"].iloc[list(va)].min()
        assert f["ts"].iloc[list(va)].max() < te_min


@pytest.mark.parametrize("groups", [7, 40, 333])
def test_group_key_never_crosses_boundary(groups):
    t = task(group_key="lot")
    f = std_frame(t, raw_rows(1000, 3, groups=groups))
    sp, test = split.plan(f, t, seed=1)
    g = f["group"]
    tr, va, te = set(g.iloc[list(sp.train_idx)]), set(g.iloc[list(sp.valid_idx)]), set(g.iloc[_test_idx(f, sp)])
    assert not tr & va and not va & te and not tr & te
    assert f["ts"].iloc[list(sp.train_idx)].max() < f["ts"].iloc[_test_idx(f, sp)].min()


def test_interleaved_groups_still_disjoint():
    t = task(group_key="lot")
    raw = raw_rows(600, 4)
    raw["lot"] = [f"G{i % 25:02d}" for i in range(600)]      # 시간상 완전히 섞인 그룹
    f = std_frame(t, raw)
    sp, _ = split.plan(f, t, seed=1)
    g = f["group"]
    sets = [set(g.iloc[list(sp.train_idx)]), set(g.iloc[list(sp.valid_idx)]), set(g.iloc[_test_idx(f, sp)])]
    assert not sets[0] & sets[1] and not sets[1] & sets[2] and not sets[0] & sets[2]
    assert sp.boundaries.get("regrouped") is True


def test_plan_does_not_expose_test_indices():
    t = task()
    f = std_frame(t, raw_rows(1000, 1))
    sp, test = split.plan(f, t, seed=1)
    assert not hasattr(sp, "test_idx")
    assert "test" not in {k for k in vars(sp)} and len(test) == 200
    for fn in (lambda: list(test), lambda: test[0], lambda: np.asarray(test), lambda: test.tolist()):
        with pytest.raises(guard.TestLeak):
            fn()


def test_random_and_stratified_are_seeded():
    t = task("risk", time_key=None, split="stratified_60_20_20")
    f = std_frame(t, raw_rows(1000, 1, "risk"))
    a, _ = split.plan(f, t, seed=5)
    b, _ = split.plan(f, t, seed=5)
    c, _ = split.plan(f, t, seed=6)
    assert a.train_idx == b.train_idx and a.train_idx != c.train_idx
    rate = f["target"].mean()
    assert abs(f["target"].iloc[list(a.valid_idx)].mean() - rate) < 0.02


# ── 표본 내 평가 (D) ──────────────────────────────────
def test_in_sample_evaluation_fixture_is_rejected():
    """평창식: 전체로 재적합하고 같은 데이터로 채점 — 평가 구간 ⊂ 재적합 구간."""
    t = task()
    f = std_frame(t, raw_rows(1000, 1))
    _, test = split.plan(f, t, seed=1)
    with pytest.raises(guard.InSampleEvaluation):
        final_evaluation(f, test, list(range(len(f))), lambda df: None)
    assert test.overlaps(range(len(f)))


# ── 학습기 계측 (C) ───────────────────────────────────
@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    base = tmp_path_factory.mktemp("leak")
    out = {}
    for tenant, tid in LEARNED:
        m, t, frame, ref, syn = jobs.read_frame(tenant, tid)
        s = snapshot.freeze(frame, tenant_id=tenant, task=t, source_ref=ref, synthetic=syn, base_dir=base / "s")
        cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
        r = StandardTrainer(artifact_root=base / "a", snapshot_dir=base / "s").train(cfg)
        out[tid] = (t, frame, r)
    return out


@pytest.mark.parametrize("tenant,tid", LEARNED)
def test_learned_task_under_guard(trained, tenant, tid):
    t, frame, r = trained[tid]
    assert r.status == "succeeded", r.report
    viol = [e for e in r.ledger if not e["ok"]]
    assert viol == []
    finals = [e for e in r.ledger if e["purpose"] == "final_eval"]
    assert len(finals) == 1 and finals[0]["where"].startswith("mlcore/train/evaluate.py")
    assert [e["purpose"] for e in r.ledger] == ["final_eval", "report"]
    # 기준선 비교가 모든 지표에 있다
    assert r.test_metrics and all(v.baseline is not None and v.delta_vs_baseline is not None for v in r.test_metrics.values())
    assert isinstance(r.beats_baseline, bool) and "beats_baseline_rule" in r.report
    # 시계열: 분할이 시간순
    b = r.report["split"]
    assert b["policy"] == "time_60_20_20" and b["boundaries"]["sizes"] == {"train": 432, "valid": 144, "test": 144}
    assert b["boundaries"]["train_ts"][1] < b["boundaries"]["valid_ts"][0] <= b["boundaries"]["valid_ts"][1] < b["boundaries"]["test_ts"][0]


@pytest.mark.parametrize("tenant,tid", COMPOSITE)
def test_composite_tasks_are_not_trained(tenant, tid):
    t = jobs.load_merged(tenant).tasks[tid]          # 학습기와 같은 등록부 루트 규칙(MLP_TENANTS_DIR → 기본 tenants/)
    with pytest.raises(NotTrainable):
        StandardTrainer().train(TrainConfig(t, "snp_0000000000000000", 1, "dev", (), {}))


def test_trainer_cannot_use_test_for_selection(monkeypatch, tmp_path):
    """학습기 절차 안에서 시험 구간을 선정 목적으로 꺼내려 하면 TestLeak 이 실패 결과로 묻히지 않고 올라온다."""
    from mlcore.train import trainer as tr

    t = task()
    f = std_frame(t, raw_rows(800, 1))
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    real = tr.final_evaluation

    def leaky(frame, test, fit_idx, score):
        test.take(frame, "selection")
        return real(frame, test, fit_idx, score)

    monkeypatch.setattr(tr, "final_evaluation", leaky)
    with pytest.raises(guard.TestLeak):
        StandardTrainer(features=FEATS, frame=f, artifact_root=tmp_path).train(TrainConfig.from_task(t, sid))


def test_static_take_only_in_evaluate_and_report():
    pat = re.compile(r"\.take\(\s*[^,]+,\s*[\"'](final_eval|report|selection|calibration|interval|threshold|baseline|queue)")
    hits = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "src" / "mlcore").rglob("*.py") if pat.search(p.read_text()))
    assert hits == ["src/mlcore/train/evaluate.py", "src/mlcore/train/report.py"]
