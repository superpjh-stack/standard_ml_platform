"""학습 작업 접수 — 소스 읽기 → 스냅숏 고정 → mlp_snapshot → mlp_train_run(queued) (spec §5.5 · interfaces §4 submit).

학습 코드(mlcore.train)를 import 하지 않는다 — API 가 이 함수를 불러도 기동 경로에 학습이 따라오지 않는다(G-M06).
같은 스냅숏 + 같은 설정이면 기존 run_id 를 돌려준다(멱등, mlp_train_run UNIQUE).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

from ..serve.errors import InvalidInput     # 가벼운 오류 모듈(학습 코드 아님 — G-M06 무관)
from ..settings import get_settings
from . import snapshot
from .features import feature_defs
from .sources import ReadSpec, SourceDisconnected, SyntheticSource, make_source


class TrainBusy(Exception):
    """회사당 동시 학습 1개(spec §5.5) — 이미 queued · running 인 작업이 있다."""


class NotTrainable(InvalidInput):
    """학습 대상이 아닌 과제(review_queue · 규칙 extract · quote · optimize) — 접수 시점 422, mlp_train_run 0행 (D2-82).
    API 오류 처리기가 `ServeError` 로 받아 `{"error": {code: invalid_input, detail: {rule: not_trainable, type}}}`."""

    default_message = "학습 대상이 아닌 과제입니다 — uses 과제의 운영 모델을 씁니다"


class NoTarget(Exception):
    """지도학습 과제인데 목표 열이 없다 — doctor · 학습은 `목표 없음` 으로 보인다."""


TENANTS_DIR_ENV = "MLP_TENANTS_DIR"   # 등록부 루트 주입 (이슈 #4) — 값은 폴더 경로(os.pathsep 로 여러 개)


def tenants_base_for(tenant_id: str, tenants_base: str | Path | None = None) -> Path | None:
    """회사 등록부 `<code>.yaml` 이 있는 폴더. 순서: 인자 → 환경변수 MLP_TENANTS_DIR(여러 폴더면 앞에서부터
    `<code>.yaml` 이 있는 첫 폴더) → None(= 로더 기본 `tenants/`). API · 작업자 · 시험이 같은 규칙을 쓴다.
    폴더를 찾지 못하면 None 을 돌려 기본 폴더로 간다(없는 회사는 로더가 그대로 실패를 보인다)."""
    if tenants_base is not None:
        return Path(tenants_base)
    for d in (os.environ.get(TENANTS_DIR_ENV) or "").split(os.pathsep):
        if d and (Path(d) / f"{tenant_id}.yaml").is_file():
            return Path(d)
    return None


def load_merged(tenant_id: str, tenants_base: str | Path | None = None):
    """registry.tenants.load_and_merge 를 주입된 등록부 루트로 부른다(없으면 로더 기본값)."""
    from ..registry import tenants

    base = tenants_base_for(tenant_id, tenants_base)
    if base is None and os.environ.get(TENANTS_DIR_ENV):
        base = tenants.TENANTS_DIR          # 환경변수 폴더들에 이 회사가 없다 → 저장소 tenants/ (여러 폴더 값을 로더가 한 경로로 읽지 않게)
    return tenants.load_and_merge(tenant_id, tenants_base=base) if base is not None else tenants.load_and_merge(tenant_id)


def config_hash(def_hash: str, seed: int, code_version: str, candidates: Sequence[str], candidate_params: dict) -> str:
    obj = {"def_hash": def_hash, "seed": int(seed), "code_version": code_version, "candidates": list(candidates),
           "candidate_params": candidate_params}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def run_id_for(tenant_id: str, task_id: str, snapshot_id: str, cfg_hash: str) -> str:
    return "run_" + hashlib.sha256(f"{tenant_id}|{task_id}|{snapshot_id}|{cfg_hash}".encode()).hexdigest()[:16]


def default_seed(task, pack_meta: dict) -> int:
    return int(task.raw.get("seed", (pack_meta.get("synth") or {}).get("seed", 42)))


def task_candidates(task) -> tuple[tuple[str, ...], dict[str, dict]]:
    from .taskview import learn_view

    task = learn_view(task)               # extract 는 model: 블록의 후보 (D2-15)
    cands = tuple(task.raw.get("candidates") or ())
    params = {c: dict((task.raw.get("candidate_params") or {}).get(c) or {}) for c in cands}
    return cands, params


def source_name_for(cfg: dict, source_role: str | None) -> str:
    """기본 소스: 회사 mode 와 같은 이름(demo · eval …)의 sources 항목."""
    name = source_role or cfg["mode"]
    if name not in (cfg.get("sources") or {}):
        raise SourceDisconnected("unknown", f"소스 {name!r} 가 회사 등록부에 없다")
    return name


def read_frame(tenant_id: str, task_id: str, *, source_role: str | None = None,
               tenants_base: str | Path | None = None):
    """(merged, task, frame, source_ref, synthetic) — 회사 등록부대로 소스를 골라 표준 프레임을 읽는다."""
    m = load_merged(tenant_id, tenants_base)
    if task_id not in m.tasks:
        raise KeyError(f"과제 {task_id} 가 켜져 있지 않다")
    from .taskview import learn_view

    task = learn_view(m.tasks[task_id])   # extract 는 model: 블록의 변수 · 목표로 읽는다
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
           test: bool = False, tenants_base: str | Path | None = None) -> str:
    """접수 → run_id. 같은 스냅숏 + 설정이면 기존 run_id(멱등).

    재시도 정책(D-49 후속, progress-dev1.md §1.1): run_id 가 결정적이라 같은 스냅숏 · 설정의 **failed** 실행은
    새 행을 만들 수 없다. 그래서 같은 요청이 다시 오면 그 행을 `queued` 로 되돌린다(started_at · finished_at ·
    report · error 비움, 이전 오류는 log 에 남김) + `mlp_audit` 에 `train.retry` 1행(같은 트랜잭션).
    succeeded · queued · running 은 그대로 돌려준다. 회사에 다른 queued · running 이 있으면 TrainBusy."""
    import psycopg

    from ..db.conn import connect
    from .taskview import trainable

    m0 = load_merged(tenant_id, tenants_base)
    if task_id in m0.tasks and not trainable(m0.tasks[task_id]):        # 소스 · 스냅숏 · 실행 행보다 먼저 거부
        t0 = m0.tasks[task_id]
        raise NotTrainable(detail={"rule": "not_trainable", "type": t0.type})
    m, task, frame, ref, synthetic = read_frame(tenant_id, task_id, source_role=source_role, tenants_base=tenants_base)
    snap = snapshot.freeze(frame, tenant_id=tenant_id, task=task, source_ref=ref, synthetic=synthetic)
    snapshot.record(snap, test=test)
    s = default_seed(task, m.pack.meta) if seed is None else int(seed)
    cands, params = task_candidates(task)
    code_version = get_settings().code_version
    h = config_hash(task.def_hash, s, code_version, cands, params)
    rid = run_id_for(tenant_id, task_id, snap.snapshot_id, h)
    with connect(test) as c:
        row = c.execute("SELECT run_id, status, error, log FROM mlp_train_run WHERE tenant_id=%s AND task_id=%s "
                        "AND snapshot_id=%s AND config_hash=%s", (tenant_id, task_id, snap.snapshot_id, h)).fetchone()
        if row and row["status"] != "failed":
            return row["run_id"]
        try:
            if row:
                return _requeue_failed(c, row, tenant_id=tenant_id, actor=actor)
            c.execute("INSERT INTO mlp_train_run (run_id, tenant_id, task_id, snapshot_id, config_hash, seed, code_version, "
                      "status, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,'queued',%s)",
                      (rid, tenant_id, task_id, snap.snapshot_id, h, s, code_version, actor))
        except psycopg.errors.UniqueViolation as e:
            raise TrainBusy(f"{tenant_id}: 진행 중인 학습이 있다") from e
    return rid


def _requeue_failed(c, row: dict, *, tenant_id: str, actor: str) -> str:
    from .. import audit

    prev = row.get("error")
    note = f"재시도 접수 ({actor}) — 이전 오류: {json.dumps(prev, ensure_ascii=False, default=str) if prev else '없음'}"
    log = ((row.get("log") or "") + "\n" + note).strip()
    c.execute("UPDATE mlp_train_run SET status='queued', started_at=NULL, finished_at=NULL, report=NULL, error=NULL, "
              "log=%s, created_by=%s WHERE run_id=%s AND status='failed'", (log, actor, row["run_id"]))
    audit.write(tenant_id=tenant_id, actor=actor, action="train.retry", target=row["run_id"],
                detail={"rule": "failed_requeue", "previous_error": prev}, conn=c)
    return row["run_id"]


def _iso(ts):
    from datetime import timedelta, timezone

    return ts.astimezone(timezone(timedelta(hours=9))).isoformat(timespec="seconds") if ts is not None else None


def run_view(run_id: str, *, tenant_id: str | None = None, test: bool = False) -> dict | None:
    """GET /runs/{id} 응답 본문(contracts/api-contract.md §4). 없거나 다른 회사면 None(→ 404, 존재를 숨긴다).
    DB 행만 읽는다 — 학습 코드를 import 하지 않는다(API 가 불러도 G-M06 그대로).
    계약 키 + 화면 4 용 덧붙임(`report` 요약: 선정 사유 · 기준선 · 구간 · 보정 · 중요도 · 잔차 · 보정 곡선)."""
    from ..db.conn import connect

    with connect(test) as c:
        r = c.execute("SELECT r.*, s.rows, s.ts_from, s.ts_to, s.sha256, s.synthetic FROM mlp_train_run r "
                      "JOIN mlp_snapshot s ON s.snapshot_id = r.snapshot_id WHERE r.run_id=%s", (run_id,)).fetchone()
        if r is None or (tenant_id is not None and r["tenant_id"] != tenant_id):
            return None
        v = c.execute("SELECT version, stage FROM mlp_model_version WHERE run_id=%s", (run_id,)).fetchone()
    rep = r["report"] or {}
    test_part = rep.get("test") or {}
    return {
        "run_id": r["run_id"], "status": r["status"], "task": r["task_id"],
        "snapshot": {"snapshot_id": r["snapshot_id"], "rows": r["rows"], "ts_from": _iso(r["ts_from"]),
                     "ts_to": _iso(r["ts_to"]), "sha256": r["sha256"], "synthetic": r["synthetic"]},
        "champion": rep.get("champion"), "valid_metrics": rep.get("valid_metrics") or {},
        "test_metrics": rep.get("test_metrics") or {}, "beats_baseline": rep.get("beats_baseline"),
        "version": v["version"] if v else None, "stage": v["stage"] if v else None,
        "warnings": rep.get("warnings") or ([] if r["status"] != "failed" else
                                            [{"code": (r["error"] or {}).get("code") or "train_failed", "message": "학습 실패",
                                              "detail": r["error"] or {}}]),
        "seed": r["seed"], "code_version": r["code_version"], "config_hash": r["config_hash"],
        "created_at": _iso(r["created_at"]), "started_at": _iso(r["started_at"]), "finished_at": _iso(r["finished_at"]),
        "error": r["error"],
        "report": {k: rep.get(k) for k in ("selection_metric", "selection_reason", "valid_baseline", "baseline",
                                           "baseline_value", "baselines_compared", "beats_baseline_rule", "interval",
                                           "threshold", "threshold_rule", "calibration", "search", "outliers",
                                           "outliers_removed", "split", "task_type", "labels", "extract_metrics")}
        | {"permutation_importance": test_part.get("permutation_importance"),
           "residuals": test_part.get("residuals"), "error_by_category": test_part.get("error_by_category"),
           "calibration_curve": test_part.get("calibration_curve"),
           # 대기열 재료 요약(G2-R01) — 시험 구간 잔차 행 수 · 검증 잔차 행 수만(행 자체는 대기열 API 가 쓴다)
           "queue_residuals": ({"origin": q.get("origin"), "source": q.get("source"), "test_rows": len(q.get("test") or []),
                                "valid_rows": q.get("valid_rows")} if (q := rep.get("queue_residuals")) else None)},
    }
