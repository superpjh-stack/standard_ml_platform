"""웨이브 P 재진입(D2-70) — 코어 결함 D2-A2-01 · 03 의 단위 시험 (회사 연결 시험은 test_compat · test_*_quote_flow).

- D2-A2-01 `serve/quotes.to_csv`: 과제 `csv` 는 품목 열 순서 — 요약 행(합계 · 구성 금액 …)을 거르지 않는다.
- D2-A2-03 등록부 로더: quote `input_limits` 모양 검사(task-contract §6.3).
"""

from __future__ import annotations

import csv
import io

import pytest

from mlcore.registry import packs
from mlcore.serve import quotes


def _q(**kw):
    q = {"quote_id": "qte_X", "task": "t.quote", "status": "draft", "revision": 1, "doc_id": None,
         "costs": {"material": "100", "labor": "50"}, "total": "150", "currency": "KRW", "inputs": {"quantity": 1},
         "rates": {"markup": "0.15"}, "predictions": [{"task": "t.hours", "value": "1.5"}], "reviewed": True,
         "review_note": "=검토 메모", "confirmed_by": None, "confirmed_at": None, "overrides": [], "notice": "n",
         "lines": [{"name": "A", "material": "M1", "amount": "100", "extra": "x"}]}
    q.update(kw)
    return q


def _rows(data: bytes):
    assert data.startswith("﻿".encode("utf-8"))
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def test_csv_columns_order_lines_and_summary_is_complete():
    rows = _rows(quotes.to_csv(_q(), ["amount", "name", "missing"]))
    summary = {r[0]: r[1] for r in rows if len(r) == 2}
    assert summary["total"] == "150" and summary["costs.material"] == "100" and summary["costs.labor"] == "50"
    assert summary["review_note"] == "'=검토 메모"                                   # 수식 주입 방지
    i = rows.index(["amount", "name", "missing"])
    assert rows[i + 1] == ["100", "A", ""]                                            # 정한 순서 · 없는 열 빈 칸 · 남는 열 없음


def test_csv_without_columns_keeps_all_line_keys():
    rows = _rows(quotes.to_csv(_q()))
    assert ["name", "material", "amount", "extra"] in rows


@pytest.mark.parametrize("limits,ok", [
    ({"quantity": {"min": 1, "max": 1000, "integer": True}}, True),
    ({"quantity": {"min": 0}}, True),
    ({"x1": {"min": 0}}, False),                 # features.yaml 변수 — 범위 정본은 features.yaml
    ({"nope": {"min": 0}}, False),               # inputs 에 없는 이름
    ({"quantity": {"min": 5, "max": 1}}, False),
    ({"quantity": {"min": -1}}, False),
    ({"quantity": {"lo": 1}}, False),
    ({"quantity": {"integer": "yes"}}, False),
    ({"quantity": {"max": "10"}}, False),
    ({"quantity": {}}, False),
    (["quantity"], False),
])
def test_input_limits_shape(limits, ok):
    p = packs._validate_input_limits("t.quote", limits, ["x1", "quantity", "labor_rate"], {"x1": {"dtype": "float"}})
    assert (p == []) is ok, p
