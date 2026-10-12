"""G-M09 — 자동 승격 경로 0. `production` 을 쓰는 코드 경로는 `approval.decide()` 하나뿐 (spec §6.1 · contracts/interfaces.md §6).
정적: src/mlcore 의 SQL · 파이썬에서 stage 를 'production' 으로 쓰는 곳을 찾아 approval/ 의 decide 안에만 있는지 본다.
호출처: `decide(` 호출은 src/mlcore · migration 에서 api/routers/models.py 1곳뿐(D-56, 시험 제외).
동작: 감시 → 후보 → 승인 대기 · production 불변 · 동시 승인 2건 중 하나만 성공(409) — tests/test_monitor.py · tests/test_approval.py."""
import ast
import re

from gatelib import ROOT, Line, pytest_gate, read, rel, show

# SQL: UPDATE mlp_model_version SET <여기> WHERE … 의 SET 절에 stage='production' · INSERT … VALUES 에 'production'
UPDATE_SET = re.compile(r"(?is)update\s+mlp_model_version\s+set\s+(.*?)(?:\bwhere\b|[\"']\s*[,)]|$)")
INSERT_PROD = re.compile(r"(?is)insert\s+into\s+mlp_model_version\b[^;]*?values[^;]*?'production'")
# 파이썬: stage="production" 인자 · {"stage": "production"} 값
PY_PROD = re.compile(r"""(?<![\w.])stage\s*=\s*["']production["']\s*[,)]|["']stage["']\s*:\s*["']production["']""")


def _hits(txt: str) -> list[int]:
    out = [m.start() for m in UPDATE_SET.finditer(txt) if re.search(r"stage\s*=\s*'production'", m.group(1), re.I)]
    out += [m.start() for m in INSERT_PROD.finditer(txt)] + [m.start() for m in PY_PROD.finditer(txt)]
    return out


def _enclosing(tree: ast.AST, lineno: int) -> str | None:
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= lineno <= (node.end_lineno or node.lineno):
            if best is None or node.lineno > best.lineno:
                best = node
    return best.name if best else None


DECIDE_CALLER = "src/mlcore/api/routers/models.py"   # D-56: decide 호출처는 API 승인 경로 하나(시험 제외)


def decide_calls() -> list[tuple[str, int]]:
    """src/mlcore · migration 의 `decide(...)` · `approval.decide(...)` 호출(AST). 시험 · 게이트는 세지 않는다."""
    out = []
    for base in (ROOT / "src" / "mlcore", ROOT / "migration"):
        for p in base.rglob("*.py"):
            for node in ast.walk(ast.parse(read(p))):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
                    if name == "decide":
                        out.append((rel(p), node.lineno))
    return out


def run() -> list[Line]:
    writers = []
    for p in (ROOT / "src" / "mlcore").rglob("*.py"):
        txt = read(p)
        hits = _hits(txt)
        if not hits:
            continue
        tree = ast.parse(txt)
        for pos in hits:
            line = txt[:pos].count("\n") + 1
            writers.append((rel(p), line, _enclosing(tree, line)))
    allowed = [w for w in writers if w[0].startswith("src/mlcore/approval/") and w[2] == "decide"]
    others = [w for w in writers if w not in allowed]
    has_decide = (ROOT / "src" / "mlcore" / "approval").is_dir() and any(
        re.search(r"^def decide\(", read(p), re.M) for p in (ROOT / "src" / "mlcore" / "approval").glob("*.py"))
    msg = f"production 쓰기 경로 {len(writers)} (decide 안 {len(allowed)} · 밖 {len(others)})"
    calls = decide_calls()
    bad_calls = [c for c in calls if c[0] != DECIDE_CALLER]
    msg += f" · decide 호출처 {len(calls)} ({DECIDE_CALLER.rsplit('/', 1)[1]} {len(calls) - len(bad_calls)})"
    if bad_calls or len(calls) != 1:
        return [Line("G-M09", "감시·승인", "FAIL", msg + f" — 호출처는 API 승인 경로 1곳이어야 한다(D-56): {calls[:4]}")]
    if others:
        return [Line("G-M09", "감시·승인", "FAIL", msg + f": {others[:3]}")]
    if not has_decide:
        return [Line("G-M09", "감시·승인", "FAIL", msg + " · approval.decide() 없음 — 승인 경로 미구현")]
    a = pytest_gate("G-M09", "", "tests/test_approval.py")
    m = pytest_gate("G-M09", "", "tests/test_monitor.py")
    ok = a.status == m.status == "PASS" and len(allowed) >= 1
    return [Line("G-M09", "감시·승인", "PASS" if ok else "FAIL", f"{msg} · {a.measured} · {m.measured}")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
