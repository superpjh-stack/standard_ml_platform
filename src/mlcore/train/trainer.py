"""표준 학습기 (contracts/interfaces.md §4 · spec §5).

절차 고정 — 바꿀 수 있는 설정이 없다:
  1) 분할(split.plan) — 시험 구간 인덱스는 GuardedTest 만 가진다.
  2) 학습 구간으로 후보 학습 → 검증 구간으로 선정 · 예측 구간(split conformal) · 임계값.
  3) 학습+검증으로 재적합 → evaluate.final_evaluation 으로 시험 구간 1회 평가(기준선 함께).
  4) report.test_report(시험 구간 `report` 목적) → 산출물 4종 + SHA-256.
기준선: regression = 재적합 구간 목표 평균, risk = 재적합 구간 양성률 상수, anomaly = 기대 오염률 (std/metrics.yaml).
과제 · 변수 · 목표 이름은 전부 TaskDef · FeatureDef 에서 온다(코어는 업종을 모른다).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from ..data import snapshot as snapshots
from ..data.features import FeatureDef, feature_defs
from ..data.jobs import config_hash as _config_hash
from ..data.jobs import default_seed, run_id_for, submit, task_candidates  # noqa: F401  submit 은 interfaces §4 이름
from ..settings import ROOT, get_settings
from . import artifacts, metrics, split
from .candidates import CandidateUnavailable, build
from .evaluate import final_evaluation
from .guard import AccessLedger, InSampleEvaluation, TestLeak
from .report import test_report

calls = 0                      # 학습 호출 계측 (G-M06: API 기동 후 0)
TRAINABLE = ("regression", "risk", "anomaly")


class NotTrainable(Exception):
    """합성 과제(optimize 등)는 학습하지 않는다 — uses 과제의 production 모델을 쓴다."""


@dataclass(frozen=True)
class TrainConfig:
    task: object
    snapshot_id: str
    seed: int
    code_version: str
    candidates: tuple[str, ...]
    candidate_params: dict[str, dict]

    def config_hash(self) -> str:
        return _config_hash(self.task.def_hash, self.seed, self.code_version, self.candidates, self.candidate_params)

    @classmethod
    def from_task(cls, task, snapshot_id: str, *, seed: int | None = None, code_version: str | None = None,
                  pack_meta: dict | None = None) -> "TrainConfig":
        cands, params = task_candidates(task)
        s = default_seed(task, pack_meta or {}) if seed is None else int(seed)
        return cls(task, snapshot_id, s, code_version or get_settings().code_version, cands, params)


@dataclass(frozen=True)
class MetricValue:
    value: float
    baseline: float | None
    delta_vs_baseline: float | None


@dataclass(frozen=True)
class TrainResult:
    run_id: str
    status: Literal["succeeded", "failed"]
    champion: str | None
    valid_metrics: dict[str, dict[str, float]]
    selection_reason: str
    test_metrics: dict[str, MetricValue]
    beats_baseline: bool
    artifact_dir: str | None
    report: dict
    warnings: list[dict]
    ledger: list[dict]
    artifact_sha256: str | None = None
    synthetic: bool = False
    test_predictions: tuple[float, ...] = field(default=(), repr=False)


def tenant_of(task) -> str:
    return task.id.split(".", 1)[0]


def resolve_features(task) -> list[FeatureDef]:
    from ..registry.tenants import load_and_merge

    m = load_and_merge(tenant_of(task))
    return feature_defs(m.pack.features, task.raw.get("features") or [], m.tenant.config.get("categories") or {},
                        m.pack.std_name)


def _w(code: str, message: str, **detail) -> dict:
    return {"code": code, "message": message, "detail": detail}


def _conformal_q(abs_resid: np.ndarray, alpha: float) -> float:
    r = np.sort(np.asarray(abs_resid, float))
    n = len(r)
    if n == 0:
        return float("nan")
    k = math.ceil((n + 1) * (1 - alpha))
    return float(r[min(k, n) - 1])


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


class StandardTrainer:
    def __init__(self, *, features: Sequence[FeatureDef] | None = None, artifact_root: Path | None = None,
                 frame: pd.DataFrame | None = None, snapshot_dir: Path | None = None, synthetic: bool | None = None):
        self.features = list(features) if features is not None else None
        self.artifact_root = Path(artifact_root) if artifact_root is not None else get_settings().artifact_dir
        self.frame = frame
        self.snapshot_dir = snapshot_dir
        self.synthetic = synthetic

    # ── 입력 ─────────────────────────────────────────────
    def _load(self, cfg: TrainConfig) -> tuple[pd.DataFrame, dict]:
        if self.frame is not None:
            frame = snapshots.canonical(self.frame)
            sha = snapshots.content_sha256(frame)
            if cfg.snapshot_id != "snp_" + sha[:16]:
                raise snapshots.SnapshotCorrupt(f"{cfg.snapshot_id}: 주어진 프레임의 해시와 다르다")
            synth = self.synthetic if self.synthetic is not None else bool((frame.get("_source") == "synthetic").all())
            return frame, {"sha256": sha, "synthetic": synth, "source_ref": {}}
        frame = snapshots.load(cfg.snapshot_id, base_dir=self.snapshot_dir)
        info = snapshots.load_info(cfg.snapshot_id, base_dir=self.snapshot_dir)
        return frame, info

    def train(self, cfg: TrainConfig) -> TrainResult:
        global calls
        calls += 1
        task = cfg.task
        if task.type not in TRAINABLE:
            raise NotTrainable(f"{task.id}: {task.type} 는 학습 과제가 아니다")
        tenant = tenant_of(task)
        run_id = run_id_for(tenant, task.id, cfg.snapshot_id, cfg.config_hash())
        frame, info = self._load(cfg)
        feats = self.features if self.features is not None else resolve_features(task)
        ledger = AccessLedger()
        try:
            return self._train(cfg, run_id, tenant, frame, info, feats, ledger)
        except (TestLeak, InSampleEvaluation):
            raise                                   # 누수는 치명 결함 — 실패 결과로 덮지 않는다
        except Exception as e:  # 그 밖의 실패는 failed 로 보인다(숨기지 않는다)
            return TrainResult(run_id, "failed", None, {}, f"학습 실패: {type(e).__name__}: {e}", {}, False, None,
                               {"run_id": run_id, "error": {"type": type(e).__name__, "message": str(e)}},
                               [_w("train_failed", f"{type(e).__name__}: {e}")], ledger.events(),
                               synthetic=bool(info.get("synthetic")))

    # ── 본 절차 ──────────────────────────────────────────
    def _train(self, cfg, run_id, tenant, frame, info, feats, ledger) -> TrainResult:
        task, raw, ttype, seed = cfg.task, cfg.task.raw, cfg.task.type, cfg.seed
        names = [f.name for f in feats]
        missing_cols = [n for n in names if n not in frame.columns]
        if missing_cols:
            raise KeyError(f"스냅숏에 변수 열이 없다: {missing_cols}")
        warnings: list[dict] = []
        supervised = ttype in ("regression", "risk")
        if supervised:
            if "target" not in frame.columns or not frame["target"].notna().any():
                raise ValueError("목표 없음")
            n_missing = int(frame["target"].isna().sum())
            if n_missing:
                warnings.append(_w("target_missing_rows", "목표 결측 행을 학습에서 뺐다", rows=n_missing))
                frame = frame[frame["target"].notna()].reset_index(drop=True)
        n = len(frame)
        if n < 200:
            warnings.append(_w("few_rows", "행 < 200", rows=n))
        for nm in names:
            r = float(frame[nm].isna().mean()) if n else 0.0
            if r > 0.30:
                warnings.append(_w("high_missing", "결측률 > 30% 변수", feature=nm, rate=r))

        positive = (raw.get("target") or {}).get("positive", 1)

        def y_of(df: pd.DataFrame) -> np.ndarray:
            if ttype == "risk":
                return (df["target"].to_numpy(dtype=float) == float(positive)).astype(int)
            return df["target"].to_numpy(dtype=float)

        sp, test = split.plan(frame, task, seed, ledger=ledger)
        if not sp.train_idx or not sp.valid_idx or len(test) == 0:
            raise ValueError(f"분할 구간이 비었다: {sp.boundaries.get('sizes')}")
        if sp.boundaries.get("regrouped"):
            warnings.append(_w("group_regrouped", "group_key 가 시간상 섞여 그룹 블록 순서로 잘랐다"))
        folds = sp.folds or ((sp.train_idx, sp.valid_idx),)
        X_all = frame[names]
        y_all = y_of(frame) if supervised else None
        clip = raw.get("clip") or {}

        def clipped(p: np.ndarray) -> np.ndarray:
            if ttype != "regression":
                return p
            lo = clip.get("min")
            hi = clip.get("max")
            return np.clip(p, -np.inf if lo is None else lo, np.inf if hi is None else hi)

        def predict(model, X) -> np.ndarray:
            if ttype == "regression":
                return clipped(np.asarray(model.predict(X), float))
            if ttype == "risk":
                cls = list(model.classes_)
                return np.asarray(model.predict_proba(X), float)[:, cls.index(1)]
            return -np.asarray(model.score_samples(X), float)          # anomaly: 클수록 이상

        # ── 2) 후보 학습 · 검증 ──────────────────────────
        threshold = (raw.get("thresholds") or {}).get("review_prob", 0.5) if ttype == "risk" else None
        contamination = float(raw.get("contamination", 0.0)) if ttype == "anomaly" else None
        sel = metrics.selection_metric(ttype)
        valid_metrics: dict[str, dict] = {}
        oof: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name in cfg.candidates:
            try:
                preds, ys = [], []
                for tr, va in folds:
                    tr, va = list(tr), list(va)
                    m = build(name, ttype, feats, cfg.candidate_params.get(name), seed)
                    if supervised:
                        m.fit(X_all.iloc[tr], y_all[tr])
                        preds.append(predict(m, X_all.iloc[va]))
                        ys.append(y_all[va])
                    else:
                        m.fit(X_all.iloc[tr])
                        thr = float(np.quantile(predict(m, X_all.iloc[tr]), 1 - contamination))
                        preds.append((predict(m, X_all.iloc[va]) >= thr).astype(float))
                p, yv = np.concatenate(preds), (np.concatenate(ys) if ys else None)
            except CandidateUnavailable as e:
                warnings.append(_w("candidate_unavailable", str(e), candidate=name))
                continue
            oof[name] = (p, yv)
            if ttype == "regression":
                valid_metrics[name] = metrics.regression(yv, p)
            elif ttype == "risk":
                valid_metrics[name] = metrics.risk(yv, p, threshold)
            else:
                valid_metrics[name] = metrics.anomaly(p)
        if not valid_metrics:
            raise ValueError("학습 가능한 후보가 없다")

        # 검증 구간 기준선 (학습 구간 평균 · 양성률 — 검증 · 시험 값을 보지 않는다)
        base_parts, base_y = [], []
        if supervised:
            for tr, va in folds:
                const = float(np.mean(y_all[list(tr)]))
                base_parts.append(np.full(len(va), const))
                base_y.append(y_all[list(va)])
            bp, by = np.concatenate(base_parts), np.concatenate(base_y)
            base_valid = metrics.regression(by, bp) if ttype == "regression" else metrics.risk(by, bp, threshold)
        else:
            base_valid = {"flag_rate": contamination}

        # 선정 — 검증 구간만
        if sel is not None:
            champion = None
            for name in valid_metrics:                       # 동률이면 과제 YAML 의 앞 후보
                v = valid_metrics[name][sel]
                if champion is None or metrics.better(sel, v, valid_metrics[champion][sel]):
                    champion = name
            reason = (f"검증 구간 {sel} {'최소' if metrics.direction(sel) == 'lower' else '최대'}: {champion} "
                      f"{valid_metrics[champion][sel]:.6g} (검증 기준선 {base_valid[sel]:.6g}) — 후보 {len(valid_metrics)}개, "
                      f"분할 {sp.policy}")
        else:
            champion = next(iter(valid_metrics))
            reason = f"비지도 — 후보 {champion} 하나, 임계값은 학습+검증 점수 {1 - contamination:.3f} 분위"

        # 예측 구간 · 임계값 — 검증 구간(또는 재적합 구간) 잔차 · 점수로만
        interval = None
        if ttype == "regression":
            icfg = raw.get("interval") or {}
            alpha = float(icfg.get("alpha", 0.1))
            p, yv = oof[champion]
            q = _conformal_q(np.abs(yv - p), alpha)
            bq = _conformal_q(np.abs(by - bp), alpha)
            interval = {"method": icfg.get("method", "split_conformal"), "alpha": alpha, "q": q, "baseline_q": bq,
                        "fit_on": "valid", "n": int(len(yv))}
        cal = (raw.get("calibration") or {}).get("method", "none")
        if ttype == "risk" and cal not in (None, "none"):
            warnings.append(_w("calibration_not_applied", f"보정 {cal} 은 아직 구현하지 않았다(A0) — 보정 없이 학습", method=cal))

        # ── 3) 학습+검증 재적합 → 시험 1회 ───────────────
        fit_idx = list(sp.fit_idx)
        model = build(champion, ttype, feats, cfg.candidate_params.get(champion), seed)
        if supervised:
            model.fit(X_all.iloc[fit_idx], y_all[fit_idx])
            base_const = float(np.mean(y_all[fit_idx]))
        else:
            model.fit(X_all.iloc[fit_idx])
            base_const = contamination
        anomaly_thr = float(np.quantile(predict(model, X_all.iloc[fit_idx]), 1 - contamination)) if ttype == "anomaly" else None
        if ttype == "risk":
            rate = base_const
            if rate < 0.05 or rate > 0.95:
                warnings.append(_w("target_imbalance", "목표 불균형(양성률 < 5% 또는 > 95%)", positive_rate=rate))

        def score(df: pd.DataFrame):
            X = df[names]
            p = predict(model, X)
            if ttype == "regression":
                y = y_of(df)
                lo, hi = clipped(p - interval["q"]), clipped(p + interval["q"])
                b = np.full(len(df), base_const)
                bm = metrics.regression(y, b, clipped(b - interval["baseline_q"]), clipped(b + interval["baseline_q"]))
                return metrics.regression(y, p, lo, hi), bm, p
            if ttype == "risk":
                y = y_of(df)
                return metrics.risk(y, p, threshold), metrics.risk(y, np.full(len(df), base_const), threshold), p
            flags = (p >= anomaly_thr).astype(float)
            return metrics.anomaly(flags), {"flag_rate": contamination}, p

        tm, bm, test_pred = final_evaluation(frame, test, fit_idx, score)
        test_metrics = {k: MetricValue(**v) for k, v in metrics.with_baseline(tm, bm).items()}
        if sel is not None:
            beats = sel in test_metrics and test_metrics[sel].baseline is not None and \
                metrics.better(sel, test_metrics[sel].value, test_metrics[sel].baseline)
            rule = f"시험 {sel} 이 기준선보다 {'낮다' if metrics.direction(sel) == 'lower' else '높다'}"
        else:
            fr = test_metrics["flag_rate"].value
            beats = 0.5 * contamination <= fr <= 2.0 * contamination
            rule = "시험 flag_rate 가 기대 오염률의 0.5~2배 안 (D-50 가설 — 라벨 없는 비지도라 우열 비교가 없다)"
        if not beats:
            warnings.append(_w("below_baseline", "기준선 미달 — candidate 까지만", metric=sel or "flag_rate"))

        # ── 4) 보고 · 산출물 ────────────────────────────
        rep_test = test_report(frame, test, model=model, task_type=ttype, features=feats,
                               y_of=y_of, predict=lambda X: predict(model, X), seed=seed)
        fit = frame.iloc[fit_idx]
        lock_ranges, fills = {}, {}
        for f in feats:
            s = fit[f.name]
            if f.numeric:
                v = s.dropna().to_numpy(dtype=float)
                lock_ranges[f.name] = {"p1": float(np.percentile(v, 1)) if len(v) else None,
                                       "p99": float(np.percentile(v, 99)) if len(v) else None}
                fills[f.name] = float(np.median(v)) if len(v) else None
            else:
                lock_ranges[f.name] = {"values": sorted({str(x) for x in s.dropna().tolist()})}
                fills[f.name] = s.dropna().astype(str).value_counts().sort_index().idxmax() if s.notna().any() else None
        features_lock = artifacts.lock(
            names, feats, ranges=lock_ranges, fills=fills, baseline=base_const,
            interval={k: interval[k] for k in ("method", "alpha", "q")} if interval else None,
            extra={"task_id": task.id, "pack_task_id": task.pack_id, "task_type": ttype, "def_hash": task.def_hash,
                   "snapshot_id": cfg.snapshot_id, "target": raw.get("target"),
                   "positive": positive if ttype == "risk" else None, "clip": clip or None,
                   "threshold": threshold if ttype == "risk" else anomaly_thr, "contamination": contamination,
                   "score": {"regression": "predict", "risk": "predict_proba[:,1]", "anomaly": "-score_samples"}[ttype],
                   "range_from": "train+valid p1/p99 (test excluded)", "rows_fit": len(fit_idx),
                   "max_imputed": raw.get("max_imputed", 3),
                   "defined_values": {f.name: list(f.values) for f in feats if f.values}})
        report = {
            "run_id": run_id, "tenant_id": tenant, "task_id": task.id, "task_type": ttype,
            "snapshot": {"snapshot_id": cfg.snapshot_id, "sha256": info.get("sha256"), "rows": n,
                         "synthetic": bool(info.get("synthetic")), "source_ref": info.get("source_ref") or {}},
            "config": {"seed": seed, "code_version": cfg.code_version, "candidates": list(cfg.candidates),
                       "candidate_params": cfg.candidate_params, "config_hash": cfg.config_hash()},
            "split": {"policy": sp.policy, "boundaries": sp.boundaries},
            "selection_metric": sel, "valid_metrics": valid_metrics, "valid_baseline": base_valid,
            "champion": champion, "selection_reason": reason,
            "baseline": {"regression": "train_mean", "risk": "train_positive_rate", "anomaly": "contamination"}[ttype],
            "baseline_value": base_const, "test_metrics": metrics.with_baseline(tm, bm),
            "beats_baseline": bool(beats), "beats_baseline_rule": rule, "interval": interval,
            "outliers_removed": 0, "test": rep_test, "warnings": warnings, "ledger": ledger.events(),
            "test_predictions_sha256": hashlib.sha256(np.asarray(test_pred, float).tobytes()).hexdigest(),
        }
        out_dir = self.artifact_root / tenant / task.id / run_id
        report = artifacts.clean(report)
        bundle = artifacts.write(out_dir, model=model, features_lock=features_lock, report=report)
        report = {**report, "artifact_sha256": bundle}
        return TrainResult(run_id, "succeeded", champion, artifacts.clean(valid_metrics), reason, test_metrics,
                           bool(beats), _rel(out_dir), report, artifacts.clean(warnings), ledger.events(),
                           artifact_sha256=bundle, synthetic=bool(info.get("synthetic")),
                           test_predictions=tuple(float(x) for x in test_pred))


def train(cfg: TrainConfig, **kw) -> TrainResult:
    return StandardTrainer(**kw).train(cfg)
