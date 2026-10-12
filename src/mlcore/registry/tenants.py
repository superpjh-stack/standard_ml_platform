"""회사 등록부 로더 · 병합 규칙 5 (contracts/tenant-contract.md · spec §11.3).

Phase 0 아키텍트 초안 — 이후 소유는 개발3. 위반은 RegistryRejected 로 기동을 거부한다.
R4(live + 합성 production)만은 spec §11.3-4 대로 "그 과제만 끈다" (decisions.md D-27).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..settings import ROOT
from .packs import PACKS_DIR, Pack, def_hash, load_pack, sha256_file, task_schema

TENANTS_DIR = ROOT / "tenants"
CODE_RE = re.compile(r"^[a-z][a-z0-9]{1,7}$")
ENV_RE = re.compile(r"^MLP_[A-Z0-9_]+$")
TEMPLATE_CODE = "tpl"                       # _template.yaml 검증용 대입 코드


class RegistryRejected(Exception):
    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule, self.detail = rule, detail


@dataclass
class Tenant:
    code: str
    path: Path
    config: dict
    overrides: dict[str, dict] = field(default_factory=dict)    # 과제 짧은 이름 → 덮어쓰기 YAML
    formulas: dict[str, str] = field(default_factory=dict)      # 회사 플러그인 이름 → sha256


@dataclass(frozen=True)
class TaskDef:
    id: str
    pack_id: str
    type: str
    raw: dict
    def_hash: str


@dataclass
class Merged:
    tenant: Tenant
    pack: Pack
    tasks: dict[str, TaskDef]
    disabled: dict[str, str]
    warnings: list[str]


def _env_names(obj, path="") -> list[tuple[str, object]]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.endswith("_env"):
                out.append((f"{path}.{k}", v))
            out += _env_names(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _env_names(v, f"{path}[{i}]")
    return out


def load_tenant(code_or_path: str | Path, base: Path = TENANTS_DIR) -> Tenant:
    path = Path(code_or_path) if isinstance(code_or_path, Path) or str(code_or_path).endswith(".yaml") else base / f"{code_or_path}.yaml"
    text = path.read_text(encoding="utf-8")
    is_template = path.stem == "_template"
    if is_template:
        text = text.replace("__code__", TEMPLATE_CODE).replace("__name__", "템플릿")
    cfg = yaml.safe_load(text) or {}
    code = cfg.get("code")
    expected = TEMPLATE_CODE if is_template else path.stem
    if path.name == "tenant.yaml":           # 불량 픽스처 폴더 형식
        expected = code
    if not isinstance(code, str) or not CODE_RE.match(code) or code != expected:
        raise RegistryRejected("T0", f"code {code!r} ≠ 파일 이름 {expected!r}")
    for key in ("name", "pack", "mode", "tasks"):
        if not cfg.get(key):
            raise RegistryRejected("T0", f"필수 키 {key} 없음")
    if cfg["mode"] not in ("demo", "eval", "live"):
        raise RegistryRejected("T0", f"mode {cfg['mode']!r}")
    for where, val in _env_names(cfg):
        if val is not None and (not isinstance(val, str) or not ENV_RE.match(val)):
            raise RegistryRejected("T1", f"{where} 는 MLP_ 환경변수 이름이어야 한다")
    overrides, formulas = {}, {}
    # 덮어쓰기 위치: tenants/<code>/tasks/ (불량 픽스처 폴더는 <dir>/tasks/)
    task_dir = (path.parent / "tasks") if path.name == "tenant.yaml" else (path.parent / path.stem / "tasks")
    for p in sorted(task_dir.glob("*.yaml")) if task_dir.is_dir() else []:
        overrides[p.stem] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    f_dir = task_dir.parent / "formulas"
    for p in sorted(f_dir.glob("*.py")) if f_dir.is_dir() else []:
        formulas[p.stem] = sha256_file(p)
    return Tenant(code, path, cfg, overrides, formulas)


def all_codes(base: Path = TENANTS_DIR, include_template: bool = False) -> list[str]:
    codes = sorted(p.stem for p in base.glob("*.yaml"))
    return [c for c in codes if include_template or not c.startswith("_")]


def _apply_override(name: str, base: dict, over: dict) -> dict:
    """R1 — 덮어쓸 수 없는 키를 바꾸면 거부."""
    sc = task_schema()
    for key in sc["immutable_on_override"]:
        if key in over and over[key] != base.get(key):
            raise RegistryRejected("R1", f"{name}: 덮어쓰기로 {key} 를 바꿀 수 없다")
    for key in sc["not_removable_on_override"]:
        if key in over and not over[key]:
            raise RegistryRejected("R1", f"{name}: {key} 를 지울 수 없다(승인 지점)")
    if "id" in over and over["id"] != base.get("id"):
        raise RegistryRejected("R1", f"{name}: id 를 바꿀 수 없다")
    merged = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


def merge(pack: Pack, tenant: Tenant,
          production_synthetic: Callable[[str], bool | None] | None = None) -> Merged:
    cfg = tenant.config
    if cfg["pack"] != pack.code:
        raise RegistryRejected("T0", f"pack {cfg['pack']!r} ≠ {pack.code!r}")
    enabled = list((cfg.get("tasks") or {}).get("enable") or [])
    short: dict[str, str] = {}
    for full in enabled:
        code, _, name = full.partition(".")
        if code != tenant.code or name not in pack.tasks:
            raise RegistryRejected("T0", f"켜진 과제 {full!r} 가 팩 {pack.code} 에 없다")
        short[name] = full
    for name in tenant.overrides:
        if name not in pack.tasks:
            raise RegistryRejected("T0", f"덮어쓰기 {name!r} 가 팩에 없다")

    mode = cfg["mode"]
    sources = cfg.get("sources") or {}
    has_synth = mode != "live" and any((s or {}).get("kind") == "synthetic" for s in sources.values())
    mapped = set((cfg.get("feature_map") or {}).values())
    categories = cfg.get("categories") or {}
    warnings: list[str] = []
    tasks: dict[str, TaskDef] = {}
    disabled: dict[str, str] = {}

    for name, full in short.items():
        raw = _apply_override(name, pack.tasks[name], tenant.overrides.get(name, {}))
        # R2 — 켜진 과제의 변수가 feature_map 또는 합성 소스로 채워지는가
        feats = list(raw.get("features") or []) + list(raw.get("fixed") or []) + list(raw.get("controls") or [])
        for f in dict.fromkeys(feats):
            fdef = pack.features.get(f, {})
            if fdef.get("values_from") == "tenant" and not categories.get(f):
                raise RegistryRejected("R2", f"{full}: 범주 {f} 값 목록(categories)이 없다")
            if f in mapped or has_synth:
                continue
            if fdef.get("required", True):
                raise RegistryRejected("R2", f"{full}: 필수 변수 {f} 를 채울 원천이 없다")
            warnings.append(f"{full}: 선택 변수 {f} 미대응 (doctor 경고)")
        # R3 — uses 의존 과제가 켜져 있는가
        for u in raw.get("uses") or []:
            if u.split(".", 1)[-1] not in short:
                raise RegistryRejected("R3", f"{full}: 의존 과제 {u} 가 꺼져 있다")
        # R5 — 같은 이름 · 다른 구현의 플러그인
        for fname, module in (raw.get("formulas") or {}).items():
            if module in tenant.formulas and module in pack.formulas and tenant.formulas[module] != pack.formulas[module]:
                raise RegistryRejected("R5", f"{full}: 비용식 {module} 이 팩과 회사에 다른 구현으로 있다")
        # R4 — live 인데 production 이 합성 스냅숏이면 그 과제만 끈다
        if mode == "live" and production_synthetic and production_synthetic(full):
            disabled[full] = "model_not_ready: live 회사의 합성 스냅숏 모델"
            continue
        tasks[full] = TaskDef(full, raw["id"], raw["type"], raw, def_hash(raw))
    for module, digest in tenant.formulas.items():
        if module in pack.formulas and pack.formulas[module] != digest:
            raise RegistryRejected("R5", f"비용식 {module} 이 팩과 회사에 다른 구현으로 있다")
    return Merged(tenant, pack, tasks, disabled, warnings)


def load_and_merge(code: str, *, tenants_base: Path = TENANTS_DIR, packs_base: Path = PACKS_DIR,
                   production_synthetic: Callable[[str], bool | None] | None = None) -> Merged:
    t = load_tenant(code, tenants_base)
    return merge(load_pack(t.config["pack"], packs_base), t, production_synthetic)
