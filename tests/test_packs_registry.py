"""팩 · 회사 등록부 로드 시험 (G-S02 · G-M03 · pack-contract · task-contract · feature-contract).

개발3 담당: packs/* 내용 · tenants/* · registry/{packs,tenants}.py 의 합성 생성기 노출(progress-dev3.md §1).
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from mlcore.registry import packs, tenants
from mlcore.settings import ROOT

A0 = {"ks": "ks.remaining_hours", "sw": "sw.delta_e"}


@pytest.mark.parametrize("code", ["press", "textile", "_template"])
def test_pack_loads_against_contract(code):
    p = packs.load_pack(code)                                       # 스키마 위반이면 PackInvalid
    assert len(p.tasks) >= 2
    assert packs.validate_features(p.features) == []
    synth = [f for f in (p.path / "synth").glob("*.py") if f.stem != "__init__"]
    assert synth, "synth/*.py 없음"
    assert (p.path / p.meta["synth"]["module"]).is_file()


@pytest.mark.parametrize("code,task,target,features", [
    ("press", "remaining_hours", "remaining_hours",
     ["press_force", "vibration", "motor_current", "equip_temp", "mold_temp", "cycle_time", "shot_count", "machine_code", "product_type"]),
    ("textile", "delta_e", "delta_e",
     ["set_temp", "set_pressure", "line_speed", "ink_usage", "dwell_time", "absorb_rate", "fabric_strength", "print_type", "color_tone"]),
])
def test_a0_task_definitions_match_source_inventory(code, task, target, features):
    # migration/source_inventory.md §1.2-1.3 · §2.2-2.3 — 변수 9 · 후보 4 · 시간순 432/144/144 · 그룹 경계 없음
    t = packs.load_pack(code).tasks[task]
    assert t["type"] == "regression" and t["target"]["name"] == target
    assert t["features"] == features
    assert t["candidates"] == ["ridge", "random_forest", "extra_trees", "gbr"]
    assert t["split"] == "time_60_20_20" and t["time_key"] and t["group_key"] is None
    assert t["interval"]["method"] == "split_conformal"
    assert t["out_of_range"] == "predict_with_warning"            # D-07


def test_feature_ranges_match_source():
    # 원천 FEATURE_META (source_inventory §1.2 · §2.2) — 검증 범위 = 원천 min/max, D-30 원천 값 우선
    pf, tf = packs.load_pack("press").features, packs.load_pack("textile").features
    assert (pf["press_force"]["min"], pf["press_force"]["max"]) == (180, 320)
    assert (pf["shot_count"]["min"], pf["shot_count"]["max"], pf["shot_count"]["integer"]) == (5000, 180000, True)
    assert pf["machine_code"]["values_from"] == "tenant" and pf["product_type"]["values_from"] == "tenant"
    assert (tf["set_temp"]["min"], tf["set_temp"]["max"], tf["set_temp"]["step"]) == (140, 210, 10)
    assert (tf["set_pressure"]["min"], tf["set_pressure"]["max"], tf["set_pressure"]["step"]) == (2, 6, 1)
    assert tf["color_tone"]["values"] == ["연한 색상", "중간 색상", "진한 색상"]
    assert [k for k, v in tf.items() if v.get("controllable")] == ["set_temp", "set_pressure", "line_speed", "ink_usage", "dwell_time"]


def test_synth_bounds_inside_feature_bounds():
    # 합성 행은 입력 검증 범위 안 (impossible_cells 0 — 원천 tests/test_api.py 의 기대)
    for code in ("press", "textile", "_template"):
        p = packs.load_pack(code)
        d = packs.load_synth(p)(p.meta["synth"]["rows"], p.meta["synth"]["seed"])
        for name, f in p.features.items():
            if f["dtype"] in ("float", "int"):
                s = d[name].dropna()
                assert s.min() >= f["min"] and s.max() <= f["max"], (code, name)
            elif f.get("values"):
                assert set(d[name]) <= set(f["values"]), (code, name)


@pytest.mark.parametrize("code", ["ks", "sw"])
def test_tenant_demo_source_and_enabled_tasks(code):
    m = tenants.load_and_merge(code)
    assert m.disabled == {}
    assert A0[code] in m.tasks and len(m.tasks) == 4
    src = m.tenant.config["sources"]["demo"]
    assert src == {"kind": "synthetic", "seed": 42}                 # source_inventory §0 — 시드 42 (D-30)
    for task_id in m.tasks:
        call = tenants.synth_call(m, task_id)
        assert call.seed == 42 and call.rows == 720
        assert call.spec.path.is_file()
        assert call.source_ref["kind"] == "synthetic" and len(call.source_ref["synth_sha256"]) == 64
        assert call.target == (m.tasks[task_id].raw.get("target") or {}).get("name")


def test_synth_call_resolution_and_errors():
    m = tenants.load_and_merge("ks")
    # 과제 진입점(synth/<task>.py)이 있으면 그것, 없으면 pack.yaml synth.module (공용)
    assert tenants.synth_call(m, "ks.remaining_hours").spec.path.name == "remaining_hours.py"
    assert tenants.synth_call(m, "ks.failure_24h").spec.path.name == "press_lots.py"
    a = tenants.synth_call(m, "ks.remaining_hours").generate()
    b = tenants.synth_call(m, "ks.failure_24h").generate()
    pd.testing.assert_frame_equal(a, b)                             # 같은 원천 demo_data() 를 공유
    assert set(a["machine_code"]) == set(m.tenant.config["categories"]["machine_code"])
    with pytest.raises(KeyError):
        tenants.synth_call(m, "ks.nope")
    with pytest.raises(ValueError):
        tenants.synth_call(m, "ks.remaining_hours", role="eval")   # eval 은 csv


def test_synth_modules_have_no_company_terms():
    # G-M01 의 팩 쪽 규칙을 생성기 파일에 한정해 빠르게 확인(정식 판정은 gates/check_core_terms.py)
    import sys
    sys.path.insert(0, str(ROOT / "gates"))
    from gatelib import tenant_words
    names, tables, cats = tenant_words()
    for f in (ROOT / "packs").glob("*/synth/*.py"):
        txt = f.read_text(encoding="utf-8")
        for label, pat in {**names, **tables, **cats}.items():
            assert not pat.search(txt), f"{f.relative_to(ROOT)}: {label}"
        assert not re.search(r"FEATURE_META\s*=|CONTROL_META\s*=", txt)
