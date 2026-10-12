"""QA2-1 — 고려솔더 IQR 범위 · 조성 합 input_rules · derived · 수락 표집 (krs · pc).

1. IQR: 표준 학습 보고서의 제거 수(폴드 · 재적합)를 이 스크립트가 split.plan 으로 다시 만든 구간에서 독립 계산
   (학습 구간만 / 학습+검증만)과 견주고, '분할 전 전체'(원천) · '검증 포함' · '시험 포함' 이었다면 몇이었을지도 센다.
2. input_rules: 원천 규칙(krs `abs(합-100) > .1` 거부 · pc `98 <= 합 <= 102`)과 표준 `check_rules` 를 경계 근처 무작위
   20만 조합 + 경계 정확값에서 견준다(불일치 0 기대).
3. 수락 표집: Optimizer.space(코어) 점 전부가 derived 식 = 100 − 합 · [min, max] ∩ 학습 범위(p1~p99) 안 · 점 수 = max_points ·
   뽑은 수 ≥ 점 수 · 시드 고정 재현.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import joblib  # noqa: F401
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot  # noqa: E402
from mlcore.data.features import feature_defs  # noqa: E402
from mlcore.serve import validate  # noqa: E402
from mlcore.serve.errors import ServeError  # noqa: E402
from mlcore.tasks.optimize import Optimizer  # noqa: E402
from mlcore.train import split  # noqa: E402
from mlcore.train.trainer import StandardTrainer, TrainConfig, iqr_filter, resolve_features  # noqa: E402


def iqr_count(frame, idx, cols, k=1.5):
    sub = frame.iloc[list(idx)]
    mask = np.zeros(len(sub), bool)
    for c in cols:
        v = pd.to_numeric(sub[c], errors="coerce").to_numpy(float)
        ok = ~np.isnan(v)
        q1, q3 = np.percentile(v[ok], [25, 75])
        mask |= ok & ((v < q1 - k * (q3 - q1)) | (v > q3 + k * (q3 - q1)))
    return int(mask.sum())


def rules_probe():
    rng = np.random.default_rng(1)
    out = {}
    krs_rule = [{"name": "composition_sum", "expr": "sn_pct + ag_pct + cu_pct + sb_pct + flux_pct", "between": [99.9, 100.1]}]
    pc_rule = [{"name": "recipe_sum", "expr": "cabbage_pct + radish_pct + seasoning_pct + salt_pct", "between": [98, 102]}]
    for name, rule, keys, src_ok, center, width in (
            ("krs", krs_rule, ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct"], lambda t: not abs(t - 100) > .1, 100.0, 0.1),
            ("pc", pc_rule, ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"], lambda t: 98 <= t <= 102, 100.0, 2.0)):
        mism, n = [], 0
        for _ in range(200000):
            parts = rng.uniform(0.1, 5, len(keys) - 1)
            target = center + rng.choice([-1, 1]) * width + rng.normal(0, 1e-13 if rng.random() < .5 else 1e-3)
            vals = [target - parts.sum(), *parts]
            inp = dict(zip(keys, vals))
            tot = 0.0
            for k in keys:
                tot += inp[k]
            s_ok = src_ok(tot)
            try:
                validate.check_rules(inp, rule); t_ok = True
            except ServeError:
                t_ok = False
            n += 1
            if s_ok != t_ok and len(mism) < 5:
                mism.append({"inputs": inp, "sum": tot, "source": s_ok, "std": t_ok})
        out[name] = {"n": n, "mismatch": len(mism), "examples": mism}
    return out


def main():
    work = Path(tempfile.mkdtemp(prefix="qa21-sk-"))
    out = {"rules": rules_probe()}
    # 1. IQR (krs)
    m, t, frame, ref, syn = jobs.read_frame("krs", "krs.joint_strength", source_role="demo")
    frame = snapshot.canonical(frame)
    feats = resolve_features(t, merged=m)
    s = snapshot.freeze(frame, tenant_id="krs", task=t, source_ref=ref, synthetic=syn, base_dir=work / "s")
    r = StandardTrainer(features=feats, frame=frame, artifact_root=work / "a").train(TrainConfig.from_task(t, s.snapshot_id, pack_meta=m.pack.meta))
    cols = t.raw["outlier"]["columns"]
    sp, _ = split.plan(frame, t, seed=t.raw["seed"])
    n = len(frame)
    te = sorted(set(range(n)) - set(sp.fit_idx))
    out["iqr"] = {"report": {"folds": r.report["outliers"]["folds"], "refit": r.report["outliers"]["refit"], "columns": r.report["outliers"]["columns"]},
                  "independent_train_only": iqr_count(frame, sp.train_idx, cols),
                  "independent_train_valid": iqr_count(frame, sp.fit_idx, cols),
                  "if_whole_720(source K6)": iqr_count(frame, range(n), cols),
                  "if_train_plus_test": iqr_count(frame, sorted(set(sp.train_idx) | set(te)), cols),
                  "core_iqr_filter_train": iqr_filter(frame, sp.train_idx, cols, 1.5)[1],
                  "valid_rows_kept_for_selection": len(sp.valid_idx), "test_rows_kept": len(te)}
    # 3. 수락 표집
    for code, opt_task, derived_name in (("krs", "krs.recipe_optimize", "sn_pct"), ("pc", "pc.recipe_optimize", "seasoning_pct")):
        mm = jobs.load_merged(code)
        task = mm.tasks[opt_task]
        uses = f"{code}.{task.raw['uses'][0].split('.', 1)[1]}"
        m2, t2, fr2, ref2, syn2 = jobs.read_frame(code, uses, source_role="demo")
        s2 = snapshot.freeze(fr2, tenant_id=code, task=t2, source_ref=ref2, synthetic=syn2, base_dir=work / f"s{code}")
        r2 = StandardTrainer(features=resolve_features(t2, merged=m2), artifact_root=work / f"a{code}", snapshot_dir=work / f"s{code}").train(
            TrainConfig.from_task(t2, s2.snapshot_id, pack_meta=m2.pack.meta))
        art = Path(r2.artifact_dir); art = art if art.is_absolute() else ROOT / art
        lock = json.loads((art / "features.lock.json").read_text(encoding="utf-8"))
        raw = task.raw
        names = list(dict.fromkeys(list(raw.get("controls") or []) + list(raw.get("fixed") or []) + list(raw.get("derived") or {})))
        defs = {f.name: f for f in feature_defs(mm.pack.features, names, mm.tenant.config.get("categories") or {}, mm.pack.std_name)}
        prm = {k: v.get("default") for k, v in (raw.get("params") or {}).items() if v.get("default") is not None}
        cats = mm.tenant.config.get("categories") or {}
        fixed = {k: (cats.get(k) or [None])[0] for k in raw.get("fixed") or []}
        sp1 = Optimizer(None).space(task, [lock], prm, defs, fixed=fixed)
        sp2 = Optimizer(None).space(task, [lock], prm, defs, fixed=fixed)
        pts = sp1.points
        import re as _re
        comp = [c for c in (raw.get("controls") or []) if c in _re.findall(r"[a-z_]+", raw["derived"][derived_name])]
        dv = pts[derived_name].to_numpy(float)
        recomputed = 100 - pts[comp].to_numpy(float).sum(axis=1)
        f = defs[derived_name]
        lk = lock["features"][derived_name]
        lo, hi = max(float(f.min), lk["p1"]), min(float(f.max), lk["p99"])
        ctrl_ok = {}
        for c in raw.get("controls") or []:
            lc = lock["features"].get(c) or {}
            v = pts[c].to_numpy(float)
            ctrl_ok[c] = bool(((v >= max(float(defs[c].min), lc.get("p1", -np.inf)) - 1e-9) &
                               (v <= min(float(defs[c].max), lc.get("p99", np.inf)) + 1e-9)).all())
        out[f"accept_{code}"] = {"strategy": sp1.strategy, "points": len(pts), "max_points": raw["search"]["max_points"],
                                 "drawn": sp1.n_drawn, "capped": sp1.capped,
                                 "derived_eq_100_minus_sum_maxerr": float(np.abs(dv - recomputed).max()),
                                 "derived_in_range": bool(((dv >= lo - 1e-9) & (dv <= hi + 1e-9)).all()), "range": [lo, hi],
                                 "controls_in_train_range": ctrl_ok,
                                 "seed_reproducible": bool(sp1.points.equals(sp2.points)),
                                 "rule_sum_ok_all": bool(np.allclose(pts[comp + [derived_name]].to_numpy(float).sum(axis=1), 100, atol=1e-8))}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
