"""F13-1 (이슈 #13 · DEF-QA1-006 잔여) — guard 우회 '다른 문법' 6종이 ledger(실행) 또는 check_leakage(정적)에서 막힌다.

QA-R2 재현(outputs/qa-r2/qa1/guard_bypass_r2.py · static_bypass_r2.py)의 6종:
  ① getattr 문자열 조립 ② gc.get_referents ③ slot 서술자 ④ np.setdiff1d 여집합 ⑤ 리스트 내포 여집합 ⑥ 변수 키 test_ts.
실행 시 막는 것(①②③⑥): 래퍼가 인덱스를 속성으로 들고 있지 않고(클로저), 모르는 속성 조회는 기록 후 TestLeak,
SplitPlan.boundaries 에 test_ts 가 없다(시험 시각 범위는 final_eval 뒤 `bounds()` 로만).
정적으로 막는 것(①~⑥ 전부): gates/check_leakage.py BYPASS 패턴 (decisions.md D2-41).
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mlcore.train import guard, split

from tests._dev1 import raw_rows, std_frame, task

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def planned():
    t = task()
    f = std_frame(t, raw_rows(1000, 1))
    sp, test = split.plan(f, t, seed=1)
    true_te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
    return t, f, sp, test, true_te


def _leaks(obj, true_te) -> bool:
    try:
        return sorted(int(i) for i in obj) == true_te
    except Exception:
        return False


def test_getattr_string_assembly_is_recorded_and_refused(planned):
    _, _, _, test, _ = planned
    with pytest.raises(guard.TestLeak):
        getattr(test, "_Guarded" + "Test__idx")
    with pytest.raises(guard.TestLeak):
        getattr(test, "_idx")
    assert test._ledger.violations()[-1]["purpose"].startswith("getattr:")


def test_gc_referents_do_not_hold_index_sequence(planned):
    _, _, _, test, true_te = planned
    refs = gc.get_referents(test)
    assert not any(isinstance(x, (list, tuple, np.ndarray)) and _leaks(x, true_te) for x in refs)


def test_slot_descriptors_do_not_expose_index(planned):
    _, _, _, test, true_te = planned
    for name, d in type(test).__dict__.items():
        if hasattr(d, "__get__") and type(d).__name__ == "member_descriptor":
            v = d.__get__(test)
            assert not (isinstance(v, (list, tuple, np.ndarray)) and _leaks(v, true_te)), name
    assert not any(k.endswith("idx") for k in type(test).__slots__)


def test_split_plan_boundaries_have_no_test_ts(planned):
    _, f, sp, test, true_te = planned
    k = "test" + "_ts"
    assert k not in sp.boundaries                      # 변수 키로도 꺼낼 것이 없다
    with pytest.raises(guard.TestLeak):
        test.bounds()                                  # final_eval 전에는 시험 시각 범위도 없다
    test.take(f, "final_eval")
    b = test.bounds()
    assert b["test_ts"][0] == str(f["ts"].iloc[true_te].min())


def test_static_check_flags_all_six_syntaxes():
    sys.path.insert(0, str(ROOT / "gates"))
    try:
        import check_leakage as cl
    finally:
        sys.path.pop(0)
    cases = {
        "getattr 문자열 조립": "x = getattr(test, '_Guarded' + 'Test__idx')",
        "getattr 변수 이름": "x = getattr(test, name)",
        "gc.get_referents": "x = gc.get_referents(test)",
        "클로저 셀": "x = fn.__closure__[0].cell_contents",
        "slot 서술자": "v = d.__get__(test)",
        "np.setdiff1d": "te = np.setdiff1d(np.arange(len(f)), np.r_[sp.train_idx, sp.valid_idx])",
        "isin invert": "te = np.flatnonzero(~np.isin(np.arange(n), fit))",
        "리스트 내포 여집합": "te = [i for i in range(len(f)) if i not in fit]",
        "set difference": "te = set(range(n)).difference(fit)",
        "변수 키 boundaries": "c = sp.boundaries[k]",
        "변수 키 get": "c = sp.boundaries.get(k)",
        "test_ts 조립": "k = 'test' + '_ts'",
    }
    missed = [n for n, src in cases.items() if not cl.scan_bypass("src/mlcore/train/x.py", src)]
    assert missed == []
    ok = ["e = getattr(err, 'code', None)", "klass = getattr(importlib.import_module(mod), cls)",
          "bounds['sizes'] = {'train': a}", "rows = [i for i in idx if i in keep]"]
    assert [s for s in ok if cl.scan_bypass("src/mlcore/train/x.py", s)] == []
    assert cl._static() == []                          # 지금 src 에 우회 0
