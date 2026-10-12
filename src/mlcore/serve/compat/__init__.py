"""호환 라우터 — 옛 회사 경로 · 옛 응답 키 (spec §15 M4 · D-18 · contracts/predict-contract.md §7 · api-contract.md §5). 소유 개발2.

코어는 회사 · 팩 이름을 모른다. 옛 경로 목록 · 옛 요청 키 이름 · 상태 문구 · 반올림 자리 · 장비 대응은 전부
`tenants/<code>.yaml: compat` 에서, 옛 출력 키 이름은 과제 정의(`target.name`)에서 온다(spec §7 — "기존 출력 키는
prediction.value + 과제 target.name 으로 대신한다").

| 옛 경로 꼴(compat.routes)   | 표준 호출 |
|---|---|
| `…/predict` (POST)          | 켜진 regression · risk · anomaly 과제 predict 3회 → 옛 묶음 키 |
| `…/optimize` (POST)         | 켜진 optimize 과제 1개 |
| `…/overview` (GET)          | 묶음 과제들의 production 학습 보고서 |
| `…/records` · `…/records/{id}` (GET) | 묶음 과제 production 스냅숏 행(표준 records — 개발3 B12 가 생기면 그것으로 바꾼다) |
| `/api/health` 꼴(`…/health`, GET) | 등록부 production 여부 |

옛 422 모양 `{"detail": [{loc, msg, type}]}` 를 재현한다. 입력값은 되풀이하지 않는다(loc · type · 표준 메시지만).
옛 서비스와 달리 **API 키가 필요하다**(역할 판정은 표준과 같다 — decisions D-59). 운영 모델이 없으면 503 — 지어내지 않는다.
"""

from __future__ import annotations

import json
import math
from typing import Any

from ...registry.artifacts import load_artifacts
from ...registry.models import ModelNotReady, Registry
from ..errors import ServeError
from ..predict import PredictRequest, Predictor

BUNDLE_TYPES = ("regression", "risk", "anomaly")
DEFAULT_ROUND = {"risk": 4}          # 두 원천 모두 위험 확률 4자리 — 그 밖은 compat.round 가 정한다(없으면 반올림하지 않는다)


class CompatError(Exception):
    """옛 모양 오류 — status · body 를 그대로 돌려준다."""

    def __init__(self, status: int, body: Any):
        super().__init__(str(status))
        self.status, self.body = status, body


def _no_nan(x: str):
    raise ValueError("NaN · Infinity 는 허용하지 않습니다")


def parse_body(raw: bytes) -> Any:
    try:
        return json.loads(raw or b"null", parse_constant=_no_nan)
    except ValueError:
        raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "JSON 형식이 아니거나 NaN · Infinity 가 있습니다",
                                            "type": "json_invalid"}]}) from None


def old_422(e: ServeError, rename_back: dict[str, str], prefix: tuple = ("body",)) -> CompatError:
    field = (e.detail or {}).get("field")
    loc = list(prefix) + ([rename_back.get(field, field)] if field else [])
    return CompatError(422, {"detail": [{"loc": loc, "msg": e.message, "type": e.code}]})


class Compat:
    """한 회사의 호환 응답. catalog = serve.catalog.TaskCatalog(병합 등록부)."""

    def __init__(self, catalog: Any, registry: Registry | None = None):
        self.catalog = catalog
        self.merged = catalog.merged
        self.cfg = self.merged.tenant.config.get("compat") or {}
        self.registry = registry or Registry()
        self.rename = dict(self.cfg.get("input_rename") or {})               # 옛 키 → 팩 변수
        self.back = {v: k for k, v in self.rename.items()}                    # 팩 변수 → 옛 키
        self.round = dict(self.cfg.get("round") or {})                        # 옛 출력 키 → 소수 자리
        self.status_text = dict(self.cfg.get("status_text") or {})
        specs = [catalog.get(catalog.tenant_id, t) for t in catalog.ids()]
        self.bundle = {}
        for ttype in BUNDLE_TYPES:
            s = next((x for x in specs if x.task.type == ttype), None)
            if s is not None:
                self.bundle[ttype] = s
        self.optimizer_spec = next((x for x in specs if x.task.type == "optimize"), None)

    # ── 경로 ─────────────────────────────────────────────────────────────
    def routes(self) -> list[str]:
        return list(self.cfg.get("routes") or [])

    def resolve(self, method: str, path: str) -> tuple[str, str | None] | None:
        """(동작, 경로 인자) — compat.routes 에 있는 것만."""
        for r in self.routes():
            if path == r:
                for suffix, (m, action) in {"/predict": ("POST", "predict"), "/optimize": ("POST", "optimize"),
                                            "/overview": ("GET", "overview"), "/records": ("GET", "records"),
                                            "/health": ("GET", "health")}.items():
                    if r.endswith(suffix) and method == m:
                        return action, None
            if r.endswith("/records") and path.startswith(r + "/") and method == "GET":
                rest = path[len(r) + 1:]
                if rest and "/" not in rest:
                    return "record", rest
        return None

    # ── 공통 ─────────────────────────────────────────────────────────────
    def _round(self, key: str, ttype: str, v: float | None) -> float | None:
        if v is None:
            return None
        nd = self.round.get(key, DEFAULT_ROUND.get(ttype))
        return float(round(v, nd)) if nd is not None else float(v)

    def _target_key(self, spec) -> str:
        return (spec.task.raw.get("target") or {}).get("name") or spec.task.id.split(".", 1)[1]

    def _features(self, spec) -> list:
        return list(spec.defs)

    def _to_inputs(self, body: Any, spec, *, prefix: tuple = ("body",)) -> dict:
        """옛 요청 → 팩 변수 inputs. 옛 모델처럼 키는 전부 있어야 하고(값 null 허용) 모르는 키는 거부."""
        if not isinstance(body, dict):
            raise CompatError(422, {"detail": [{"loc": list(prefix), "msg": "객체여야 합니다", "type": "model_attributes_type"}]})
        names = [f.name for f in self._features(spec)]
        old_names = [self.back.get(n, n) for n in names]
        errs = [{"loc": list(prefix) + [k if isinstance(k, str) and k.isidentifier() else "?"], "msg": "알 수 없는 입력입니다",
                 "type": "extra_forbidden"} for k in body if k not in old_names]
        errs += [{"loc": list(prefix) + [k], "msg": "필수 항목입니다", "type": "missing"} for k in old_names if k not in body]
        if errs:
            raise CompatError(422, {"detail": errs})
        return {self.rename.get(k, k): v for k, v in body.items()}

    def _need(self, ttype: str):
        s = self.bundle.get(ttype)
        if s is None:
            raise CompatError(404, {"detail": "이 회사에는 해당 과제가 켜져 있지 않습니다"})
        return s

    # ── 옛 묶음 예측 ──────────────────────────────────────────────────────
    def predict(self, body: Any, *, caller: str) -> dict:
        reg = self._need("regression")
        inputs = self._to_inputs(body, reg)
        outs = {}
        pred = Predictor(self.catalog, self.registry)
        for ttype, spec in self.bundle.items():
            sub = {f.name: inputs.get(f.name) for f in spec.defs}
            try:
                outs[ttype] = pred.predict(self.catalog.tenant_id, spec.task.id, PredictRequest(inputs=sub),
                                           caller=caller, channel="compat")
            except ServeError as e:
                if e.status == 422:
                    raise old_422(e, self.back) from None
                if e.status == 503:
                    raise CompatError(503, {"detail": e.message, "code": e.code}) from None
                raise
        return self.bundle_response(outs, inputs)

    def bundle_response(self, outs: dict[str, dict], inputs: dict) -> dict:
        reg, risk, ano = outs.get("regression"), outs.get("risk"), outs.get("anomaly")
        reg_spec = self.bundle["regression"]
        labels = {f.name: f.label for f in reg_spec.defs}
        msgs: list[str] = []
        imputed: list[str] = []
        for o in outs.values():
            for n in o["imputed_fields"]:
                lab = labels.get(n, n)
                if lab not in imputed:
                    imputed.append(lab)
        if imputed:
            msgs.append("학습 데이터 중앙값 대체: " + ", ".join(imputed))
        for o in outs.values():
            for w in o["warnings"]:
                if w["code"] in ("imputed", "synthetic_model"):      # 보정은 위 한 줄로, 합성은 배지(옛 응답에 없다)
                    continue
                text = w["message"] + (f" ({labels.get(w['field'], w['field'])})" if w["field"] else "")
                if text not in msgs:
                    msgs.append(text)
        key = self._target_key(reg_spec)
        out = {key: self._round(key, "regression", reg["prediction"]["value"]) if reg else None}
        out["risk_probability"] = self._round("risk_probability", "risk", risk["probability"]) if risk else None
        out["anomaly"] = bool(ano["anomaly"]["flag"]) if ano and ano["anomaly"]["flag"] is not None else False
        out["status"] = self.status_text.get("review", "review") if msgs else self.status_text.get("ok", "ok")
        out["warnings"] = msgs
        out["imputed_fields"] = imputed
        for ck, mapping in self.cfg.items():                       # equipment_by_<변수>: {값: [코드, 이름]}
            if ck.startswith("equipment_by_") and isinstance(mapping, dict):
                v = inputs.get(ck[len("equipment_by_"):])
                pair = mapping.get(v)
                out["equipment"] = (pair[1] if isinstance(pair, (list, tuple)) and len(pair) > 1 else pair) if pair else None
        out["model"] = reg["model"]["name"] if reg else None
        out["risk_model"] = risk["model"]["name"] if risk else None
        out["version"] = reg["model"]["version"] if reg else None
        out["notice"] = reg["notice"] if reg else next(iter(outs.values()))["notice"]
        return out

    # ── 옛 최적화 ─────────────────────────────────────────────────────────
    def optimize(self, body: Any, *, caller: str) -> dict:
        from ...tasks.optimize import OptimizeRequest, Optimizer
        spec = self.optimizer_spec
        if spec is None:
            raise CompatError(404, {"detail": "이 회사에는 최적화 과제가 켜져 있지 않습니다"})
        if not isinstance(body, dict) or not isinstance(body.get("record"), dict):
            raise CompatError(422, {"detail": [{"loc": ["body", "record"], "msg": "필수 항목입니다", "type": "missing"}]})
        task = spec.task.raw
        pnames = list((task.get("params") or {}))
        extra = [k for k in body if k != "record" and k not in pnames]
        missing = [k for k in pnames if k not in body]
        if extra or missing:
            raise CompatError(422, {"detail": [{"loc": ["body", k], "msg": "알 수 없는 입력입니다", "type": "extra_forbidden"} for k in extra]
                              + [{"loc": ["body", k], "msg": "필수 항목입니다", "type": "missing"} for k in missing]})
        reg = self._need("regression")
        inputs = self._to_inputs(body["record"], reg, prefix=("body", "record"))
        controls = list(task.get("controls") or [])
        fixed = {n: inputs.get(n) for n in task.get("fixed") or []}
        current = {n: inputs.get(n) for n in controls} if controls else None
        if current is not None and any(v is None for v in current.values()):
            missing = [self.back.get(n, n) for n, v in current.items() if v is None]
            raise CompatError(422, {"detail": [{"loc": ["body", "record", k], "msg": "조절 변수는 모두 입력해야 합니다",
                                                "type": "missing"} for k in missing]})
        params = {k: body[k] for k in pnames}
        old_pred = self.predict(body["record"], caller=caller)
        try:
            out = Optimizer(self.catalog, self.registry).optimize(
                self.catalog.tenant_id, spec.task.id, OptimizeRequest(fixed=fixed, current=current, params=params),
                caller=caller, channel="compat")
        except ServeError as e:
            if e.status == 422:
                raise old_422(e, self.back) from None
            if e.status == 503:
                raise CompatError(503, {"detail": e.message, "code": e.code}) from None
            raise
        rec = out["recommendation"]
        rename = dict(self.cfg.get("optimize_rename") or {})          # 표준 이름 → 옛 행 키 (회사 값)

        def row(c: dict) -> dict:
            r = {self.back.get(k, k): v for k, v in c["conditions"].items()}
            for k, v in c["predictions"].items():
                r[rename.get(k, k)] = v
            r["violation"] = c["violation"]
            return r

        unmet = [x["name"] for x in rec["best"]["constraints"] if not x["satisfied"]]
        tb = ", ".join(f"{t['name']} {'최소' if t['direction'] == 'minimize' else '최대'}" for t in rec["objective"]["tiebreak"])
        objective = (f"제약 충족 후보 중 {rec['objective']['name']} "
                     f"{'최소화' if rec['objective']['direction'] == 'minimize' else '최대화'}" + (f", 동률이면 {tb}" if tb else ""))
        res = {"feasible": rec["feasible"]}
        if current is not None:
            res["current"] = old_pred
            res["current_cost_index"] = rec["current"]["objective_value"] if rec["current"] else None
        else:
            res["prediction"] = old_pred
        res.update({"candidate_count": rec["n_candidates"], "feasible_count": rec["n_feasible"],
                    "recommendation": row(rec["best"]), "alternatives": [row(c) for c in rec["candidates"]],
                    "unmet_constraints": unmet})
        if current is not None:
            res["warnings"] = [w["message"] for w in out["warnings"] if w["code"] != "synthetic_model"]
        res.update({"objective": objective, "notice": out["notice"]})
        return res

    # ── 옛 개요 ───────────────────────────────────────────────────────────
    def _prod(self, ttype: str):
        spec = self.bundle.get(ttype)
        if spec is None:
            return None, None, None
        try:
            ref = self.registry.get(self.catalog.tenant_id, spec.task.id)
        except ModelNotReady:
            return spec, None, None
        return spec, ref, load_artifacts(ref)

    def overview(self) -> dict:
        rs, rref, rld = self._prod("regression")
        ks_, kref, kld = self._prod("risk")
        if rref is None:
            raise CompatError(503, {"detail": "운영(production) 모델이 없습니다", "code": "model_not_ready"})

        def table(ld, keys: tuple, sort_key: str) -> list[dict]:
            rows = [{"model": name, **{k: (None if v.get(k) is None or (isinstance(v.get(k), float) and math.isnan(v[k]))
                                          else round(float(v[k]), 3 if k in ("mae", "rmse") else 4)) for k in keys}}
                    for name, v in (ld.report.get("valid_metrics") or {}).items()]
            return sorted(rows, key=lambda r: (r[sort_key] if r[sort_key] is not None else math.inf, r["model"]))

        def test(ld, keys: tuple) -> dict:
            tm = ld.report.get("test_metrics") or {}
            return {k: round(float(tm[k]["value"]), 3 if k in ("mae", "rmse") else 4) for k in keys if k in tm}

        sizes = ((rld.report.get("split") or {}).get("boundaries") or {}).get("sizes") or {}
        snap = rld.report.get("snapshot") or {}
        out = {"data_mode": "synthetic_demo" if rref.synthetic else self.merged.tenant.config.get("mode"),
               "version": rref.version, "rows": snap.get("rows"),
               "champion": rref.algo, "risk_champion": kref.algo if kref else None,
               "metrics": table(rld, ("mae", "rmse", "r2"), "mae"),
               "risk_metrics": table(kld, ("roc_auc", "pr_auc", "brier"), "brier") if kld else [],
               "test_metrics": test(rld, ("mae", "rmse", "r2")),
               "risk_test_metrics": test(kld, ("roc_auc", "pr_auc", "brier")) if kld else {},
               "split": {"train": sizes.get("train"), "validation": sizes.get("valid"), "test": sizes.get("test"),
                         "method": "시간순 60/20/20 분할 · 검증셋 선정 후 학습+검증 재학습 · 최종 테스트 분리"
                         if (rld.report.get("split") or {}).get("policy") == "time_60_20_20"
                         else (rld.report.get("split") or {}).get("policy")},
               "features": {self.back.get(f.name, f.name): {"label": f.label, "unit": f.unit, "min": f.min, "max": f.max,
                                                            "default": f.default}
                            for f in rs.defs if f.dtype != "category"},
               "risk_threshold": (ks_.task.raw.get("thresholds") or {}).get("review_prob") if ks_ else None,
               "warning": "표준 ML 플랫폼 호환 응답입니다. 지표는 등록부 운영 모델의 학습 보고서(시험 1회)입니다."}
        return out

    # ── 옛 기록 목록 ──────────────────────────────────────────────────────
    def _frame(self):
        from ...data import snapshot
        import pandas as pd
        rs, rref, _ = self._prod("regression")
        if rref is None:
            raise CompatError(503, {"detail": "운영(production) 모델이 없습니다", "code": "model_not_ready"})
        base = snapshot.load(rref.snapshot_id)
        key = self._target_key(rs)
        df = pd.DataFrame({"lot_id": base["entity_id"].astype(str),
                           "recorded_at": pd.to_datetime(base["ts"]).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
                           .str.replace(r"(\+\d\d)(\d\d)$", r"\1:\2", regex=True)})
        for f in rs.defs:
            df[self.back.get(f.name, f.name)] = base[f.name].to_numpy()
        df[key] = base["target"].to_numpy()
        ks_, kref, _ = self._prod("risk")
        if kref is not None:
            other = snapshot.load(kref.snapshot_id)
            m = dict(zip(other["entity_id"].astype(str), other["target"]))
            df[self._target_key(ks_)] = df["lot_id"].map(m)
        return df

    @staticmethod
    def _json_rows(frame) -> list[dict]:
        return json.loads(frame.to_json(orient="records", force_ascii=False))

    def records(self, query: dict) -> dict:
        rs = self._need("regression")
        errs = []

        def intq(name, default, lo, hi):
            v = query.get(name)
            if v is None:
                return default
            try:
                x = int(v)
            except ValueError:
                errs.append({"loc": ["query", name], "msg": "정수여야 합니다", "type": "int_parsing"})
                return default
            if x < lo or (hi is not None and x > hi):
                errs.append({"loc": ["query", name], "msg": "범위 밖입니다", "type": "range"})
            return x

        limit = intq("limit", 15, 1, 100)
        offset = intq("offset", 0, 0, None)
        search = query.get("search", "")
        if len(search) > 60:
            errs.append({"loc": ["query", "search"], "msg": "60자 이하", "type": "string_too_long"})
        cats = {self.back.get(f.name, f.name): f for f in rs.defs if f.dtype == "category"}
        filters = {}
        for k, v in query.items():
            if k in ("limit", "offset", "search"):
                continue
            if k not in cats:
                continue                                            # 옛 서비스도 모르는 쿼리는 무시했다
            if cats[k].values and v not in cats[k].values:
                errs.append({"loc": ["query", k], "msg": "허용된 값이 아닙니다", "type": "literal_error"})
            filters[k] = v
        if errs:
            raise CompatError(422, {"detail": errs})
        df = self._frame()
        for k, v in filters.items():
            df = df[df[k] == v]
        if search:
            df = df[df["lot_id"].str.contains(search, case=False, regex=False)]
        df = df.sort_values(["recorded_at", "lot_id"], ascending=[False, True])
        return {"total": int(len(df)), "limit": limit, "offset": offset,
                "records": self._json_rows(df.iloc[offset:offset + limit])}

    def record(self, lot_id: str) -> dict:
        df = self._frame()
        row = df[df["lot_id"] == lot_id]
        if row.empty:
            raise CompatError(404, {"detail": "LOT를 찾을 수 없습니다"})
        return {"record": self._json_rows(row)[0], "source": "표준 ML 플랫폼 등록부 운영 모델의 학습 스냅숏"}

    # ── 옛 health ────────────────────────────────────────────────────────
    def health(self) -> dict:
        ready, version, synthetic = True, None, False
        for ttype, spec in self.bundle.items():
            try:
                ref = self.registry.get(self.catalog.tenant_id, spec.task.id)
                synthetic = synthetic or ref.synthetic
                if ttype == "regression":
                    version = ref.version
            except ModelNotReady:
                ready = False
        return {"status": "ok", "model_ready": ready,
                "data_mode": "synthetic_demo" if synthetic else self.merged.tenant.config.get("mode"), "version": version}
