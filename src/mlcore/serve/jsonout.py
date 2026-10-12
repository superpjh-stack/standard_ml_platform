"""정확한 10진 JSON — Decimal 을 float 로 바꾸지 않고 숫자 그대로 쓴다 (견적 · 문서 응답, G2-Q01 "응답까지 float 0").

FastAPI 기본 직렬화(jsonable_encoder)는 Decimal 을 float 로 바꾼다. 견적 응답은 이 함수로 직접 직렬화한다.
금액은 계약대로 **문자열**(원 단위 정수)이고, 입력 · 품목 수치는 Decimal 의 10진 표기 그대로(지수 표기 없음).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from starlette.responses import Response


def _num(d: Decimal) -> str:
    if not d.is_finite():
        raise ValueError("유한하지 않은 Decimal")
    text = format(d, "f")
    return text


def dumps(obj: Any) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, Decimal):
        return _num(obj)
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return json.dumps(obj, allow_nan=False)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, (datetime, date)):
        return json.dumps(obj.isoformat())
    if isinstance(obj, dict):
        return "{" + ",".join(f"{json.dumps(str(k), ensure_ascii=False)}:{dumps(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    raise TypeError(f"JSON 으로 쓸 수 없는 형 {type(obj).__name__}")


def loads(text: str | bytes) -> Any:
    """JSON 숫자 중 실수는 Decimal 로(float 를 거치지 않는다). NaN · Infinity 는 거부."""
    def _const(name):
        raise ValueError(f"허용하지 않는 상수 {name}")
    return json.loads(text, parse_float=Decimal, parse_constant=_const)


class DecimalJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return dumps(content).encode("utf-8")
