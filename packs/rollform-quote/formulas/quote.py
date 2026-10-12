"""견적식 — 전개 소재 · 가공(개당 분) · 준비 · 가산 · 부가세 (task-contract §6.3 · source_inventory §10.6 · D2-07 · D2-07a).

원천 `api/quote.py:6-35 calculate()` 를 **읽어** 이관했다(실행하지 않는다). 단계 · 반올림 순서는 원천 그대로(D2-07):

    minutes    = 예측 개당 가공 분, 소수 4자리                         (원천 round(predict_time, 4))
    weight     = 길이 × 전개 폭 × 두께 / 10⁹ × 밀도(재질)              (개당 kg — 홀 · 슬롯 스크랩은 빼지 않는다)
    material   = weight × kg 단가(재질) × (1 + 손실률) × 수량, 원 단위
    processing = minutes × 분당 기계 단가 × 수량, 원 단위
    setup      = 준비 분 × 분당 기계 단가, 원 단위                      (주문당 1회)
    base       = material + processing + setup ;  markup = base × 가산율, 원 단위
    subtotal   = base + markup ;  vat = subtotal × 부가세율, 원 단위 ;  total = subtotal + vat
    unit_price = subtotal / 수량, 소수 2자리                            (원천은 float round — 원천 결함 O2, 표준은 Decimal)

표준은 **Decimal · ROUND_HALF_UP 만** 쓴다(float · round() 0 — gates/check_decimal.py). 원천은 float 곱을 `Decimal(str(x))` 로
바꿔 HALF_UP 하므로, float 곱의 이진 오차가 .5 경계를 넘는 행에서만 1원 다를 수 있다 — 그런 행은 D2-07a 사유로 대조표에 남긴다
(허용폭 확대 없음). 단가 · 계수는 과제 `rates`(10진 문자열). 재질별 밀도 · kg 단가는 단가표(`rate_tables`) — `rates["density"]` ·
`rates["price_kg"]` 가 `{재질: Decimal}` 로 온다(칸은 회사 등록부, 팩은 빈 표).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

WON = Decimal("1")
MINUTES = Decimal("0.0001")
WEIGHT = Decimal("0.0001")
CENTS = Decimal("0.01")
MM3_PER_M3 = Decimal("1000000000")
TASK = "machining_minutes"                 # uses 과제 짧은 이름 (predicted 키)


def _d(v) -> Decimal:
    """입력 값 → Decimal. 코어가 JSON 숫자를 Decimal 로 읽어 넘긴다 — 그 밖의 수는 문자열을 거친다(이진 오차를 늘리지 않게)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool 은 금액 입력이 아니다")
    return Decimal(str(v))


def _won(v: Decimal) -> Decimal:
    return v.quantize(WON, rounding=ROUND_HALF_UP)


def _table(rates: dict, name: str, key: str) -> Decimal:
    table = rates[name]
    if not isinstance(table, dict) or key not in table:
        raise KeyError(f"단가표 {name} 에 {key!r} 칸이 없습니다")
    return _d(table[key])


def quote(inputs: dict, lines: list[dict], predicted: dict, rates: dict) -> dict:
    qty = _d(inputs["quantity"])
    if qty <= 0:
        raise ValueError("quantity 는 0보다 커야 합니다")
    grade = str(inputs["steel_grade"])
    minutes = _d(predicted[TASK]).quantize(MINUTES, rounding=ROUND_HALF_UP)
    per_min = _d(rates["machine_per_min"])
    weight = (_d(inputs["part_length_mm"]) * _d(inputs["blank_width_mm"]) * _d(inputs["sheet_thickness_mm"])
              / MM3_PER_M3 * _table(rates, "density", grade))
    material = _won(weight * _table(rates, "price_kg", grade) * (Decimal("1") + _d(rates["scrap_rate"])) * qty)
    processing = _won(minutes * per_min * qty)
    setup = _won(_d(rates["setup_minutes"]) * per_min)
    base = material + processing + setup
    markup = _won(base * _d(rates["markup"]))
    subtotal = base + markup
    vat = _won(subtotal * _d(rates["vat_rate"]))
    line = {"name": "롤포밍 부품", "steel_grade": grade, "quantity": inputs["quantity"],
            "weight_per_piece": weight.quantize(WEIGHT, rounding=ROUND_HALF_UP), "minutes_per_piece": minutes,
            "total_minutes": (minutes * qty + _d(rates["setup_minutes"])).quantize(CENTS, rounding=ROUND_HALF_UP),
            "unit_price": (subtotal / qty).quantize(CENTS, rounding=ROUND_HALF_UP), "amount": subtotal}
    costs = {"material": material, "processing": processing, "setup": setup, "markup": markup,
             "subtotal": subtotal, "vat": vat}
    return {"lines": [line], "costs": costs, "total": subtotal + vat, "predicted": {TASK: minutes}}
