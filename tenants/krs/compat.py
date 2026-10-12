"""krs 호환 모양 플러그인 — 옛 경로 응답 키 · 공급사 옛 표기 (api-contract §5 · §6.3 · predict-contract §7.1). 소유 개발2.

원천 `../Koreal Solder ML AI/api/{main,ml_service}.py` 를 **읽어** 옛 응답 모양만 옮겼다(원천 실행 0).
예측 · 대기열 · 표본은 표준 서비스 그대로다 — 원천의 분할 전 IQR · 시험 구간 선정 · 정제 전체 재채점 대시보드
(ml_service.py:59-73 · :96-117 · :169-195)는 가져오지 않는다. 옛 `/api/quality/overview` 는 표준 대기열(|잔차| ≥ 4 MPa,
시험 구간 · 실측이 붙은 운영 잔차)이다. 공급사 옛 값 A · B · C ↔ 회사 범주 값(등록부 categories.supplier, 같은 순서 — D2-61).
"""

from __future__ import annotations

from typing import Any

from mlcore.serve.compat import CompatError

OLD_SUPPLIERS = ["A", "B", "C"]                                                  # ml_service.py:40 · main.py:22,33
COMPOSITION = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct"]               # main.py:70
OLD_FEATURES = ["sn_pct", "ag_pct", "cu_pct", "sb_pct", "flux_pct", "temperature_c", "mixing_min", "supplier"]   # ml_service.py:20
TARGET = "joint_strength_mpa"                                                    # ml_service.py:22
RECOMMENDED = {"temperature_c": (232, 260, "권장 용탕 온도(232~260°C)를 벗어났습니다."),     # ml_service.py:154-155
               "mixing_min": (35, 75, "권장 혼합 시간(35~75분)을 벗어났습니다.")}            # ml_service.py:156-157
LOW_TEXT = "예측 접합강도가 내부 검토 기준 35 MPa보다 낮습니다."                            # ml_service.py:158-159
STATUS = {"warn": "주의", "ok": "정상"}                                            # ml_service.py:163 · :174
PREDICT_NOTICE = "데모 모델 예측이며 출하 승인이나 품질 판정을 대체하지 않습니다."            # ml_service.py:165
QUEUE_NOTICE = "실측값과 모델 예측의 절대 오차가 4 MPa 이상인 LOT을 주의로 표시합니다."       # ml_service.py:194
DATA_MODE = "재현 가능한 데모 샘플"                                                 # main.py:44
NUMERIC = OLD_FEATURES[:-1]                                                      # ml_service.py:21
LIMITS = {"sn_pct": (93.0, 99.2), "ag_pct": (0.3, 4.2), "cu_pct": (0.1, 1.2), "sb_pct": (0.0, 2.0),     # ml_service.py:23-27
          "flux_pct": (0.05, 0.8), "temperature_c": (225.0, 270.0), "mixing_min": (20.0, 90.0)}       # (데이터 상태 판정 범위)
STATES = {"normal": "정상", "missing": "결측", "outlier": "이상"}                   # ml_service.py:207 · main.py:80
RECORDS_LIMIT, Q_MAX = 20, 40                                                    # main.py:78-79
OPT_DEFAULTS = {"target_strength": 48, "max_cost": None, "supplier": "A"}        # main.py:19-22 OptimizeRequest
OPT_RANGE = {"target_strength": (30, 70), "max_cost": (0, 200)}                  # main.py:20-21
OPT_NOTICE = "샘플 데이터 기반 추천입니다. 현장 적용 전 품질 승인과 시험 생산이 필요합니다."   # ml_service.py:145


def _cfg(info: dict) -> dict:
    from pathlib import Path

    import yaml
    p = Path(__file__).resolve().parent.parent / f"{info['tenant']}.yaml"
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _suppliers(info: dict) -> tuple[dict, dict]:
    """(옛 → 표준, 표준 → 옛) — 회사 범주 목록의 순서가 원천 A · B · C 순서다."""
    std = list((_cfg(info).get("categories") or {}).get("supplier") or [])
    fwd = dict(zip(OLD_SUPPLIERS, std))
    return fwd, {v: k for k, v in fwd.items()}


def _r(v, nd):
    return None if v is None else round(float(v), nd)


def shape_health(res: dict, info: dict) -> dict:
    return {"status": res["status"], "model_ready": res["model_ready"]}           # main.py:38


def shape_overview(o: dict, info: dict) -> dict:
    """main.py:44 · ml_service.py:121 — quality · models(RMSE ↑) · champion. 정제 통계(statistics · 이상치 행 수)는
    원천이 분할 전 전체로 쟀다 — 표준은 학습 구간 IQR 이라 내지 않는다(differs)."""
    models = sorted(({"name": m["model"], "r2": m["r2"], "mae": m["mae"], "rmse": m["rmse"]} for m in o["metrics"]),
                    key=lambda m: (m["rmse"] if m["rmse"] is not None else float("inf"), m["name"]))
    return {"quality": {"source_rows": o["rows"], "missing_cells": o["missing_cells"]}, "models": models,
            "champion": o["champion"], "features": OLD_FEATURES, "target": TARGET, "data_mode": DATA_MODE}


def shape_samples(out: dict, info: dict) -> dict:
    """main.py:47-51 — {total, items}. 공급사는 옛 표기."""
    _, back = _suppliers(info)
    items = []
    for r in out["items"]:
        row = {"lot_id": r.get("lot_id"), **{k: r.get(k) for k in OLD_FEATURES}, TARGET: r.get(TARGET)}
        row["supplier"] = back.get(row["supplier"], row["supplier"])
        items.append(row)
    return {"total": out["total"], "items": items}


def parse_predict_one(old: Any, info: dict) -> Any:
    """옛 QualityPredictRequest(main.py:25-33): supplier 기본 "A" · 옛 표기 → 회사 범주 값. 권장 범위 경고는 원천 문구라
    입력을 기억해 shape 에서 낸다(거부 아님). 조성 합 ±0.1 거부는 표준 input_rules(422)."""
    if not isinstance(old, dict):
        return old
    fwd, _ = _suppliers(info)
    body = {**old}
    sup = body.get("supplier", "A")
    if sup not in fwd:
        raise CompatError(422, {"detail": [{"loc": ["body", "supplier"], "msg": "A · B · C 중 하나입니다", "type": "literal_error"}]})
    body["supplier"] = fwd[sup]
    info["_old_inputs"] = {k: body.get(k) for k in RECOMMENDED}
    return body


def shape_predict_one(out: dict, info: dict) -> dict:
    """ml_service.py:160-166 — model · predicted_strength(소수 2) · status(주의 · 정상) · warnings(문구) · notice."""
    warnings = []
    for k, (lo, hi, text) in RECOMMENDED.items():
        v = (info.get("_old_inputs") or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not lo <= float(v) <= hi:
            warnings.append(text)
    for w in out["warnings"]:
        if w["code"] == "synthetic_model":
            continue
        text = LOW_TEXT if w["code"] == "threshold_exceeded" else w["message"]
        if text not in warnings:
            warnings.append(text)
    return {"model": out["model"]["name"], "predicted_strength": _r((out["prediction"] or {}).get("value"), 2),
            "status": STATUS["warn"] if warnings else STATUS["ok"], "warnings": warnings, "notice": PREDICT_NOTICE}


def shape_review_list(out: dict, info: dict) -> dict:
    """main.py:62-64 · ml_service.py:169-195 의 모양 — 내용은 표준 대기열(열린 항목, |잔차| ↓, limit). 평가 행 수 ·
    정상 LOT 수 · 평균 절대오차(정제 전체 표본 내 채점) · 모델 이름과 행의 공급사 · 공정값은 내지 않는다(differs)."""
    prefix = (_cfg(info).get("compat") or {}).get("entity_prefix") or ""

    def lot(e: str) -> str:                        # 표준 records 와 같은 LOT 번호 규칙(serve/compat Compat.lot_id)
        if not prefix or e.startswith(prefix):
            return e
        for i in range(len(prefix)):
            if e.startswith(prefix[i:]):
                return prefix + e[len(prefix) - i:]
        return prefix + e

    items = sorted(out["items"], key=lambda i: (-abs(float(i["residual"])), i["item_id"]))
    return {"flagged_lots": out["total"],
            "review_threshold": (out.get("rule") or {}).get("abs_residual_ge"),
            "flagged": [{"lot_id": lot(str(i["entity_id"])), "actual_strength": _r(i["actual"], 2),
                         "predicted_strength": _r(i["predicted"], 2), "absolute_error": _r(abs(float(i["residual"])), 2),
                         "status": STATUS["warn"]} for i in items],
            "notice": QUEUE_NOTICE}


def shape_records(out: dict, info: dict) -> dict:
    """main.py:76-82 · ml_service.py:198-229 — {total, offset, limit, items, summary}. 공급사는 옛 표기 · 행 상태 열 포함."""
    _, back = _suppliers(info)
    items = []
    for r in out["records"]:
        row = {"lot_id": r.get("lot_id"), **{k: r.get(k) for k in OLD_FEATURES}, TARGET: r.get(TARGET),
               "missing_fields": r.get("missing_fields"), "data_status": r.get("data_status")}
        row["supplier"] = back.get(row["supplier"], row["supplier"])
        items.append(row)
    return {"total": out["total"], "offset": out["offset"], "limit": out["limit"], "items": items,
            "summary": info.get("_summary")}


# ── 최적화 ───────────────────────────────────────────────────────────────────────────────
def _e(field: str, msg: str, typ: str) -> CompatError:
    return CompatError(422, {"detail": [{"loc": ["body", field], "msg": msg, "type": typ}]})


def parse_optimize(old: Any, info: dict) -> dict:
    """옛 OptimizeRequest(main.py:19-22) — 목표 강도(기본 48, 30~70) · 비용 상한(선택, 0~200) · 공급사(기본 A). 현재 배합은 받지
    않는다 → 표준 본문 `{fixed, params}`(현재값 없는 최적화, D2-A2-02). 모르는 키는 무시(원천 그대로)."""
    if not isinstance(old, dict):
        raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "객체여야 합니다", "type": "model_attributes_type"}]})
    vals = {k: old.get(k, d) for k, d in OPT_DEFAULTS.items()}
    for k, (lo, hi) in OPT_RANGE.items():
        v = vals[k]
        if v is None and k == "max_cost":
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _e(k, "숫자여야 합니다", "float_parsing")
        if not lo <= v <= hi:
            raise _e(k, f"{lo} 이상 {hi} 이하", "greater_than_equal" if v < lo else "less_than_equal")
    fwd, _ = _suppliers(info)
    if vals["supplier"] not in fwd:
        raise _e("supplier", "A · B · C 중 하나입니다", "literal_error")
    info["_opt"] = {"target": float(vals["target_strength"]), "supplier": vals["supplier"]}
    params = {"target_strength": vals["target_strength"]}
    if vals["max_cost"] is not None:
        params["max_cost"] = vals["max_cost"]
    return {"fixed": {"supplier": fwd[vals["supplier"]]}, "params": params}


def shape_optimize(out: dict, info: dict) -> dict:
    """ml_service.py:139-146 — feasible · model · target_strength · predicted_strength · cost_index(소수 2) · composition(소수 3) ·
    process(온도 · 혼합 소수 1 · 공급사 옛 표기) · notice. 추천 1개(표준 상위 5 중 best)."""
    from mlcore.registry.models import Registry
    rec = out["recommendation"]
    cond, pred = rec["best"]["conditions"], rec["best"]["predictions"]
    opt = info.get("_opt") or {}
    uses = out.get("uses") or []
    model = Registry().get(info["tenant"], uses[0]["task"]).algo if uses else None
    return {"feasible": rec["feasible"], "model": model, "target_strength": opt.get("target"),
            "predicted_strength": _r(pred.get(rec["objective"]["tiebreak"][0]["name"]), 2),
            "cost_index": _r(pred.get(rec["objective"]["name"]), 2),
            "composition": {k: _r(cond.get(k), 3) for k in COMPOSITION},
            "process": {"temperature_c": _r(cond.get("temperature_c"), 1), "mixing_min": _r(cond.get("mixing_min"), 1),
                        "supplier": opt.get("supplier")},
            "notice": OPT_NOTICE}


# ── 기록 필터 ───────────────────────────────────────────────────────────────────────────
def _q422(field: str, msg: str, typ: str) -> CompatError:
    return CompatError(422, {"detail": [{"loc": ["query", field], "msg": msg, "type": typ}]})


def parse_records(query: dict, info: dict) -> dict:
    """옛 records 쿼리(main.py:76-82) → 표준 쿼리: 기본 limit 20 · `q`(LOT 검색, 40자, 앞뒤 공백 제거) → search ·
    `supplier`(A · B · C) → 회사 범주 값 · `state`(정상 · 결측 · 이상)는 records_frame 이 거른다. 옛 서비스에 없는 search 는 버린다."""
    q = {k: v for k, v in query.items() if k not in ("search", "q", "state", "supplier")}
    q.setdefault("limit", str(RECORDS_LIMIT))
    text = (query.get("q") or "").strip()
    if len(query.get("q") or "") > Q_MAX:
        raise _q422("q", f"{Q_MAX}자 이하", "string_too_long")
    if text:
        q["search"] = text
    if "supplier" in query:
        fwd, _ = _suppliers(info)
        if query["supplier"] not in fwd:
            raise _q422("supplier", "A · B · C 중 하나입니다", "literal_error")
        q["supplier"] = fwd[query["supplier"]]
    state = query.get("state")
    if state is not None and state not in STATES.values():
        raise _q422("state", "정상 · 결측 · 이상 중 하나입니다", "literal_error")
    info["_state"] = state
    return q


def records_frame(df, n_all: int, info: dict):
    """ml_service.py:198-229 — 행 상태(결측 칸 수 · 범위 밖 = 이상) · state 필터 · summary(전체 · 정상 · 결측 · 이상)."""
    import numpy as np
    import pandas as pd
    df = df.copy()
    missing = df[[c for c in OLD_FEATURES if c in df.columns]].isna().sum(axis=1)
    outlier = pd.Series(False, index=df.index)
    for col in NUMERIC:
        lo, hi = LIMITS[col]
        x = pd.to_numeric(df[col], errors="coerce")
        outlier |= ((x < lo) | (x > hi)).fillna(False)
    df["missing_fields"] = missing.astype(int)
    df["data_status"] = np.select([missing > 0, outlier], [STATES["missing"], STATES["outlier"]], default=STATES["normal"])
    if info.get("_state"):
        df = df[df["data_status"] == info["_state"]]
    info["_summary"] = {"all": int(n_all), **{k: int((df["data_status"] == v).sum()) for k, v in STATES.items()}}
    return df
