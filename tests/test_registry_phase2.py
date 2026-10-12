"""2차 등록부 로더 — 유형 3(review_queue · extract · quote) 과제 키 검사 · 모르는 덮어쓰기 키 거부 · material_aliases.

기대값 출처: contracts/task-contract.md §4 task-schema · §6.1~§6.4 · contracts/tenant-contract.md §3 · DEF-QAR2-004(F20-4).
시험은 임시 폴더의 최소 팩 · 등록부로 한다(저장소 팩 · 회사를 고치지 않는다).
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from mlcore.registry import packs, tenants

pytestmark = [pytest.mark.gate("G2-T01")]

FEATURES = {
    "size_a": {"label": "A", "unit": "mm", "dtype": "float", "min": 0, "max": 100, "default": 10, "required": False, "impute": "median"},
    "size_b": {"label": "B", "unit": "mm", "dtype": "float", "min": 0, "max": 100, "default": 10, "required": False, "impute": "median"},
    "grade": {"label": "등급", "dtype": "category", "values_from": "tenant", "required": True},
}
REG = {
    "id": "toy.value", "type": "regression", "title": "값", "entity": "job", "time_key": None,
    "target": {"name": "value", "unit": "h", "direction": "lower_is_better"},
    "features": ["size_a", "size_b", "grade"], "split": "random_60_20_20", "candidates": ["ridge"],
    "interval": {"method": "split_conformal", "alpha": 0.1}, "out_of_range": "predict_with_warning",
    "approver_role": "lead",
}
QUEUE = {
    "id": "toy.queue", "type": "review_queue", "title": "대기열", "entity": "job", "out_of_range": "predict_with_warning",
    "approver_role": "lead", "uses": ["toy.value"], "rule": {"top_quantile": 0.1}, "quantile_from": "valid",
    "origins": ["test_split", "live_residual"], "max_items": 50, "schedule": "daily_after_monitor",
}
EXTRACT = {
    "id": "toy.read", "type": "extract", "title": "추출", "entity": "drawing", "out_of_range": "reject", "approver_role": "lead",
    "document": {"formats": ["dxf"], "max_bytes": 5242880, "max_entities": 20000, "unit_override": ["mm", "inch"]},
    "extractors": [{"name": "boxes", "kind": "rule", "module": "extractors/boxes.py", "version": "1.0.0"}],
    "labels": "none", "outputs": ["regions"],
}
QUOTE = {
    "id": "toy.quote", "type": "quote", "title": "견적", "entity": "job", "out_of_range": "reject", "approver_role": "lead",
    "uses": ["toy.value"], "from_extract": "toy.read", "recognized": {"bom": "bom_rows"},
    "inputs": ["bom", "quantity", "size_a"], "formula": "formulas/quote.py",
    "rates": {"markup": "0.15", "vat_rate": "0.10"}, "rounding": "ROUND_HALF_UP", "currency": "KRW",
    "confirm": {"requires": ["reviewed", "review_note"], "review_note_min": 5, "approver_role": "lead"},
}
EXTRACTOR_SRC = 'NAME = "boxes"\nVERSION = "1.0.0"\nKIND = "rule"\n\ndef extract(raw, filename, *, unit=None, limits=None, model=None):\n    return {}\n'
QUOTE_SRC = "from decimal import Decimal\n\ndef quote(inputs, lines, predicted, rates):\n    return {}\n"


def make_pack(root: Path, tasks: dict[str, dict], *, extractors=("boxes",), formula=True) -> Path:
    d = root / "packs" / "toy"
    (d / "tasks").mkdir(parents=True)
    (d / "synth").mkdir()
    (d / "synth" / "__init__.py").write_text("", encoding="utf-8")
    (d / "synth" / "rows.py").write_text("def generate(rows=10, seed=1, *, categories=None):\n    raise NotImplementedError\n",
                                         encoding="utf-8")
    meta = {"code": "toy", "name": "시험", "version": "0.1.0", "core_min": "0.1.0",
            "synth": {"module": "synth/rows.py", "seed": 1, "rows": 10}, "notice": "참고용",
            "monitor": {"psi_warn": 0.2, "psi_retrain": 0.3, "oor_warn": 0.05, "missing_warn_pp": 0.1, "perf_drop": 0.25,
                        "perf_window_days": 30},
            "tasks": sorted(tasks)}
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    (d / "features.yaml").write_text(yaml.safe_dump(FEATURES, allow_unicode=True), encoding="utf-8")
    for name, t in tasks.items():
        (d / "tasks" / f"{name}.yaml").write_text(yaml.safe_dump(t, allow_unicode=True), encoding="utf-8")
    if extractors:
        (d / "extractors").mkdir()
        for e in extractors:
            (d / "extractors" / f"{e}.py").write_text(EXTRACTOR_SRC.replace("boxes", e), encoding="utf-8")
    if formula:
        (d / "formulas").mkdir()
        (d / "formulas" / "quote.py").write_text(QUOTE_SRC, encoding="utf-8")
    return root / "packs"


def all_tasks(**changes) -> dict[str, dict]:
    out = {"value": copy.deepcopy(REG), "queue": copy.deepcopy(QUEUE), "read": copy.deepcopy(EXTRACT),
           "quote": copy.deepcopy(QUOTE)}
    for name, patch in changes.items():
        if patch is None:
            out.pop(name)
            continue
        for k, v in patch.items():
            if v is ...:
                out[name].pop(k, None)
            else:
                out[name][k] = v
    return out


def problems(tmp_path: Path, **changes) -> list[str]:
    base = make_pack(tmp_path, all_tasks(**changes))
    try:
        packs.load_pack("toy", base)
    except packs.PackInvalid as e:
        return e.problems
    return []


# ── 1. 정상 팩은 통과 ─────────────────────────────────────────────────────────────

def test_valid_phase2_pack_loads(tmp_path):
    base = make_pack(tmp_path, all_tasks())
    p = packs.load_pack("toy", base)
    assert {t["type"] for t in p.tasks.values()} == {"regression", "review_queue", "extract", "quote"}
    assert set(p.extractors) == {"boxes"} and len(p.extractors["boxes"]) == 64      # 플러그인 해시(R5)


def test_search_key_is_only_required_for_optimize(tmp_path):
    """웨이브 P 이전에는 non-learned 과제 전부에 search.strategy 를 요구했다 — optimize 만이어야 한다."""
    assert problems(tmp_path) == []


# ── 2. review_queue (§6.1) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("patch, needle", [
    ({"rule": {"abs_residual_ge": 4.0, "top_quantile": 0.1}}, "rule"),          # 둘 다
    ({"rule": {"bottom": 0.1}}, "rule"),                                          # 모르는 규칙
    ({"rule": {"top_quantile": 1.5}}, "top_quantile"),                           # 0 < q < 1
    ({"rule": {"abs_residual_ge": -1}}, "abs_residual_ge"),                      # 양수
    ({"rule": {"abs_residual_ge": True}}, "abs_residual_ge"),                    # bool 은 수가 아니다
    ({"quantile_from": ...}, "quantile_from"),                                    # top_quantile 이면 필수
    ({"quantile_from": "test"}, "quantile_from"),                                 # 고정값 valid
    ({"origins": ["train_split"]}, "origins"),                                    # 학습 구간 잔차 금지(G2-R01)
    ({"origins": ["test_split", "valid_split"]}, "origins"),
    ({"origins": []}, "origins"),
    ({"uses": ["toy.value", "toy.value"]}, "uses"),                               # 정확히 1개
    ({"uses": ["toy.read"]}, "uses"),                                             # regression · risk 만
    ({"max_items": 0}, "max_items"),
    ({"schedule": "hourly"}, "schedule"),
])
def test_review_queue_keys_rejected(tmp_path, patch, needle):
    p = problems(tmp_path, queue=patch)
    assert any(needle in x for x in p), p


def test_review_queue_abs_rule_needs_no_quantile_from(tmp_path):
    assert problems(tmp_path, queue={"rule": {"abs_residual_ge": 4.0}, "quantile_from": ...}) == []


def test_review_queue_abs_rule_rejects_quantile_from(tmp_path):
    p = problems(tmp_path, queue={"rule": {"abs_residual_ge": 4.0}})
    assert any("quantile_from" in x for x in p), p


# ── 3. extract (§6.2) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch, needle", [
    ({"entity": "job"}, "entity"),
    ({"document": {"formats": ["dxf"], "max_bytes": 6_000_000, "max_entities": 20000}}, "max_bytes"),   # spec 상한 초과
    ({"document": {"formats": ["dxf"], "max_bytes": 5242880, "max_entities": 20001}}, "max_entities"),
    ({"document": {"formats": ["pdf"], "max_bytes": 5242880, "max_entities": 20000}}, "formats"),
    ({"document": {"formats": ["dxf"], "max_bytes": 5242880, "max_entities": 20000, "unit_override": ["ft"]}}, "unit_override"),
    ({"extractors": []}, "extractors"),
    ({"extractors": [{"name": "boxes", "kind": "ocr", "module": "extractors/boxes.py", "version": "1"}]}, "kind"),
    ({"extractors": [{"name": "nothere", "kind": "rule", "module": "extractors/nothere.py", "version": "1"}]}, "module"),
    ({"extractors": [{"name": "boxes", "kind": "rule", "module": "../escape.py", "version": "1"}]}, "module"),
    ({"extractors": [{"name": "boxes", "kind": "rule", "module": "extractors/boxes.py"}]}, "version"),
    ({"extractors": [{"name": "boxes", "kind": "rule", "module": "extractors/boxes.py", "version": "1"},
                     {"name": "boxes", "kind": "rule", "module": "extractors/boxes.py", "version": "1"}]}, "중복"),
    ({"labels": "guessed"}, "labels"),
    ({"outputs": ["regions", "pixels"]}, "outputs"),
    ({"extractors": [{"name": "boxes", "kind": "model", "module": "extractors/boxes.py", "version": "1"}]}, "model"),
])
def test_extract_keys_rejected(tmp_path, patch, needle):
    p = problems(tmp_path, read=patch)
    assert any(needle in x for x in p), p


def test_extract_model_block_checked(tmp_path):
    ok = {"extractors": [{"name": "boxes", "kind": "model", "module": "extractors/boxes.py", "version": "1"}],
          "labels": "synthetic",
          "model": {"features": ["size_a", "size_b"], "classes": ["outer", "hole"], "split": "stratified_60_20_20",
                    "candidates": ["logreg", "rf_clf"], "selection": "macro_f1"}}
    assert problems(tmp_path, read=ok) == []
    bad = copy.deepcopy(ok)
    bad["model"].update(features=["nope"], split="random_60_20_20", candidates=["ridge"], selection="accuracy", classes=[])
    p = problems(tmp_path / "b", read=bad)
    for needle in ("nope", "split", "ridge", "selection", "classes"):
        assert any(needle in x for x in p), (needle, p)


# ── 4. quote (§6.3) ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch, needle", [
    ({"uses": ["toy.queue"]}, "uses"),
    ({"uses": []}, "uses"),
    ({"from_extract": "toy.value"}, "from_extract"),
    ({"recognized": ...}, "recognized"),
    ({"inputs": []}, "inputs"),
    ({"formula": "formulas/nothere.py"}, "formula"),
    ({"formula": "quote"}, "formula"),
    ({"rates": {"markup": 0.15}}, "rates"),                     # float 를 거치지 않게 문자열만
    ({"rates": {"markup": "1e-2"}}, "rates"),
    ({"rates": {"markup": "abc"}}, "rates"),
    ({"rounding": "ROUND_HALF_EVEN"}, "rounding"),
    ({"currency": "USD"}, "currency"),
    ({"confirm": {"requires": ["reviewed"], "review_note_min": 5, "approver_role": "lead"}}, "confirm"),
    ({"confirm": {"requires": ["reviewed", "review_note"], "review_note_min": 3, "approver_role": "lead"}}, "review_note_min"),
    ({"confirm": {"requires": ["reviewed", "review_note"], "review_note_min": 5}}, "approver_role"),
    ({"csv": "a,b"}, "csv"),
])
def test_quote_keys_rejected(tmp_path, patch, needle):
    p = problems(tmp_path, quote=patch)
    assert any(needle in x for x in p), p


def test_quote_without_extract_is_allowed(tmp_path):
    assert problems(tmp_path, quote={"from_extract": ..., "recognized": ...}) == []


# ── 5. 덮어쓰기 — 모르는 키 거부 (DEF-QAR2-004 · F20-4) · 2차 덮어쓰기 규칙 (§6.4) ─────────────

def tenant_dir(tmp_path: Path, overrides: dict[str, dict] | None = None, **cfg_patch) -> Path:
    d = tmp_path / "tenants"
    (d / "tt" / "tasks").mkdir(parents=True)
    cfg = {"code": "tt", "name": "시험사", "pack": "toy", "mode": "demo", "hub_company": "tt",
           "tasks": {"enable": ["tt.value", "tt.queue", "tt.read", "tt.quote"]},
           "categories": {"grade": ["G1", "G2"]},
           "sources": {"demo": {"kind": "synthetic", "seed": 1}}}
    cfg.update(cfg_patch)
    (d / "tt.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    for name, o in (overrides or {}).items():
        (d / "tt" / "tasks" / f"{name}.yaml").write_text(yaml.safe_dump(o, allow_unicode=True), encoding="utf-8")
    return d


def merge(tmp_path: Path, overrides=None, **cfg_patch):
    pbase = make_pack(tmp_path, all_tasks())
    return tenants.load_and_merge("tt", tenants_base=tenant_dir(tmp_path, overrides, **cfg_patch), packs_base=pbase)


def test_phase2_tenant_merges(tmp_path):
    m = merge(tmp_path)
    assert sorted(m.tasks) == ["tt.queue", "tt.quote", "tt.read", "tt.value"]


@pytest.mark.parametrize("name, over", [
    ("value", {"auto_promote": True}),                  # QA 재현 키
    ("value", {"threshold": {"review_above": 3}}),      # 오타(thresholds)
    ("queue", {"rules": {"top_quantile": 0.2}}),        # 오타(rule)
    ("quote", {"rate": {"markup": "0.2"}}),             # 오타(rates)
])
def test_unknown_override_key_rejected(tmp_path, name, over):
    with pytest.raises(tenants.RegistryRejected) as e:
        merge(tmp_path, {name: over})
    assert e.value.rule == "R1" and "모르는" in e.value.detail


@pytest.mark.parametrize("name, over", [
    ("value", {"thresholds": {"review_above": 30}, "notice": "회사 문구", "title": "값(회사)", "monitor": {"psi_warn": 0.25}}),
    ("value", {"candidates": ["ridge"], "candidate_params": {"ridge": {"alpha": 2}}}),
    ("queue", {"rule": {"top_quantile": 0.2}, "max_items": 20, "reason": "|잔차| {abs_residual:.2f}"}),
    ("read", {"document": {"max_bytes": 1048576, "max_entities": 2000}}),
    ("quote", {"rates": {"markup": "0.20"}, "csv": ["name", "amount"]}),
    ("quote", {"recognized": {"tolerance": "0.001"}}),
    ("value", {"type": "regression"}),                  # 같은 값 다시 적기는 허용
])
def test_allowed_overrides_merge(tmp_path, name, over):
    m = merge(tmp_path, {name: over})
    raw = m.tasks[f"tt.{name}"].raw
    for k, v in over.items():
        if isinstance(v, dict):
            assert all(raw[k][kk] == vv for kk, vv in v.items())
        else:
            assert raw[k] == v


@pytest.mark.parametrize("name, over, needle", [
    ("queue", {"rule": {"abs_residual_ge": 3.0}}, "rule"),                 # 같은 종류 안에서만
    ("queue", {"rule": {"top_quantile": 2}}, "top_quantile"),              # 병합 결과도 검사
    ("queue", {"origins": ["test_split"]}, "origins"),                     # 바꿀 수 없다
    ("queue", {"quantile_from": "test"}, "quantile_from"),
    ("read", {"document": {"max_bytes": 6_000_000}}, "document"),          # 낮추기만
    ("read", {"document": {"formats": ["dxf", "pdf"]}}, "document"),
    ("read", {"labels": "synthetic"}, "labels"),
    ("read", {"extractors": []}, "extractors"),
    ("quote", {"formula": "formulas/other.py"}, "formula"),
    ("quote", {"rounding": "ROUND_HALF_EVEN"}, "rounding"),
    ("quote", {"currency": "USD"}, "currency"),
    ("quote", {"rates": {"new_rate": "1"}}, "rates"),                       # 값만 — 새 단가 이름 추가 불가
    ("quote", {"rates": {"markup": 0.2}}, "rates"),                        # float
    ("quote", {"confirm": {"requires": ["reviewed"]}}, "confirm"),         # requires 빼기 불가
    ("quote", {"recognized": {"bom": "objects"}}, "recognized"),           # tolerance 만
    ("quote", {"uses": ["toy.queue"]}, "uses"),
])
def test_forbidden_phase2_overrides(tmp_path, name, over, needle):
    with pytest.raises(tenants.RegistryRejected) as e:
        merge(tmp_path, {name: over})
    assert e.value.rule == "R1" and needle in e.value.detail, e.value.detail


# ── 6. material_aliases (tenant-contract §3 — 2차 새 최상위 키) ─────────────────────

def test_material_aliases_valid(tmp_path):
    m = merge(tmp_path, material_aliases={"GRADE1": "G1", "G-2": "G2"})
    assert tenants.material_aliases(m) == {"GRADE1": "G1", "G-2": "G2"}
    assert tenants.normalize_category(m, "grade1") == "G1"           # 대문자 비교(원천 재질 규칙)
    assert tenants.normalize_category(m, "G2") == "G2"
    assert tenants.normalize_category(m, "ZZ") == "ZZ"               # 모르면 그대로(검증은 추출기 · 입력 검증 몫)


@pytest.mark.parametrize("aliases", [
    ["G1"],                                  # 표가 아니다
    {"GRADE1": "G9"},                        # 정규 값이 회사 categories 에 없다
    {"G1": "G2"},                            # 정규 값 자체를 별칭으로
    {"": "G1"},
    {"GRADE1": 3},
])
def test_material_aliases_rejected(tmp_path, aliases):
    with pytest.raises(tenants.RegistryRejected) as e:
        merge(tmp_path, material_aliases=aliases)
    assert "material_aliases" in e.value.detail


# ── 7. 추출기 R5 — 같은 이름 · 다른 구현 ─────────────────────────────────────────

def test_extractor_plugin_conflict_r5(tmp_path):
    pbase = make_pack(tmp_path, all_tasks())
    tdir = tenant_dir(tmp_path)
    (tdir / "tt" / "extractors").mkdir()
    (tdir / "tt" / "extractors" / "boxes.py").write_text(EXTRACTOR_SRC + "# 회사 구현\n", encoding="utf-8")
    with pytest.raises(tenants.RegistryRejected) as e:
        tenants.load_and_merge("tt", tenants_base=tdir, packs_base=pbase)
    assert e.value.rule == "R5"
    shutil.copy(pbase / "toy" / "extractors" / "boxes.py", tdir / "tt" / "extractors" / "boxes.py")   # 같은 구현은 허용
    tenants.load_and_merge("tt", tenants_base=tdir, packs_base=pbase)


# ── 8. 1차 덮어쓰기 · 불량 픽스처 회귀 (모르는 키 검사가 기존 등록부를 깨지 않는다) ─────────────

def test_repo_registries_still_load():
    for code in tenants.all_codes():
        tenants.load_and_merge(code)
