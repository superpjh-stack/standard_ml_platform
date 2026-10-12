"""회사 등록부 로더 · 병합 규칙 5 (contracts/tenant-contract.md · spec §11.3).

Phase 0 아키텍트 초안 — 이후 소유는 개발3. 위반은 RegistryRejected 로 기동을 거부한다.
R4(live + 합성 production)만은 spec §11.3-4 대로 "그 과제만 끈다" (decisions.md D-27).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..settings import ROOT
from .packs import PACKS_DIR, Pack, SynthSpec, def_hash, load_pack, load_synth, sha256_file, synth_spec, task_schema

TENANTS_DIR = ROOT / "tenants"
TENANTS_ENV = "MLP_TENANTS_DIR"            # 등록부 루트 덮어쓰기(시험 · 새 회사 연습을 임시 폴더로 격리 — G-M10)


def tenants_dirs() -> list[Path]:
    """MLP_TENANTS_DIR 의 폴더 목록(os.pathsep 로 여러 개, 호출 시점). 없으면 빈 목록."""
    return [Path(x) for x in (os.environ.get(TENANTS_ENV) or "").split(os.pathsep) if x]


def tenants_dir() -> Path:
    """등록부 루트(새 회사를 만드는 곳 · 회사 목록을 세는 곳) — MLP_TENANTS_DIR 의 첫 폴더, 없으면 저장소 tenants/."""
    dirs = tenants_dirs()
    return dirs[0] if dirs else TENANTS_DIR


def tenant_base(code: str) -> Path:
    """회사 하나의 등록부 폴더 — MLP_TENANTS_DIR 목록 중 `<code>.yaml` 이 있는 첫 폴더, 없으면 저장소 tenants/.
    `mlcore.data.jobs.tenants_base_for` 와 같은 규칙(decisions.md D-W1-06)."""
    for d in tenants_dirs():
        if (d / f"{code}.yaml").is_file():
            return d
    return TENANTS_DIR
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


def load_tenant(code_or_path: str | Path, base: Path | None = None) -> Tenant:
    is_path = isinstance(code_or_path, Path) or str(code_or_path).endswith(".yaml")
    if base is None and not is_path:
        base = tenant_base(str(code_or_path))
    path = Path(code_or_path) if is_path else Path(base) / f"{code_or_path}.yaml"
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


def all_codes(base: Path | None = None, include_template: bool = False) -> list[str]:
    """등록부의 회사 코드. MLP_TENANTS_DIR 가 있으면 그 폴더들만(시험 · 새 회사 격리), 없으면 저장소 tenants/."""
    bases = [Path(base)] if base is not None else (tenants_dirs() or [TENANTS_DIR])
    codes = sorted({p.stem for b in bases for p in b.glob("*.yaml")})
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


def load_and_merge(code: str, *, tenants_base: Path | None = None, packs_base: Path = PACKS_DIR,
                   production_synthetic: Callable[[str], bool | None] | None = None) -> Merged:
    t = load_tenant(code, tenants_base)
    return merge(load_pack(t.config["pack"], packs_base), t, production_synthetic)


# ── 합성 소스 해석 (synthetic 어댑터가 쓴다 — progress-dev3.md §1) ──────────────────────────

@dataclass(frozen=True)
class SynthCall:
    """회사 · 과제 하나의 합성 생성 호출. 시드는 회사 sources.<role>.seed > pack.yaml synth.seed."""
    tenant_id: str
    task_id: str                          # <tenant>.<task>
    spec: SynthSpec
    seed: int
    rows: int
    categories: dict[str, list[str]]      # 회사 등록부 categories (values_from: tenant 범주)
    target: str | None                    # 과제 target.name — 생성 프레임의 목표 열 이름(anomaly 는 None)
    source_ref: dict                      # 스냅숏 source_ref 에 그대로 넣을 값(경로는 저장소 상대)
    pack: Pack = field(repr=False, compare=False, hash=False, default=None)  # type: ignore[assignment]

    def generate(self, rows: int | None = None, seed: int | None = None):
        """pandas.DataFrame — entity_id · ts · 변수 · 목표 열(들). 표준 프레임 열 추가는 어댑터 몫."""
        fn = load_synth(self.pack, self.spec.task)
        return fn(rows if rows is not None else self.rows, seed if seed is not None else self.seed,
                  categories=self.categories or None)


def synth_call(merged: Merged, task_id: str, role: str = "demo") -> SynthCall:
    """켜진 과제 task_id 의 합성 생성 호출을 만든다. role 소스가 synthetic 이 아니면 ValueError."""
    if task_id not in merged.tasks:
        raise KeyError(f"{task_id}: 켜진 과제가 아니다")
    src = (merged.tenant.config.get("sources") or {}).get(role) or {}
    if src.get("kind") != "synthetic":
        raise ValueError(f"{merged.tenant.code}: sources.{role} 가 synthetic 이 아니다")
    task = merged.tasks[task_id]
    short = task.pack_id.split(".", 1)[1]
    spec = synth_spec(merged.pack, short)
    seed = int(src["seed"]) if src.get("seed") is not None else spec.seed
    rows = int(src["rows"]) if src.get("rows") is not None else spec.rows
    cats = {k: list(v) for k, v in (merged.tenant.config.get("categories") or {}).items()}
    target = ((task.raw.get("target") or {}).get("name"))
    try:
        rel_path = str(spec.path.resolve().relative_to(ROOT))
    except ValueError:
        rel_path = str(spec.path)
    digest = hashlib.sha256()
    for f in sorted((spec.path.parent).glob("*.py")):          # 진입점 + 공용 모듈 전부
        digest.update(f.name.encode() + b"\0" + f.read_bytes())
    ref = {"kind": "synthetic", "role": role, "module": rel_path, "seed": seed, "rows": rows,
           "synth_sha256": digest.hexdigest()}
    return SynthCall(merged.tenant.code, task_id, spec, seed, rows, cats, target, ref, merged.pack)


# ── 새 회사 (make tenant NEW=<code> PACK=<pack> [CSV=<path>] — G-M10 · spec §17-9 · D-51) ────────────

class TenantExists(Exception):
    pass


def scaffold(code: str, pack: str = "_template", *, csv: str | Path | None = None, name: str | None = None,
             base: Path | None = None, packs_base: Path = PACKS_DIR) -> Path:
    """`tenants/_template.yaml` 을 복사해 `<base>/<code>.yaml` **하나만** 만든다(코드 수정 0줄).

    - `pack` 의 `pack.yaml tasks` 를 전부 켠다(`<code>.<task>`). `values_from: tenant` 범주는 빈 목록 + `# 미확인`
      (값을 지어내지 않는다 — 비어 있으면 병합 규칙 R2 가 거부한다).
    - `csv` 를 주면 `sources.eval.path` 가 그 파일(절대 경로)을 가리키고 `mode: eval` 이다. CSV 는 복사하지 않는다(T4).
    - 만든 뒤 병합 규칙 5 로 다시 읽어 보고, 거부되면 파일을 지우고 RegistryRejected 를 올린다.
    """
    base = tenants_dir() if base is None else base
    if not CODE_RE.match(code or "") or code == TEMPLATE_CODE:
        raise RegistryRejected("T0", f"회사 코드 {code!r} 는 ^[a-z][a-z0-9]{{1,7}}$ 이어야 한다")
    target = base / f"{code}.yaml"
    if target.exists() or (base / code).exists():
        raise TenantExists(f"{target.name} 가 이미 있다 — 덮어쓰지 않는다")
    p = load_pack(pack, packs_base)
    text = (TENANTS_DIR / "_template.yaml").read_text(encoding="utf-8")
    head = (f"# 회사 등록부 — `make tenant NEW={code} PACK={pack}` 로 만들었다 (contracts/tenant-contract.md).\n"
            "# 비밀값은 환경변수 이름만(MLP_<CODE>_*). 확인 못 한 값은 null + \"# 미확인\".\n")
    text = re.sub(r"\A(#[^\n]*\n)+", head, text)
    text = text.replace("__code__", code)
    text = re.sub(r"^name: __name__[^\n]*", f"name: {name}" if name else f"name: {code}                      # 미확인",
                  text, flags=re.M)
    text = re.sub(r"^pack: \S+", f"pack: {pack}", text, flags=re.M)
    enable = ", ".join(f"{code}.{t}" for t in p.meta.get("tasks") or sorted(p.tasks))
    text = re.sub(r"^  enable: \[[^\]]*\]", f"  enable: [{enable}]", text, flags=re.M)
    cats = [f for f, d in p.features.items() if isinstance(d, dict) and d.get("values_from") == "tenant"]
    if cats:
        body = "\n".join(f"  {f}: []                    # 미확인 — 회사 값 목록" for f in cats)
        text = re.sub(r"^categories: \{\}", "categories:\n" + body, text, flags=re.M)
    if csv is not None:
        path = json.dumps(str(Path(csv).resolve()), ensure_ascii=False)     # YAML 큰따옴표 문자열(공백 · : 안전)
        text = re.sub(r"^(  eval:\s+\{kind: csv, path: )[^}]*\}", lambda m: f"{m.group(1)}{path}}}", text, flags=re.M)
        text = re.sub(r"^mode: \w+", "mode: eval", text, flags=re.M)
    base.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    try:
        load_and_merge(code, tenants_base=base, packs_base=packs_base)
    except Exception:
        target.unlink()
        raise
    return target
