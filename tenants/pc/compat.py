"""pc 호환 모양 플러그인 — 옛 경로 응답 키 (api-contract §5 · §6.3 · predict-contract §7.1). 소유 개발2.

원천 `../PyoungChang ML AI/api/{main,ml_service}.py` 를 **읽어** 옛 응답 모양만 옮겼다(원천 실행 0).
예측 · 대기열 · 기록은 표준 서비스 그대로다 — 원천의 표본 내 평가(전체 재적합 후 같은 데이터 채점, ml_service.py:78-79)는
가져오지 않는다. 옛 `/api/quality/overview` 의 우선순위 목록은 표준 대기열(시험 구간 · 운영 잔차 · 검증 분위 임계값)이다.
표준이 다르게 정해 내지 않는 키는 `tests/compat_expected.yaml pc.differs`.
"""

from __future__ import annotations

from typing import Any

from mlcore.serve.compat import CompatError

COMPOSITION = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]          # ml_service.py:21
WARN_BAND = (99.7, 100.3)                                                         # ml_service.py:84 (데모 경고 — 거부는 input_rules)
TEXT = {"review": "검토 필요", "ok": "예측 범위 양호",                              # ml_service.py:86
        "below": "예측 점수가 데모 검토 기준보다 낮아 관능·이화학 검사가 필요합니다.",     # ml_service.py:85
        "queue": "잔차 우선순위는 불량 판정이 아니라 데이터/모델 검토 순서입니다."}      # main.py:47
QUEUE_TOP = 8                                                                     # main.py:44 [:8]
NUMERIC = [*COMPOSITION, "brine_salinity_pct", "brining_hours", "fermentation_temp_c", "fermentation_hours",
           "storage_temp_c"]                                                       # ml_service.py:22 (settings 키 순서 :105)
OPT_PARAMS = {"target_score": (65, 95), "max_material_cost": (45, 100)}           # main.py:24 OptimizeInput
OPT_NOTICE = "데모 탐색 결과이며 승인 배합표 확인과 시험 생산 후 적용해야 합니다."           # ml_service.py:106
OPT_UNMET = {"target_score": "목표 품질점수 {target:.1f}점 미달",                     # ml_service.py:102
             "max_material_cost": "원재료비 지수 상한 초과"}                           # ml_service.py:103
RECORDS_LIMIT, RECORDS_SEARCH_MAX = 25, 30                                       # main.py:50-51
OLD_KEYS = ["lot_id", "produced_at", *COMPOSITION, "brine_salinity_pct", "brining_hours", "fermentation_temp_c",
            "fermentation_hours", "storage_temp_c", "cabbage_origin", "line", "sensory_score"]   # ml_service.py:50-53 열 순서


def _cfg(info: dict) -> dict:
    """같은 등록부 폴더의 `<code>.yaml` (회사 이름 · compat 값을 코드에 두지 않는다)."""
    from pathlib import Path

    import yaml
    p = Path(__file__).resolve().parent.parent / f"{info['tenant']}.yaml"
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _r(v, nd):
    return None if v is None else round(float(v), nd)


# ── health · overview ────────────────────────────────────────────────────────────────────
def shape_health(res: dict, info: dict) -> dict:
    mode = "demo" if res["data_mode"] in ("synthetic_demo", "demo") else res["data_mode"]
    return {"status": res["status"], "model_ready": res["model_ready"], "data_mode": mode,
            "product": _cfg(info).get("name")}                                    # main.py:28


def shape_overview(o: dict, info: dict) -> dict:
    """main.py:30-34. metrics 키는 원천 이름(mae_score · rmse_score) · 원천 정렬(MAE ↑). limits(합성 생성 범위)는 내지 않는다(differs)."""
    cfg = _cfg(info)
    back = {v: k for k, v in ((cfg.get("compat") or {}).get("input_rename") or {}).items()}
    cats = [back.get(c, c) for c in (cfg.get("categories") or {})]
    return {"data_mode": "demo" if o["data_mode"] in ("synthetic_demo", "demo") else o["data_mode"], "rows": o["rows"],
            "missing_cells": o["missing_cells"], "duplicate_lots": o["duplicate_lots"],
            "features": list(o["features"]) + cats, "target": {"name": "sensory_score", "unit": "점"},
            "champion": o["champion"],
            "metrics": [{"model": m["model"], "r2": m["r2"], "mae_score": m["mae"], "rmse_score": m["rmse"]} for m in o["metrics"]],
            "warning": o["warning"]}


# ── 예측 ─────────────────────────────────────────────────────────────────────────────────
def parse_predict_one(old: Any, info: dict) -> Any:
    """옛 ProcessInput 그대로(표준 입력 변환 · 검증은 코어 — compat.input_rename · input_rules 배합 합 98~102 거부).
    원천의 배합 합 경고(99.7~100.3, 거부 아님)는 문구라 여기서 합을 기억해 두고 shape 에서 원천 문구로 낸다."""
    if isinstance(old, dict):
        vals = [old.get(k) for k in COMPOSITION]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            info["_recipe_total"] = float(sum(vals))
    return old


def shape_predict_one(out: dict, info: dict) -> dict:
    """ml_service.py:82-87 — prediction_score(소수 2) · status · warnings(문구) · model · notice."""
    warnings = []
    total = info.get("_recipe_total")
    if total is not None and not WARN_BAND[0] <= total <= WARN_BAND[1]:
        warnings.append(f"배합 합계가 {total:.2f}%입니다(데모 허용 99.7~100.3%).")
    for w in out["warnings"]:
        if w["code"] == "synthetic_model":                  # 합성 배지(옛 응답에 없다 — notice 로 알린다)
            continue
        text = TEXT["below"] if w["code"] == "threshold_exceeded" else w["message"]
        if text not in warnings:
            warnings.append(text)
    return {"prediction_score": _r((out["prediction"] or {}).get("value"), 2),
            "status": TEXT["review"] if warnings else TEXT["ok"], "warnings": warnings,
            "model": out["model"]["name"], "notice": out["notice"]}


# ── 잔차 검토 ────────────────────────────────────────────────────────────────────────────
def shape_review_list(out: dict, info: dict) -> dict:
    """main.py:42-47 의 모양 — 내용은 표준 대기열(열린 항목, |잔차| ↓ 상위 8). 임계값 = 대기열 항목 임계값(검증 구간 분위)."""
    prefix = (_cfg(info).get("compat") or {}).get("entity_prefix") or ""
    items = sorted(out["items"], key=lambda i: (-abs(float(i["residual"])), i["item_id"]))[:QUEUE_TOP]

    def lot(e: str) -> str:                       # 표준 records 와 같은 LOT 번호 규칙(serve/compat Compat.lot_id)
        if not prefix or e.startswith(prefix):
            return e
        for i in range(len(prefix)):
            if e.startswith(prefix[i:]):
                return prefix + e[len(prefix) - i:]
        return prefix + e

    thr = next((i["threshold"] for i in out["items"] if i.get("threshold") is not None), None)
    return {"residual_review_threshold": _r(thr, 2),
            "priority_queue": [{"lot_id": lot(str(i["entity_id"])), "measured_score": _r(i["actual"], 2),
                                "predicted_score": _r(i["predicted"], 2), "residual_score": _r(abs(float(i["residual"])), 2)}
                               for i in items],
            "notice": TEXT["queue"]}


# ── 기록 ─────────────────────────────────────────────────────────────────────────────────
def shape_records(out: dict, info: dict) -> dict:
    """main.py:49-59 — {total, limit, offset, records}. 행 키는 원천 열 순서(lot_id · produced_at · 변수 · 목표)."""
    rows = []
    for r in out["records"]:
        row = {**r, "produced_at": r.get("recorded_at")}
        rows.append({k: row.get(k) for k in OLD_KEYS})
    return {"total": out["total"], "limit": out["limit"], "offset": out["offset"], "records": rows}


# ── 최적화 ───────────────────────────────────────────────────────────────────────────────
def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _e(field: str, msg: str, typ: str) -> CompatError:
    return CompatError(422, {"detail": [{"loc": ["body", field], "msg": msg, "type": typ}]})


def parse_optimize(old: Any, info: dict) -> dict:
    """옛 OptimizeInput(main.py:23-25) — 목표 점수 · 원재료비 상한(필수) + 산지 · 라인(기본 = 회사 범주 첫 값 = 원천 기본
    평창 · K1). 현재 배합은 받지 않는다 → 표준 본문 `{fixed, params}`(현재값 없는 최적화, D2-A2-02). 모르는 키는 무시(원천 그대로)."""
    if not isinstance(old, dict):
        raise CompatError(422, {"detail": [{"loc": ["body"], "msg": "객체여야 합니다", "type": "model_attributes_type"}]})
    params = {}
    for k, (lo, hi) in OPT_PARAMS.items():
        v = old.get(k)
        if v is None:
            raise _e(k, "필수 항목입니다", "missing")
        if not _num(v):
            raise _e(k, "숫자여야 합니다", "float_parsing")
        if not lo <= v <= hi:
            raise _e(k, f"{lo} 이상 {hi} 이하", "greater_than_equal" if v < lo else "less_than_equal")
        params[k] = v
    cats = _cfg(info).get("categories") or {}
    back = {v: k for k, v in ((_cfg(info).get("compat") or {}).get("input_rename") or {}).items()}
    fixed = {}
    for var, allowed in cats.items():
        old_key = back.get(var, var)
        v = old.get(old_key, allowed[0] if allowed else None)
        if v not in allowed:
            raise _e(old_key, "허용된 값이 아닙니다", "literal_error")
        fixed[old_key] = v
    info["_opt"] = {"target": float(params["target_score"]), "context": dict(fixed)}
    return {"fixed": fixed, "params": params}


def shape_optimize(out: dict, info: dict) -> dict:
    """ml_service.py:104-106 — feasible · prediction_score · material_cost_index(소수 2) · settings(공정 9, 소수 3) · context ·
    unmet_constraints(원천 문구) · model(운영 모델 후보 코드) · notice. 추천 1개(표준 상위 5 중 best)."""
    from mlcore.registry.models import Registry
    rec = out["recommendation"]
    best = rec["best"]
    cond, pred = best["conditions"], best["predictions"]
    score_name = rec["objective"]["tiebreak"][0]["name"]
    opt = info.get("_opt") or {}
    unmet = [OPT_UNMET[c["name"]].format(target=opt.get("target", 0.0)) for c in best["constraints"]
             if not c["satisfied"] and c["name"] in OPT_UNMET]
    uses = out.get("uses") or []
    model = Registry().get(info["tenant"], uses[0]["task"]).algo if uses else None
    return {"feasible": rec["feasible"], "prediction_score": _r(pred.get(score_name), 2),
            "material_cost_index": _r(pred.get(rec["objective"]["name"]), 2),
            "settings": {k: _r(cond.get(k), 3) for k in NUMERIC}, "context": opt.get("context"),
            "unmet_constraints": unmet, "model": model, "notice": OPT_NOTICE}


def parse_records(query: dict, info: dict) -> dict:
    """옛 records 쿼리(main.py:50-51) — 기본 limit 25 · search 30자. line · cabbage_origin 필터는 표준 범주 거르개(옛 키 이름)."""
    q = dict(query)
    q.setdefault("limit", str(RECORDS_LIMIT))
    if len(q.get("search") or "") > RECORDS_SEARCH_MAX:
        raise CompatError(422, {"detail": [{"loc": ["query", "search"], "msg": f"{RECORDS_SEARCH_MAX}자 이하",
                                            "type": "string_too_long"}]})
    return q
