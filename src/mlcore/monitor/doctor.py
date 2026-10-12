"""doctor — 회사 소스 점검 (spec §4.1 · G-M08 · contracts/api-contract.md §4 `doctor`). 소유 개발3.

    uv run python -m mlcore.monitor.doctor --tenant <code>          # fixture 모드(기본): 합성 · CSV 만 실제로 읽는다
    make doctor TENANT=<code>                                         # (Makefile 연결은 아키텍트)

소스(등록부 `sources.<role>`)마다 `연결`/`미연결` · 행 수 · 기간 · 변수 대응률 · 결측률 · `목표 없음` 을 낸다.
- synthetic · csv: 어댑터 `probe(spec)` 로 실제로 읽는다(개발1 어댑터).
- gateway · dataplatform · mes: fixture 모드에서는 **부르지 않는다**(D-13) → `미연결` + 사유. 대응률 · 목표는 그 소스의
  테이블(`tables` · `table` · `view`)에 속한 `feature_map` · `target_map` 열로 소스별로 센다(D-122). 실연결 확인은 사람이 `doctor-live`.
실패는 숨기지 않는다 — 예외는 `미연결` + message 로 보인다(키 · 호스트 · DSN 값은 쓰지 않는다).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from ..registry import tenants

FIXTURE_KINDS = ("synthetic", "csv")
LIVE_KINDS = ("gateway", "dataplatform", "mes")


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat(timespec="seconds") if ts is not None else None


def _learned(merged: tenants.Merged) -> list[tenants.TaskDef]:
    """학습 보기(`data.taskview.learn_view`) 로 본 학습 과제 — extract 는 model: 블록의 변수 · 라벨 열(D2-44 · D2-45)."""
    from ..data.taskview import learn_view
    out = []
    for t in merged.tasks.values():
        v = learn_view(t)
        if v.raw.get("features"):
            out.append(v)
    return out


def _features(merged: tenants.Merged) -> list[str]:
    out: dict[str, None] = {}
    for t in _learned(merged) + [t for t in merged.tasks.values() if t.type == "optimize"]:
        for key in ("features", "fixed", "controls"):
            for f in t.raw.get(key) or []:
                out[f] = None
    return list(out)


def _probe_fixture(merged: tenants.Merged, role: str, cfg: dict) -> dict:
    from ..data.features import feature_defs
    from ..data.sources import ReadSpec, SourceDisconnected, SyntheticSource, make_source

    tcfg = merged.tenant.config
    cats = tcfg.get("categories") or {}
    learned = _learned(merged)
    per_task: dict[str, Any] = {}
    first = None
    for task in learned:
        try:
            if cfg.get("kind") == "synthetic":
                src = SyntheticSource.from_call(tenants.synth_call(merged, task.id, role=role))
            else:
                src = make_source(cfg, pack_dir=merged.pack.path, pack_meta=merged.pack.meta, categories=cats)
        except (SourceDisconnected, ImportError, FileNotFoundError, KeyError, ValueError) as e:
            reason = getattr(e, "reason", None) or f"{type(e).__name__}: {e}"
            return {"status": "미연결", "message": str(reason)[:200]}
        feats = feature_defs(merged.pack.features, task.raw.get("features") or [], cats, merged.pack.std_name)
        cmap = {**(tcfg.get("feature_map") or {}), **(tcfg.get("target_map") or {})} if cfg.get("kind") != "synthetic" else {}
        health = src.probe(ReadSpec(tenant_id=merged.tenant.code, task=task, features=feats, columns_map=cmap))
        if not health.connected:
            return {"status": "미연결", "message": health.message}
        per_task[task.id] = health
        first = first or health
    if first is None:
        return {"status": "미연결", "message": "학습 과제가 없다"}
    covers = [h.feature_coverage for h in per_task.values() if h.feature_coverage is not None]
    targets = {tid: ("목표 없음" if h.has_target is False else "있음") for tid, h in per_task.items()
               if h.has_target is not None}
    missing: dict[str, float] = {}
    for h in per_task.values():
        missing.update(h.missing_rates or {})
    return {"status": "연결", "rows": first.rows, "ts_from": _iso(first.ts_from), "ts_to": _iso(first.ts_to),
            "coverage": min(covers) if covers else None, "missing_rates": missing,
            "target": "목표 없음" if "목표 없음" in targets.values() else ("있음" if targets else None),
            "targets": targets, "message": first.message}


def _source_tables(cfg: dict) -> list[str]:
    """소스가 읽는 원천 테이블 · 뷰 이름(등록부 `tables` · `table` · `view`). 비어 있으면 미확인."""
    out = list(cfg.get("tables") or [])
    for key in ("table", "view"):
        if cfg.get(key):
            out.append(cfg[key])
    return list(dict.fromkeys(str(t) for t in out))


def _static_live(merged: tenants.Merged, role: str, cfg: dict) -> dict:
    """원천을 부르지 않고 등록부만으로 **소스별로** 센다(DEF-QA1-005 · D-122).

    - 대응률 = 이 소스의 테이블(`tables` · `table` · `view`)에 속한 `feature_map` 열이 채우는 변수 / 켜진 과제 변수.
    - 목표 = 이 소스의 테이블에 속한 `target_map` 열이 과제 목표를 채우는가.
    - 소스 테이블이 등록부에 없으면(뷰 이름 미확인 등) 대응률 null · 목표 null(과제별 `미확인`) — 지어내지 않는다.
      단 `target_map` 어디에도 목표가 없으면 어느 소스든 `목표 없음` 이다.
    """
    tcfg = merged.tenant.config
    feats = _features(merged)
    tables = _source_tables(cfg)
    known = bool(tables)

    def of_source(cmap: dict) -> set[str]:
        return {v for k, v in (cmap or {}).items() if str(k).split(".", 1)[0] in tables}

    fmap_all = set((tcfg.get("feature_map") or {}).values())
    tmap_all = set((tcfg.get("target_map") or {}).values())
    mapped = of_source(tcfg.get("feature_map")) if known else set()
    tmap = of_source(tcfg.get("target_map")) if known else set()
    targets = {}
    for t in _learned(merged):
        name = (t.raw.get("target") or {}).get("name")
        if not name:
            continue
        if name not in tmap_all:
            targets[t.id] = "목표 없음"
        elif not known:
            targets[t.id] = "미확인"
        else:
            targets[t.id] = "있음" if name in tmap else "목표 없음"
    vals = set(targets.values())
    target = "목표 없음" if "목표 없음" in vals else ("있음" if vals == {"있음"} else None)
    unmapped = [f for f in feats if f not in (mapped if known else fmap_all)]
    msg = "fixture 모드 — 실연결은 doctor-live 에서 사람이 확인 (D-13)"
    if not known:
        msg += " · 소스 테이블 · 뷰 미확인 — 대응률 · 목표를 셀 수 없다"
    return {"status": "미연결", "rows": None, "ts_from": None, "ts_to": None,
            "coverage": (len([f for f in feats if f in mapped]) / len(feats) if feats else None) if known else None,
            "missing_rates": {}, "target": target, "targets": targets, "unmapped": unmapped, "tables": tables,
            "message": msg}


def doctor(tenant_id: str, *, merged: tenants.Merged | None = None, live: bool = False) -> dict:
    """→ {tenant, mode, sources: [{role, kind, status, rows, ts_from, ts_to, coverage, missing_rates, target, message, …}]}."""
    if live:
        raise PermissionError("doctor-live 는 루프에서 돌리지 않는다 — BLOCKED (D-13)")
    merged = merged or tenants.load_and_merge(tenant_id)
    out = []
    for role, cfg in (merged.tenant.config.get("sources") or {}).items():
        cfg = cfg or {}
        kind = cfg.get("kind")
        if kind in FIXTURE_KINDS:
            info = _probe_fixture(merged, role, cfg)
        elif kind in LIVE_KINDS:
            info = _static_live(merged, role, cfg)
        else:
            info = {"status": "미연결", "message": f"알 수 없는 소스 종류 {kind!r}"}
        base = {"role": role, "kind": kind, "status": "미연결", "rows": None, "ts_from": None, "ts_to": None,
                "coverage": None, "missing_rates": {}, "target": None, "message": ""}
        out.append({**base, **info})
    return {"tenant": merged.tenant.code, "mode": merged.tenant.config.get("mode"), "sources": out,
            "warnings": list(merged.warnings), "disabled": dict(merged.disabled)}


def render(rep: dict) -> str:
    lines = [f"doctor {rep['tenant']} (mode {rep['mode']}, fixture 모드)"]
    for s in rep["sources"]:
        cov = "-" if s["coverage"] is None else f"{s['coverage'] * 100:.1f}%"
        miss = max(s["missing_rates"].values()) if s["missing_rates"] else None
        lines.append(f"  {s['role']:<8} {s['kind'] or '-':<12} {s['status']:<4} rows={s['rows'] if s['rows'] is not None else '-'}"
                     f" 기간={s['ts_from'] or '-'}~{s['ts_to'] or '-'} 대응률={cov}"
                     f" 최대결측률={'-' if miss is None else f'{miss * 100:.1f}%'} 목표={s['target'] or '-'} · {s['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="회사 소스 점검 (fixture 모드)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = doctor(a.tenant)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
