"""개발2 시험 도우미 — 시험 DB(ml_test_db) · 임시 회사 · 가짜 학습 결과 · API 키.

- 시험마다 **새 회사 코드**(t + 6 hex)를 만든다: tenants/<원본>.yaml 을 임시 폴더에 복사하고 코드만 바꿔
  실제 로더(registry.tenants.load_and_merge)로 병합한다. 추가만 테이블(mlp_prediction · mlp_audit)을 지우지 않고도 서로 섞이지 않는다.
- 학습기(개발1)가 아직 없으므로 가짜 TrainResult 를 만든다: 작은 sklearn Pipeline 을 합성 프레임에 적합하고
  registry.artifacts.save_artifacts 로 산출물 4개를 쓴 뒤, mlp_snapshot · mlp_train_run 행을 직접 넣는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_ART = Path(tempfile.mkdtemp(prefix="mlp-dev2-art-"))
os.environ["MLP_DB_DSN"] = os.environ.get("MLP_TEST_DB_DSN") or "dbname=ml_test_db host=/tmp"
os.environ["MLP_ARTIFACT_DIR"] = str(_ART)
os.environ.pop("MLP_TENANT", None)

from mlcore.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from mlcore import auth  # noqa: E402
from mlcore.db.conn import connect  # noqa: E402
from mlcore.registry import artifacts, tenants  # noqa: E402
from mlcore.registry.packs import def_hash  # noqa: E402
from mlcore.registry.models import Registry  # noqa: E402

KST = timezone(timedelta(hours=9))
SCHEMA_RE = re.compile(r"```json predict-response-schema\n(.*?)```", re.S)


def response_schema() -> dict:
    return json.loads(SCHEMA_RE.search((ROOT / "contracts" / "predict-contract.md").read_text(encoding="utf-8")).group(1))


def db_ok() -> bool:
    try:
        with connect() as c:
            c.execute("SELECT 1 FROM mlp_model_version LIMIT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


# ── 임시 회사 ──────────────────────────────────────────────────────────────
def make_tenant(source: str, tmp: Path, *, overrides: dict[str, dict] | None = None, mode: str | None = None):
    """tenants/<source>.yaml 을 새 코드로 복사 → 병합 → mlp_tenant · mlp_task 행. → Merged."""
    code = "t" + secrets.token_hex(3)
    text = (ROOT / "tenants" / f"{source}.yaml").read_text(encoding="utf-8")
    text = re.sub(rf"^code: {source}\b", f"code: {code}", text, flags=re.M)
    text = re.sub(rf"(?<![A-Za-z0-9_]){source}\.(?=[a-z])", f"{code}.", text)
    if mode:
        text = re.sub(r"^mode: \w+", f"mode: {mode}", text, flags=re.M)
    base = tmp / f"tenants-{code}"
    base.mkdir(parents=True)
    (base / f"{code}.yaml").write_text(text, encoding="utf-8")
    for short, over in (overrides or {}).items():
        d = base / code / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        import yaml
        (d / f"{short}.yaml").write_text(yaml.safe_dump(over, allow_unicode=True), encoding="utf-8")
    m = tenants.load_and_merge(code, tenants_base=base)
    cfg = m.tenant.config
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode) VALUES (%s,%s,%s,%s)",
                  (code, cfg["name"] + " (시험)", cfg["pack"], cfg["mode"]))
        for task_id, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                      "VALUES (%s,%s,%s,%s,%s,%s)", (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    return m


def keys(m) -> dict[str, str]:
    """역할별 API 키(평문은 여기서만). approver 는 회사의 모든 과제 approver_role 을 맡는다."""
    roles = sorted({td.raw["approver_role"] for td in m.tasks.values()})
    out = {}
    with connect() as c:
        for role in ("viewer", "operator", "approver", "admin"):
            raw, h = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer) "
                      "VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                      (m.tenant.code, h, raw[:8], role, json.dumps(roles if role == "approver" else []), f"test-{role}"))
            out[role] = raw
        raw, h = auth.new_key()   # 다른 과제 담당 approver (own_task 시험)
        c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer) "
                  "VALUES (%s,%s,%s,'approver','[\"nobody\"]'::jsonb,'test-other-approver')", (m.tenant.code, h, raw[:8]))
        out["approver_other"] = raw
    return out


def hdr(key: str) -> dict:
    return {"X-API-Key": key}


# ── 가짜 학습 ──────────────────────────────────────────────────────────────
def task_features(m, task_id: str) -> dict[str, dict]:
    from mlcore.serve.catalog import TaskCatalog
    return TaskCatalog(m).get(m.tenant.code, task_id).features


def synth_frame(feats: dict[str, dict], n: int, seed: int) -> pd.DataFrame:
    """[min, max] 의 가운데 80% 에서 균등 — 학습 범위(p1~p99)가 검증 범위보다 좁아 out_of_range 를 시험할 수 있다."""
    rng = np.random.default_rng(seed)
    cols = {}
    for name, f in feats.items():
        if f["dtype"] == "category":
            cols[name] = rng.choice(list(f["values"]), size=n)
        else:
            lo, hi = float(f["min"]), float(f["max"])
            pad = (hi - lo) * 0.1
            x = rng.uniform(lo + pad, hi - pad, size=n)
            cols[name] = np.round(x).astype(int) if f["dtype"] == "int" else x
    return pd.DataFrame(cols)


def _target(frame: pd.DataFrame, feats: dict[str, dict], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 1)
    y = np.zeros(len(frame))
    for i, (name, f) in enumerate(feats.items()):
        if f["dtype"] == "category":
            codes = {v: j for j, v in enumerate(f["values"])}
            y += frame[name].map(codes).to_numpy() * (i + 1) * 0.3
        else:
            lo, hi = float(f["min"]), float(f["max"])
            y += ((frame[name].to_numpy(dtype=float) - lo) / (hi - lo)) * ((-1) ** i) * (i + 1)
    return y + rng.normal(0, 0.1, len(frame))


def fake_train(m, task_id: str, *, seed: int = 0, n: int = 300, beats_baseline: bool = True,
               synthetic: bool = True, warnings: list | None = None, snapshot_source: dict | None = None):
    """→ TrainResult 모양 객체(SimpleNamespace). DB 에 mlp_snapshot · mlp_train_run(succeeded) 행을 넣는다."""
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    code = m.tenant.code
    td = m.tasks[task_id]
    feats = task_features(m, task_id)
    frame = synth_frame(feats, n, seed)
    y = _target(frame, feats, seed)
    cats = [k for k, f in feats.items() if f["dtype"] == "category"]
    nums = [k for k in feats if k not in cats]
    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), cats), ("num", StandardScaler(), nums)])
    if td.type == "risk":
        y = (y > np.quantile(y, 0.7)).astype(int)
        model = Pipeline([("pre", pre), ("m", LogisticRegression(max_iter=500))]).fit(frame, y)
        baseline, interval = float(y.mean()), None
    else:
        model = Pipeline([("pre", pre), ("m", Ridge(alpha=1.0))]).fit(frame, y)
        resid = np.abs(y - model.predict(frame))
        baseline = float(y.mean())
        interval = {"method": "split_conformal", "alpha": 0.1, "q": float(np.quantile(resid, 0.9))}
    ranges, fills = {}, {}
    for k, f in feats.items():
        if f["dtype"] == "category":
            ranges[k] = {"values": sorted(set(frame[k]))}
            fills[k] = str(frame[k].mode().iloc[0])
        else:
            ranges[k] = {"p1": float(np.quantile(frame[k], 0.01)), "p99": float(np.quantile(frame[k], 0.99))}
            fills[k] = float(np.median(frame[k]))
    lock = artifacts.features_lock(list(feats), feats, ranges=ranges, fills=fills, baseline=baseline, interval=interval)
    run_id = "run_" + secrets.token_hex(8)
    vdir = Path(get_settings().artifact_dir) / code / task_id / run_id
    report = {"warnings": warnings or [], "champion": "ridge" if td.type != "risk" else "logreg"}
    artifacts.save_artifacts(vdir, model, report, lock)
    sha = hashlib.sha256(frame.to_csv(index=False).encode() + run_id.encode()).hexdigest()
    snapshot_id = "snp_" + sha[:16]
    ts_from = datetime(2026, 1, 1, tzinfo=KST)
    ts_to = ts_from + timedelta(hours=n - 1)
    with connect() as c:
        c.execute("INSERT INTO mlp_snapshot (snapshot_id, tenant_id, task_id, rows, ts_from, ts_to, columns, missing_rates, "
                  "ranges, sha256, source_ref, synthetic, path) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,'{}'::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s)",
                  (snapshot_id, code, task_id, n, ts_from, ts_to, json.dumps(list(frame.columns)), json.dumps(ranges), sha,
                   json.dumps(snapshot_source or {"kind": "synthetic", "seed": seed, "generator": "tests/_dev2.py"}),
                   synthetic, f"var/snapshots/{code}/{task_id}/{snapshot_id}.parquet"))
        c.execute("INSERT INTO mlp_train_run (run_id, tenant_id, task_id, snapshot_id, config_hash, seed, code_version, status, "
                  "started_at, finished_at, report) VALUES (%s,%s,%s,%s,%s,%s,'test','succeeded',now(),now(),%s::jsonb)",
                  (run_id, code, task_id, snapshot_id, def_hash({"run": run_id}), seed, json.dumps(report)))
    metric = "mae" if td.type != "risk" else "brier"
    return SimpleNamespace(
        run_id=run_id, status="succeeded", champion=report["champion"], valid_metrics={}, selection_reason="test",
        test_metrics={metric: {"value": 1.0, "baseline": 2.0 if beats_baseline else 0.5,
                               "delta_vs_baseline": -1.0 if beats_baseline else 0.5}},
        beats_baseline=beats_baseline, artifact_dir=str(vdir), report=report, warnings=warnings or [], ledger=[],
        frame=frame, lock=lock)


def registered(m, task_id: str, **kw):
    res = fake_train(m, task_id, **kw)
    return Registry().register(res, tenant_id=m.tenant.code, task_id=task_id), res


def to_production(m, task_id: str, **kw):
    """학습 → candidate → staging → 승인 요청 → decide(approve). → ModelRef(production)."""
    from mlcore import approval
    ref, res = registered(m, task_id, **kw)
    reg = Registry()
    reg.stage(m.tenant.code, task_id, ref.version, actor="test-admin")
    aid = reg.request_promotion(m.tenant.code, task_id, ref.version, actor="test-approver", action="promote", reason=None)
    approval.decide(aid, actor="test-approver", actor_role="approver", approve=True, reason="시험")
    return reg.get(m.tenant.code, task_id), res


def safe_inputs(res) -> dict:
    """학습 보정값(중앙값 · 최빈값) — 학습 범위 한가운데."""
    out = {}
    for k, item in res.lock["features"].items():
        v = item["fill"]
        out[k] = int(round(v)) if item["dtype"] == "int" else v
    return out


def sample_inputs(res, row: int = 0) -> dict:
    """학습 프레임의 한 행(학습 범위 안) — JSON 으로 보낼 수 있는 값."""
    out = {}
    for k, v in res.frame.iloc[row].items():
        out[k] = v.item() if hasattr(v, "item") else v
    return out


def client(m):
    """API TestClient — 임시 회사 등록부를 app.state 에 꽂는다(기동은 학습하지 않는다)."""
    from fastapi.testclient import TestClient

    from mlcore.api.main import app
    tc = TestClient(app)
    tc.__enter__()
    app.state.registry = m
    app.state.catalog = None
    return tc


def count(sql: str, params=()) -> int:
    with connect() as c:
        return c.execute(sql, params).fetchone()["n"]
