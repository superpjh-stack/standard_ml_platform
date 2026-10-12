"""견적식 — 소재 · 가공(공수) · 외주 · 가산 · 부가세 (task-contract §6.3 · progress-dev2 2차 §2.1.2 · source_inventory §11.6).

원천 `api/quote.py:5-23 calculate()` 를 **읽어** 이관했다(실행하지 않는다). 단계 · 반올림 순서는 원천 그대로(D2-07):

    mass      = Σ 개당중량 × 수량                         → 회귀 입력 total_mass_kg (prepare)
    hours     = 예측 공수, 소수 4자리                     (원천 round(…, 4))
    line      = 개당중량 × 수량 × kg 단가 × (1 + 손실률) × 대수, 원 단위
    material  = Σ line
    labor     = hours × 시간 단가 × 대수, 원 단위
    outsource = 외주비 × 대수, 원 단위
    markup    = (material + labor + outsource) × 가산율, 원 단위
    subtotal  = material + labor + outsource + markup ;  vat = subtotal × 부가세율, 원 단위 ;  total = subtotal + vat

표준은 **Decimal · ROUND_HALF_UP 만** 쓴다(float · round() 0 — gates/check_decimal.py). 원천은 float + Python round
(짝수 반올림)라 정확히 .5 로 떨어지는 단계에서 1원 다를 수 있다 — 그런 행은 D2-07a 사유로 대조표에 남긴다(허용폭 확대 없음).
단가 · 계수는 과제 `rates`(10진 문자열, 회사는 값만 덮어쓴다). 품목 kg 단가는 BOM 행 입력(`price_kg`)이다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

WON = Decimal("1")
HOURS = Decimal("0.0001")
WEIGHT = Decimal("0.0001")
TASK = "labor_hours"                      # uses 과제 짧은 이름 (predicted 키)


def _d(v) -> Decimal:
    """입력 값 → Decimal. 코어가 JSON 숫자를 Decimal 로 읽어 넘긴다 — float 가 오면 문자열을 거친다(이진 오차를 늘리지 않게)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool 은 금액 입력이 아니다")
    return Decimal(str(v))


def _won(v: Decimal) -> Decimal:
    return v.quantize(WON, rounding=ROUND_HALF_UP)


def prepare(inputs: dict, lines: list[dict]) -> dict:
    """예측 전 파생 입력 — BOM 총중량(대당) → 회귀 입력 total_mass_kg (원천 quote.py:6-8)."""
    mass = sum((_d(r["mass_kg"]) * _d(r["quantity"]) for r in lines), Decimal("0"))
    return {"total_mass_kg": mass}


def quote(inputs: dict, lines: list[dict], predicted: dict, rates: dict) -> dict:
    qty = _d(inputs["quantity"])
    hours = _d(predicted[TASK]).quantize(HOURS, rounding=ROUND_HALF_UP)
    scrap = Decimal("1") + _d(rates["scrap_rate"])
    out_lines = []
    for r in lines:
        weight = _d(r["mass_kg"]) * _d(r["quantity"])
        amount = _won(weight * _d(r["price_kg"]) * scrap * qty)
        out_lines.append({"name": str(r["name"]), "material": r.get("material"), "quantity": r["quantity"],
                          "mass_kg": r["mass_kg"], "price_kg": r["price_kg"],
                          "weight_total": weight.quantize(WEIGHT, rounding=ROUND_HALF_UP), "amount": amount})
    material = sum((ln["amount"] for ln in out_lines), Decimal("0"))
    labor_rate = _d(inputs["labor_rate"]) if inputs.get("labor_rate") is not None else _d(rates["labor_per_hour"])
    labor = _won(hours * labor_rate * qty)
    outsource = _won(_d(inputs.get("outsource_cost", 0)) * qty)
    markup = _won((material + labor + outsource) * _d(rates["markup"]))
    subtotal = material + labor + outsource + markup
    vat = _won(subtotal * _d(rates["vat_rate"]))
    costs = {"material": material, "labor": labor, "outsource": outsource, "markup": markup, "subtotal": subtotal, "vat": vat}
    return {"lines": out_lines, "costs": costs, "total": subtotal + vat, "predicted": {TASK: hours}}
