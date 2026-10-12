"""eval CSV fixture 의 표기 규칙 (DEF-QA21-004 · #27 · D2-102).

규칙: `migration/make_fixtures.py --kind csv` 는 demo 합성 프레임을 **반올림 없이** pandas 기본 표기(최단 왕복 repr)로 쓴다.
CSV 어댑터(`pd.read_csv` 기본 파서)는 최단 표기를 비트 단위로 되돌리지 못한다 — 실수 열은 |eval − demo| ≤ 1e-12 · max(1, |demo|)
(1 ulp 급, 실측 최대 1.8e-12)이고, 그래서 eval 스냅숏 해시는 demo 와 다르다. 행 · 키 · 범주 · 정수 열 · 시각은 같다.
등록부 주석은 이 규칙(D2-102)을 가리킨다 — "demo 와 같은 행" 만으로 비트 동일을 뜻하지 않는다.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from migration import make_fixtures

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ("ks", "sw", "krs", "pc", "ot", "kd")
REL_TOL = 1e-12


@pytest.mark.parametrize("code", TENANTS)
def test_committed_csv_is_regenerated_bit_for_bit(code):
    frame = make_fixtures.frame_for(code)
    assert (ROOT / "tests" / "fixtures" / code / "snapshot.csv").read_bytes() == make_fixtures.to_csv_bytes(frame)


@pytest.mark.parametrize("code", TENANTS)
def test_csv_roundtrip_within_rule(code):
    demo = make_fixtures.frame_for(code)
    back = pd.read_csv(io.BytesIO(make_fixtures.to_csv_bytes(demo)), encoding="utf-8-sig")
    assert list(back.columns) == list(demo.columns) and len(back) == len(demo)
    for c in demo.columns:
        if c == "ts":
            want = demo[c].dt.strftime(make_fixtures.TS_FORMAT)          # 시각 없는 팩(krs · ot · kd)은 빈 칸 ↔ NaT
            assert back[c].isna().tolist() == want.isna().tolist()
            assert (back[c].dropna() == want.dropna()).all()
        elif demo[c].dtype.kind == "f":
            d, e = demo[c].to_numpy(float), back[c].to_numpy(float)
            assert np.array_equal(np.isnan(d), np.isnan(e))
            ok = ~np.isnan(d)
            assert (np.abs(e[ok] - d[ok]) <= REL_TOL * np.maximum(1.0, np.abs(d[ok]))).all(), c
        else:
            assert back[c].astype(str).tolist() == demo[c].astype(str).tolist(), c


@pytest.mark.parametrize("code", TENANTS)
def test_registry_comment_points_to_rule(code):
    line = next(ln for ln in (ROOT / "tenants" / f"{code}.yaml").read_text(encoding="utf-8").splitlines()
                if ln.lstrip().startswith("eval:"))
    assert "D2-102" in line, line
