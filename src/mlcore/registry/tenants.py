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
from . import packs as _packs
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
    extractors: dict[str, str] = field(default_factory=dict)    # 회사 추출기 플러그인 이름 → sha256 (R5)


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
    e_dir = task_dir.parent / "extractors"
    extractors = {p.stem: sha256_file(p) for p in sorted(e_dir.glob("*.py")) if not p.stem.startswith("_")} \
        if e_dir.is_dir() else {}
    _check_aliases(cfg)
    return Tenant(code, path, cfg, overrides, formulas, extractors)


# ── material_aliases (tenant-contract §3 — 2차 새 최상위 키, 범주 값 정규화 표) ───────────────────────

ALIASES_KEY = "material_aliases"


def _check_aliases(cfg: dict) -> None:
    """{<별칭>: <정규 값>} — 정규 값은 회사 categories 의 값이어야 하고, 정규 값 자체를 별칭으로 두지 않는다."""
    if ALIASES_KEY not in cfg or cfg[ALIASES_KEY] in (None, {}):
        return
    table = cfg[ALIASES_KEY]
    if not isinstance(table, dict):
        raise RegistryRejected("T0", f"{ALIASES_KEY} 는 {{별칭: 정규 값}} 표여야 한다")
    canon = {str(v) for vals in (cfg.get("categories") or {}).values() for v in (vals or [])}
    for alias, value in table.items():
        if not isinstance(alias, str) or not alias.strip() or not isinstance(value, str) or not value.strip():
            raise RegistryRejected("T0", f"{ALIASES_KEY}: 별칭 · 정규 값은 비지 않은 문자열 ({alias!r}: {value!r})")
        if value not in canon:
            raise RegistryRejected("T0", f"{ALIASES_KEY}: 정규 값 {value!r} 가 회사 categories 에 없다")
        if alias in canon or alias.upper() in {c.upper() for c in canon}:
            raise RegistryRejected("T0", f"{ALIASES_KEY}: {alias!r} 는 정규 값이라 별칭으로 둘 수 없다")


def material_aliases(merged: "Merged") -> dict[str, str]:
    """회사 별칭 표(대문자 키). 추출기 · 견적 입력 검증 전에 적용한다(tenant-contract §3)."""
    return {str(k).upper(): str(v) for k, v in (merged.tenant.config.get(ALIASES_KEY) or {}).items()}


def normalize_category(merged: "Merged", value: str) -> str:
    """원천 재질 규칙(대문자 비교 + 별칭 통합). 모르는 값은 그대로 돌려준다 — 거부는 검증 단계 몫."""
    table = material_aliases(merged)
    key = str(value).strip().upper()
    if key in table:
        return table[key]
    canon = {str(v).upper(): str(v) for vals in (merged.tenant.config.get("categories") or {}).values() for v in vals or []}
    return canon.get(key, value)


def all_codes(base: Path | None = None, include_template: bool = False) -> list[str]:
    """등록부의 회사 코드. MLP_TENANTS_DIR 가 있으면 그 폴더들만(시험 · 새 회사 격리), 없으면 저장소 tenants/."""
    bases = [Path(base)] if base is not None else (tenants_dirs() or [TENANTS_DIR])
    codes = sorted({p.stem for b in bases for p in b.glob("*.yaml")})
    return [c for c in codes if include_template or not c.startswith("_")]


# R1 보강(D-121) — tenant-contract R1 "승인 지점(approver_role)을 바꿀 수 없다" · 목표는 팩 정의(누수 방지).
# task-contract §4 immutable_on_override 에도 있다(D-121). 여기서는 병합 결과로 비교한다(부분 dict 덮어쓰기 · 지우기 포함).
FIXED_ON_OVERRIDE = ("approver_role", "target")


# task-contract §3 "바꿀 수 있다" + §6.4(2차). 이 밖의 키(오타 · `auto_promote` 같은 모르는 키)는 R1 거부 — DEF-QAR2-004.
# 계약 task-schema 블록에 `overridable_on_override` 가 생기면 그 값을 쓴다(아키텍트 요청 D2-30).
OVERRIDABLE = ("thresholds", "features", "candidates", "candidate_params", "constraints", "params", "monitor", "notice",
               "title", "rule", "max_items", "reason", "document", "rates", "csv", "recognized")
# 같은 값으로 다시 적는 것만 허용(바꾸면 R1) — 계약 §4 immutable 목록 + §6.4 의 `quantile_from` · `confirm`.
SAME_VALUE_ONLY = ("id", "quantile_from", "confirm")


def _check_override_keys(name: str, base: dict, over: dict, sc: dict) -> None:
    allowed = set(sc.get("overridable_on_override") or OVERRIDABLE) | set(sc["immutable_on_override"]) | set(SAME_VALUE_ONLY)
    unknown = sorted(str(k) for k in over if k not in allowed)
    if unknown:
        raise RegistryRejected("R1", f"{name}: 모르는 덮어쓰기 키 {unknown} — 바꿀 수 있는 키만 "
                                     f"({', '.join(sc.get('overridable_on_override') or OVERRIDABLE)})")
    for key in SAME_VALUE_ONLY:
        if key in over and over[key] != base.get(key):
            raise RegistryRejected("R1", f"{name}: 덮어쓰기로 {key} 를 바꿀 수 없다")


def _phase2_override(name: str, base: dict, over: dict, sc: dict) -> dict:
    """§6.4 — 대기열 rule 은 같은 종류 안의 값만 · document 상한은 낮추기만 · rates 는 값만 · recognized 는 tolerance 만.
    병합할 값(dict 키 → 새 값)을 돌려준다. rule 은 통째로 바꾼다(종류 하나라 dict 합치기를 하지 않는다)."""
    out: dict = {}
    if "rule" in over:
        r, b = over["rule"], base.get("rule") or {}
        if not isinstance(r, dict) or set(r) != set(b):
            raise RegistryRejected("R1", f"{name}: rule 은 같은 종류({sorted(b)}) 안에서 값만 바꿀 수 있다 (있음 {r!r})")
        out["rule"] = dict(r)
    if "document" in over:
        d, b = over["document"], base.get("document") or {}
        if not isinstance(d, dict):
            raise RegistryRejected("R1", f"{name}: document 덮어쓰기는 map")
        merged = {**b, **d}
        probs = _packs.validate_document(name, merged, sc, ceiling=b)
        if probs:
            raise RegistryRejected("R1", f"{name}: document 상한은 낮추기만 — {probs[0]}")
        out["document"] = merged
    if "rates" in over:
        r, b = over["rates"], base.get("rates") or {}
        if not isinstance(r, dict) or set(r) - set(b):
            extra = sorted(set(r) - set(b)) if isinstance(r, dict) else r
            raise RegistryRejected("R1", f"{name}: rates 는 팩 단가 이름의 값만 덮어쓴다 (새 이름 {extra})")
        tables = set((base.get("rate_tables") or {}))
        merged_r = {**b}
        for k, v in r.items():            # 단가표(rate_tables)는 칸(회사 범주 값)을 채운다 — 이름은 팩 것만
            merged_r[k] = {**(b.get(k) or {}), **v} if k in tables and isinstance(v, dict) else v
        probs = _packs.validate_rates(name, merged_r, tables)
        if probs:
            raise RegistryRejected("R1", f"{name}: rates — {probs[0]}")
        out["rates"] = merged_r
    if "recognized" in over:
        r, b = over["recognized"], base.get("recognized") or {}
        if not isinstance(r, dict) or any(k != "tolerance" and r[k] != b.get(k) for k in r):
            raise RegistryRejected("R1", f"{name}: recognized 는 tolerance 만 바꿀 수 있다 (있음 {r!r})")
        out["recognized"] = {**b, **r}
    return out


def _apply_override(name: str, base: dict, over: dict, pack: Pack | None = None) -> dict:
    """R1 — 덮어쓸 수 없는 키를 바꾸거나 모르는 키를 쓰면 거부. 병합 결과는 과제 계약으로 다시 검사한다."""
    sc = task_schema()
    _check_override_keys(name, base, over, sc)
    for key in sc["immutable_on_override"]:
        if key in over and over[key] != base.get(key):
            raise RegistryRejected("R1", f"{name}: 덮어쓰기로 {key} 를 바꿀 수 없다")
    for key in sc["not_removable_on_override"]:
        if key in over and not over[key]:
            raise RegistryRejected("R1", f"{name}: {key} 를 지울 수 없다(승인 지점)")
    if "id" in over and over["id"] != base.get("id"):
        raise RegistryRejected("R1", f"{name}: id 를 바꿀 수 없다")
    merged = copy.deepcopy(base)
    special = _phase2_override(name, base, over, sc)
    for k, v in over.items():
        if k in special:
            merged[k] = special[k]
        elif isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    for key in FIXED_ON_OVERRIDE:            # 같은 값을 다시 적는 것은 허용, 값이 달라지면 거부(지우기 포함)
        if key in over and merged.get(key) != base.get(key):
            what = "승인 지점" if key == "approver_role" else "목표 — 팩 정의만"
            raise RegistryRejected("R1", f"{name}: 덮어쓰기로 {key} 를 바꿀 수 없다({what})")
    _check_target_leak(name, merged)
    if over and pack is not None:              # 병합 결과도 과제 계약을 지킨다(예: rule 값 범위 · 없는 변수 추가)
        probs = _packs.validate_task(name, merged, pack.code, pack.features, pack.tasks, pack.path)
        if probs:
            raise RegistryRejected("R1", f"{name}: 덮어쓴 결과가 과제 계약 위반 — {probs[0]}")
    return merged


def _check_target_leak(name: str, task: dict) -> None:
    """R1 — 목표 열이 입력(features · fixed · controls)에 있으면 거부(목표 누수, DEF-QA1-004)."""
    tname = (task.get("target") or {}).get("name") if isinstance(task.get("target"), dict) else None
    inputs = set(task.get("features") or []) | set(task.get("fixed") or []) | set(task.get("controls") or [])
    if tname and tname in inputs:
        raise RegistryRejected("R1", f"{name}: 목표 target {tname!r} 가 입력 변수에 있다(목표 누수)")


def _check_compat_routes(cfg: dict, task_types: dict[str, str]) -> None:
    """compat.routes 객체 항목(2차 호환 경로) — 호환 라우터와 같은 표(serve/compat_routes.py)로 기동 때 검사(T0)."""
    from ..serve.compat_routes import CompatConfigError, check_routes
    try:
        check_routes((cfg.get("compat") or {}).get("routes"), task_types)
    except CompatConfigError as e:
        raise RegistryRejected("T0", str(e)) from None


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
    _check_compat_routes(cfg, {n: pack.tasks[n].get("type") for n in short})

    mode = cfg["mode"]
    sources = cfg.get("sources") or {}
    has_synth = mode != "live" and any((s or {}).get("kind") == "synthetic" for s in sources.values())
    mapped = set((cfg.get("feature_map") or {}).values())
    categories = cfg.get("categories") or {}
    warnings: list[str] = []
    tasks: dict[str, TaskDef] = {}
    disabled: dict[str, str] = {}

    for name, full in short.items():
        raw = _apply_override(name, pack.tasks[name], tenant.overrides.get(name, {}), pack)
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
        for u in list(raw.get("uses") or []) + list(raw.get("warn_with") or []):     # warn_with 도 의존 과제(D-76)
            if u.split(".", 1)[-1] not in short:
                raise RegistryRejected("R3", f"{full}: 의존 과제 {u} 가 꺼져 있다")
        # R2 — 견적 단가표(rate_tables: {단가 이름: 범주 변수})는 회사 범주 값마다 한 칸 · 남는 칸 없음 (D2-45)
        for tbl, var in (raw.get("rate_tables") or {}).items():
            want = {str(v) for v in (categories.get(var) or [])}
            have = set(((raw.get("rates") or {}).get(tbl) or {}))
            if not want:
                raise RegistryRejected("R2", f"{full}: 단가표 {tbl} 의 범주 {var} 값 목록(categories)이 없다")
            if have != want:
                raise RegistryRejected("R2", f"{full}: 단가표 {tbl} 칸이 회사 범주 {var} 와 다르다 "
                                             f"(없음 {sorted(want - have)} · 남음 {sorted(have - want)})")
        # R5 — 같은 이름 · 다른 구현의 플러그인
        for fname, module in (raw.get("formulas") or {}).items():
            if module in tenant.formulas and module in pack.formulas and tenant.formulas[module] != pack.formulas[module]:
                raise RegistryRejected("R5", f"{full}: 비용식 {module} 이 팩과 회사에 다른 구현으로 있다")
        # R4 — live 인데 production 이 합성 스냅숏이면 그 과제만 끈다. 확인할 수 없으면 켜지 않는다(D-120)
        if mode == "live" and production_synthetic is not None:
            try:
                is_synth = production_synthetic(full)
            except ProductionUnknown as e:
                disabled[full] = f"model_not_ready: production 스냅숏을 확인할 수 없다 ({e})"
                continue
            if is_synth:
                disabled[full] = "model_not_ready: live 회사의 합성 스냅숏 모델"
                continue
        tasks[full] = TaskDef(full, raw["id"], raw["type"], raw, def_hash(raw))
    for module, digest in tenant.formulas.items():
        if module in pack.formulas and pack.formulas[module] != digest:
            raise RegistryRejected("R5", f"비용식 {module} 이 팩과 회사에 다른 구현으로 있다")
    for module, digest in tenant.extractors.items():
        if module in pack.extractors and pack.extractors[module] != digest:
            raise RegistryRejected("R5", f"추출기 {module} 이 팩과 회사에 다른 구현으로 있다")
    return Merged(tenant, pack, tasks, disabled, warnings)


def load_and_merge(code: str, *, tenants_base: Path | None = None, packs_base: Path = PACKS_DIR,
                   production_synthetic: Callable[[str], bool | None] | None = None) -> Merged:
    t = load_tenant(code, tenants_base)
    return merge(load_pack(t.config["pack"], packs_base), t, production_synthetic)


# ── R4 실경로 — 등록부 DB 의 production 스냅숏 synthetic (DEF-QA3-001 · D-120) ──────────────────

class ProductionUnknown(Exception):
    """등록부 DB 에서 production 모델의 스냅숏을 읽을 수 없다 — live 과제는 켜지 않는다(fail closed)."""


class ProductionLookup:
    """`merge(production_synthetic=)` 콜백 — 과제 → production 의 스냅숏이 합성인가(True/False), production 없음 None.

    처음 부를 때 한 번 회사 production 전부를 읽는다(mlp_model_version ⋈ mlp_snapshot, 둘 중 하나라도 synthetic 이면 합성).
    live 회사가 아니면 merge 가 부르지 않으므로 demo · eval 기동은 DB 를 보지 않는다. `rows` 는 시험 · 게이트용 주입값.
    """

    SQL = ("SELECT mv.task_id, (mv.synthetic OR coalesce(s.synthetic, true)) AS synthetic "
           "FROM mlp_model_version mv LEFT JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id "
           "WHERE mv.tenant_id = %s AND mv.stage = 'production'")

    def __init__(self, tenant_id: str, rows: dict[str, bool] | None = None):
        self.tenant_id = tenant_id
        self._rows = dict(rows) if rows is not None else None

    def _load(self) -> dict[str, bool]:
        if self._rows is None:
            from ..db.conn import connect          # 지연 import — 등록부 로더가 DB 없이도 import 되게
            try:
                with connect() as c:
                    self._rows = {r["task_id"]: bool(r["synthetic"]) for r in c.execute(self.SQL, (self.tenant_id,))}
            except Exception as e:  # noqa: BLE001 — DB 없음 · 스키마 없음 모두 '확인 불가'(값은 쓰지 않는다)
                raise ProductionUnknown(f"등록부 DB {type(e).__name__}") from None
        return self._rows

    def __call__(self, task_id: str) -> bool | None:
        return self._load().get(task_id)


def db_production_synthetic(tenant_id: str) -> ProductionLookup:
    """등록부 DB 를 실제로 조회하는 R4 콜백(기동 경로의 기본)."""
    return ProductionLookup(tenant_id)


def load_for_serving(code: str, *, tenants_base: Path | None = None, packs_base: Path = PACKS_DIR,
                     production_synthetic: Callable[[str], bool | None] | None = None) -> Merged:
    """API 기동 경로의 병합 — 병합 규칙 5 + R4 를 **DB 조회 콜백을 기본으로** 판정한다(spec §11.3-4 · D-27 · D-120).
    등록부 루트는 `tenant_base(code)`(= `data.jobs.tenants_base_for`, D-65). 학습 · doctor 는 `load_and_merge` 를 쓴다 —
    꺼진 과제도 실데이터로 다시 학습해 합성 모델을 교체할 수 있어야 하기 때문."""
    cb = production_synthetic if production_synthetic is not None else db_production_synthetic(code)
    return load_and_merge(code, tenants_base=tenants_base, packs_base=packs_base, production_synthetic=cb)


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
    # 우선순위: 회사 소스 tasks.<과제> > 팩 synth.tasks.<과제> > 회사 소스 rows · seed > 팩 synth (D2-45)
    own = dict(((src.get("tasks") or {}).get(short)) or {})
    pack_own = _packs.synth_task_override(merged.pack, short)
    seed = int(own.get("seed", pack_own.get("seed", src["seed"] if src.get("seed") is not None else spec.seed)))
    rows = int(own.get("rows", pack_own.get("rows", src["rows"] if src.get("rows") is not None else spec.rows)))
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
