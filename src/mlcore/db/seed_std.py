"""표준 시드 — tenants/*.yaml(템플릿 제외) 의 회사 · 켜진 과제를 mlp_tenant · mlp_task 에 넣는다 (멱등).

`uv run python -m mlcore.db.seed_std [--test]`. std/*.yaml 은 DB 가 아니라 파일이 정본이라 넣지 않고 형식만 검사한다.
모델 · 스냅숏 · 예측은 넣지 않는다 — 운영 모델은 학습 → 승인으로만 생긴다.
"""

from __future__ import annotations

import argparse
import json

from ..registry import packs, tenants
from .conn import connect

STD_FILES = ("task_types", "statuses", "metrics", "split_policies", "candidates", "roles")


def check_std() -> dict[str, int]:
    counts = {}
    for name in STD_FILES:
        data = packs.std(name)
        key = {"task_types": "types", "statuses": "statuses", "metrics": "metrics", "split_policies": "policies",
               "candidates": "candidates", "roles": "roles"}[name]
        counts[name] = len(data[key])
    return counts


def seed(test: bool = False) -> dict:
    counts = check_std()
    n_tenant = n_task = 0
    with connect(test) as c:
        for code in tenants.all_codes():
            m = tenants.load_and_merge(code)
            cfg = m.tenant.config
            c.execute(
                "INSERT INTO mlp_tenant (tenant_id, name, pack, mode, hub_company, config_hash) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, pack=EXCLUDED.pack, mode=EXCLUDED.mode, "
                "hub_company=EXCLUDED.hub_company, config_hash=EXCLUDED.config_hash, updated_at=now()",
                (code, cfg["name"], cfg["pack"], cfg["mode"], cfg.get("hub_company"), packs.def_hash(cfg)))
            n_tenant += 1
            for task_id, td in m.tasks.items():
                c.execute(
                    "INSERT INTO mlp_task (tenant_id, task_id, pack_task_id, type, def_hash, enabled, approver_role) "
                    "VALUES (%s,%s,%s,%s,%s,true,%s) ON CONFLICT (tenant_id, task_id) DO UPDATE SET "
                    "pack_task_id=EXCLUDED.pack_task_id, type=EXCLUDED.type, def_hash=EXCLUDED.def_hash, "
                    "approver_role=EXCLUDED.approver_role, enabled=true, disabled_reason=NULL, updated_at=now()",
                    (code, task_id, td.pack_id, td.type, td.def_hash, td.raw["approver_role"]))
                n_task += 1
            for task_id, reason in m.disabled.items():
                c.execute("UPDATE mlp_task SET enabled=false, disabled_reason=%s WHERE tenant_id=%s AND task_id=%s",
                          (reason, code, task_id))
    return {"std": counts, "tenants": n_tenant, "tasks": n_task}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="ml_test_db 에 넣는다")
    print(json.dumps(seed(ap.parse_args().test), ensure_ascii=False))
