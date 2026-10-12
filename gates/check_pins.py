"""G-S07 — 의존성 고정. uv.lock · web/package-lock.json 존재, pyproject · package.json 에 `latest` · `^` · `~` · 범위 0,
Python 3.12 하나 (requires-python · .python-version · uv.lock)."""
import json
import re
import tomllib

from gatelib import ROOT, Line, read, show

EXACT_PY = re.compile(r"^[A-Za-z0-9_.\-]+(\[[A-Za-z0-9_,\-]+\])?==[0-9][0-9A-Za-z.\-+]*$")
EXACT_JS = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([\-+][0-9A-Za-z.\-]+)?$")


def run() -> list[Line]:
    problems = []
    for f in ("uv.lock", "web/package-lock.json", "pyproject.toml", "web/package.json"):
        if not (ROOT / f).is_file():
            problems.append(f"{f} 없음")
    if problems:
        return [Line("G-S07", "의존성 고정", "FAIL", "; ".join(problems))]
    py = tomllib.loads(read(ROOT / "pyproject.toml"))
    deps = list(py["project"].get("dependencies", []))
    for grp in (py.get("dependency-groups") or {}).values():
        deps += [d for d in grp if isinstance(d, str)]
    deps += list((py.get("build-system") or {}).get("requires", []))
    bad_py = [d for d in deps if not EXACT_PY.match(d.replace(" ", ""))]
    if bad_py:
        problems.append(f"pyproject 범위 버전 {bad_py[:4]}")
    if py["project"].get("requires-python") != "==3.12.*":
        problems.append(f"requires-python {py['project'].get('requires-python')!r}")
    pv = read(ROOT / ".python-version").strip() if (ROOT / ".python-version").is_file() else ""
    if pv != "3.12":
        problems.append(f".python-version {pv!r}")
    lock = read(ROOT / "uv.lock")
    m = re.search(r'^requires-python = "([^"]+)"', lock, re.M)
    if not m or m.group(1) != "==3.12.*":
        problems.append(f"uv.lock requires-python {m.group(1) if m else None!r}")
    pkg = json.loads(read(ROOT / "web" / "package.json"))
    js = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    bad_js = [f"{k}@{v}" for k, v in js.items() if not EXACT_JS.match(v)]
    if bad_js:
        problems.append(f"package.json 범위 버전 {bad_js[:4]}")
    pl = json.loads(read(ROOT / "web" / "package-lock.json"))
    root = (pl.get("packages") or {}).get("", {})
    lock_js = {**root.get("dependencies", {}), **root.get("devDependencies", {})}
    if lock_js != js:
        problems.append("package-lock 루트 의존성이 package.json 과 다르다")
    if problems:
        return [Line("G-S07", "의존성 고정", "FAIL", "; ".join(problems[:5]))]
    return [Line("G-S07", "의존성 고정", "PASS", f"uv.lock · package-lock.json 있음 · Python {len(deps)}개 == 고정 · JS {len(js)}개 정확 버전 · Python 3.12 하나")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
