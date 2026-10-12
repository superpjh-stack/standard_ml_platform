"""G-M05 — 누수 없는 평가 (goal §2.2 · spec §5.3 · contracts/interfaces.md §3).

판정은 네 단계이고 **모두** 통과해야 PASS 다.
  A. 계측 래퍼 자체 시험 — `mlcore.train.guard` 가 금지 목적 · 2회 평가 · 직접 인덱스 접근 · 표본 내 평가를 막고 기록하는가.
  B. 정적 검사 — `GuardedTest.take(` 호출 위치가 train/evaluate.py · train/report.py 뿐, 래퍼 내부 인덱스 직접 접근 0,
     시험 구간을 끄는 설정 문자열(`disable_guard` · `leak_check=False` 등) 0,
     래퍼 우회 패턴 0(DEF-QA1-006 · D-86: vars · __dict__ · 이름 맹글링 · copy/deepcopy · 여집합 · test_ts 읽기 · overlaps 질의).
  C. 동적 검사 — 켜진 과제 8 각각을 fixture 스냅숏으로 래퍼 아래에서 학습해 ledger 위반 0 · final_eval 정확히 1회 ·
     시계열 과제는 시간순 · group_key 경계 교집합 0 · 모든 candidate 에 기준선 비교.
  D. 표본 내 평가 픽스처(평창식)가 InSampleEvaluation 으로 거부되는가.
학습기(`mlcore.train.trainer`)가 없으면 C 는 대상 없음 → FAIL (가짜 PASS 금지).
"""
from __future__ import annotations

import importlib
import re

from gatelib import ROOT, Line, read, rel, show

ALLOWED_TAKE = {"src/mlcore/train/evaluate.py", "src/mlcore/train/report.py", "src/mlcore/train/guard.py"}
DISABLE_PAT = re.compile(r"(disable_guard|leak_check\s*=\s*False|skip_leak|no_guard|guard\s*=\s*None|ALLOW_TEST_LEAK)")
# 래퍼 우회 패턴 (DEF-QA1-006 · D-86) — (이름, 정규식, 예외 파일). src/mlcore 에만 적용한다(시험 코드는 판정용으로 여집합을 쓴다).
BYPASS = (
    ("래퍼 내부 속성 접근(이름 맹글링)", re.compile(r"_GuardedTest__"), {"src/mlcore/train/guard.py"}),
    ("vars()/__dict__ 로 래퍼 속성 열람", re.compile(r"\bvars\(|\.__dict__\b"), {"src/mlcore/train/guard.py"}),
    ("래퍼 복사(final_eval 2회 · 인덱스 복제)", re.compile(r"copy\.(?:copy|deepcopy)\(\s*(?:self\.)?_?test\b"), set()),
    ("시험 인덱스 여집합 복원", re.compile(r"set\(\s*range\(\s*len\([^)]*\)\s*\)\s*\)\s*-\s*set\("), set()),
    ("분할 경계 test_ts 로 시험 행 자르기", re.compile(r"\[\s*[\"']test_ts[\"']\s*\](?!\s*=[^=])|\.get\(\s*[\"']test_ts[\"']"),
     {"src/mlcore/train/split.py"}),
    ("overlaps() 질의(표본 내 평가 판정 밖)", re.compile(r"\.overlaps\("), {"src/mlcore/train/guard.py"}),
)


def scan_bypass(r: str, txt: str) -> list[str]:
    """한 파일(저장소 상대 경로 r)의 래퍼 우회 패턴 — 위반 문구 목록."""
    out = []
    for name, pat, exempt in BYPASS:
        if r in exempt:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            if pat.search(line):
                out.append(f"{r}:{i}: {name}")
    return out


def _self_test() -> tuple[int, int, list[str]]:
    import pandas as pd
    from mlcore.train import guard

    frame = pd.DataFrame({"y": range(10)})
    cases: list[tuple[str, bool]] = []
    fails = []

    def expect_leak(name, fn):
        try:
            fn()
            cases.append((name, False))
            fails.append(f"{name}: 막지 않음")
        except guard.TestLeak:
            cases.append((name, True))

    # 정상 흐름: final_eval 1회 → report
    led = guard.AccessLedger()
    t = guard.GuardedTest(range(8, 10), led)
    ok = len(t.take(frame, "final_eval")) == 2 and len(t.take(frame, "report")) == 2 and not led.violations() and led.final_eval_count() == 1
    cases.append(("정상 흐름", ok))
    if not ok:
        fails.append("정상 흐름 실패")
    for purpose in sorted(guard.FORBIDDEN):
        led2 = guard.AccessLedger()
        t2 = guard.GuardedTest(range(8, 10), led2)
        expect_leak(f"금지:{purpose}", lambda t2=t2, p=purpose: t2.take(frame, p))
        if not led2.violations():
            fails.append(f"금지:{purpose} 기록 없음")
    expect_leak("final_eval 2회", lambda: t.take(frame, "final_eval"))
    t3 = guard.GuardedTest(range(8, 10), guard.AccessLedger())
    expect_leak("final_eval 전 report", lambda: t3.take(frame, "report"))
    expect_leak("직접 iter", lambda: list(t3))
    expect_leak("직접 getitem", lambda: t3[0])
    expect_leak("직접 tolist", lambda: t3.tolist())
    try:
        import numpy as np
        np.asarray(t3)
        cases.append(("직접 array", False))
        fails.append("직접 array: 막지 않음")
    except guard.TestLeak:
        cases.append(("직접 array", True))
    try:
        guard.assert_not_in_sample(range(0, 10), guard.GuardedTest(range(8, 10), guard.AccessLedger()))
        cases.append(("표본 내 평가", False))
        fails.append("표본 내 평가: 거부 안 함")
    except guard.InSampleEvaluation:
        cases.append(("표본 내 평가", True))
    guard.assert_not_in_sample(range(0, 8), guard.GuardedTest(range(8, 10), guard.AccessLedger()))
    # 우회 경로 (DEF-QA1-006): 복사 · 직렬화 · 같은 ledger 의 다른 래퍼로 final_eval 2회 · 겹침 질의 반복 · vars()
    import copy
    import pickle
    t4 = guard.GuardedTest(range(8, 10), guard.AccessLedger())
    expect_leak("copy.copy", lambda: copy.copy(t4))
    expect_leak("copy.deepcopy", lambda: copy.deepcopy(t4))
    expect_leak("pickle", lambda: pickle.dumps(t4))
    led5 = guard.AccessLedger()
    guard.GuardedTest(range(8, 10), led5).take(frame, "final_eval")
    expect_leak("같은 ledger 다른 래퍼 final_eval 2회", lambda: guard.GuardedTest(range(8, 10), led5).take(frame, "final_eval"))
    t6 = guard.GuardedTest(range(8, 10), guard.AccessLedger())
    t6.overlaps([0])
    expect_leak("overlaps 2회째", lambda: t6.overlaps([8]))
    try:
        vars(t6)
        cases.append(("vars() 열람", False))
        fails.append("vars(): 래퍼 속성이 보인다")
    except TypeError:
        cases.append(("vars() 열람", True))
    return sum(ok for _, ok in cases), len(cases), fails


def _static() -> list[str]:
    problems = []
    for p in (ROOT / "src" / "mlcore").rglob("*.py"):
        r = rel(p)
        txt = read(p)
        if ".take(" in txt and re.search(r"\.take\(\s*[^,]+,\s*[\"'](final_eval|report|selection|calibration|interval|threshold|baseline|queue)", txt) and r not in ALLOWED_TAKE:
            problems.append(f"{r}: 시험 구간 take 호출 위치가 허용 밖")
        if "_GuardedTest__idx" in txt and not r.endswith("guard.py"):
            problems.append(f"{r}: 래퍼 내부 인덱스 직접 접근")
        if DISABLE_PAT.search(txt):
            problems.append(f"{r}: 누수 장치를 끄는 설정")
        problems += scan_bypass(r, txt)
    for p in list((ROOT / "packs").rglob("*.yaml")) + list((ROOT / "tenants").rglob("*.yaml")):
        if DISABLE_PAT.search(read(p)):
            problems.append(f"{rel(p)}: 누수 장치를 끄는 설정")
    return problems


def run() -> list[Line]:
    try:
        passed, total, fails = _self_test()
    except ModuleNotFoundError as e:
        return [Line("G-M05", "누수 없는 평가", "FAIL", f"계측 래퍼 없음: {e.name}")]
    static = _static()
    try:
        importlib.import_module("mlcore.train.trainer")
        trainer = True
    except ModuleNotFoundError:
        trainer = False
    head = f"A 래퍼 자체 시험 {passed}/{total}" + (f" ({'; '.join(fails[:3])})" if fails else "")
    head += f" · B 정적 위반 {len(static)}" + (f" ({'; '.join(static[:3])})" if static else "")
    if fails or static:
        return [Line("G-M05", "누수 없는 평가", "FAIL", head)]
    if not trainer:
        return [Line("G-M05", "누수 없는 평가", "FAIL", head + " · C 학습기(mlcore.train.trainer) 없음 — 계측 대상 0/8 · D 표본 내 평가 픽스처 대상 없음")]
    # C · D — 학습기가 생기면 tests/test_split.py 가 과제 8 을 래퍼 아래에서 돌린다 (개발1 · QA1)
    from gatelib import pytest_gate
    t = pytest_gate("G-M05", "누수 없는 평가", "tests/test_split.py")
    return [Line("G-M05", "누수 없는 평가", t.status, head + " · C/D " + t.measured)]


if __name__ == "__main__":
    raise SystemExit(show(run()))
