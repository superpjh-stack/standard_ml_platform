"""G2-Q01 (정적) — 견적식은 Decimal · ROUND_HALF_UP 만 (goal2 §0.2 · §2 · D2-07).

대상: 팩 견적식 `packs/*/formulas/quote*.py` + 코어 견적 경로 `src/mlcore/**/quote*.py`(웨이브 P 개발2).
대상 파일이 0 이면 **FAIL**(대상 없음 — 가짜 PASS 금지).
AST 로 찾는 float 경로(하나라도 있으면 FAIL):
  F1 float 리터럴(`0.15`, `1e9`) — 계수는 `Decimal("0.15")` 문자열로
  F2 `float(…)` 호출 · F3 내장 `round(…)` 호출(짝수 반올림 · float) · F4 `math.` · `numpy` · `np.` 사용
  F5 `Decimal(<float 리터럴 · 산술식 · 다른 호출>)` — `Decimal("…")` · `Decimal(int)` · `Decimal(str(…))` · 이름 · 첨자만 허용
     (입력 dict 값은 요청 검증이 Decimal 로 바꾼 뒤 온다 — JSON float 가 그대로 오면 tests/test_quote.py 가 잡는다)
  F6 `.quantize(` 에 `rounding=ROUND_HALF_UP` 가 없음 · F7 `ROUND_HALF_EVEN` 등 다른 반올림 상수
  F8 `/` 나눗셈 결과를 quantize 없이 반환하는지는 시험(tests/test_quote.py)이 원 단위로 본다 — 정적 검사는 F1~F7.
"""
from __future__ import annotations

import ast
from pathlib import Path

from gatelib import ROOT, Line, read, rel, show

ROUNDINGS_BAD = {"ROUND_HALF_EVEN", "ROUND_HALF_DOWN", "ROUND_DOWN", "ROUND_UP", "ROUND_CEILING", "ROUND_FLOOR", "ROUND_05UP"}


def targets() -> list[Path]:
    out = sorted((ROOT / "packs").glob("*/formulas/quote*.py"))
    out += sorted(p for p in (ROOT / "src" / "mlcore").rglob("quote*.py") if "__pycache__" not in p.parts)
    return out


def scan(path: Path) -> list[str]:
    tree = ast.parse(read(path), filename=str(path))
    found = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            found.append(f"F1 float 리터럴 {node.value!r}:{line}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if isinstance(fn, ast.Name) and name == "float":
                found.append(f"F2 float():{line}")
            if isinstance(fn, ast.Name) and name == "round":
                found.append(f"F3 round():{line}")
            if name == "Decimal" and node.args:
                a = node.args[0]
                ok = (isinstance(a, ast.Constant) and isinstance(a.value, (str, int)) and not isinstance(a.value, bool)) \
                    or (isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id == "str") \
                    or isinstance(a, (ast.Name, ast.Subscript, ast.Attribute))
                if not ok:
                    found.append(f"F5 Decimal(수식):{line}")
            if name == "quantize":
                kw = {k.arg: k.value for k in node.keywords}
                r = kw.get("rounding") if "rounding" in kw else (node.args[1] if len(node.args) > 1 else None)
                rname = r.id if isinstance(r, ast.Name) else r.attr if isinstance(r, ast.Attribute) else None
                if rname != "ROUND_HALF_UP":
                    found.append(f"F6 quantize 반올림 {rname or '없음'}:{line}")
        elif isinstance(node, (ast.Name, ast.Attribute)):
            nm = node.id if isinstance(node, ast.Name) else node.attr
            if nm in ROUNDINGS_BAD:
                found.append(f"F7 {nm}:{line}")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("math", "np", "numpy"):
                found.append(f"F4 {node.value.id}.{node.attr}:{line}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(m and m.split(".")[0] in ("math", "numpy") for m in mods):
                found.append(f"F4 import {','.join(m for m in mods if m)}:{line}")
    return found


def run() -> list[Line]:
    files = targets()
    if not files:
        return [Line("G2-Q01", "견적 Decimal", "FAIL",
                     "대상 없음 — packs/*/formulas/quote*.py · src/mlcore/**/quote*.py 0개(웨이브 P 개발2 · A2 개발3)")]
    bad = {rel(f): v for f in files if (v := scan(f))}
    if bad:
        first = "; ".join(f"{k} {v[:2]}" for k, v in list(bad.items())[:3])
        return [Line("G2-Q01", "견적 Decimal", "FAIL", f"float 경로 {sum(map(len, bad.values()))}건 / 파일 {len(bad)}: {first}")]
    return [Line("G2-Q01", "견적 Decimal", "PASS", f"견적식 {len(files)} 파일 float 경로 0 · quantize 전부 ROUND_HALF_UP")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
