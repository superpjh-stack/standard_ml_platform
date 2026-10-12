"""개발3 시험 도우미 — 시험 DB(ml_test_db) · 임시 등록부 루트(MLP_TENANTS_DIR) · 학습 → production.

- 시험마다 **새 회사 코드**를 만든다(추가만 테이블 mlp_prediction · mlp_audit 을 지우지 않고 격리).
  `tenants/<원본>.yaml` 을 임시 폴더에 새 코드로 복사하고, 등록부 루트를 `MLP_TENANTS_DIR` 로 그 폴더에 둔다 —
  학습기 · 작업자 · API 가 모두 같은 로더(`registry.tenants.tenants_dir()`)를 쓰므로 코드 경로는 그대로다.
- production 은 시험에서도 `approval.decide()` 로만 만든다(승인 요청 → 결정).
"""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["MLP_DB_DSN"] = os.environ.get("MLP_TEST_DB_DSN") or "dbname=ml_test_db host=/tmp"
os.environ.pop("MLP_TENANT", None)

from mlcore.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from mlcore import auth  # noqa: E402
from mlcore.db.conn import connect  # noqa: E402
from mlcore.registry import tenants  # noqa: E402


def db_ok() -> bool:
    try:
        with connect() as c:
            c.execute("SELECT 1 FROM mlp_monitor_daily LIMIT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


def new_code(prefix: str = "d") -> str:
    return prefix + secrets.token_hex(3)


def copy_tenant(source: str, base: Path, code: str | None = None, *, mode: str | None = None) -> str:
    """tenants/<source>.yaml → <base>/<code>.yaml (코드 · 과제 접두만 바꾼다)."""
    code = code or new_code()
    text = (ROOT / "tenants" / f"{source}.yaml").read_text(encoding="utf-8")
    text = re.sub(rf"^code: {source}\b", f"code: {code}", text, flags=re.M)
    text = re.sub(rf"(?<![A-Za-z0-9_]){source}\.(?=[a-z])", f"{code}.", text)
    if mode:
        text = re.sub(r"^mode: \w+", f"mode: {mode}", text, flags=re.M)
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{code}.yaml").write_text(text, encoding="utf-8")
    return code


def register_db(code: str) -> tenants.Merged:
    """병합 → mlp_tenant · mlp_task 행 (seed_std 와 같은 열)."""
    from mlcore.registry.packs import def_hash

    m = tenants.load_and_merge(code)
    cfg = m.tenant.config
    with connect() as c:
        c.execute("INSERT INTO mlp_tenant (tenant_id, name, pack, mode, hub_company, config_hash) VALUES (%s,%s,%s,%s,%s,%s) "
                  "ON CONFLICT (tenant_id) DO NOTHING",
                  (code, cfg["name"] + " (시험)", cfg["pack"], cfg["mode"], cfg.get("hub_company"), def_hash(cfg)))
        for task_id, td in m.tasks.items():
            c.execute("INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, approver_role) "
                      "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                      (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
    return m


def keys(m) -> dict[str, str]:
    roles = sorted({td.raw["approver_role"] for td in m.tasks.values()})
    out = {}
    with connect() as c:
        for role in ("viewer", "operator", "approver", "admin"):
            raw, h = auth.new_key()
            c.execute("INSERT INTO mlp_api_key (tenant_id, key_hash, key_prefix, role, approver_roles, consumer) "
                      "VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                      (m.tenant.code, h, raw[:8], role, json.dumps(roles if role == "approver" else []), f"test-{role}"))
            out[role] = raw
    return out


def hdr(key: str) -> dict:
    return {"X-API-Key": key}


def train_to_production(code: str, task_id: str, *, source_role: str | None = None) -> str:
    """접수 → 작업자(run_and_register) → stage → 승인 요청 → approval.decide → production 버전."""
    from mlcore import approval
    from mlcore.data import jobs
    from mlcore.registry.models import Registry
    from mlcore.serve import training

    rid = jobs.submit(code, task_id, actor="test-admin", source_role=source_role)
    result, ref = training.run_and_register(rid)
    assert result.status == "succeeded" and ref is not None, result.report
    reg = Registry()
    reg.stage(code, task_id, ref.version, actor="test-admin", role="admin")
    aid = reg.request_promotion(code, task_id, ref.version, actor="test-approver", action="promote", reason="시험 준비")
    out = approval.decide(aid, actor="test-approver", actor_role="approver", approve=True, reason="시험 준비")
    assert out["production_version"] == ref.version
    return ref.version


def production_version(code: str, task_id: str) -> str | None:
    with connect() as c:
        row = c.execute("SELECT version FROM mlp_model_version WHERE tenant_id=%s AND task_id=%s AND stage='production'",
                        (code, task_id)).fetchone()
    return row["version"] if row else None


def client(code: str):
    """API TestClient — MLP_TENANT=code 로 기동(lifespan 이 등록부를 병합한다, 학습하지 않는다)."""
    from fastapi.testclient import TestClient

    from mlcore.api.main import app

    os.environ["MLP_TENANT"] = code
    get_settings.cache_clear()
    tc = TestClient(app)
    tc.__enter__()
    app.state.catalog = None
    os.environ.pop("MLP_TENANT", None)
    get_settings.cache_clear()
    return tc
