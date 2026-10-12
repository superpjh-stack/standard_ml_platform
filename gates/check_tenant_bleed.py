"""G-S06(격리) — 다른 회사의 코드명 · 회사명 · 데이터 파일이 그 회사 폴더 밖에 0 (goal §2.1).

- 회사 파일(tenants/<a>.yaml · tenants/<a>/ · tests/fixtures/<a>/)에 다른 회사 b 의 코드 · 이름 · 별칭 0.
- 데이터 파일(.parquet · .csv · .db · .sqlite · .joblib · .sql 데이터 사본)은 tests/fixtures/<code>/ · tenants/<code>/ 안에만.
- 코드 폴더(src/ · web/src/ · packs/ · gates/ · db/)에 회사명 · 별칭 0 (코드는 G-M01 이 더 엄격하게 본다).
문서(contracts/ · migration/ · docs/ · outputs/ · tests/fixtures/README.md · 루트 *.md)는 회사를 이름으로 부를 수 있다.
"""
import re

import yaml

from gatelib import ROOT, Line, read, rel, show, tracked_files, word_pattern

DATA_SUFFIX = {".parquet", ".csv", ".db", ".sqlite", ".joblib"}
CODE_DIRS = ("src/", "web/src/", "packs/", "gates/", "db/")


def _tenants() -> dict[str, list[re.Pattern]]:
    out = {}
    for f in sorted((ROOT / "tenants").glob("*.yaml")):
        if f.stem.startswith("_"):
            continue
        cfg = yaml.safe_load(read(f)) or {}
        words = [cfg["code"], cfg["name"], *(cfg.get("aliases") or [])]
        out[cfg["code"]] = [word_pattern(w) for w in words]
    return out


def _owner(r: str) -> str | None:
    m = re.match(r"tenants/([a-z][a-z0-9]*)(\.yaml|/)", r) or re.match(r"tests/fixtures/([a-z][a-z0-9]*)/", r)
    return m.group(1) if m else None


def run() -> list[Line]:
    tenants = _tenants()
    files = tracked_files()
    problems = []
    checked = 0
    for f in files:
        r = rel(f)
        owner = _owner(r)
        if f.suffix in DATA_SUFFIX or (f.suffix == ".sql" and r.startswith("tests/")):
            if owner not in tenants and not r.startswith("tests/fixtures/bad_registry/"):
                problems.append(f"데이터 파일 위치 {r}")
        if owner in tenants and f.suffix not in (".parquet", ".joblib", ".db", ".sqlite"):
            txt = read(f)
            checked += 1
            for other, pats in tenants.items():
                if other != owner and any(p.search(txt) for p in pats):
                    problems.append(f"{r} 에 다른 회사 '{other}'")
        elif r.startswith(CODE_DIRS):
            txt = read(f)
            for code, pats in tenants.items():
                if any(p.search(txt) for p in pats[1:]):     # 이름 · 별칭 (코드 토큰은 G-M01)
                    problems.append(f"{r} 에 회사명 '{code}'")
    if problems:
        return [Line("G-S06", "회사 격리", "FAIL", f"{len(problems)}건: " + "; ".join(problems[:6]) + (" …" if len(problems) > 6 else ""))]
    return [Line("G-S06", "회사 격리", "PASS", f"회사 {len(tenants)} · 회사 파일 {checked}개 교차 오염 0 · 폴더 밖 데이터 파일 0 · 코드 폴더 회사명 0")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
