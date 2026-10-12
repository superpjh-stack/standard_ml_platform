"""학습 작업 접수 — 소스 읽기 → 스냅숏 고정 → mlp_snapshot → mlp_train_run(queued) (spec §5.5 · interfaces §4 submit).

학습 코드(mlcore.train)를 import 하지 않는다 — API 가 이 함수를 불러도 기동 경로에 학습이 따라오지 않는다(G-M06).
같은 스냅숏 + 같은 설정이면 기존 run_id 를 돌려준다(멱등, mlp_train_run UNIQUE).
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from ..settings import get_settings
from . import snapshot
from .features import feature_defs
from .sources import ReadSpec, SourceDisconnected, SyntheticSource, make_source


class TrainBusy(Exception):
    """회사당 동시 학습 1개(spec §5.5) — 이미 queued · running 인 작업이 있다."""


class NoTarget(Exception):
    """지도학습 과제인데 목표 열이 없다 — doctor · 학습은 `목표 없음` 으로 보인다."""


def config_hash(def_hash: str, seed: int, code_version: str, candidates: Sequence[str], candidate_params: dict) -> str:
    obj = {"def_hash": def_hash, "seed": int(seed), "code_version": code_version, "candidates": list(candidates),
           "candidate_params": candidate_params}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def run_id_for(tenant_id: str, task_id: str, snapshot_id: str, cfg_hash: str) -> str:
    return "run_" + hashlib.sha256(f"{tenant_id}|{task_id}|{snapshot_id}|{cfg_hash}".encode()).hexdigest()[:16]


def default_seed(task, pack_meta: dict) -> int:
    return int(task.raw.get("seed", (pack_meta.get("synth") or {}).get("seed", 42)))


def task_candidates(task) -> tuple[tuple[str, ...], dict[str, dict]]:
    cands = tuple(task.raw.get("candidates") or ())
    params = {c: dict((task.raw.get("candidate_params") or {}).get(c) or {}) for c in cands}
    return cands, params


def source_name_for(cfg: dict, source_role: str | None) -> str:
    """기본 소스: 회사 mode 와 같은 이름(demo · eval …)의 sources 항목."""
    name = source_role or cfg["mode"]
    if name not in (cfg.get("sources") or {}):
        raise SourceDisconnected("unknown", f"소스 {name!r} 가 회사 등록부에 없다")
    return name


def read_frame(tenant_id: str, task_id: str, *, source_role: str | None = None):
    """(merged, task, frame, source_ref, synthetic) — 회사 등록부대로 소스를 골라 표준 프레임을 읽는다."""
    from ..registry.tenants import load_and_merge

    m = load_and_merge(tenant_id)
    if task_id not in m.tasks:
        raise KeyError(f"과제 {task_id} 가 켜져 있지 않다")
    task = m.tasks[task_id]
    cfg = m.tenant.config
    sname = source_name_for(cfg, source_role)
    scfg = cfg["sources"][sname]
    cats = cfg.get("categories") or {}
    if scfg.get("kind") == "synthetic":
        from ..registry.tenants import synth_call

        try:
            src = SyntheticSource.from_call(synth_call(m, task_id, role=sname))
        except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
            raise SourceDisconnected("synthetic", f"{type(e).__name__}: {e}") from e
    else:
        src = make_source(scfg, pack_dir=m.pack.path, pack_meta=m.pack.meta, categories=cats)
    feats = feature_defs(m.pack.features, task.raw.get("features") or [], cats, m.pack.std_name)
    cmap = {**(cfg.get("feature_map") or {}), **(cfg.get("target_map") or {})} if scfg.get("kind") != "synthetic" else {}
    frame = src.read(ReadSpec(tenant_id=tenant_id, task=task, features=feats, columns_map=cmap))
    if (task.raw.get("target") or {}).get("name") and ("target" not in frame.columns or not frame["target"].notna().any()):
        raise NoTarget(f"{task_id}: 목표 없음")
    ref = {"source": sname, **src.source_ref()}
    return m, task, frame, ref, scfg.get("kind") == "synthetic"


def submit(tenant_id: str, task_id: str, *, actor: str, source_role: str | None = None, seed: int | None = None,
           test: bool = False) -> str:
    import psycopg

    from ..db.conn import connect

    m, task, frame, ref, synthetic = read_frame(tenant_id, task_id, source_role=source_role)
    snap = snapshot.freeze(frame, tenant_id=tenant_id, task=task, source_ref=ref, synthetic=synthetic)
    snapshot.record(snap, test=test)
    s = default_seed(task, m.pack.meta) if seed is None else int(seed)
    cands, params = task_candidates(task)
    code_version = get_settings().code_version
    h = config_hash(task.def_hash, s, code_version, cands, params)
    rid = run_id_for(tenant_id, task_id, snap.snapshot_id, h)
    with connect(test) as c:
        row = c.execute("SELECT run_id FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s AND snapshot_id=%s "
                        "AND config_hash=%s", (tenant_id, task_id, snap.snapshot_id, h)).fetchone()
        if row:
            return row["run_id"]
        try:
            c.execute("INSERT INTO mlp_train_run (run_id, tenant_id, task_id, snapshot_id, config_hash, seed, code_version, "
                      "status, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,'queued',%s)",
                      (rid, tenant_id, task_id, snap.snapshot_id, h, s, code_version, actor))
        except psycopg.errors.UniqueViolation as e:
            raise TrainBusy(f"{tenant_id}: 진행 중인 학습이 있다") from e
    return rid
