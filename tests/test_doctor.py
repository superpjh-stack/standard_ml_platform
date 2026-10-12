"""G-M08 — doctor(fixture): 소스별 행 수 · 기간 · 변수 대응률 · 결측률, 또는 `미연결` · `목표 없음`. 소유 개발3.

기대값은 원천 조사(migration/source_inventory.md §3 · §4 — 대응률 sw 7/9 · ks 6/9, ks 목표 원천 없음 D-33)와
fixture(720행 · 결측 각 8행) 에서 온다. 실연결(doctor-live)은 BLOCKED (D-13) — 여기서는 부르지 않는다.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from mlcore.monitor import doctor as dr
from mlcore.registry import tenants

pytestmark = pytest.mark.gate("G-M08")


def by_role(rep: dict) -> dict:
    return {s["role"]: s for s in rep["sources"]}


@pytest.mark.parametrize("code,start,mapped,miss", [
    ("ks", "2026-08-01T00:00:00+09:00", 6 / 9, {"vibration", "motor_current", "mold_temp"}),
    ("sw", "2026-08-01T08:00:00+09:00", 7 / 9, {"absorb_rate", "fabric_strength", "ink_usage"}),
])
def test_fixture_sources(code, start, mapped, miss):
    rep = dr.doctor(code)
    s = by_role(rep)
    assert rep["tenant"] == code and set(s) == {"demo", "eval", "train", "gateway", "actuals"}
    for role in ("demo", "eval"):
        x = s[role]
        assert x["status"] == "연결" and x["rows"] == 720 and x["ts_from"] == start
        assert x["coverage"] == 1.0 and x["target"] == "있음"
        assert {k for k, v in x["missing_rates"].items() if v > 0} == miss
        assert all(x["missing_rates"][k] == pytest.approx(8 / 720) for k in miss)
    for role in ("train", "gateway", "actuals"):
        x = s[role]
        assert x["status"] == "미연결" and x["rows"] is None and "D-13" in x["message"]
        assert x["coverage"] == pytest.approx(mapped)                       # 인벤토리 대응률


def test_ks_live_sources_show_no_target():
    s = by_role(dr.doctor("ks"))
    for role in ("train", "gateway", "actuals"):
        assert s[role]["target"] == "목표 없음"                            # D-33: 정비 · 고장 이력 원천 없음
        assert set(s[role]["unmapped"]) == {"motor_current", "equip_temp", "product_type"}
    s = by_role(dr.doctor("sw"))
    assert s["train"]["target"] == "있음" and set(s["train"]["unmapped"]) == {"dwell_time", "color_tone"}


def _tmp_tenant(tmp_path, monkeypatch, eval_path: str) -> str:
    base = tmp_path / "tenants"
    base.mkdir()
    text = (tenants.TENANTS_DIR / "sw.yaml").read_text(encoding="utf-8")
    text = text.replace("code: sw", "code: dtst").replace("sw.", "dtst.")
    text = text.replace("path: tests/fixtures/sw/snapshot.csv", f"path: {eval_path}")
    (base / "dtst.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("MLP_TENANTS_DIR", str(base))
    return "dtst"


def test_missing_csv_is_disconnected(tmp_path, monkeypatch):
    code = _tmp_tenant(tmp_path, monkeypatch, str(tmp_path / "없음.csv"))
    x = by_role(dr.doctor(code))["eval"]
    assert x["status"] == "미연결" and x["rows"] is None and "CSV 없음" in x["message"]


def test_csv_without_target_says_no_target(tmp_path, monkeypatch):
    src = tenants.TENANTS_DIR.parent / "tests" / "fixtures" / "sw" / "snapshot.csv"
    df = pd.read_csv(src, encoding="utf-8-sig").drop(columns=["delta_e", "defect"])
    p = tmp_path / "no_target.csv"
    df.to_csv(p, index=False, encoding="utf-8-sig")
    code = _tmp_tenant(tmp_path, monkeypatch, str(p))
    x = by_role(dr.doctor(code))["eval"]
    assert x["status"] == "연결" and x["rows"] == 720 and x["target"] == "목표 없음"
    assert set(x["targets"].values()) == {"목표 없음"}


def test_live_is_blocked_and_never_called():
    with pytest.raises(PermissionError, match="D-13"):
        dr.doctor("ks", live=True)


def test_no_secret_values_in_output(monkeypatch, capsys):
    secret = "zzSECRETzz-value"
    for name in ("MLP_KS_DP_URL", "MLP_KS_DP_KEY", "MLP_KS_MES_RO_DSN", "MLP_KS_GW_RO_DSN"):
        monkeypatch.setenv(name, secret)
    assert dr.main(["--tenant", "ks", "--json"]) == 0
    out = capsys.readouterr().out
    assert secret not in out
    rep = json.loads(out)
    assert {s["status"] for s in rep["sources"]} == {"연결", "미연결"}
    assert dr.main(["--tenant", "sw"]) == 0
    text = capsys.readouterr().out
    assert "대응률=77.8%" in text and "미연결" in text
