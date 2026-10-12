"""G-M06 — 재현 · 등록부.
  A. 같은 스냅숏 + 시드 + 코드 버전으로 과제 8 을 2회 학습 → 시험 예측 차이 0 (D-19: 같은 머신 0, OMP_NUM_THREADS=1).
  B. 재기동 시 학습 함수 호출 0회(계측) — 정적: api 기동 경로가 train 모듈을 import · 호출하지 않는다.
  C. 산출물 해시 · 패키지 버전 불일치 → 503 model_artifact_mismatch · production 과제당 1 — tests/test_registry.py.
학습기가 없으면 A 는 대상 없음 → FAIL."""
import importlib
import re

from gatelib import ROOT, Line, pytest_gate, read, show


def startup_static() -> list[str]:
    problems = []
    api = ROOT / "src" / "mlcore" / "api"
    for p in api.rglob("*.py"):
        txt = read(p)
        if re.search(r"from\s+\.\.\s*train|from\s+mlcore\.train|import\s+mlcore\.train|\.fit\(", txt):
            problems.append(f"{p.relative_to(ROOT)}: 기동 경로에 학습 코드")
        if "lru_cache" in txt and "state(" in txt:
            problems.append(f"{p.relative_to(ROOT)}: @lru_cache state() 기동 학습 패턴")
    return problems


def run() -> list[Line]:
    st = startup_static()
    head = f"B 기동 경로 학습 코드 {len(st)}건" + (f" ({'; '.join(st[:2])})" if st else "")
    try:
        importlib.import_module("mlcore.train.trainer")
    except ModuleNotFoundError:
        return [Line("G-M06", "재현·등록부", "FAIL", f"A 학습기 없음 — 재학습 대조 0/8 · {head} · C {pytest_gate('G-M06', '', 'tests/test_registry.py').measured}")]
    t = pytest_gate("G-M06", "재현·등록부", "tests/test_determinism.py")
    r = pytest_gate("G-M06", "재현·등록부", "tests/test_registry.py")
    ok = not st and t.status == r.status == "PASS"
    return [Line("G-M06", "재현·등록부", "PASS" if ok else "FAIL", f"A {t.measured} · {head} · C {r.measured}")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
