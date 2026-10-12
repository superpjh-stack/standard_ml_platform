"""웨이브 P 마감 — A2 팩(solder · rollform-quote · kimchi)을 코어 수정 없이 붙이기 위한 코어 장치 회귀 (docs/freeze-readiness.md · D2-45).

① G-M01 std 어휘: 과제 이름 = 자기 유형 코드만 코어 금지어에서 빠지고, 다른 겹침은 팩 위반(D2-31)
② 추출기 context(categories · material_aliases · params · previous) · 결과 replaces(규칙 → 모델 다듬기)
③ 견적 단가표 rate_tables(범주별 kg 단가 · 밀도) — 팩은 빈 표, 회사가 칸을 채우고 범주와 다르면 R2
④ 과제별 합성 행 수(pack.yaml synth.tasks — 객체 설명자 1,600 ≠ 작업 900)
"""
from __future__ import annotations

import dataclasses
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from mlcore.registry import packs, tenants
from mlcore.registry.tenants import RegistryRejected
from mlcore.serve import documents
from mlcore.tasks.extract import merge_results

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gates"))
import check_core_terms  # noqa: E402


# ① ────────────────────────────────────────────────────────────────────────────────────────────
def _fake_pack(tasks: dict, features: dict | None = None):
    return SimpleNamespace(code="zz", tasks=tasks, features=features or {"x1": {}})


def test_std_task_name_equal_to_own_type_is_exempt():
    vocab = check_core_terms.std_vocabulary()
    assert {"quote", "extract", "review_queue", "mae", "review", "not_found"} <= vocab
    allowed, bad = check_core_terms.std_collisions(_fake_pack({"quote": {"type": "quote"}}), vocab)
    assert allowed == {"quote"} and bad == []


@pytest.mark.parametrize("tasks,features", [
    ({"quote": {"type": "regression"}}, None),              # 다른 유형의 과제가 유형 코드를 이름으로
    ({"t": {"type": "regression", "target": {"name": "mae"}}}, None),   # 목표 이름이 지표 이름
    ({"t": {"type": "regression"}}, {"review": {}}),        # 변수 이름이 상태 코드
])
def test_other_std_collisions_fail_on_the_pack(tasks, features):
    allowed, bad = check_core_terms.std_collisions(_fake_pack(tasks, features), check_core_terms.std_vocabulary())
    assert not allowed and len(bad) == 1 and "D2-31" in bad[0]


def test_gate_passes_with_eto_quote():
    (line,) = check_core_terms.run()
    assert line.status == "PASS" and "['quote']" in line.measured, line.measured


# ② ────────────────────────────────────────────────────────────────────────────────────────────
def test_merge_replaces_previous_objects_and_counts():
    rule = SimpleNamespace(NAME="geo", KIND="rule")
    model = SimpleNamespace(NAME="cls", KIND="model")
    a = {"objects": [{"id": "o1", "label": "?"}], "counts": {"hole": 1}, "dimensions": {"length": 10}}
    b = {"objects": [{"id": "o1", "label": "hole"}], "counts": {"hole": 1}, "confidence": 0.9,
         "replaces": ["objects", "counts"]}
    out = merge_results([(rule, a), (model, b)])
    assert out["objects"] == [{"id": "o1", "label": "hole"}] and out["counts"] == {"hole": 1}
    assert out["dimensions"] == {"length": 10} and out["confidence"] == 0.9
    with pytest.raises(TypeError):
        merge_results([(rule, {"replaces": ["warnings"]})])


def test_context_only_to_extractors_that_accept_it():
    seen = {}

    def old(raw, filename, *, unit, limits, model=None):
        return {"n": 0}

    def new(raw, filename, *, unit, limits, model=None, context=None):
        seen.update(context)
        return {"n": 1}
    ctx = {"categories": {"m": ["A"]}, "material_aliases": {"B": "A"}, "params": {"score_min": 0.8}, "previous": None}
    assert documents.call_extractor(SimpleNamespace(extract=old), b"", "a.dxf", unit="mm", limits={}, model=None,
                                    context=ctx) == {"n": 0}
    assert documents.call_extractor(SimpleNamespace(extract=new), b"", "a.dxf", unit="mm", limits={}, model=None,
                                    context=ctx) == {"n": 1}
    assert seen["params"] == {"score_min": 0.8}


def test_extract_context_is_tenant_values():
    m = tenants.load_and_merge("kd")
    ctx = documents.extract_context(m)
    assert ctx["categories"]["main_material"] == m.tenant.config["categories"]["main_material"]
    assert ctx["material_aliases"]["SUS304"] == "STS304"


def test_extractor_params_validated():
    sc = packs.task_schema() if hasattr(packs, "task_schema") else None
    pack = packs.load_pack("eto")
    task = dict(pack.tasks["drawing_regions"])
    task["extractors"] = [dict(task["extractors"][0], params={"score_min": 0.8, "kinds": ["a", "b"]}), task["extractors"][1]]
    assert not [p for p in packs.validate_task("drawing_regions", task, "eto", pack.features, pack.tasks, pack.path)
                if "params" in p or "모르는 키" in p]
    task["extractors"][0] = dict(task["extractors"][0], params={"bad": {"nested": 1}}, extra=1)
    probs = packs.validate_task("drawing_regions", task, "eto", pack.features, pack.tasks, pack.path)
    assert any("params" in p for p in probs) and any("모르는 키" in p for p in probs), probs
    del sc


# ③ ────────────────────────────────────────────────────────────────────────────────────────────
def test_validate_rates_tables():
    assert packs.validate_rates("q", {"vat": "0.10", "price_kg": {}}, {"price_kg"}) == []
    assert packs.validate_rates("q", {"vat": "0.10", "price_kg": {"A": "1450"}}, {"price_kg"}) == []
    assert packs.validate_rates("q", {"vat": "0.10", "price_kg": {"A": 1450.0}}, {"price_kg"})
    assert packs.validate_rates("q", {"vat": "0.10", "price_kg": {"A": "1"}})            # 표가 아닌데 map
    assert packs.validate_rates("q", {"vat": "0.10"}, {"price_kg"})                      # 표 이름 없음


@pytest.fixture()
def rate_world(tmp_path):
    pk = tmp_path / "packs"
    shutil.copytree(ROOT / "packs" / "eto", pk / "eto", ignore=shutil.ignore_patterns("__pycache__"))
    q = yaml.safe_load((pk / "eto" / "tasks" / "quote.yaml").read_text(encoding="utf-8"))
    q["rates"]["price_kg"] = {}
    q["rate_tables"] = {"price_kg": "main_material"}
    (pk / "eto" / "tasks" / "quote.yaml").write_text(yaml.safe_dump(q, allow_unicode=True), encoding="utf-8")
    tb = tmp_path / "tenants"
    tb.mkdir()
    shutil.copy(ROOT / "tenants" / "kd.yaml", tb / "kd.yaml")
    mats = yaml.safe_load((tb / "kd.yaml").read_text(encoding="utf-8"))["categories"]["main_material"]
    return pk, tb, mats


def _over(tb: Path, rates: dict):
    d = tb / "kd" / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quote.yaml").write_text(yaml.safe_dump({"rates": rates}, allow_unicode=True), encoding="utf-8")


def test_rate_table_filled_by_tenant(rate_world):
    pk, tb, mats = rate_world
    _over(tb, {"price_kg": {m: str(1000 + i) for i, m in enumerate(mats)}})
    m = tenants.load_and_merge("kd", tenants_base=tb, packs_base=pk)
    assert m.tasks["kd.quote"].raw["rates"]["price_kg"][mats[0]] == "1000"


@pytest.mark.parametrize("which", ["missing", "extra", "new_name"])
def test_rate_table_must_match_tenant_categories(rate_world, which):
    pk, tb, mats = rate_world
    table = {m: "1" for m in mats}
    if which == "missing":
        table.pop(mats[0])
        _over(tb, {"price_kg": table})
    elif which == "extra":
        table["NOPE"] = "1"
        _over(tb, {"price_kg": table})
    else:
        _over(tb, {"price_kg": table, "new_rate": "1"})
    with pytest.raises(RegistryRejected) as e:
        tenants.load_and_merge("kd", tenants_base=tb, packs_base=pk)
    assert e.value.rule in (("R1",) if which == "new_name" else ("R2",))


# ④ ────────────────────────────────────────────────────────────────────────────────────────────
def test_per_task_synth_rows_and_seed():
    pack = packs.load_pack("eto")
    meta = {**pack.meta, "synth": {**pack.meta["synth"], "tasks": {"drawing_regions": {"rows": 1600, "seed": 7}}}}
    p2 = dataclasses.replace(pack, meta=meta)
    s = packs.synth_spec(p2, "drawing_regions")
    assert (s.rows, s.seed) == (1600, 7)
    assert (packs.synth_spec(p2, "labor_hours").rows, packs.synth_spec(p2, "labor_hours").seed) == (900, 42)
    m = tenants.load_and_merge("kd")
    m2 = dataclasses.replace(m, pack=p2)
    call = tenants.synth_call(m2, "kd.drawing_regions")
    assert (call.rows, call.seed) == (1600, 7)                 # 팩 과제 고유 값이 회사 소스 rows(900)보다 앞선다
    assert tenants.synth_call(m2, "kd.labor_hours").rows == 900
