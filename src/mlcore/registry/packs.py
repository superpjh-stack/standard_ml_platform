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


def validate_task(name: str, task: dict, pack_code: str, features: dict, all_tasks: dict) -> list[str]:
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
        problems += validate_task(n, t, code, raw_features, tasks)
    formulas = {p.stem: sha256_file(p) for p in sorted((path / "formulas").glob("*.py")) if p.stem != "__init__"}
    problems += _validate_synth(path, meta)
    if problems:
        raise PackInvalid(code, problems)
    return Pack(code, path, meta, raw_features, std_name, tasks, formulas)


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
