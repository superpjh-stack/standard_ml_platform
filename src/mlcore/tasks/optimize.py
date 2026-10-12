"""optimize 추론부 — 조건 추천 (spec §8.1 · contracts/interfaces.md §8 · predict-contract §3 · task-contract §2 · D-25). 소유 개발2.

공간: 조절 변수(controls) = [학습 범위 p1, p99] ∩ [min, max] 위의 `min + k·step` 점만 만든다(학습 범위 밖 점 0 — G-M13).
      결정 변수(decision_vars, 모델 입력 아님) = [min, max 또는 params[max_param]] 위의 step 점(학습 범위 없음).
전략: search.strategy grid · auto → 공간 ≤ max_points 면 grid, 아니면 random(과제 seed 고정, max_points 개). random → 항상 random.
평가: uses 과제의 **production** 모델(등록부 · 해시 대조 산출물)로 일괄 예측 → formulas(팩 순수 함수) → 제약 → 목적 · tiebreak 정렬 → 상위 5.
      충족 0 이면 least_violation(위반 최소, 동률이면 목적) + status review. 결과는 mlp_recommendation(needs_approval) 1행과
      승인 요청(mlp_approval kind=recommendation, pending) 1행. **설비 · MES 에 쓰지 않는다.**
코어는 변수 · 과제 이름을 모른다 — 전부 과제 정의(TaskDef.raw) · 변수 정의(FeatureDef) · 산출물 lock 에서 온다.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .. import approval, audit
from ..db.conn import connect
from ..registry.artifacts import load_artifacts
from ..registry.models import ModelRef, Registry
from ..serve.contract import to_contract
from ..serve.errors import InvalidInput, MissingRequired, NotFound, OutOfBounds, ServeError
from ..serve.ids import new_id
from ..serve.validate import check_missing, impute, range_check, validate_bounds, validate_format
from .base import kind_for, warn

TOP = 5
FEASIBLE_EPS = 1e-10
EXPR = re.compile(r"^\s*(?P<lhs>.+?)\s*(?P<op><=|>=|<|>)\s*(?P<rhs>.+?)\s*$")


@dataclass(frozen=True)
class OptimizeRequest:
    fixed: dict[str, Any]
    current: dict[str, Any] | None = None
    params: dict[str, float] | None = None
    entity_id: str | None = None
    request_approval: bool = True          # false = mlp_recommendation 만, mlp_approval 0 (D2-08)


@dataclass
class SearchSpace:
    axes: dict[str, list]                 # 이름 → 점 목록 (조절 변수 · 결정 변수)
    kinds: dict[str, str]                 # 이름 → "control" | "decision"
    ranges: dict[str, tuple | None]       # 조절 변수의 실제 탐색 구간 [lo, hi] (학습 범위 ∩ min/max)
    size: int = 0
    strategy: str = "grid"
    points: pd.DataFrame = field(default_factory=pd.DataFrame)


class InfeasibleSpace(ServeError):
    status, code, default_message = 422, "invalid_input", "학습 범위 ∩ 검증 범위에 탐색할 점이 없습니다"


# ── 제약 식 — `<lhs> (<=|>=|<|>) <rhs>`, 항은 이름 · 숫자 · + - * (task-contract §2) ─────────────────
def _compile(side: str) -> ast.Expression:
    tree = ast.parse(side, mode="eval")
    for node in ast.walk(tree):
        ok = isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
                               ast.Add, ast.Sub, ast.Mult, ast.USub, ast.UAdd))
        if not ok or (isinstance(node, ast.Constant) and not isinstance(node.value, (int, float))):
            raise ServeError("제약 식에 허용되지 않는 항이 있습니다", {"rule": "constraint_expr", "field": None})
    return tree


def _eval(node: ast.AST, env: dict[str, Any]):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ServeError("제약 식의 이름을 찾을 수 없습니다", {"rule": "constraint_name", "field": node.id})
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    a, b = _eval(node.left, env), _eval(node.right, env)
    if isinstance(node.op, ast.Add):
        return a + b
    if isinstance(node.op, ast.Sub):
        return a - b
    return a * b


@dataclass(frozen=True)
class Constraint:
    name: str
    expr: str
    op: str
    lhs: ast.Expression
    rhs: ast.Expression

    @classmethod
    def parse(cls, c: dict) -> "Constraint":
        m = EXPR.match(c["expr"])
        if not m:
            raise ServeError("제약 식 모양이 아닙니다", {"rule": "constraint_expr", "field": c.get("name")})
        return cls(c["name"], c["expr"], m["op"], _compile(m["lhs"]), _compile(m["rhs"]))

    def evaluate(self, env: dict[str, Any], n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """→ (lhs, rhs, slack, satisfied, violation) 점마다."""
        lhs = np.broadcast_to(np.asarray(_eval(self.lhs, env), dtype=float), (n,)).astype(float)
        rhs = np.broadcast_to(np.asarray(_eval(self.rhs, env), dtype=float), (n,)).astype(float)
        slack = rhs - lhs if self.op in ("<=", "<") else lhs - rhs
        sat = slack > 0 if self.op in ("<", ">") else slack >= -FEASIBLE_EPS
        viol = np.where(sat, 0.0, np.maximum(0.0, -slack) / np.maximum(np.abs(rhs), 1e-9))
        if self.op in ("<", ">"):     # 엄격 부등호에서 경계(slack 0)는 위반량 0 이지만 충족도 아니다 — 아주 작은 위반으로 센다
            viol = np.where(~sat & (viol == 0), FEASIBLE_EPS * 10, viol)
        return lhs, rhs, slack, sat, viol


# ── 팩 · 회사 비용식 (formulas/<module>.py::cost(row, params) -> float) ───────────────────────────────
_FORMULAS: dict[tuple[str, str], Callable] = {}


def load_formula(merged: Any, module: str) -> Callable:
    """회사 플러그인(tenants/<code>/formulas/) 이 있으면 그것, 없으면 팩 formulas/. 같은 이름 · 다른 내용은 병합 규칙 5 가 막는다."""
    own = merged.tenant.path.parent / merged.tenant.code / "formulas" / f"{module}.py"
    path = own if own.is_file() else merged.pack.path / "formulas" / f"{module}.py"
    if not path.is_file():
        raise ServeError("비용식 모듈이 없습니다", {"rule": "formula_missing", "field": module})
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    key = (str(path), digest)
    fn = _FORMULAS.get(key)
    if fn is None:
        spec = importlib.util.spec_from_file_location(f"_mlp_formula_{digest[:12]}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)               # type: ignore[union-attr]
        fn = getattr(mod, "cost", None)
        if not callable(fn):
            raise ServeError("비용식 모듈에 cost(row, params) 가 없습니다", {"rule": "formula_cost", "field": module})
        _FORMULAS[key] = fn
    return fn


def _short(task_id: str) -> str:
    return task_id.split(".", 1)[1] if "." in task_id else task_id


def _lattice(lo: float, hi: float, base: float, step: float) -> list[float]:
    """base + k·step 중 [lo, hi] 안의 점 (부동소수 오차 1e-9 허용, 소수 10자리로 정리)."""
    if step is None or step <= 0:
        raise ServeError("탐색 간격(step)이 없습니다", {"rule": "step", "field": None})
    k0 = math.ceil((lo - base) / step - 1e-9)
    k1 = math.floor((hi - base) / step + 1e-9)
    return [round(base + k * step, 10) for k in range(k0, k1 + 1)]


def _num(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e15 else round(f, 6)
    return v


class Optimizer:
    def __init__(self, catalog: Any, registry: Registry | None = None):
        self.catalog = catalog
        self.registry = registry or Registry()

    # ── 의존 과제 ─────────────────────────────────────────────────────────
    def _uses(self, spec: Any) -> list[tuple[Any, ModelRef, Any]]:
        """uses(팩 과제 id) → (회사 과제 spec, production ModelRef, LoadedModel). 운영 모델이 없으면 503 model_not_ready."""
        by_pack = {s.task.pack_id: s for s in (self.catalog.get(spec.tenant_id, t) for t in self.catalog.ids())}
        out = []
        for pack_id in spec.task.raw.get("uses") or []:
            dep = by_pack.get(pack_id)
            if dep is None:                    # 병합 규칙 3 이 기동 때 막지만, 여기서도 지어내지 않는다
                self.catalog.require_servable(spec.tenant_id, f"{spec.tenant_id}.{_short(pack_id)}")   # 꺼진 의존 → 503
                raise NotFound("의존 과제가 켜져 있지 않습니다")
            ref = self.registry.get(spec.tenant_id, dep.task.id)
            self.catalog.require_servable(spec.tenant_id, dep.task.id, ref)   # live + 합성 → 503 (D-120a)
            loaded = load_artifacts(ref)
            out.append((dep, ref, loaded))
        if not out:
            raise ServeError("의존 과제(uses)가 없습니다", {"rule": "uses", "field": None})
        return out

    # ── 공간 ────────────────────────────────────────────────────────────
    def space(self, task: Any, locks: list[dict], params: dict, defs: dict) -> SearchSpace:
        raw = task.raw
        axes, kinds, ranges = {}, {}, {}
        for name in raw.get("controls") or []:
            f = defs[name]
            if f.dtype == "category":
                seen = None
                for lk in locks:
                    item = (lk.get("features") or {}).get(name)
                    if item is not None:
                        vals = set(item.get("values") or [])
                        seen = vals if seen is None else seen & vals
                allowed = list(f.values or [])
                axes[name] = [v for v in allowed if seen is None or v in seen]
                ranges[name] = None
            else:
                lo, hi = f.min, f.max
                for lk in locks:               # 학습 범위 ∩ (모든 의존 모델의 p1~p99)
                    item = (lk.get("features") or {}).get(name)
                    if item is not None and item.get("p1") is not None:
                        lo = item["p1"] if lo is None else max(lo, item["p1"])
                        hi = item["p99"] if hi is None else min(hi, item["p99"])
                if lo is None or hi is None:
                    raise InfeasibleSpace(detail={"rule": "no_range", "field": name})
                base = f.min if f.min is not None else lo
                axes[name] = _lattice(lo, hi, base, f.step)
                ranges[name] = (lo, hi)
            kinds[name] = "control"
            if not axes[name]:
                raise InfeasibleSpace(detail={"rule": "empty_axis", "field": name})
        for name, d in (raw.get("decision_vars") or {}).items():
            lo, hi = self._decision_bounds(d, params)
            if hi is None:
                raise ServeError("결정 변수 상한이 없습니다", {"rule": "decision_max", "field": name})
            axes[name] = _lattice(lo, float(hi), lo, float(d["step"]))
            kinds[name] = "decision"
            ranges[name] = None
            if not axes[name]:
                raise InfeasibleSpace(detail={"rule": "empty_axis", "field": name})
        size = int(np.prod([len(v) for v in axes.values()])) if axes else 0
        search = raw.get("search") or {}
        max_points = int(search.get("max_points", 10000))
        strat = search.get("strategy", "auto")
        strategy = "random" if strat == "random" or size > max_points else "grid"
        names = list(axes)
        if strategy == "grid":
            grids = np.meshgrid(*[np.asarray(axes[n], dtype=object) for n in names], indexing="ij")
            pts = pd.DataFrame({n: g.ravel() for n, g in zip(names, grids)})
        else:
            rng = np.random.default_rng(int(raw.get("seed", 42)))
            n = min(max_points, size)
            flat = rng.choice(size, size=n, replace=False) if size < 2**62 else rng.integers(0, size, n)
            flat = np.sort(flat)
            cols, rem = {}, flat.copy()
            for name in reversed(names):       # 혼합 기수 → 축별 색인
                L = len(axes[name])
                cols[name] = np.asarray(axes[name], dtype=object)[rem % L]
                rem = rem // L
            pts = pd.DataFrame({n: cols[n] for n in names})
        for n in names:                         # 수치 축은 float
            if kinds[n] == "decision" or defs.get(n) is None or defs[n].dtype != "category":
                pts[n] = pts[n].astype(float)
        return SearchSpace(axes, kinds, ranges, size, strategy, pts)

    @staticmethod
    def _decision_bounds(d: dict, params: dict) -> tuple[float, float | None]:
        """결정 변수 [min, max] — max_param 이 있으면 요청 params 의 그 값(task-contract §2 decision_vars)."""
        hi = params[d["max_param"]] if d.get("max_param") else d.get("max")
        return float(d.get("min", 0)), (None if hi is None else float(hi))

    # ── 요청 검증 ─────────────────────────────────────────────────────────
    def _params(self, task: Any, given: dict | None) -> dict:
        spec = task.raw.get("params") or {}
        given = dict(given or {})
        unknown = [k for k in given if k not in spec]
        if unknown:
            raise InvalidInput("알 수 없는 제약 값입니다", {"field": str(unknown[0])[:64], "rule": "unknown_key"})
        out = {}
        for name, p in spec.items():
            v = given.get(name, p.get("default"))
            if v is None:
                raise MissingRequired("제약 값이 없습니다", {"field": name, "rule": "required"})
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise InvalidInput("숫자여야 합니다", {"field": name, "rule": "type"})
            if p.get("min") is not None and v < p["min"]:
                raise OutOfBounds(detail={"field": name, "rule": "min"})
            if p.get("max") is not None and v > p["max"]:
                raise OutOfBounds(detail={"field": name, "rule": "max"})
            out[name] = float(v)
        return out

    # ── 실행 ────────────────────────────────────────────────────────────
    def optimize(self, tenant_id: str, task_id: str, req: OptimizeRequest, *, caller: str, channel: str = "api") -> dict:
        self.catalog.require_servable(tenant_id, task_id)                    # 꺼진 과제 → 503 (D-120a)
        spec = self.catalog.get(tenant_id, task_id)
        task = spec.task
        if task.type != "optimize":     # 회귀 · 2차 유형 과제의 /optimize — 경로가 유형과 맞지 않는다 (predict-contract §8)
            raise NotFound("최적화 과제가 아닙니다", {"rule": "type_route", "field": None})
        raw = task.raw
        defs = {f.name: f for f in spec.defs}
        controls = list(raw.get("controls") or [])
        fixed_names = list(raw.get("fixed") or [n for n in defs if n not in controls])
        fixed_defs = [defs[n] for n in fixed_names]
        # 1) 형식 → min/max → 필수 (predict 와 같은 순서 · 같은 규칙)
        validate_format(req.fixed, fixed_defs)
        validate_bounds(req.fixed, fixed_defs)
        check_missing(req.fixed, fixed_defs, spec.max_imputed)
        params = self._params(task, req.params)
        dvars = raw.get("decision_vars") or {}
        if req.current is not None:
            cur_defs = [defs[n] for n in controls]
            extra = {k: v for k, v in req.current.items() if k in dvars}
            validate_format({k: v for k, v in req.current.items() if k not in dvars}, cur_defs)
            validate_bounds({k: v for k, v in req.current.items() if k not in dvars}, cur_defs)
            for k, v in extra.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                    raise InvalidInput("숫자여야 합니다", {"field": k, "rule": "type"})
                lo, hi = self._decision_bounds(dvars[k], params)       # 탐색 공간과 같은 [min, max | params[max_param]]
                if float(v) < lo:
                    raise OutOfBounds(detail={"field": k, "rule": "min"})
                if hi is not None and float(v) > hi:
                    raise OutOfBounds(detail={"field": k, "rule": "max"})   # DEF-QA3-006
            missing = [n for n in controls + list(dvars) if req.current.get(n) is None]
            if missing:
                raise MissingRequired("현재 조건은 조절 · 결정 변수를 모두 넣어야 합니다", {"field": missing[0], "rule": "required"})
        # 2) 의존 과제 production 모델
        uses = self._uses(spec)
        locks = [ld.lock for _, _, ld in uses]
        # 3) 고정 입력 보정 · 범위 판정 (의존 모델마다 자기 학습 보정값 · 학습 범위)
        imputed, oor, near = [], [], []
        filled_by: list[dict] = []
        for dep, ref, ld in uses:
            dep_fixed = [defs[n] for n in fixed_names if n in ld.lock.get("order", [])]
            sub = {n: req.fixed.get(n) for n in (d.name for d in dep_fixed)}
            f, imp = impute(sub, dep_fixed, ld.lock, spec.max_imputed)
            o, nr = range_check(f, ld.lock, skip=imp)
            filled_by.append(f)
            imputed += [x for x in imp if x not in imputed]
            oor += [x for x in o if x not in oor]
            near += [x for x in nr if x not in near and x not in oor]
        # 4) 공간
        sp = self.space(task, locks, params, defs)
        pts = sp.points
        n = len(pts)
        # 5) 의존 과제 일괄 예측 (+ current 1점)
        cur_row = None
        if req.current is not None:
            cur_row = pd.DataFrame([{k: (float(req.current[k]) if sp.kinds.get(k) == "decision" or defs.get(k) is None
                                         or defs[k].dtype != "category" else req.current[k]) for k in sp.axes}])
        evals = self._evaluate(spec, uses, filled_by, pts, cur_row, params)
        env_all, preds, intervals = evals["env"], evals["preds"], evals["intervals"]
        # 6) 제약
        cons = [Constraint.parse(c) for c in raw.get("constraints") or []]
        total = n + (1 if cur_row is not None else 0)
        cres = [c.evaluate(env_all, total) for c in cons]
        violation = np.sum([cr[4] for cr in cres], axis=0) if cres else np.zeros(total)
        feasible_mask = violation <= FEASIBLE_EPS
        # 7) 목적 · 정렬
        obj = raw["objective"]
        oname = obj.get("minimize") or obj.get("maximize")
        odir = "minimize" if "minimize" in obj else "maximize"
        tiebreak = [{"name": t.get("minimize") or t.get("maximize"), "direction": "minimize" if "minimize" in t else "maximize"}
                    for t in obj.get("tiebreak") or []]
        def col(name: str) -> np.ndarray:
            v = env_all.get(name)
            if v is None:
                raise ServeError("목적 이름을 찾을 수 없습니다", {"rule": "objective_name", "field": name})
            return np.broadcast_to(np.asarray(v, dtype=float), (total,)).astype(float)
        ovals = col(oname)
        keys = [ovals if odir == "minimize" else -ovals]
        keys += [col(t["name"]) if t["direction"] == "minimize" else -col(t["name"]) for t in tiebreak]
        grid_idx = np.arange(n)
        feas = grid_idx[feasible_mask[:n]]
        if len(feas):
            pool = feas
            order = np.lexsort([k[pool] for k in reversed(keys)])
        else:
            pool = grid_idx
            order = np.lexsort([k[pool] for k in reversed(keys)] + [violation[pool]])
        top = pool[order[:TOP]]
        # 8) 후보 모양
        def cand(i: int) -> dict:
            conds = {k: _num(pts.iloc[i][k]) if i < n else _num(cur_row.iloc[0][k]) for k in sp.axes}
            return {
                "conditions": conds,
                "predictions": {k: float(round(float(np.asarray(v)[i] if np.ndim(v) else v), 6)) for k, v in preds.items()},
                "intervals": {k: (None if v is None else [round(float(v[0][i]), 6), round(float(v[1][i]), 6)])
                              for k, v in intervals.items()},
                "constraints": [{"name": c.name, "expr": c.expr, "lhs": round(float(cr[0][i]), 6), "rhs": round(float(cr[1][i]), 6),
                                 "satisfied": bool(cr[3][i]), "slack": round(float(cr[2][i]), 6)} for c, cr in zip(cons, cres)],
                "violation": round(float(violation[i]), 10),
                "objective_value": round(float(ovals[i]), 6),
            }
        cands = [cand(int(i)) for i in top]
        best = cands[0]
        current = cand(n) if cur_row is not None else None
        improvement = None
        if current is not None:
            d = current["objective_value"] - best["objective_value"]
            improvement = {oname: round(d if odir == "minimize" else -d, 6)}
        in_rate = self._in_range(pts, sp, locks)
        feasible = bool(len(feas))
        # 9) 상태 · 경고
        warnings = [warn("imputed", x, "학습 보정값으로 보정했습니다") for x in imputed]
        warnings += [warn("out_of_range", x, "고정 입력이 학습 범위(p1~p99) 밖입니다") for x in oor]
        warnings += [warn("near_range", x, "고정 입력이 학습 범위 가장자리입니다") for x in near]
        status = "needs_approval"
        if not feasible:
            status = "review"
            warnings.append(warn("infeasible", None, "제약을 모두 만족하는 조건이 없어 위반이 가장 작은 조건을 보입니다"))
            for c in best["constraints"]:
                if not c["satisfied"]:
                    warnings.append(warn("constraint_unmet", c["name"], "추천 조건이 이 제약을 만족하지 않습니다"))
        if oor:
            status = "review"              # 고정 입력이 학습 범위 밖 — 사람이 검토 (optimize 허용 상태 안에서)
        if evals["flags"] is not None and bool(np.asarray(evals["flags"])[int(top[0])]):
            warnings.append(warn("extrapolation", None, "추천 조건이 학습 분포와 다른 조합입니다"))
        warnings += self._warn_with(spec, req.fixed, cands)                # D-76 — 경고만(목적 · 제약 · 순위 불사용)
        synthetic = any(ref.synthetic for _, ref, _ in uses)
        if synthetic:
            warnings.append(warn("synthetic_model", None, "합성 데이터로 학습한 모델을 썼습니다"))
        uses_out = [{"task": dep.task.id, "version": ref.version, "synthetic": ref.synthetic} for dep, ref, _ in uses]
        rec_id = new_id("rec")
        out = to_contract({
            "task": task.id, "type": "optimize", "tenant": tenant_id, "entity_id": req.entity_id,
            "prediction": None, "probability": None, "anomaly": None,
            "recommendation": {
                "rec_id": rec_id, "feasible": feasible, "strategy": sp.strategy, "n_candidates": n,
                "n_feasible": int(len(feas)), "in_train_range_rate": in_rate,
                "objective": {"name": oname, "direction": odir, "tiebreak": tiebreak},
                "best": best, "candidates": cands, "current": current, "improvement": improvement,
                "on_infeasible": None if feasible else raw.get("on_infeasible", "least_violation"),
            },
            "status": status, "warnings": warnings, "imputed_fields": imputed, "out_of_range_fields": oor,
            "explain": None, "model": None, "uses": uses_out, "prediction_id": None,
            "synthetic": synthetic, "notice": spec.notice,
        })
        self._record(spec, out, req, params, caller=caller, channel=channel)
        return out

    # ── 이상 경고 (task-contract §2 warn_with · D-76) ─────────────────────────────────────
    def anomaly_flags(self, tenant_id: str, anomaly_task_id: str, fixed: dict, conditions: list[dict]) -> list[bool]:
        """이상 탐지 과제의 **production** 모델로 후보 조건마다 flag. 고정 입력은 그 모델의 학습 보정값으로 채운다.
        운영 모델이 없으면 ModelNotReady(503) — 호출자가 숨기지 않고 경고로 보인다."""
        dep = self.catalog.get(tenant_id, anomaly_task_id)
        if dep.task.type != "anomaly":
            raise ServeError("warn_with 는 anomaly 과제만 받습니다", {"rule": "warn_with_type", "field": None})
        ref = self.registry.get(tenant_id, dep.task.id)
        self.catalog.require_servable(tenant_id, dep.task.id, ref)
        ld = load_artifacts(ref)
        order = list(ld.lock["order"])
        given = set().union(*(set(c) for c in conditions)) if conditions else set()
        fdefs = [d for d in dep.defs if d.name not in given]
        filled, _ = impute({d.name: fixed.get(d.name) for d in fdefs}, fdefs, ld.lock, len(fdefs))
        frame = pd.DataFrame([{n: (c[n] if n in c else filled.get(n)) for n in order} for c in conditions], columns=order)
        kind = kind_for("anomaly")
        vals = np.asarray(kind.values(ld, frame), dtype=float)
        thr = kind._threshold(ld)
        return [bool(v >= thr) for v in vals]

    def _warn_with(self, spec, fixed: dict, cands: list[dict]) -> list[dict]:
        """추천(best) 조건이 warn_with 과제에 걸리면 경고. 계약 §5 경고 코드 enum 에 `anomaly_flag` 가 없어(계약 불일치 —
        decisions D-131) 같은 뜻의 `extrapolation`(field = 그 과제)을 쓴다. 운영 모델이 없으면 확인 못 했음을 경고로 보인다."""
        out = []
        by_pack = {s.task.pack_id: s for s in (self.catalog.get(spec.tenant_id, t) for t in self.catalog.ids())}
        for pack_id in spec.task.raw.get("warn_with") or []:
            dep = by_pack.get(pack_id)
            if dep is None:
                raise NotFound("warn_with 과제가 켜져 있지 않습니다")
            try:
                flags = self.anomaly_flags(spec.tenant_id, dep.task.id, fixed, [c["conditions"] for c in cands])
            except ServeError as e:
                if e.status != 503:
                    raise
                out.append(warn("extrapolation", dep.task.id, f"이상 탐지 운영 모델을 쓸 수 없어 확인하지 못했습니다 ({e.code})"))
                continue
            if flags and flags[0]:
                out.append(warn("extrapolation", dep.task.id, "추천 조건이 이상 탐지에 걸렸습니다 — 시험으로 먼저 확인하세요"))
        return out

    def _evaluate(self, spec, uses, filled_by, pts: pd.DataFrame, cur_row, params: dict) -> dict:
        """의존 모델 예측 · 비용식 · 이름 환경(제약 · 목적용)."""
        frames = [pts] + ([cur_row] if cur_row is not None else [])
        allpts = pd.concat(frames, ignore_index=True) if len(frames) > 1 else pts.reset_index(drop=True)
        total = len(allpts)
        env: dict[str, Any] = {k: v for k, v in params.items()}
        for name in allpts.columns:
            if allpts[name].dtype != object:
                env[name] = allpts[name].to_numpy(dtype=float)
        preds: dict[str, Any] = {}
        intervals: dict[str, Any] = {}
        flags = None
        fixed_num: dict[str, float] = {}
        for (dep, ref, ld), filled in zip(uses, filled_by):
            order = ld.lock["order"]
            frame = pd.DataFrame(index=range(total))
            for c in order:
                if c in allpts.columns:
                    frame[c] = allpts[c].to_numpy()
                else:
                    frame[c] = filled.get(c)
                    if isinstance(filled.get(c), (int, float)) and not isinstance(filled.get(c), bool):
                        fixed_num.setdefault(c, float(filled[c]))
            frame = frame[order]
            kind = kind_for(dep.task.type)
            short = _short(dep.task.id)
            if dep.task.type == "anomaly":
                pieces = kind.score(ld, frame, dep.task)
                flags = np.array([bool(p["anomaly"]["flag"]) for p in pieces]) if flags is None else \
                    flags | np.array([bool(p["anomaly"]["flag"]) for p in pieces])
                continue
            vals = np.asarray(kind.values(ld, frame), dtype=float)
            if dep.task.type == "regression":
                clip = dep.task.raw.get("clip") or {}
                lo = -np.inf if clip.get("min") is None else float(clip["min"])
                hi = np.inf if clip.get("max") is None else float(clip["max"])
                q = (ld.lock.get("interval") or {}).get("q")
                intervals[short] = None if q is None else (np.clip(vals - q, lo, hi), np.clip(vals + q, lo, hi))
                vals = np.clip(vals, lo, hi)
            else:
                vals = np.clip(vals, 0.0, 1.0)
                intervals[short] = None
            preds[short] = vals
            env[short] = vals
        for k, v in fixed_num.items():
            env.setdefault(k, v)
        merged = self.catalog.merged
        for fname, module in (spec.task.raw.get("formulas") or {}).items():
            fn = load_formula(merged, module)
            rows = pd.DataFrame({k: (np.broadcast_to(v, (total,)) if np.ndim(v) else np.full(total, v))
                                 for k, v in env.items()})
            cat_cols = [c for c in allpts.columns if allpts[c].dtype == object]
            for c in cat_cols:
                rows[c] = allpts[c].to_numpy()
            vals = np.array([float(fn(r, params)) for r in rows.to_dict("records")], dtype=float)
            if not np.all(np.isfinite(vals)):
                raise ServeError("비용식이 유한한 값을 내지 않았습니다", {"rule": "formula_finite", "field": fname})
            preds[fname] = vals
            env[fname] = vals
        return {"env": env, "preds": preds, "intervals": intervals, "flags": flags}

    @staticmethod
    def _in_range(pts: pd.DataFrame, sp: SearchSpace, locks: list[dict]) -> float:
        """탐색점 중 모든 조절 변수가 모든 의존 모델의 학습 범위(p1~p99 · 본 범주) 안인 비율 — 1.0 이 아니면 결함."""
        if not len(pts):
            return 0.0
        ok = np.ones(len(pts), dtype=bool)
        for name, kind in sp.kinds.items():
            if kind != "control":
                continue
            for lk in locks:
                item = (lk.get("features") or {}).get(name)
                if item is None:
                    continue
                if "values" in item and item.get("p1") is None:
                    vals = set(item.get("values") or [])
                    if vals:
                        ok &= pts[name].isin(vals).to_numpy()
                elif item.get("p1") is not None:
                    x = pts[name].to_numpy(dtype=float)
                    ok &= (x >= item["p1"] - 1e-9) & (x <= item["p99"] + 1e-9)
        return round(float(ok.mean()), 6)

    def _record(self, spec, out: dict, req: OptimizeRequest, params: dict, *, caller: str, channel: str) -> None:
        """mlp_recommendation(needs_approval) + 승인 요청(kind=recommendation, action=apply) — 한 트랜잭션. 설비 · MES 쓰기 0."""
        rec = out["recommendation"]
        uses_versions = {u["task"]: u["version"] for u in out["uses"]}
        fixed_inputs = {"fixed": dict(req.fixed), "params": params, "current": req.current, "entity_id": req.entity_id}
        stored = {"candidates": rec["candidates"], "current": rec["current"], "strategy": rec["strategy"],
                  "n_candidates": rec["n_candidates"], "n_feasible": rec["n_feasible"],
                  "in_train_range_rate": rec["in_train_range_rate"], "objective": rec["objective"],
                  "status": out["status"], "warnings": out["warnings"], "channel": channel,
                  "request_approval": req.request_approval}
        evidence = {"rec_id": rec["rec_id"], "feasible": rec["feasible"], "best": rec["best"], "uses": out["uses"],
                    "objective": rec["objective"], "status": out["status"]}
        with connect() as c:
            c.execute("INSERT INTO mlp_recommendation (rec_id, tenant_id, task_id, fixed_inputs, candidates, uses_versions, "
                      "feasible, status, created_by) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,'needs_approval',%s)",
                      (rec["rec_id"], spec.tenant_id, spec.task.id, json.dumps(fixed_inputs, ensure_ascii=False, default=str),
                       json.dumps(stored, ensure_ascii=False), json.dumps(uses_versions), rec["feasible"], caller))
            approval_id = None
            if req.request_approval:
                approval_id = new_id("apr")
                c.execute("INSERT INTO mlp_approval (approval_id, tenant_id, task_id, kind, ref_id, action, approver_role, state, "
                          "requested_by, evidence, expires_at) VALUES (%s,%s,%s,'recommendation',%s,'apply',%s,'pending',%s,%s::jsonb, "
                          "now() + make_interval(secs => %s))",
                          (approval_id, spec.tenant_id, spec.task.id, rec["rec_id"], spec.task.raw["approver_role"], caller,
                           json.dumps(evidence, ensure_ascii=False), approval.ttl_hours("recommendation") * 3600))   # D-130
            audit.write(tenant_id=spec.tenant_id, actor=caller, role=None, action="recommendation.create",
                        target=f"{spec.task.id}@{rec['rec_id']}",
                        detail={"approval_id": approval_id, "feasible": rec["feasible"], "uses": uses_versions}, conn=c)
