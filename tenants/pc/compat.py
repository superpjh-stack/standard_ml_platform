"""pc 호환 모양 플러그인 — 옛 경로 응답 키 (api-contract §5 · §6.3 · predict-contract §7.1). 소유 개발2.

원천 `../PyoungChang ML AI/api/{main,ml_service}.py` 를 **읽어** 옛 응답 모양만 옮겼다(원천 실행 0).
예측 · 대기열 · 기록은 표준 서비스 그대로다 — 원천의 표본 내 평가(전체 재적합 후 같은 데이터 채점, ml_service.py:78-79)는
가져오지 않는다. 옛 `/api/quality/overview` 의 우선순위 목록은 표준 대기열(시험 구간 · 운영 잔차 · 검증 분위 임계값)이다.
표준이 다르게 정해 내지 않는 키는 `tests/compat_expected.yaml pc.differs`.
"""

from __future__ import annotations

from typing import Any

COMPOSITION = ["cabbage_pct", "radish_pct", "seasoning_pct", "salt_pct"]          # ml_service.py:21
WARN_BAND = (99.7, 100.3)                                                         # ml_service.py:84 (데모 경고 — 거부는 input_rules)
TEXT = {"review": "검토 필요", "ok": "예측 범위 양호",                              # ml_service.py:86
        "below": "예측 점수가 데모 검토 기준보다 낮아 관능·이화학 검사가 필요합니다.",     # ml_service.py:85
        "queue": "잔차 우선순위는 불량 판정이 아니라 데이터/모델 검토 순서입니다."}      # main.py:47
QUEUE_TOP = 8                                                                     # main.py:44 [:8]
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
