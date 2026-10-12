"""G-V01 — 얇은 수직 관통 (goal §2.0 · 웨이브 A0). 소유 개발2.

`ks.remaining_hours`(팩 press) 와 `sw.delta_e`(팩 textile) 가 **같은 mlcore 코드와 다른 팩 · 등록부만으로**
API 를 끝까지 돈다:

  POST …/train(admin, 202 queued) → [작업 실행 → candidate 등록] → GET …/models(candidate · 기준선 비교)
  → POST …/models/{v}/stage(admin) → POST …/models/{v}/promote(approver, 승인 요청만 — production 그대로)
  → POST /approvals/{id}/decide(approver → approval.decide()) → production
  → POST …/predict(operator, 표준 18키 계약) → mlp_prediction 1행 → POST …/actuals
  → GET /predictions/{id}/trace(admin) — 스냅숏 해시 · 소스 참조 · 실측.

격리 (tests/_dev2.py 방식): 시험마다 tenants/<ks|sw>.yaml 을 새 회사 코드로 복사한 임시 등록부를 쓴다.
학습기(개발1 `data.jobs.submit` · `train.jobs.execute`)는 등록부 루트를 `mlcore.data.jobs.tenants_base_for`
(인자 → 환경변수 `MLP_TENANTS_DIR` → 기본 tenants/)로 찾는다 — 시험은 그 공식 주입 경로(환경변수)로 임시 폴더를 알린다.
코드 함수를 바꿔 끼우는 우회(monkeypatch)는 없다(웨이브 A 에서 걷어냄).
API 키 · 역할은 실제 auth 경로(mlp_api_key 해시 조회 → 미들웨어 → auth.require)로 보낸다 — 우회 없음.

**우회 (D-57):** POST …/train 은 queued 작업만 만든다. queued 작업을 실행하는 주체(작업자 · 배경 작업)가
계약에 아직 없어서, 이 시험은 작업자 진입점 `serve.training.run_and_register(run_id)` 를 **직접 부른다**
(= 작업자가 할 일: `train.jobs.execute` → `Registry.register()`). 아키텍트가 D-57 을 정하면 그 경로로 바꾼다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.serve import training

pytestmark = [pytest.mark.gate("G-V01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

ROOT = Path(__file__).resolve().parents[1]
KEYS_18 = {"task", "type", "tenant", "entity_id", "prediction", "probability", "anomaly", "recommendation", "status",
           "warnings", "imputed_fields", "out_of_range_fields", "explain", "model", "uses", "prediction_id",
           "synthetic", "notice"}

# (원본 회사 등록부, 과제 짧은 이름, 기대 팩) — 코드는 같고 팩 · 등록부만 다르다
CASES = [("ks", "remaining_hours", "press"), ("sw", "delta_e", "textile")]


@pytest.fixture
def world(tmp_path, monkeypatch, request):
    source, short, pack = request.param
    m = h.make_tenant(source, tmp_path)
    base = tmp_path / f"tenants-{m.tenant.code}"
    monkeypatch.setenv(h.TENANTS_DIR_ENV, str(base))     # 등록부 루트 주입 — 환경변수(공식 경로), 코드 바꿔 끼우기 없음
    return SimpleNamespace(m=m, task=f"{m.tenant.code}.{short}", pack=pack, k=h.keys(m), tc=h.client(m), source=source)


def _inputs_from_lock(artifact_dir: str) -> dict:
    """학습 산출물 features.lock.json 의 보정값(학습 구간 중앙값 · 최빈값) — 학습 범위 한가운데 입력."""
    p = Path(artifact_dir)
    lock = json.loads(((p if p.is_absolute() else ROOT / p) / "features.lock.json").read_text(encoding="utf-8"))
    return h.safe_inputs(SimpleNamespace(lock=lock))


@pytest.mark.parametrize("world", CASES, ids=[f"{s}.{t}" for s, t, _ in CASES], indirect=True)
def test_vertical_slice(world):
    m, task, k, tc = world.m, world.task, world.k, world.tc
    t = m.tenant.code
    base = f"/api/v1/tenants/{t}/tasks/{task}"
    assert m.pack.code == world.pack                                   # 다른 팩 · 같은 코어

    # ── 모델 없음 → 503 model_not_ready (지어내지 않는다) ─────────────────────
    r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": {}})
    assert r.status_code in (422, 503)
    # ── 학습 요청: 역할 검사(실제 auth) → admin 202 queued ───────────────────
    assert tc.post(f"{base}/train", headers=h.hdr(k["operator"]), json={}).status_code == 403
    assert tc.post(f"{base}/train", json={}).status_code == 401
    r = tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert r.json()["status"] == "queued" and run_id.startswith("run_")
    again = tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={})   # 같은 스냅숏 · 설정 → 멱등
    assert again.status_code == 200 and again.json() == {"run_id": run_id, "status": "queued", "reused": True}

    # ── 작업 실행 → candidate 등록 (D-57 우회: 작업자 진입점 직접 호출) ──────────
    result, ref = training.run_and_register(run_id)
    assert result.status == "succeeded" and ref is not None and ref.stage == "candidate"
    assert result.synthetic is True and ref.synthetic is True

    # ── candidate 와 기준선 비교 ──────────────────────────────────────────────
    r = tc.get(f"{base}/models", headers=h.hdr(k["approver"]))
    assert r.status_code == 200, r.text
    (cand,) = r.json()["items"]
    assert (cand["version"], cand["stage"], cand["synthetic"]) == (ref.version, "candidate", True)
    assert cand["beats_baseline"] is True
    primary = cand["metrics"]["mae"]
    assert primary["value"] is not None and primary["baseline"] is not None
    assert primary["value"] < primary["baseline"]                       # 회귀 MAE — 기준선(학습 평균)을 이김

    # ── candidate 는 운영에 안 나간다 ────────────────────────────────────────
    probe = _inputs_from_lock(result.artifact_dir)
    r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": probe})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_ready"

    # ── stage (admin 만) ────────────────────────────────────────────────────
    assert tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["approver"])).status_code == 403
    r = tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["admin"]))
    assert r.status_code == 200 and r.json() == {"version": ref.version, "stage": "staging"}, r.text

    # ── promote = 승인 요청만 (production 그대로) ───────────────────────────────
    assert tc.post(f"{base}/models/{ref.version}/promote", headers=h.hdr(k["approver_other"]),
                   json={"reason": "시험"}).status_code == 403                    # 다른 과제 담당
    r = tc.post(f"{base}/models/{ref.version}/promote", headers=h.hdr(k["approver"]), json={"reason": "수직 관통"})
    assert r.status_code == 202 and r.json()["state"] == "pending", r.text
    aid = r.json()["approval_id"]
    r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": probe})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_ready"   # 승인 전엔 운영 모델 없음
    pend = tc.get(f"/api/v1/tenants/{t}/approvals", headers=h.hdr(k["operator"]), params={"state": "pending"})
    assert [a["approval_id"] for a in pend.json()["items"]] == [aid]

    # ── 승인 결정 = approval.decide() (API 결정 경로) ──────────────────────────
    assert tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["operator"]),
                   json={"decision": "approve", "reason": "x"}).status_code == 403
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]),
                json={"decision": "approve", "reason": "수직 관통 승인"})
    assert r.status_code == 200, r.text
    assert r.json() == {"approval_id": aid, "state": "approved", "production_version": ref.version}
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"   # 두 번 결정되지 않는다
    stages = {i["version"]: i["stage"] for i in tc.get(f"{base}/models", headers=h.hdr(k["admin"])).json()["items"]}
    assert stages == {ref.version: "production"}

    # ── predict — 표준 18키 계약 ───────────────────────────────────────────────
    assert tc.post(f"{base}/predict", headers=h.hdr(k["viewer"]), json={"inputs": probe}).status_code == 403
    entity = f"VS-{world.source}-0001"
    r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": probe, "entity_id": entity})
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out) == KEYS_18
    jsonschema.validate(out, h.response_schema())
    assert (out["task"], out["type"], out["tenant"], out["entity_id"]) == (task, "regression", t, entity)
    assert out["status"] == "ok" and out["synthetic"] is True
    assert isinstance(out["prediction"]["value"], float) and out["prediction"]["unit"]
    lo, hi = out["prediction"]["interval"]
    assert lo <= out["prediction"]["value"] <= hi
    assert out["prediction"]["baseline"] is not None
    assert out["probability"] is None and out["anomaly"] is None and out["recommendation"] is None
    assert out["model"]["version"] == ref.version and out["model"]["snapshot_id"] == ref.snapshot_id
    pid = out["prediction_id"]

    # ── mlp_prediction 1행 ────────────────────────────────────────────────────
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE prediction_id = %s", (pid,)) == 1
    assert h.count("SELECT count(*) AS n FROM mlp_prediction WHERE tenant_id = %s", (t,)) == 1
    with connect() as c:
        row = c.execute("SELECT task_id, version, entity_id, status, synthetic, outputs FROM mlp_prediction "
                        "WHERE prediction_id = %s", (pid,)).fetchone()
    assert (row["task_id"], row["version"], row["entity_id"], row["status"], row["synthetic"]) == \
        (task, ref.version, entity, "ok", True)
    assert row["outputs"] == out

    # ── actuals ──────────────────────────────────────────────────────────────
    actual = round(out["prediction"]["value"] + 0.5, 3)
    r = tc.post(f"{base}/actuals", headers=h.hdr(k["operator"]),
                json={"entity_id": entity, "value": actual,
                      "observed_at": datetime.now(timezone.utc).isoformat()})   # 예측 뒤(D2-112)
    assert r.status_code == 200, r.text
    assert r.json()["linked_prediction_ids"] == [pid]

    # ── trace — 스냅숏 해시 · 소스 참조까지 (admin 만) ─────────────────────────
    assert tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k["approver"])).status_code == 403
    r = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(k["admin"]))
    assert r.status_code == 200, r.text
    tr = r.json()
    with connect() as c:
        snap = c.execute("SELECT s.* FROM mlp_train_run r JOIN mlp_snapshot s USING (snapshot_id) WHERE r.run_id = %s",
                         (run_id,)).fetchone()
    assert tr["prediction"]["prediction_id"] == pid and tr["prediction"]["outputs"] == out
    assert tr["model"] == {"version": ref.version, "stage": "production", "algo": ref.algo,
                           "artifact_sha256": ref.artifact_sha256}
    assert tr["run"]["run_id"] == run_id and tr["run"]["config_hash"] and tr["run"]["seed"] == 42
    s = tr["snapshot"]
    assert s["snapshot_id"] == ref.snapshot_id == snap["snapshot_id"]
    assert s["sha256"] == snap["sha256"] and len(s["sha256"]) == 64
    assert s["rows"] == snap["rows"] > 0 and s["synthetic"] is True and s["ts_from"] and s["ts_to"]
    assert tr["sources"], "소스 참조가 비었다"
    src = tr["sources"][0]
    assert src["kind"] == "synthetic" and src["ref"] == snap["source_ref"]
    assert [a["value"] for a in tr["actuals"]] == [actual]

    # 다른 회사 키로는 추적이 보이지 않는다(존재를 숨긴다)
    other = h.make_tenant(world.source, Path(h._ART) / f"other-{t}")
    r = tc.get(f"/api/v1/predictions/{pid}/trace", headers=h.hdr(h.keys(other)["admin"]))
    assert r.status_code == 404
