"""업종 팩 로더 (contracts/pack-contract.md · task-contract.md · feature-contract.md).

Phase 0 아키텍트 초안 — 이후 소유는 개발3. 코어는 팩 내용(변수 · 과제 이름)을 모른다:
여기서는 YAML 을 읽고 계약 모양만 검사한다.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..settings import ROOT

PACKS_DIR = ROOT / "packs"
STD_DIR = ROOT / "std"
CONTRACTS_DIR = ROOT / "contracts"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PACK_RE = re.compile(r"^(_template|[a-z][a-z0-9\-]*)$")


class PackInvalid(Exception):
    def __init__(self, pack: str, problems: list[str]):
        super().__init__(f"{pack}: " + "; ".join(problems))
        self.pack, self.problems = pack, problems


@dataclass
class Pack:
    code: str
    path: Path
    meta: dict
    features: dict[str, dict]
    std_name: dict
    tasks: dict[str, dict]                    # 과제 짧은 이름 → YAML
    formulas: dict[str, str] = field(default_factory=dict)   # 이름 → sha256
    extractors: dict[str, str] = field(default_factory=dict)  # 추출기 플러그인 이름 → sha256 (병합 규칙 R5)

    def task_id(self, name: str) -> str:
        return f"{self.code}.{name}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def def_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def std(name: str) -> dict:
    return _yaml(STD_DIR / f"{name}.yaml")


def task_schema() -> dict:
    """contracts/task-contract.md §4 의 기계 판독 블록."""
    text = (CONTRACTS_DIR / "task-contract.md").read_text(encoding="utf-8")
    m = re.search(r"```yaml task-schema\n(.*?)```", text, re.S)
    if not m:
        raise RuntimeError("task-contract.md 에 task-schema 블록이 없다")
    return yaml.safe_load(m.group(1))


def validate_features(features: dict[str, dict]) -> list[str]:
    problems = []
    for name, f in features.items():
        if not NAME_RE.match(name):
            problems.append(f"F1 변수 이름 {name!r}")
        if not isinstance(f, dict):
            problems.append(f"{name}: 정의가 map 이 아니다")
            continue
        for key in ("label", "dtype"):
            if key not in f:
                problems.append(f"{name}: {key} 없음")
        dtype = f.get("dtype")
        if dtype in ("float", "int"):
            if f.get("min") is None or f.get("max") is None or not f["min"] < f["max"]:
                problems.append(f"F2 {name}: min < max 아님")
            elif f.get("default") is not None and not f["min"] <= f["default"] <= f["max"]:
                problems.append(f"F2 {name}: default 범위 밖")
            if "unit" not in f:
                problems.append(f"{name}: 수치 변수 unit 없음")
        elif dtype == "category":
            if not f.get("values") and f.get("values_from") != "tenant":
                problems.append(f"{name}: 범주 values 또는 values_from 없음")
        elif dtype != "bool":
            problems.append(f"{name}: dtype {dtype!r}")
        if f.get("controllable") and not (isinstance(f.get("step"), (int, float)) and f["step"] > 0):
            problems.append(f"F3 {name}: controllable 인데 step 없음")
    return problems


def validate_task(name: str, task: dict, pack_code: str, features: dict, all_tasks: dict,
                  pack_path: Path | None = None) -> list[str]:
    """과제 YAML 한 개를 계약(task-contract §4 · std/*.yaml)으로 검사한다."""
    sc = task_schema()
    types = std("task_types")["types"]
    cands = std("candidates")["candidates"]
    splits = std("split_policies")["policies"]
    p: list[str] = []
    for key in sc["common_required"]:
        if task.get(key) in (None, ""):
            p.append(f"{name}: {key} 없음")
    if task.get("id") != f"{pack_code}.{name}":
        p.append(f"{name}: id {task.get('id')!r} ≠ {pack_code}.{name}")
    ttype = task.get("type")
    if ttype not in types:
        p.append(f"{name}: type {ttype!r} 이 std/task_types.yaml 에 없다")
        return p
    rule = sc["by_type"].get(ttype, {})
    for key in rule.get("required", []):
        if task.get(key) in (None, "", [], {}):
            p.append(f"{name}: {ttype} 필수 {key} 없음")
    for sub in ("target", "thresholds"):
        for key in rule.get(f"{sub}_required", []):
            if not isinstance(task.get(sub), dict) or key not in task[sub]:
                p.append(f"{name}: {sub}.{key} 없음")
    for key, allowed in (("entity", "entity"), ("out_of_range", "out_of_range"), ("on_infeasible", "on_infeasible")):
        if key in task and task[key] not in sc["enums"][allowed]:
            p.append(f"{name}: {key} {task[key]!r}")
    learned = rule.get("learned", True)
    if learned:
        for key in sc["learned_required"]:
            if not task.get(key):
                p.append(f"{name}: 학습 과제 필수 {key} 없음")
        for f in task.get("features") or []:
            if f not in features:
                p.append(f"F5 {name}: 변수 {f!r} 가 features.yaml 에 없다")
        tname = (task.get("target") or {}).get("name") if isinstance(task.get("target"), dict) else None
        if tname and tname in (task.get("features") or []):
            p.append(f"{name}: 목표 {tname!r} 가 입력 변수에 있다(목표 누수, D-121)")
        if task.get("split") not in splits:
            p.append(f"{name}: split {task.get('split')!r}")
        if task.get("time_key") and task.get("split") not in sc["time_split_policies"]:
            p.append(f"{name}: time_key 가 있는데 split 이 시간순이 아니다(누수 규칙)")
        for c in task.get("candidates") or []:
            if c not in cands:
                p.append(f"{name}: 후보 {c!r} 가 std/candidates.yaml 에 없다")
            elif ttype not in cands[c]["types"]:
                p.append(f"{name}: 후보 {c!r} 는 {ttype} 용이 아니다")
    else:
        for u in task.get("uses") or []:
            short = u.split(".", 1)[-1]
            if not u.startswith(pack_code + ".") or short not in all_tasks:
                p.append(f"{name}: uses {u!r} 가 팩에 없다")
        if ttype == "review_queue":
            return p + _validate_review_queue(name, task, all_tasks, sc)
        if ttype == "extract":
            return p + _validate_extract(name, task, features, pack_path, sc, cands, splits)
        if ttype == "quote":
            return p + _validate_quote(name, task, pack_code, all_tasks, pack_path, sc)
        for f in (task.get("controls") or []) + (task.get("fixed") or []):
            if f not in features:
                p.append(f"{name}: 변수 {f!r} 가 features.yaml 에 없다")
        for f in task.get("controls") or []:
            if f in features and not features[f].get("controllable"):
                p.append(f"{name}: controls {f!r} 가 controllable 이 아니다")
        for c in task.get("constraints") or []:
            if not isinstance(c, dict) or not re.fullmatch(r"\s*[^<>=]+\s*(<=|>=|<|>)\s*[^<>=]+\s*", str(c.get("expr", ""))):
                p.append(f"{name}: 제약 식 모양 {c!r}")
        strat = (task.get("search") or {}).get("strategy")
        if strat not in sc["enums"]["search_strategy"]:
            p.append(f"{name}: search.strategy {strat!r}")
    return p


# ── 2차 유형 키 (contracts/task-contract.md §6.1 ~ §6.3, 웨이브 P 개발3) ───────────────────────────────
# 아래 표의 값은 계약 §6 본문 그대로다. task-schema 블록에 같은 이름의 키가 생기면 그 값을 쓴다(계약이 정본) —
# 아키텍트에 task-schema 로 옮기기를 요청해 두었다(decisions.md D2-30).
PHASE2_DEFAULTS: dict[str, Any] = {
    "review_rules": ["abs_residual_ge", "top_quantile"],          # §6.1 rule — 둘 중 하나
    "review_quantile_from": ["valid"],                            # §6.1 quantile_from 고정값
    "review_schedule": ["daily_after_monitor"],                   # §6.1 schedule
    "review_uses_types": ["regression", "risk"],
    "document_limits": {"max_bytes": 5242880, "max_entities": 20000},   # spec §8.3 상한 — 팩 · 회사는 낮추기만
    "document_formats": ["dxf"],
    "document_unit_override": ["mm", "inch"],
    "extract_outputs": ["regions", "objects", "bom_rows"],
    "extract_model_selection": ["macro_f1"],
    "quote_uses_types": ["regression"],
    "quote_confirm_requires": ["reviewed", "review_note"],
    "quote_review_note_min": 5,
}
DECIMAL_STR_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")            # predict-contract §8.3 rates 패턴(지수 표기 · float 금지)
MODULE_RE = {"extractors": re.compile(r"^extractors/([a-z][a-z0-9_]*)\.py$"),
             "formulas": re.compile(r"^formulas/([a-z][a-z0-9_]*)\.py$")}


def phase2_rule(sc: dict, key: str):
    return sc.get(key, PHASE2_DEFAULTS[key])


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _module_ok(task_name: str, kind: str, module, pack_path: Path | None) -> list[str]:
    m = MODULE_RE[kind].match(str(module or ""))
    if not m:
        return [f"{task_name}: {kind} module {module!r} 는 '{kind}/<이름>.py' 여야 한다"]
    if pack_path is not None and not (pack_path / module).is_file():
        return [f"{task_name}: {kind} module {module} 파일이 팩에 없다"]
    return []


def _uses_types(name: str, task: dict, all_tasks: dict, allowed: list[str], what: str) -> list[str]:
    uses = task.get("uses") or []
    if not isinstance(uses, list) or len(uses) != 1:
        return [f"{name}: {what} uses 는 과제 정확히 1개 (있음 {uses!r})"]
    dep = all_tasks.get(str(uses[0]).split(".", 1)[-1]) or {}
    if dep and dep.get("type") not in allowed:
        return [f"{name}: uses {uses[0]} 의 유형 {dep.get('type')!r} — {allowed} 만"]
    return []


def _validate_review_queue(name: str, task: dict, all_tasks: dict, sc: dict) -> list[str]:
    p = _uses_types(name, task, all_tasks, phase2_rule(sc, "review_uses_types"), "review_queue")
    rule = task.get("rule")
    kinds = phase2_rule(sc, "review_rules")
    if not isinstance(rule, dict) or len(rule) != 1 or next(iter(rule)) not in kinds:
        p.append(f"{name}: rule 은 {kinds} 중 정확히 하나의 {{종류: 값}} (있음 {rule!r})")
    else:
        kind, val = next(iter(rule.items()))
        if kind == "abs_residual_ge" and not (_is_number(val) and val > 0):
            p.append(f"{name}: rule.abs_residual_ge 는 양수 (있음 {val!r})")
        if kind == "top_quantile" and not (_is_number(val) and 0 < val < 1):
            p.append(f"{name}: rule.top_quantile 은 0 < q < 1 (있음 {val!r})")
        qf = task.get("quantile_from")
        if kind == "top_quantile" and qf not in phase2_rule(sc, "review_quantile_from"):
            p.append(f"{name}: top_quantile 이면 quantile_from: valid 필수 — 검증 구간 잔차 분위 (있음 {qf!r})")
        if kind == "abs_residual_ge" and qf is not None:
            p.append(f"{name}: abs_residual_ge 에는 quantile_from 을 두지 않는다 (있음 {qf!r})")
    origins = task.get("origins")
    allowed = sc["enums"]["review_origin"]
    if not isinstance(origins, list) or not origins or any(o not in allowed for o in origins) or len(set(origins)) != len(origins):
        p.append(f"{name}: origins 는 {allowed} 의 비지 않은 부분집합 — 학습 · 검증 구간 잔차 금지(G2-R01) (있음 {origins!r})")
    if "max_items" in task and not (isinstance(task["max_items"], int) and not isinstance(task["max_items"], bool)
                                    and task["max_items"] >= 1):
        p.append(f"{name}: max_items 는 1 이상 정수 (있음 {task['max_items']!r})")
    if "reason" in task and not isinstance(task["reason"], str):
        p.append(f"{name}: reason 은 문자열 틀")
    if "schedule" in task and task["schedule"] not in phase2_rule(sc, "review_schedule"):
        p.append(f"{name}: schedule {task['schedule']!r} — {phase2_rule(sc, 'review_schedule')} 만")
    return p


def validate_document(name: str, doc, sc: dict, ceiling: dict | None = None) -> list[str]:
    """document 상한 — spec 상한(또는 덮어쓰기 때는 팩 값 = ceiling)을 넘을 수 없다."""
    lim = ceiling or phase2_rule(sc, "document_limits")
    if not isinstance(doc, dict):
        return [f"{name}: document 는 map"]
    p = []
    for key in ("max_bytes", "max_entities"):
        v = doc.get(key)
        cap = lim.get(key)
        if not (isinstance(v, int) and not isinstance(v, bool) and 0 < v <= cap):
            p.append(f"{name}: document.{key} 는 1 ~ {cap} 정수 (있음 {v!r})")
    for key, rule_key in (("formats", "document_formats"), ("unit_override", "document_unit_override")):
        allowed = (ceiling or {}).get(key) or phase2_rule(sc, rule_key)
        v = doc.get(key, [] if key == "unit_override" else None)
        if not isinstance(v, list) or (key == "formats" and not v) or any(x not in allowed for x in v):
            p.append(f"{name}: document.{key} 는 {allowed} 의 부분집합 (있음 {v!r})")
    return p


def _validate_extract(name: str, task: dict, features: dict, pack_path: Path | None, sc: dict,
                      cands: dict, splits: dict) -> list[str]:
    p: list[str] = []
    if task.get("entity") != "drawing":
        p.append(f"{name}: extract 의 entity 는 drawing (있음 {task.get('entity')!r})")
    p += validate_document(name, task.get("document"), sc)
    exs = task.get("extractors")
    if not isinstance(exs, list) or not exs:
        return p + [f"{name}: extractors 는 1개 이상"]
    seen: set[str] = set()
    has_model = False
    for e in exs:
        if not isinstance(e, dict):
            p.append(f"{name}: extractors 항목 {e!r} 는 map")
            continue
        en = e.get("name")
        if not isinstance(en, str) or not NAME_RE.match(en):
            p.append(f"{name}: 추출기 name {en!r}")
        elif en in seen:
            p.append(f"{name}: 추출기 {en} 중복")
        seen.add(str(en))
        if e.get("kind") not in sc["enums"]["extractor_kind"]:
            p.append(f"{name}: 추출기 {en} kind {e.get('kind')!r} — {sc['enums']['extractor_kind']} 만")
        has_model = has_model or e.get("kind") == "model"
        p += _module_ok(name, "extractors", e.get("module"), pack_path)
        if MODULE_RE["extractors"].match(str(e.get("module") or "")) and \
                MODULE_RE["extractors"].match(str(e["module"])).group(1) != en:
            p.append(f"{name}: 추출기 {en} 의 module 이름이 다르다 ({e.get('module')})")
        if not isinstance(e.get("version"), str) or not e.get("version"):
            p.append(f"{name}: 추출기 {en} version 없음(문자열)")
    if task.get("labels") not in sc["enums"]["labels"]:
        p.append(f"{name}: labels {task.get('labels')!r} — {sc['enums']['labels']} 만")
    outs = task.get("outputs", [])
    allowed_out = phase2_rule(sc, "extract_outputs")
    if not isinstance(outs, list) or any(o not in allowed_out for o in outs):
        p.append(f"{name}: outputs 는 {allowed_out} 의 부분집합 (있음 {outs!r})")
    model = task.get("model")
    if has_model and not isinstance(model, dict):
        p.append(f"{name}: kind: model 추출기가 있으면 model 블록 필수")
    if isinstance(model, dict):
        for f in model.get("features") or ["<없음>"]:
            if f not in features:
                p.append(f"{name}: model.features 변수 {f!r} 가 features.yaml 에 없다")
        if not isinstance(model.get("classes"), list) or len(model.get("classes") or []) < 2:
            p.append(f"{name}: model.classes 는 2개 이상 목록")
        if model.get("split") != "stratified_60_20_20" or model.get("split") not in splits:
            p.append(f"{name}: model.split 은 stratified_60_20_20 (있음 {model.get('split')!r})")
        for c in model.get("candidates") or ["<없음>"]:
            if c not in cands or "extract" not in cands[c]["types"]:
                p.append(f"{name}: model.candidates {c!r} 는 extract 후보가 아니다")
        if model.get("selection") not in phase2_rule(sc, "extract_model_selection"):
            p.append(f"{name}: model.selection 은 macro_f1 (있음 {model.get('selection')!r})")
    return p


def validate_rates(name: str, rates) -> list[str]:
    if not isinstance(rates, dict) or not rates:
        return [f"{name}: rates 는 비지 않은 {{이름: \"10진 문자열\"}}"]
    bad = {k: v for k, v in rates.items() if not (isinstance(k, str) and NAME_RE.match(k)
                                                    and isinstance(v, str) and DECIMAL_STR_RE.match(v))}
    return [f"{name}: rates 값은 10진 문자열만(float · 지수 표기 금지 — G2-Q01) {bad!r}"] if bad else []


def _validate_quote(name: str, task: dict, pack_code: str, all_tasks: dict, pack_path: Path | None,
                    sc: dict) -> list[str]:
    p = _uses_types(name, task, all_tasks, phase2_rule(sc, "quote_uses_types"), "quote")
    fx = task.get("from_extract")
    if fx is not None:
        dep = all_tasks.get(str(fx).split(".", 1)[-1]) if str(fx).startswith(pack_code + ".") else None
        if not dep or dep.get("type") != "extract":
            p.append(f"{name}: from_extract {fx!r} 는 같은 팩의 extract 과제여야 한다")
        rec = task.get("recognized")
        if not isinstance(rec, dict) or not rec:
            p.append(f"{name}: from_extract 가 있으면 recognized 대응 필수")
    inputs = task.get("inputs")
    if not isinstance(inputs, list) or not inputs or not all(isinstance(x, str) and NAME_RE.match(x) for x in inputs):
        p.append(f"{name}: inputs 는 비지 않은 이름 목록")
    p += _module_ok(name, "formulas", task.get("formula"), pack_path)
    p += validate_rates(name, task.get("rates"))
    if task.get("rounding") not in sc["enums"]["rounding"]:
        p.append(f"{name}: rounding {task.get('rounding')!r} — {sc['enums']['rounding']} 만")
    if task.get("currency") not in sc["enums"]["currency"]:
        p.append(f"{name}: currency {task.get('currency')!r} — {sc['enums']['currency']} 만")
    conf = task.get("confirm")
    need = phase2_rule(sc, "quote_confirm_requires")
    if not isinstance(conf, dict):
        p.append(f"{name}: confirm 은 map")
    else:
        if not set(need) <= set(conf.get("requires") or []):
            p.append(f"{name}: confirm.requires 는 {need} 를 포함해야 한다")
        rmin = conf.get("review_note_min")
        if not (isinstance(rmin, int) and not isinstance(rmin, bool) and rmin >= phase2_rule(sc, "quote_review_note_min")):
            p.append(f"{name}: confirm.review_note_min 은 {phase2_rule(sc, 'quote_review_note_min')} 이상 정수")
        if not conf.get("approver_role"):
            p.append(f"{name}: confirm.approver_role 없음(확정 = approver 이상, D2-04)")
    if "csv" in task and not (isinstance(task["csv"], list) and all(isinstance(x, str) for x in task["csv"])):
        p.append(f"{name}: csv 는 열 이름 목록")
    return p


def load_pack(code: str, base: Path = PACKS_DIR) -> Pack:
    path = base / code
    problems: list[str] = []
    if not PACK_RE.match(code):
        problems.append(f"팩 코드 {code!r}")
    for f in ("pack.yaml", "features.yaml"):
        if not (path / f).is_file():
            problems.append(f"{f} 없음")
    if problems:
        raise PackInvalid(code, problems)
    meta = _yaml(path / "pack.yaml")
    raw_features = _yaml(path / "features.yaml")
    std_name = raw_features.pop("std_name", {}) or {}
    if meta.get("code") != code:
        problems.append(f"pack.yaml code {meta.get('code')!r} ≠ 폴더 {code!r}")
    problems += validate_features(raw_features)
    files = sorted(p.stem for p in (path / "tasks").glob("*.yaml"))
    declared = list(meta.get("tasks") or [])
    if sorted(declared) != files:
        problems.append(f"pack.yaml tasks {declared} ≠ tasks/*.yaml {files}")
    if len(files) < 2:
        problems.append("과제 < 2")
    tasks = {n: _yaml(path / "tasks" / f"{n}.yaml") for n in files}
    for n, t in tasks.items():
        problems += validate_task(n, t, code, raw_features, tasks, path)
    formulas = {p.stem: sha256_file(p) for p in sorted((path / "formulas").glob("*.py")) if p.stem != "__init__"}
    extractors = {p.stem: sha256_file(p) for p in sorted((path / "extractors").glob("*.py"))
                  if not p.stem.startswith("_")}
    problems += _validate_synth(path, meta)
    if problems:
        raise PackInvalid(code, problems)
    return Pack(code, path, meta, raw_features, std_name, tasks, formulas, extractors)


def all_codes(base: Path = PACKS_DIR) -> list[str]:
    return sorted(p.name for p in base.iterdir() if (p / "pack.yaml").is_file())


def terms(pack: Pack) -> set[str]:
    """코어 금지어 — 이 팩의 변수 이름 · 과제 이름 · 목표 이름 (G-M01)."""
    words = set(pack.features) | set(pack.tasks)
    for t in pack.tasks.values():
        tgt = t.get("target") or {}
        if tgt.get("name"):
            words.add(tgt["name"])
        words |= set((t.get("formulas") or {}).keys()) | set((t.get("decision_vars") or {}).keys())
    return words


# ── 합성 생성기 (contracts/pack-contract.md §4 · spec §4.2) ─────────────────────────────────
# 해석 순서: 과제 진입점 synth/<task>.py 가 있으면 그것, 없으면 pack.yaml synth.module (팩 공용 모듈).
# 생성 함수 모양: generate(rows: int, seed: int, *, categories: dict[str, list[str]] | None = None) -> DataFrame
# 반환 열: entity_id · ts(KST tz) · features.yaml 변수 · 목표 열(과제 target.name 이름 그대로, 여러 개일 수 있다).

@dataclass(frozen=True)
class SynthSpec:
    pack: str
    task: str | None            # 과제 짧은 이름(None = 팩 공용)
    path: Path                  # 실제로 읽는 .py
    seed: int                   # pack.yaml synth.seed
    rows: int                   # pack.yaml synth.rows


def _validate_synth(path: Path, meta: dict) -> list[str]:
    s = meta.get("synth") or {}
    mod, problems = s.get("module"), []
    if not mod:
        return ["pack.yaml synth.module 없음"]
    if not (path / mod).is_file():
        problems.append(f"synth.module {mod} 파일 없음")
    if not isinstance(s.get("seed"), int) or not isinstance(s.get("rows"), int) or s["rows"] <= 0:
        problems.append("pack.yaml synth.seed · rows 는 정수")
    return problems


def synth_spec(pack: Pack, task: str | None = None) -> SynthSpec:
    s = pack.meta.get("synth") or {}
    if task is not None and task not in pack.tasks:
        raise KeyError(f"{pack.code}: 과제 {task!r} 없음")
    own = pack.path / "synth" / f"{task}.py" if task else None
    path = own if own is not None and own.is_file() else pack.path / s["module"]
    return SynthSpec(pack.code, task, path, int(s["seed"]), int(s["rows"]))


def _synth_package(pack: Pack) -> str:
    """팩 synth/ 폴더를 고유 이름의 패키지로 올린다(과제 진입점이 공용 모듈을 상대 import 한다)."""
    synth_dir = pack.path / "synth"
    name = "mlcore_pack_synth_" + hashlib.sha256(str(synth_dir.resolve()).encode()).hexdigest()[:12]
    if name not in sys.modules:
        init = synth_dir / "__init__.py"
        spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(synth_dir)])
        if spec is None or spec.loader is None:
            raise ImportError(f"{pack.code}: synth/__init__.py 를 읽을 수 없다")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


def load_synth(pack: Pack, task: str | None = None) -> Callable[..., Any]:
    """합성 생성 함수 `generate` 를 돌려준다. 원천 코드를 부르지 않는다 — 팩 안의 이관본만."""
    spec = synth_spec(pack, task)
    module = importlib.import_module(f"{_synth_package(pack)}.{spec.path.stem}")
    fn = getattr(module, "generate", None)
    if not callable(fn):
        raise ImportError(f"{spec.path}: generate() 없음")
    return fn
