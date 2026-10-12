"""G-M09 — 감시: 손 계산 fixture 대조 · 드리프트 → 재학습 후보 → 승인 요청 · production 불변. 소유 개발3.

손 계산 기대값은 tests/fixtures/<t>/psi_hand.json (migration/make_fixtures.py 의 mlcore 없는 순수 파이썬 계산 +
손으로 셀 수 있는 사례의 산식). 드리프트 입력은 tests/fixtures/<t>/drift.parquet (손질 금지 — 다시 만들어 대조).
"""

from __future__ import annotations

import ast
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import _dev3 as h
from migration import make_fixtures
from mlcore.monitor import stats as mp

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
KST = timezone(timedelta(hours=9))
pytestmark = pytest.mark.gate("G-M09")
TENANTS = ["ks", "sw"]


def hand(t: str) -> dict:
    return json.loads((FIX / t / "psi_hand.json").read_text(encoding="utf-8"))


# ── 손 계산 대조 (DB 없음) ──────────────────────────────────────────────────
@pytest.mark.parametrize("t", TENANTS)
def test_psi_matches_hand_cases(t):
    for c in hand(t)["cases"]:
        got = mp.psi(c["expected"], c["actual"], categorical=c["categorical"])
        assert got == pytest.approx(c["psi"], abs=1e-12), c["name"]
    cases = {c["name"]: c for c in hand(t)["cases"]}
    # 산식 그대로 (사람이 셀 수 있는 값)
    assert cases["numeric_deciles"]["psi"] == pytest.approx(0.4 * math.log(5) + 4 * (1e-6 - 0.1) * math.log(1e-6 / 0.1), abs=1e-12)
    assert cases["categorical"]["psi"] == pytest.approx(0.6 * math.log(2.5), abs=1e-12)
    assert cases["identical"]["psi"] == 0.0
    edges = list(mp.bin_edges(cases["numeric_deciles"]["expected"]))
    assert edges == pytest.approx([1.9, 2.8, 3.7, 4.6, 5.5, 6.4, 7.3, 8.2, 9.1])


@pytest.mark.parametrize("t", TENANTS)
def test_oor_and_missing_match_hand(t):
    ch = hand(t)["checks"]
    assert mp.oor_rate(ch["oor_rate"]["values"], ch["oor_rate"]["range"]) == pytest.approx(ch["oor_rate"]["rate"])
    assert mp.oor_rate(ch["oor_rate_category"]["values"], ch["oor_rate_category"]["range"]) == pytest.approx(1 / 3)
    assert mp.missing_rate(ch["missing_rate"]["values"]) == pytest.approx(0.4)
    assert math.isnan(mp.psi([1, 2, 3], []))                       # 운영 값이 없으면 계산 불가(0 으로 꾸미지 않는다)


@pytest.mark.parametrize("t", TENANTS)
def test_drift_fixture_psi_matches_hand(t):
    hd = hand(t)["drift"]
    snap = pd.read_parquet(FIX / t / "snapshot.parquet")
    drift = pd.read_parquet(FIX / t / "drift.parquet")
    from mlcore.registry import tenants
    feats = tenants.load_and_merge(t).pack.features
    for f in hd["features"]:
        got = mp.psi(snap[f], drift[f], categorical=feats[f].get("dtype") == "category")
        assert got == pytest.approx(hd["psi"][f], rel=1e-9, abs=1e-12), f
    shifted = set(hd["shift"])
    assert shifted and all(hd["psi"][f] >= 0.3 for f in shifted)          # 일부러 옮긴 변수 = retrain 기준 이상
    assert all(hd["psi"][f] < 0.2 for f in hd["features"] if f not in shifted)   # 나머지는 경고 아래


@pytest.mark.parametrize("t", TENANTS)
def test_drift_fixture_is_regenerated_not_edited(t):
    stored = pd.read_parquet(FIX / t / "drift.parquet")
    fresh = make_fixtures.drift_frame(t)
    pd.testing.assert_frame_equal(stored.reset_index(drop=True), fresh.reset_index(drop=True), check_dtype=False)
    assert len(stored) == 168 and not ({"remaining_hours", "failure_24h", "delta_e", "defect"} & set(stored.columns))


def test_thresholds_only_from_yaml(tmp_path):
    from mlcore.monitor import daily
    from mlcore.registry import tenants

    m = tenants.load_and_merge("ks")
    th = daily.thresholds(m, m.tasks["ks.remaining_hours"])
    assert th == {"psi_warn": 0.2, "psi_retrain": 0.3, "oor_warn": 0.05, "missing_warn_pp": 0.10, "perf_drop": 0.25,
                  "perf_window_days": 30.0}
    m.pack.meta = {**m.pack.meta, "monitor": {}}
    with pytest.raises(daily.MonitorConfigMissing):              # 코드 기본값으로 채우지 않는다
        daily.thresholds(m, m.tasks["ks.failure_24h"])


def test_levels():
    assert mp.level(0.35, 0.2, 0.3) == "retrain" and mp.level(0.25, 0.2, 0.3) == "warn" and mp.level(0.1, 0.2, 0.3) == "ok"


def test_scheduler_is_kst_0200():
    from mlcore.monitor import scheduler

    s = scheduler.build("ks")
    (job,) = s.get_jobs()
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("2", "0")
    assert job.trigger.timezone.utcoffset(datetime(2026, 10, 12)) == timedelta(hours=9)
    nxt = job.trigger.get_next_fire_time(None, datetime(2026, 10, 12, 3, 0, tzinfo=KST))
    assert (nxt.astimezone(KST).hour, nxt.astimezone(KST).minute, nxt.astimezone(KST).date()) == (2, 0, date(2026, 10, 13))


def test_monitor_never_writes_production():
    """정적: monitor/ 에 production 쓰기 · approval.decide 호출 · 승인 모듈 import 가 0."""
    for p in (ROOT / "src" / "mlcore" / "monitor").glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        assert not re.search(r"UPDATE\s+mlp_model_version|INSERT\s+INTO\s+mlp_model_version|SET\s+stage", txt, re.I), p.name
        tree = ast.parse(txt)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "decide":
                pytest.fail(f"{p.name}: decide 호출")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any(n == "approval" or n.endswith(".approval") or n.startswith("mlcore.approval")
                               for n in names), p.name


# ── DB: 드리프트 → 후보 → 승인 요청 · production 불변 ────────────────────────────
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    base = tmp_path_factory.mktemp("tenants")
    with pytest.MonkeyPatch.context() as mpatch:
        mpatch.setenv("MLP_TENANTS_DIR", str(base))
        code = h.copy_tenant("ks", base)
        m = h.register_db(code)
        task = f"{code}.remaining_hours"
        v1 = h.train_to_production(code, task)
        yield {"code": code, "task": task, "v1": v1, "m": m}


DAY = date(2026, 9, 3)


def test_no_drift_no_candidate(world):
    from mlcore.monitor import daily

    code, task = world["code"], world["task"]
    calm = make_fixtures.drift_frame("ks", shift={})              # 같은 분포 · 다른 시드
    rows = daily.run_daily(code, DAY - timedelta(days=1), frames={task: calm})
    (summary,) = [r for r in rows if r["metric"] == "_summary" and r["task_id"] == task]
    assert summary["retrain"] is False and summary["run_id"] is None
    psi = {r["feature"]: r for r in rows if r["metric"] == "psi" and r["task_id"] == task}
    assert len(psi) == 9 and all(r["level"] != "retrain" for r in psi.values())
    skipped = {r["task_id"]: r.get("skipped") for r in rows if r["metric"] == "_summary"}
    assert "운영 모델 없음" in skipped[f"{code}.failure_24h"] and "학습 과제가 아님" in skipped[f"{code}.maintenance_timing"]


def test_drift_makes_candidate_and_approval_but_production_unchanged(world):
    from mlcore.db.conn import connect
    from mlcore.monitor import daily, retrain
    from mlcore.serve import training

    code, task, v1 = world["code"], world["task"], world["v1"]
    drift = pd.read_parquet(FIX / "ks" / "drift.parquet")
    rows = daily.run_daily(code, DAY, frames={task: drift}, retrain_source="eval")
    hd = hand("ks")["drift"]
    psi = {r["feature"]: r for r in rows if r["metric"] == "psi" and r["task_id"] == task}
    for f, want in hd["psi"].items():                              # 감시 계산 = 손 계산 (학습 스냅숏 = snapshot.parquet 내용)
        assert psi[f]["value"] == pytest.approx(want, rel=1e-9), f
    assert psi["vibration"]["level"] == "retrain"
    (summary,) = [r for r in rows if r["metric"] == "_summary" and r["task_id"] == task]
    assert summary["retrain"] and "psi:vibration" in summary["reasons"] and summary["run_id"]
    assert h.production_version(code, task) == v1                  # 접수만 — 운영 그대로

    with connect() as c:
        stored = c.execute("SELECT metric, feature, level FROM mlp_monitor_daily WHERE tenant_id=%s AND task_id=%s AND day=%s",
                           (code, task, DAY)).fetchall()
    kinds = {r["metric"] for r in stored}
    assert {"psi", "oor_rate", "missing_rate", "volume", "error_rate", "live_perf"} <= kinds
    assert {"metric": "psi", "feature": "vibration", "level": "retrain"} in stored
    oor = [r for r in rows if r["metric"] == "oor_rate" and r["task_id"] == task and r["feature"] == "vibration"][0]
    assert oor["value"] > 0.05 and oor["level"] == "warn"           # 오른쪽으로 옮긴 값이 학습 p99 밖
    live = [r for r in rows if r["metric"] == "live_perf" and r["task_id"] == task][0]
    assert live["value"] is None and live["detail"]["note"] == "실측 없음"   # 실측이 없으면 없다고 쓴다

    # 작업자가 후보를 등록 → 감시가 승인 요청만
    result, ref = training.run_and_register(summary["run_id"])
    assert ref is not None and ref.stage == "candidate" and ref.version != v1
    assert h.production_version(code, task) == v1
    got = retrain.request_approvals(code, task)
    (item,) = got
    assert item["version"] == ref.version and item["approval_id"], item
    with connect() as c:
        apr = c.execute("SELECT state, action, kind, ref_id, requested_by FROM mlp_approval WHERE approval_id=%s",
                        (item["approval_id"],)).fetchone()
        stages = {r["version"]: r["stage"] for r in c.execute(
            "SELECT version, stage FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s", (code, task)).fetchall()}
    assert apr == {"state": "pending", "action": "promote", "kind": "model", "ref_id": ref.version, "requested_by": "monitor"}
    assert stages == {v1: "production", ref.version: "staging"}      # 승인 전 — production 그대로
    assert retrain.request_approvals(code, task) == []               # 두 번째 실행은 새 요청 없음


def test_predictions_mode_volume_and_live_perf(world):
    """frames 없이: 그날 mlp_prediction 입력 · 실측 연결로 volume · live_perf 를 잰다.
    mlp_prediction 은 추가만(UPDATE 거부)이라 ts 를 고칠 수 없다 → 기록 시각(오늘 KST)의 하루를 잰다."""
    from mlcore.db.conn import connect
    from mlcore.monitor import daily
    from mlcore.serve import record
    from mlcore.serve.ids import new_id

    code, task, v1 = world["code"], world["task"], world["v1"]
    calm = make_fixtures.drift_frame("ks", shift={}).head(6)
    now = datetime.now(KST)
    with connect() as c:
        for i, row in enumerate(calm.to_dict("records")):
            inputs = {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
                      for k, v in row.items() if k not in ("ts", "entity_id")}
            ent = f"MON-{code}-{i}"
            record.record(prediction_id=new_id("prd"), tenant_id=code, task_id=task, version=v1, entity_id=ent,
                          inputs=inputs, outputs={"prediction": {"value": 100.0 + i}}, status="ok", caller="test",
                          channel="api", synthetic=True, conn=c)
            c.execute("INSERT INTO mlp_actual (tenant_id, task_id, entity_id, value, observed_at, source) "
                      "VALUES (%s,%s,%s,%s,%s,'api')", (code, task, ent, 110.0 + i, now))
    rows = daily.run_daily(code, now.date(), submit_retrain=False)
    vol = [r for r in rows if r["metric"] == "volume" and r["task_id"] == task][0]
    live = [r for r in rows if r["metric"] == "live_perf" and r["task_id"] == task][0]
    assert vol["value"] == 6.0
    assert live["value"] == pytest.approx(10.0) and live["detail"]["n"] == 6        # |(100+i) − (110+i)| = 10
    test_mae = live["detail"]["test"]
    assert test_mae and live["detail"]["drop"] == pytest.approx((10.0 - test_mae) / test_mae)
    assert live["level"] == ("retrain" if (10.0 - test_mae) / test_mae >= 0.25 else "ok")
    assert h.production_version(code, task) == v1
