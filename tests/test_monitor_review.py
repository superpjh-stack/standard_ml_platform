"""대기열 일정 작업 — 감시 일일 작업 뒤 실측이 붙은 운영 잔차 → mlp_review_item (task-contract §6.1 schedule · G2-R01 · D2-11).

기대:
- live_residual 항목은 **실측(mlp_actual)이 붙은 production 예측**에서만 만든다(prediction_id 필수). 실측 없는 예측 · 다른 버전 예측 0.
- top_quantile 임계값은 uses 과제 production run 보고서의 **검증 구간 잔차** 분위(train/review.threshold) — 운영 묶음으로 재지 않는다.
- 같은 prediction_id 는 한 번만(두 번 돌려도 새 항목 0). 정렬 |잔차| ↓ · max_items 상한.
- production 이 없으면 만들지 않고 이유를 남긴다. 보고서에 검증 잔차 증거가 없으면 만들지 않는다(지어내지 않는다).
- 스케줄러 run_once 가 감시 뒤에 이 작업을 부른다. production 은 바꾸지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

import _dev3 as h

pytestmark = [pytest.mark.gate("G2-R01")]
KST = timezone(timedelta(hours=9))
DAY = date(2026, 10, 1)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    base = tmp_path_factory.mktemp("tenants")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLP_TENANTS_DIR", str(base))
        code = h.copy_tenant("pc", base)
        m = h.register_db(code)
        uses = f"{code}.sensory_score"
        version = h.train_to_production(code, uses)
        tc = h.client(code)
        k = h.keys(m)
        yield {"code": code, "uses": uses, "queue": f"{code}.residual_review", "version": version, "tc": tc, "keys": k, "m": m}
        tc.__exit__(None, None, None)


def _inputs(i: int) -> dict:
    return {"cabbage_pct": 70.0, "radish_pct": 8.0, "seasoning_pct": 20.0, "salt_pct": 2.0, "brine_salinity_pct": 11.0,
            "brining_hours": 12.0, "fermentation_temp_c": 5.0, "fermentation_hours": 40.0 + i, "storage_temp_c": 1.0,
            "cabbage_origin": "평창", "prod_line": "K1"}


def predict(world, entity: str, i: int) -> dict:
    r = world["tc"].post(f"/api/v1/tenants/{world['code']}/tasks/sensory_score/predict",
                         json={"inputs": _inputs(i), "entity_id": entity}, headers=h.hdr(world["keys"]["operator"]))
    assert r.status_code == 200, r.text
    return r.json()


def actual(world, entity: str, value: float):
    r = world["tc"].post(f"/api/v1/tenants/{world['code']}/tasks/sensory_score/actuals",
                         json={"entity_id": entity, "value": value, "observed_at": datetime(2026, 10, 1, 9, tzinfo=KST).isoformat()},
                         headers=h.hdr(world["keys"]["operator"]))
    assert r.status_code in (200, 201), r.text


def items(code: str, task: str, origin: str = "live_residual") -> list[dict]:
    from mlcore.db.conn import connect

    with connect() as c:
        return c.execute("SELECT * FROM mlp_review_item WHERE tenant_id=%s AND task_id=%s AND origin=%s "
                         "ORDER BY abs(residual) DESC, item_id", (code, task, origin)).fetchall()


def test_live_residual_items_only_from_predictions_with_actuals(world):
    from mlcore.monitor import review
    from mlcore.train import review as tr

    code, queue = world["code"], world["queue"]
    preds = {f"LOT-{i:02d}": predict(world, f"LOT-{i:02d}", i) for i in range(12)}
    # 8 개만 실측 — 잔차를 크게 · 작게 섞는다(0 ~ 14 점)
    offsets = {f"LOT-{i:02d}": (i - 4) * 2.0 for i in range(8)}
    for e, off in offsets.items():
        actual(world, e, preds[e]["prediction"]["value"] + off)
    out = review.run_review(code, DAY)
    (s,) = [x for x in out if x["task_id"] == queue]
    assert s["origin"] == "live_residual" and s["version"] == world["version"] and s["rule"] == "top_quantile"
    # 임계값 = production run 보고서의 검증 구간 잔차 분위(운영 잔차로 재지 않는다)
    rep = review.run_report(code, world["uses"], world["version"])
    want = tr.threshold({"top_quantile": 0.10}, rep)["value"]
    assert s["threshold"] == pytest.approx(want) and s["threshold_from"] == "valid"
    got = items(code, queue)
    expect = {e for e, off in offsets.items() if abs(off) >= want}
    assert {r["entity_id"] for r in got} == expect and s["created"] == len(expect) and s["pairs"] == 8
    for r in got:
        p = preds[r["entity_id"]]
        assert r["prediction_id"] == p["prediction_id"] and r["origin"] == "live_residual" and r["state"] == "open"
        assert r["version"] == world["version"] and r["rule"] == "top_quantile" and r["threshold"] == pytest.approx(want)
        assert r["residual"] == pytest.approx(r["actual"] - r["predicted"]) and abs(r["residual"]) >= want
        assert r["item_id"].startswith("rvw_") and len(r["item_id"]) == 30 and r["reason"]
        assert r["decided_by"] is None and r["decided_at"] is None


def test_test_split_items_from_run_report_once_per_version(world):
    """origins 에 test_split — production run 보고서의 시험 구간 잔차(final_eval 결과)로 항목을 한 번 만든다 (D2-43 · D2-45).
    항목에 version · rule · threshold 가 있고 prediction_id 는 없다. 같은 버전 재실행은 0."""
    from mlcore.monitor import review
    from mlcore.train import review as tr

    code, queue = world["code"], world["queue"]
    review.run_review(code, DAY)
    rep = review.run_report(code, world["uses"], world["version"])
    want = tr.from_run(rep, {"top_quantile": 0.10}, task_id=queue, model_version=world["version"],
                       origins=["test_split", "live_residual"], max_items=50)
    got = items(code, queue, "test_split")
    assert want and len(got) == len(want)
    assert {r["entity_id"] for r in got} == {w["entity_id"] for w in want}
    for r in got:
        assert r["prediction_id"] is None and r["version"] == world["version"] and r["rule"] == "top_quantile"
        assert r["threshold"] == pytest.approx(want[0]["threshold"]) and r["state"] == "open"
    again = [x for x in review.run_review(code, DAY) if x["task_id"] == queue][0]
    assert again["test_split"]["created"] == 0 and len(items(code, queue, "test_split")) == len(got)


def test_second_run_creates_nothing_new(world):
    from mlcore.monitor import review

    before = items(world["code"], world["queue"])
    out = review.run_review(world["code"], DAY)
    (s,) = [x for x in out if x["task_id"] == world["queue"]]
    assert s["created"] == 0 and items(world["code"], world["queue"]) == before


def test_new_actual_later_is_picked_up_once(world):
    from mlcore.monitor import review

    p = predict(world, "LOT-LATE", 3)
    actual(world, "LOT-LATE", p["prediction"]["value"] + 40.0)          # 뒤늦게 붙은 큰 잔차
    n0 = len(items(world["code"], world["queue"]))
    (s,) = [x for x in review.run_review(world["code"], DAY + timedelta(days=1)) if x["task_id"] == world["queue"]]
    assert s["created"] == 1 and len(items(world["code"], world["queue"])) == n0 + 1
    assert items(world["code"], world["queue"])[0]["entity_id"] == "LOT-LATE"   # |잔차| 가장 큼


def test_max_items_caps_one_run(world, monkeypatch):
    from mlcore.monitor import review

    for i in range(5):
        p = predict(world, f"CAP-{i}", i)
        actual(world, f"CAP-{i}", p["prediction"]["value"] + 30.0 + i)
    m = world["m"]
    raw = m.tasks[world["queue"]].raw
    monkeypatch.setitem(raw, "max_items", 2)
    (s,) = [x for x in review.run_review(world["code"], DAY, merged=m) if x["task_id"] == world["queue"]]
    assert s["created"] == 2
    got = [r["entity_id"] for r in items(world["code"], world["queue"]) if r["entity_id"].startswith("CAP-")]
    assert got == ["CAP-4", "CAP-3"]                                      # |잔차| 큰 것부터
    monkeypatch.setitem(raw, "max_items", 50)
    (s,) = [x for x in review.run_review(world["code"], DAY, merged=m) if x["task_id"] == world["queue"]]
    assert s["created"] == 3                                              # 남은 것은 다음 실행에서(같은 예측은 한 번만)


def test_no_production_no_items(tmp_path, monkeypatch):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음")
    from mlcore.monitor import review

    monkeypatch.setenv("MLP_TENANTS_DIR", str(tmp_path))
    code = h.copy_tenant("pc", tmp_path)
    h.register_db(code)
    (s,) = [x for x in review.run_review(code, DAY) if x["task_id"] == f"{code}.residual_review"]
    assert s["created"] == 0 and "운영 모델 없음" in s["skipped"]


def test_report_without_valid_evidence_is_refused(world, monkeypatch):
    """보고서 검증 잔차 증거가 없으면 임계값을 지어내지 않는다 — 항목 0 · 사유(평창식 표본 내 거부와 같은 판정)."""
    from mlcore.monitor import review

    p = predict(world, "LOT-NOEVID", 1)
    actual(world, "LOT-NOEVID", p["prediction"]["value"] + 50.0)
    monkeypatch.setattr(review, "run_report", lambda *a, **k: {"queue_residuals": None})
    (s,) = [x for x in review.run_review(world["code"], DAY) if x["task_id"] == world["queue"]]
    assert s["created"] == 0 and s["error"]["type"] == "InSampleEvaluation"
    assert "LOT-NOEVID" not in {r["entity_id"] for r in items(world["code"], world["queue"])}


def test_scheduler_runs_review_after_monitor_and_keeps_production(world, monkeypatch):
    from mlcore.monitor import scheduler

    calls = []
    monkeypatch.setattr(scheduler, "export_hub_after", lambda day: calls.append(("hub", day)) or None)
    out = scheduler.run_once(world["code"], DAY)
    assert "review" in out and any(s["task_id"] == world["queue"] for s in out["review"])
    assert calls == [("hub", DAY)]                                        # D2-09 — 감시 일일 작업 뒤 1회
    assert h.production_version(world["code"], world["uses"]) == world["version"]


def test_review_module_never_writes_production_or_decides():
    import ast
    from pathlib import Path

    src = (Path(h.ROOT) / "src" / "mlcore" / "monitor" / "review.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute):
            assert node.attr != "decide"
    import re
    assert not re.search(r"UPDATE\s+mlp_|DELETE\s+FROM|SET\s+stage|mlp_approval", src, re.I)   # 항목은 INSERT 만, 결정은 API(PATCH)
