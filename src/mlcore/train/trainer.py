"""표준 학습기 (contracts/interfaces.md §4 · spec §5).

절차 고정 — 바꿀 수 있는 설정이 없다:
  1) 분할(split.plan) — 시험 구간 인덱스는 GuardedTest 만 가진다.
  2) 학습 구간으로 후보 학습 → 검증 구간으로 선정 · 예측 구간(split conformal) · 임계값.
  3) 학습+검증으로 재적합 → evaluate.final_evaluation 으로 시험 구간 1회 평가(기준선 함께).
  4) report.test_report(시험 구간 `report` 목적) → 산출물 4종 + SHA-256.
기준선: regression = 재적합 구간 목표 평균(시계열이면 직전 값 `last_value` 와 검증 구간에서 비교해 나은 쪽),
risk = 재적합 구간 양성률 상수, anomaly = 기대 오염률 × beats_band (std/metrics.yaml).
보정 · 구간 · 임계값은 학습 구간 모델의 검증 구간 출력으로 맞추고 재적합 모델에 그대로 씌운다:
regression 구간 q(split conformal) · risk 확률 보정(sigmoid | isotonic) · anomaly 임계값(검증 점수 1-c 분위, D-50).
선택 기능: `outlier: iqr`(학습 구간에서만 경계 · 제거) · `candidate_search`(후보당 무작위 탐색 ≤ 20, 시드 고정).
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
from ..data.calibration import CalibratedModel, fit_calibrator
from ..registry.packs import std
from .candidates import CandidateUnavailable, build
from .evaluate import final_evaluation
from .guard import AccessLedger, InSampleEvaluation, TestLeak
from .report import test_report

calls = 0                      # 학습 호출 계측 (G-M06: API 기동 후 0)
TRAINABLE = ("regression", "risk", "anomaly")




def beats_band() -> tuple[float, float]:
    """anomaly 기준선 판정 밴드 — std/metrics.yaml flag_rate.beats_band (코드 상수 없음, D-50)."""
    lo, hi = std("metrics")["metrics"]["flag_rate"]["beats_band"]
    return float(lo), float(hi)


def last_value_lag(frame: pd.DataFrame, rows) -> np.ndarray:
    """기준선 last_value — `rows`(frame 위치) 만 (ts, entity_id) 시각순으로 세웠을 때 바로 앞 행의 목표값.
    결과는 rows 순서대로, 그 구간의 첫 행은 NaN. **주어진 구간 밖 행은 보지 않는다**(DEF-QA1-001):
    선정용(검증) 기준선은 재적합 구간(학습+검증)만, 시험 기준선은 final_eval 에서 받은 시험 행 + 재적합 구간으로 만든다."""
    rows = list(rows)
    sub = frame.iloc[rows].reset_index(drop=True)
    order = sub.sort_values(["ts", "entity_id"], kind="mergesort").index
    lag = sub.loc[order, "target"].shift(1)
    return lag.reindex(sub.index).to_numpy(dtype=float)


def outlier_config(raw: dict) -> dict | None:
    """과제 `outlier: iqr` 또는 `{method: iqr, k: 1.5, columns: [...]}` → 설정. 없으면 꺼짐(spec §5.1 기본)."""
    o = raw.get("outlier")
    if o in (None, False, "none"):
        return None
    if isinstance(o, str):
        o = {"method": o}
    if o.get("method") != "iqr":
        raise ValueError(f"outlier 방법 {o.get('method')!r} — iqr 만 있다")
    return {"method": "iqr", "k": float(o.get("k", 1.5)), "columns": list(o.get("columns") or [])}


def iqr_filter(frame: pd.DataFrame, idx, cols, k: float) -> tuple[list[int], int]:
    """idx 행만으로 열별 [Q1 - k·IQR, Q3 + k·IQR] 를 재고, 하나라도 밖인 행을 idx 에서 뺀다(결측은 판정 안 함)."""
    idx = list(idx)
    sub = frame.iloc[idx]
    keep = np.ones(len(idx), dtype=bool)
    for c in cols:
        if c not in sub.columns:
            continue
        v = pd.to_numeric(sub[c], errors="coerce").to_numpy(dtype=float)
        ok = ~np.isnan(v)
        if ok.sum() < 4:
            continue
        q1, q3 = np.percentile(v[ok], [25, 75])
        lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        keep &= ~(ok & ((v < lo) | (v > hi)))
    return [i for i, kp in zip(idx, keep) if kp], int((~keep).sum())


def search_trials(space: dict, max_trials: int, seed: int) -> list[dict]:
    """후보당 무작위 탐색 — 과제 `candidate_search: {<후보>: {<파라미터>: [값, ...]}}` 의 격자에서
    시드 고정으로 최대 max_trials 개(std/candidates.yaml search.max_random_trials_per_candidate)를 뽑는다.
    격자가 그보다 작으면 전부. 첫 시도는 항상 팩 기본값(빈 조합)이다."""
    import itertools

    keys = sorted(space)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(list(space[k]) for k in keys))]
    budget = max(0, int(max_trials) - 1)
    if len(combos) > budget:
        pick = np.random.RandomState(seed).choice(len(combos), size=budget, replace=False)
        combos = [combos[i] for i in sorted(pick)]
    return [{}] + combos


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


def resolve_features(task, *, tenants_base=None, merged=None) -> list[FeatureDef]:
    from ..data.jobs import load_merged

    m = merged if merged is not None else load_merged(tenant_of(task), tenants_base)
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
            code = getattr(e, "code", None) or "train_failed"   # split.SplitRefused 등은 고유 코드(D-85)
            err = {"type": type(e).__name__, "code": code, "message": str(e)}
            if getattr(e, "detail", None):
                err["detail"] = e.detail
            warns = [_w(code, f"{type(e).__name__}: {e}", **(getattr(e, "detail", None) or {}))]
            return TrainResult(run_id, "failed", None, {}, f"학습 실패: {type(e).__name__}: {e}", {}, False, None,
                               {"run_id": run_id, "error": err, "warnings": warns}, warns,
                               ledger.events(), synthetic=bool(info.get("synthetic")))

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

        use_last_value = ttype == "regression" and bool(raw.get("time_key")) and "ts" in frame.columns
        sp, test = split.plan(frame, task, seed, ledger=ledger)      # SplitRefused → failed (code 는 보고 · 경고에)
        if not sp.train_idx or not sp.valid_idx or len(test) == 0:
            raise ValueError(f"분할 구간이 비었다: {sp.boundaries.get('sizes')}")
        folds = sp.folds or ((sp.train_idx, sp.valid_idx),)
        X_all = frame[names]
        y_all = y_of(frame) if supervised else None
        last_vals = None
        if use_last_value:      # 기준선 last_value (직전 행 목표) — 재적합 구간(학습+검증) 안에서만 잇는다. 모델 입력이 아니다
            last_vals = np.full(n, np.nan)
            last_vals[list(sp.fit_idx)] = last_value_lag(frame, sp.fit_idx)
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
        out_cfg = outlier_config(raw)
        out_cols = ([f.name for f in feats if f.numeric] + (["target"] if ttype == "regression" else [])) \
            if out_cfg and not out_cfg.get("columns") else list((out_cfg or {}).get("columns") or [])
        outliers: dict = {"method": out_cfg["method"], "k": out_cfg["k"], "columns": out_cols, "folds": []} if out_cfg else {}

        def train_rows(idx) -> list[int]:
            """학습에 쓸 행 — `outlier: iqr` 면 그 학습 구간에서만 경계를 재고 그 구간에서만 뺀다(검증 · 시험은 그대로)."""
            idx = list(idx)
            if not out_cfg:
                return idx
            kept, removed = iqr_filter(frame, idx, out_cols, out_cfg["k"])
            outliers["folds"].append(removed)
            return kept

        fold_rows = [(train_rows(tr), list(va)) for tr, va in folds]

        def fit_eval(name: str, params: dict | None):
            """후보 하나 · 하이퍼파라미터 하나 → (검증 예측 또는 점수, 검증 목표). 학습 구간 모델만 쓴다."""
            preds, ys = [], []
            for tr, va in fold_rows:
                m = build(name, ttype, feats, params, seed)
                if supervised:
                    m.fit(X_all.iloc[tr], y_all[tr])
                    ys.append(y_all[va])
                else:
                    m.fit(X_all.iloc[tr])
                preds.append(predict(m, X_all.iloc[va]))
            return np.concatenate(preds), (np.concatenate(ys) if ys else None)

        def score_valid(p, yv) -> dict:
            if ttype == "regression":
                return metrics.regression(yv, p)
            if ttype == "risk":
                return metrics.risk(yv, p, threshold)
            thr = float(np.quantile(p, 1 - contamination))
            return metrics.anomaly((p >= thr).astype(float))

        max_trials = int((std("candidates").get("search") or {}).get("max_random_trials_per_candidate", 20))
        valid_metrics: dict[str, dict] = {}
        oof: dict[str, tuple[np.ndarray, np.ndarray | None]] = {}
        chosen_params: dict[str, dict] = {}
        search_log: dict[str, dict] = {}
        for name in cfg.candidates:
            base_params = dict(cfg.candidate_params.get(name) or {})
            space = (raw.get("candidate_search") or {}).get(name) or {}
            trials = search_trials(space, max_trials, seed) if space and sel is not None else [{}]
            if space and sel is None:
                warnings.append(_w("search_skipped", "선정 지표가 없는 유형(비지도)은 하이퍼파라미터 탐색을 하지 않는다",
                                   candidate=name))
            best = None
            try:
                for i, combo in enumerate(trials):
                    params = {**base_params, **combo}
                    p, yv = fit_eval(name, params)
                    vm = score_valid(p, yv)
                    if best is None or (sel is not None and metrics.better(sel, vm[sel], best[2][sel])):
                        best = (params, (p, yv), vm, i)
            except CandidateUnavailable as e:
                warnings.append(_w("candidate_unavailable", str(e), candidate=name))
                continue
            chosen_params[name], oof[name], valid_metrics[name] = best[0], best[1], best[2]
            if space and sel is not None:
                search_log[name] = {"strategy": "random", "trials": len(trials), "max_trials": max_trials,
                                    "seed": seed, "best_trial": best[3], "best_params": best[0]}
        if not valid_metrics:
            raise ValueError("학습 가능한 후보가 없다")

        # 검증 구간 기준선 — 학습 구간 평균 · 양성률(시계열 회귀는 직전 값도) 중 검증 구간에서 나은 것
        baseline_kind = {"regression": "train_mean", "risk": "train_positive_rate", "anomaly": "contamination"}[ttype]
        base_alt: dict = {}
        if supervised:
            base_parts, base_y = [], []
            for tr, va in folds:
                base_parts.append(np.full(len(va), float(np.mean(y_all[list(tr)]))))
                base_y.append(y_all[list(va)])
            bp, by = np.concatenate(base_parts), np.concatenate(base_y)
            base_valid = metrics.regression(by, bp) if ttype == "regression" else metrics.risk(by, bp, threshold)
            if use_last_value:
                lv = np.concatenate([last_vals[list(va)] for _, va in folds])
                ok = ~np.isnan(lv)
                if ok.all():
                    lv_valid = metrics.regression(by, lv)
                    base_alt = {"train_mean": base_valid, "last_value": lv_valid}
                    if metrics.better(sel, lv_valid[sel], base_valid[sel]):
                        baseline_kind, base_valid, bp = "last_value", lv_valid, lv
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
                      f"{valid_metrics[champion][sel]:.6g} (검증 기준선 {baseline_kind} {base_valid[sel]:.6g}) — "
                      f"후보 {len(valid_metrics)}개, 분할 {sp.policy}")
            if champion in search_log:
                reason += f", 무작위 탐색 {search_log[champion]['trials']}회 중 {search_log[champion]['best_trial'] + 1}번째"
        else:
            champion = next(iter(valid_metrics))
            reason = (f"비지도 — 후보 {champion} 하나, 임계값은 학습 구간 모델의 검증 구간 점수 {1 - contamination:.3f} 분위"
                      f"(검증 {len(oof[champion][0])}행, 시험 구간 미사용)")

        # 예측 구간 · 보정 · 임계값 — 학습 구간 모델의 검증 구간 잔차 · 확률 · 점수로만 (D-50)
        interval = None
        if ttype == "regression":
            icfg = raw.get("interval") or {}
            alpha = float(icfg.get("alpha", 0.1))
            p, yv = oof[champion]
            q = _conformal_q(np.abs(yv - p), alpha)
            bq = _conformal_q(np.abs(by - bp), alpha)
            interval = {"method": icfg.get("method", "split_conformal"), "alpha": alpha, "q": q, "baseline_q": bq,
                        "fit_on": "valid", "n": int(len(yv))}
        anomaly_thr = None
        if ttype == "anomaly":
            anomaly_thr = float(np.quantile(oof[champion][0], 1 - contamination))
        cal_method = (raw.get("calibration") or {}).get("method", "none") if ttype == "risk" else None
        calibration, calibrator = None, None
        if cal_method not in (None, "none"):
            p, yv = oof[champion]
            try:
                calibrator = fit_calibrator(cal_method, p, yv)
                calibration = {"method": cal_method, "fit_on": "valid", "n": int(len(yv)),
                               "valid_raw_brier": float(metrics.risk(yv, p, threshold)["brier"])}
            except ValueError as e:
                warnings.append(_w("calibration_skipped", f"보정 {cal_method} 을 하지 못했다: {e}", method=cal_method))

        # ── 3) 학습+검증 재적합 → 시험 1회 ───────────────
        fit_all = list(sp.fit_idx)
        fit_idx = train_rows(fit_all)
        if outliers:
            outliers["refit"] = outliers["folds"].pop()
        model = build(champion, ttype, feats, chosen_params.get(champion), seed)
        if supervised:
            model.fit(X_all.iloc[fit_idx], y_all[fit_idx])
            base_const = float(np.mean(y_all[fit_all]))
        else:
            model.fit(X_all.iloc[fit_idx])
            base_const = contamination
        if calibrator is not None:
            model = CalibratedModel(model, cal_method, calibrator)
        if ttype == "risk":
            rate = base_const
            if rate < 0.05 or rate > 0.95:
                warnings.append(_w("target_imbalance", "목표 불균형(양성률 < 5% 또는 > 95%)", positive_rate=rate))

        def test_last_value(df: pd.DataFrame) -> np.ndarray:
            """시험 행의 직전 값 — final_eval 로 받은 시험 행 + 재적합 구간만으로 잇는다(시험 1회 평가 안에서만)."""
            both = pd.concat([frame.iloc[fit_all], df], ignore_index=True)
            return last_value_lag(both, range(len(both)))[len(fit_all):]

        def base_pred(df: pd.DataFrame) -> np.ndarray:
            if baseline_kind == "last_value":
                return test_last_value(df)
            return np.full(len(df), base_const)

        def score(df: pd.DataFrame):
            X = df[names]
            p = predict(model, X)
            if ttype == "regression":
                y = y_of(df)
                lo, hi = clipped(p - interval["q"]), clipped(p + interval["q"])
                b = base_pred(df)
                bm = metrics.regression(y, b, clipped(b - interval["baseline_q"]), clipped(b + interval["baseline_q"]))
                alt = {}
                if base_alt:
                    alt = {"train_mean": metrics.regression(y, np.full(len(df), base_const)),
                           "last_value": metrics.regression(y, test_last_value(df))}
                return metrics.regression(y, p, lo, hi), bm, p, alt
            if ttype == "risk":
                y = y_of(df)
                return metrics.risk(y, p, threshold), metrics.risk(y, np.full(len(df), base_const), threshold), p, {}
            flags = (p >= anomaly_thr).astype(float)
            return metrics.anomaly(flags), {"flag_rate": contamination}, p, {}

        # 재적합 구간 = 학습+검증 전체(이상치 제거 전) — 시험과 겹치면 표본 내 평가로 거부
        tm, bm, test_pred, test_alt = final_evaluation(frame, test, fit_all, score)
        test_metrics = {k: MetricValue(**v) for k, v in metrics.with_baseline(tm, bm).items()}
        if sel is not None:
            beats = sel in test_metrics and test_metrics[sel].baseline is not None and \
                metrics.better(sel, test_metrics[sel].value, test_metrics[sel].baseline)
            rule = f"시험 {sel} 이 기준선({baseline_kind})보다 {'낮다' if metrics.direction(sel) == 'lower' else '높다'}"
        else:
            lo_b, hi_b = beats_band()
            fr = test_metrics["flag_rate"].value
            beats = lo_b * contamination <= fr <= hi_b * contamination
            rule = (f"시험 flag_rate 가 기대 오염률 × [{lo_b:g}, {hi_b:g}] 안 "
                    f"(std/metrics.yaml flag_rate.beats_band — 라벨 없는 비지도라 우열 비교가 없다, D-50)")
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
                   "calibration": calibration, "baseline_kind": baseline_kind,
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
            "baseline": baseline_kind, "baseline_value": base_const,
            "baselines_compared": ({"valid": base_alt, "test": test_alt, "chosen_on": "valid"} if base_alt else None),
            "test_metrics": metrics.with_baseline(tm, bm),
            "beats_baseline": bool(beats), "beats_baseline_rule": rule, "interval": interval,
            "threshold": anomaly_thr if ttype == "anomaly" else threshold,
            "threshold_rule": ("학습 구간 모델의 검증 구간 점수 1-c 분위 → 재적합 모델에 그대로 (D-50)"
                               if ttype == "anomaly" else None),
            "calibration": calibration, "search": search_log or None, "chosen_params": chosen_params,
            "outliers": outliers or None,
            "outliers_removed": (sum(outliers["folds"]) + outliers["refit"]) if outliers else 0,
            "test": rep_test, "warnings": warnings, "ledger": ledger.events(),
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
