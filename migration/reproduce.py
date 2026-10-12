"""이관 대조 재현 (M5 · G-M12) — 표준 플랫폼 학습기로 과제 8 을 합성 시드 그대로 다시 잰다. 개발3.

    OMP_NUM_THREADS=1 uv run python migration/reproduce.py            # 표 출력
    OMP_NUM_THREADS=1 uv run python migration/reproduce.py --json out.json

- 학습 과제 6: 회사 `demo`(synthetic, 시드 42) → 표준 프레임 → 스냅숏(임시 폴더) → `StandardTrainer`(개발1) 시험 1회 지표.
  보고 수치는 **시험 구간만**(표본 내 · 학습 구간 지표는 쓰지 않는다).
- optimize 2: 원천 시험과 같은 요청(기본 입력 · 기본 제약)으로 표준 규칙의 격자를 이 도구가 직접 센다 —
  조절 변수 = `min + k·step` 중 [학습 p1, p99] ∩ [min, max](의존 모델 lock 의 교집합), 결정 변수 = [min, params 상한].
  의존 과제 모델은 위에서 학습한 산출물(model.joblib · features.lock.json). 운영 경로(`tasks/optimize.py`, 개발2)와
  같은 규칙이지만 등록부 · 승인을 거치지 않는 재현 계산이다.
원천 저장소는 읽기만 했고 실행하지 않는다. 원천 보고값은 migration/source_inventory.md §1.4 · §1.5 · §2.4 · §2.5.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.registry import tenants  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig  # noqa: E402

LEARNED = {"ks": ["remaining_hours", "failure_24h", "sensor_ood"], "sw": ["delta_e", "defect_risk", "print_ood"]}
# 원천 시험이 쓴 요청 (KwangSung · SongWol tests/test_api.py — source_inventory §1.5 · §2.5)
OPT_REQUEST = {
    "ks": {"task": "maintenance_timing", "categories": {"machine_code": 0, "product_type": 0},
           "params": {"reserve_hours": 12, "max_delay_hours": 48, "max_cost_index": 140}},
    "sw": {"task": "print_setpoint", "fixed_cat": {"print_type": "나염", "color_tone": "진한 색상"},
           "params": {"max_delta_e": 2.5, "max_risk": 0.2, "min_line_speed": 12}},
}
OPT_INFEASIBLE = {"ks": {"reserve_hours": 150, "max_delay_hours": 48, "max_cost_index": 1},
                  "sw": {"max_delta_e": 0.5, "max_risk": 0.01, "min_line_speed": 24}}


def _artifact(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def train_all(work: Path) -> dict:
    out = {}
    for code, names in LEARNED.items():
        for name in names:
            tid = f"{code}.{name}"
            m, t, frame, ref, syn = jobs.read_frame(code, tid, source_role="demo")
            s = snapshot.freeze(frame, tenant_id=code, task=t, source_ref=ref, synthetic=syn, base_dir=work / "snap")
            cfg = TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta)
            r = StandardTrainer(artifact_root=work / "art", snapshot_dir=work / "snap").train(cfg)
            out[tid] = {"type": t.type, "status": r.status, "champion": r.champion, "beats_baseline": r.beats_baseline,
                        "rows": len(frame), "split": (r.report.get("split") or {}).get("boundaries", {}).get("sizes"),
                        "test": {k: {"value": v.value, "baseline": v.baseline, "delta": v.delta_vs_baseline}
                                 for k, v in r.test_metrics.items()},
                        "valid": (r.valid_metrics or {}).get(r.champion or "", {}),
                        "artifact_dir": str(_artifact(r.artifact_dir)) if r.artifact_dir else None,
                        "snapshot_sha256": s.sha256}
    return out


def _load(art: str):
    import joblib

    d = Path(art)
    return joblib.load(d / "model.joblib"), json.loads((d / "features.lock.json").read_text(encoding="utf-8"))


def _lattice(lo, hi, base, step):
    k0 = math.ceil((lo - base) / step - 1e-9)
    k1 = math.floor((hi - base) / step + 1e-9)
    return [round(base + k * step, 10) for k in range(k0, k1 + 1)]


def _formula(pack_dir: Path, module: str):
    spec = importlib.util.spec_from_file_location(f"repro_{module}", pack_dir / "formulas" / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cost


def _score(model, lock, frame: pd.DataFrame, ttype: str) -> np.ndarray:
    x = frame[lock["order"]]
    if ttype == "risk":
        return model.predict_proba(x)[:, 1]
    y = model.predict(x)
    clip = (lock.get("clip") or {}).get("min")
    return np.maximum(clip, y) if clip is not None else y


def optimize(code: str, trained: dict, params: dict | None = None) -> dict:
    m = tenants.load_and_merge(code, tenants_base=tenants.TENANTS_DIR)
    req = OPT_REQUEST[code]
    task = m.tasks[f"{code}.{req['task']}"].raw
    feats = m.pack.features
    cats = m.tenant.config.get("categories") or {}
    params = {**{k: v["default"] for k, v in (task.get("params") or {}).items()}, **(params or req["params"])}
    uses = []
    for u in task["uses"]:
        short = u.split(".", 1)[1]
        tid = f"{code}.{short}"
        model, lock = _load(trained[tid]["artifact_dir"])
        uses.append((short, trained[tid]["type"], model, lock))
    # 고정 입력 = 원천 시험 record (기본값 · 범주 첫 값/지정 값)
    base_row = {}
    for f in task.get("fixed") or []:
        d = feats[f]
        if d.get("dtype") == "category":
            base_row[f] = (req.get("fixed_cat") or {}).get(f) or (cats.get(f) or d.get("values"))[0]
        else:
            base_row[f] = d["default"]
    axes = {}
    for c in task.get("controls") or []:
        d = feats[c]
        lo, hi = d["min"], d["max"]
        for _, _, _, lock in uses:
            it = lock["features"].get(c) or {}
            if it.get("p1") is not None:
                lo, hi = max(lo, it["p1"]), min(hi, it["p99"])
        axes[c] = _lattice(lo, hi, d["min"], d["step"])
    for name, d in (task.get("decision_vars") or {}).items():
        hi = params[d["max_param"]] if d.get("max_param") else d["max"]
        axes[name] = _lattice(float(d["min"]), float(hi), float(d["min"]), float(d["step"]))
    names = list(axes)
    pts = pd.DataFrame(list(itertools.product(*[axes[n] for n in names])), columns=names) if names else pd.DataFrame()
    frame = pts.copy()
    for k, v in base_row.items():
        if k not in frame.columns:
            frame[k] = v
    for c in task.get("controls") or []:
        base_row.setdefault(c, feats[c]["default"])
    env = {n: frame[n].to_numpy(dtype=float) for n in names}
    for short, ttype, model, lock in uses:
        env[short] = _score(model, lock, frame, ttype)
    for fname, module in (task.get("formulas") or {}).items():
        cost = _formula(m.pack.path, module)
        rows = frame.assign(**{k: v for k, v in env.items() if k not in frame.columns}).to_dict("records")
        env[fname] = np.array([cost(r, params) for r in rows])
    env.update({k: float(v) for k, v in params.items()})
    viol = np.zeros(len(frame))
    for c in task["constraints"]:
        lhs, op, rhs = _split(c["expr"])
        a, b = _ev(lhs, env, len(frame)), _ev(rhs, env, len(frame))
        over = np.maximum(0, a - b) if op in ("<=", "<") else np.maximum(0, b - a)
        viol = viol + over / np.maximum(np.abs(b), 1e-9)
    feasible = viol <= 1e-10
    obj = task["objective"]
    key = obj.get("minimize") or obj.get("maximize")
    best = None
    if feasible.any():
        order = np.lexsort(tuple(reversed([_sortkey(o, env) for o in [obj] + list(obj.get("tiebreak") or [])])))
        idx = [i for i in order if feasible[i]][0]
        best = {n: float(frame[n].iloc[idx]) for n in names} | {key: float(env[key][idx])}
    return {"task": f"{code}.{req['task']}", "candidate_count": int(len(frame)), "feasible_count": int(feasible.sum()),
            "axes": {n: len(v) for n, v in axes.items()}, "best": best, "params": params}


def _split(expr: str):
    for op in ("<=", ">=", "<", ">"):
        if op in expr:
            lhs, rhs = expr.split(op, 1)
            return lhs.strip(), op, rhs.strip()
    raise ValueError(expr)


def _ev(side: str, env: dict, n: int):
    val = eval(compile(side, "<expr>", "eval"), {"__builtins__": {}}, env)   # noqa: S307 — 과제 YAML 식(이름 · + - *)
    return np.broadcast_to(np.asarray(val, dtype=float), (n,))


def _sortkey(o: dict, env: dict):
    if "minimize" in o:
        return env[o["minimize"]]
    return -env[o["maximize"]]


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="mlp-repro-") as d:
        work = Path(d)
        trained = train_all(work)
        opt = {code: {"default": optimize(code, trained), "infeasible": optimize(code, trained, OPT_INFEASIBLE[code])}
               for code in ("ks", "sw")}
        for t in trained.values():
            t["artifact_dir"] = None
        return {"learned": trained, "optimize": opt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    res = run()
    text = json.dumps(res, ensure_ascii=False, indent=1, default=float)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
