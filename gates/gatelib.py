"""게이트 공용 — 출력 형식 `G-nn  항목  PASS|FAIL|WARN|BLOCKED  실측` (goal §2 · §5).

각 check_*.py 는 run() -> list[Line] 을 내보내고, 혼자 돌려도 같은 표를 찍는다(`uv run python gates/check_x.py`).
**가짜 PASS 금지:** 대상이 없으면 FAIL + 사유. BLOCKED 는 D-번호가 있어야 한다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STATUSES = ("PASS", "FAIL", "WARN", "BLOCKED")

import warnings  # noqa: E402
warnings.filterwarnings("ignore", message=".*httpx.*")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".ts", ".tsx", ".js", ".css", ".html", ".sql",
                 ".txt", ".csv", ".cfg", ".ini", ".sh", ".lock", ".example", ""}


@dataclass
class Line:
    gate: str
    item: str
    status: str
    measured: str

    def __post_init__(self) -> None:
        assert self.status in STATUSES, self.status
        if self.status == "BLOCKED":
            assert re.search(r"D-\d{2}", self.measured), "BLOCKED 는 D-번호가 있어야 한다"

    def render(self) -> str:
        return f"{self.gate:<6}  {self.item:<16}  {self.status:<7}  {self.measured}"


def show(lines: list[Line]) -> int:
    for ln in lines:
        print(ln.render())
    return 0 if all(ln.status in ("PASS", "BLOCKED", "WARN") for ln in lines) else 1


def tracked_files() -> list[Path]:
    """git 이 추적하거나 추적할 파일(.gitignore 제외) — 커밋될 수 있는 전부."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return [ROOT / p for p in out if p and (ROOT / p).is_file()]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def word_pattern(word: str) -> re.Pattern:
    """한글은 경계 없이, 영문 · 숫자는 식별자 경계로."""
    if re.search(r"[가-힣]", word):
        return re.compile(re.escape(word))
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])")


def pytest_gate(gate: str, item: str, test_file: str) -> Line:
    """시험 파일로 판정하는 게이트. 파일이 없으면 FAIL(대상 없음), 있으면 pytest 결과."""
    path = ROOT / test_file
    if not path.is_file():
        return Line(gate, item, "FAIL", f"{test_file} 없음 (대상 미구현)")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", str(path)],
                       cwd=ROOT, capture_output=True, text=True, env={**__import__("os").environ, "OMP_NUM_THREADS": "1"})
    tail = (r.stdout.strip().splitlines() or ["(출력 없음)"])[-1]
    return Line(gate, item, "PASS" if r.returncode == 0 else "FAIL", f"{test_file}: {tail}")


def tenant_words(include_tables: bool = True) -> tuple[dict[str, re.Pattern], dict[str, re.Pattern], dict[str, re.Pattern]]:
    """(회사 코드 · 이름 · 별칭, 원천 테이블 이름, 회사 범주 값) — 금지어 사전."""
    import yaml
    names, tables, cats = {}, {}, {}
    for f in sorted((ROOT / "tenants").glob("*.yaml")):
        if f.stem.startswith("_"):
            continue
        cfg = yaml.safe_load(read(f)) or {}
        for w in [cfg.get("code"), cfg.get("name"), *(cfg.get("aliases") or [])]:
            if w:
                names[w] = word_pattern(w)
        if include_tables:
            for key in list((cfg.get("feature_map") or {})) + list((cfg.get("target_map") or {})):
                t = key.split(".")[0]
                tables[t] = word_pattern(t)
            for s in (cfg.get("sources") or {}).values():
                for t in (s or {}).get("tables") or []:
                    tables[t] = word_pattern(t)
                if (s or {}).get("table"):
                    tables[s["table"]] = word_pattern(s["table"])
            for vals in (cfg.get("categories") or {}).values():
                for v in vals or []:
                    cats[str(v)] = word_pattern(str(v))
            eq = ((cfg.get("compat") or {}).get("equipment_by_print_type") or {})
            for pair in eq.values():
                cats[str(pair[0])] = word_pattern(str(pair[0]))
    return names, tables, cats


# ── 2차 (goal2) — 판정 대상 목록은 등록부에서 읽는다 ─────────────────────────────────────────────
PHASE1_PACKS = {"press", "textile", "_template"}
PHASE1_TENANTS = {"ks", "sw", "_template"}
# goal2 §1 표 "규모 (2차 끝)" — 판정 기준(기대값)은 정본에서, 실제 목록은 등록부 디렉터리에서.
PHASE2_PACKS = PHASE1_PACKS | {"solder", "kimchi", "rollform-quote", "eto"}
PHASE2_TENANTS = PHASE1_TENANTS | {"krs", "pc", "ot", "kd"}


def registered_packs() -> set[str]:
    """packs/<code>/pack.yaml 이 있는 팩 코드 전부 (`_template` 포함)."""
    return {p.parent.name for p in (ROOT / "packs").glob("*/pack.yaml")}


def registered_tenants() -> set[str]:
    """tenants/<code>.yaml 의 회사 코드 전부 (`_template` 포함, 덮어쓰기 폴더 제외)."""
    return {p.stem for p in (ROOT / "tenants").glob("*.yaml")}


def expected_scope(scope: str) -> tuple[set[str], set[str]]:
    """(기대 팩, 기대 회사). phase1 = 1차 게이트, phase2 = gate2 의 6개사 판정."""
    if scope == "phase2":
        return PHASE2_PACKS, PHASE2_TENANTS
    return PHASE1_PACKS, PHASE1_TENANTS
