"""누수 계측 래퍼 — 시험 구간 인덱스 접근을 기록하고 금지 목적이면 막는다 (contracts/interfaces.md §3 · G-M05).

Phase 0 아키텍트 공표 — 이후 소유 개발1. `gates/check_leakage.py` 가 같은 모듈을 쓴다.
**이 래퍼를 끄는 설정은 없다(시험 모드 포함).**

- 시험 구간 인덱스는 SplitPlan 에 없다. GuardedTest 만 들고 있고, take(frame, purpose) 로만 꺼낸다.
- 허용 목적: final_eval(정확히 1회) → 그 뒤 report(순열 중요도 · 잔차 표).
- 금지 목적(selection · calibration · interval · threshold · baseline · queue) · final_eval 2회째 · final_eval 전 report → 기록 후 TestLeak.
- 인덱스를 직접 꺼내는 길(__iter__ · __getitem__ · __array__ · tolist)은 TestLeak.
- 우회 경로(DEF-QA1-006): `__dict__` 없음(`vars()` 불가 · __slots__) · copy / deepcopy / pickle → TestLeak ·
  final_eval 1회는 **ledger 단위**(같은 ledger 의 다른 래퍼 · 복사본으로도 2회째 거부) · `overlaps()` 는 래퍼당 1회
  (표본 내 평가 판정용 — 한 행씩 묻는 질의로 인덱스를 복원하지 못하게). 정적 우회 패턴은 `gates/check_leakage.py` 가 본다.
"""

from __future__ import annotations

import inspect
import threading
from typing import Literal, Sequence

Purpose = Literal["final_eval", "report", "selection", "calibration", "interval", "threshold", "baseline", "queue"]
ALLOWED: frozenset[str] = frozenset({"final_eval", "report"})
FORBIDDEN: frozenset[str] = frozenset({"selection", "calibration", "interval", "threshold", "baseline", "queue"})


class TestLeak(Exception):
    """시험 구간이 선정 · 보정 · 구간 · 임계값 · 기준선 · 대기열에 쓰이려 했다 — 치명 결함."""

    __test__ = False  # pytest 수집 대상 아님


class InSampleEvaluation(Exception):
    """평가 구간이 학습(재적합) 구간과 겹친다 — 평창식 표본 내 평가 (spec §5.3 · F5)."""


class AccessLedger:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def record(self, purpose: str, n_rows: int, where: str, ok: bool, reason: str = "") -> None:
        with self._lock:
            self._events.append({"order": len(self._events), "purpose": purpose, "n_rows": n_rows,
                                 "where": where, "ok": ok, "reason": reason})

    def events(self) -> list[dict]:
        return [dict(e) for e in self._events]

    def violations(self) -> list[dict]:
        return [dict(e) for e in self._events if not e["ok"]]

    def final_eval_count(self) -> int:
        return sum(1 for e in self._events if e["purpose"] == "final_eval" and e["ok"])


def _caller() -> str:
    for fr in inspect.stack()[2:6]:
        if not fr.filename.endswith("guard.py"):
            return f"{fr.filename.rsplit('/src/', 1)[-1]}:{fr.lineno}"
    return "?"


class GuardedTest:
    __test__ = False
    __slots__ = ("__idx", "_ledger", "_final_done", "_overlap_done")

    def __init__(self, idx: Sequence[int], ledger: AccessLedger):
        self.__idx = tuple(int(i) for i in idx)
        self._ledger = ledger
        self._final_done = False
        self._overlap_done = False

    def __len__(self) -> int:  # 길이 조회는 접근이 아니다
        return len(self.__idx)

    def _deny(self, what: str):
        self._ledger.record(what, len(self.__idx), _caller(), ok=False, reason="직접 인덱스 접근")
        raise TestLeak(f"시험 구간 인덱스 직접 접근({what}) 금지")

    def __iter__(self):
        self._deny("iter")

    def __getitem__(self, item):
        self._deny("getitem")

    def __array__(self, *a, **k):
        self._deny("array")

    def tolist(self):
        self._deny("tolist")

    def __copy__(self):
        self._deny("copy")

    def __deepcopy__(self, memo):
        self._deny("deepcopy")

    def __reduce_ex__(self, protocol):
        self._deny("pickle")

    def overlaps(self, other_idx: Sequence[int]) -> bool:
        """표본 내 평가 판정용(래퍼당 1회) — 겹침 여부만 알려 주고 인덱스는 내주지 않는다.
        2회째는 질의로 인덱스를 복원하려는 시도로 보고 기록 후 TestLeak."""
        if self._overlap_done:
            self._ledger.record("overlaps", len(self.__idx), _caller(), ok=False, reason="overlaps 2회째")
            raise TestLeak("시험 구간 겹침 질의는 1회만(표본 내 평가 판정)")
        self._overlap_done = True
        return bool(set(self.__idx) & {int(i) for i in other_idx})

    def take(self, frame, purpose: str):
        where = _caller()
        if purpose in FORBIDDEN or purpose not in ALLOWED:
            self._ledger.record(purpose, len(self.__idx), where, ok=False, reason="금지 목적")
            raise TestLeak(f"시험 구간을 {purpose} 에 쓸 수 없다")
        if purpose == "final_eval":
            if self._final_done or self._ledger.final_eval_count():
                self._ledger.record(purpose, len(self.__idx), where, ok=False, reason="final_eval 2회째")
                raise TestLeak("시험 구간 평가는 1회만")
            self._final_done = True
        elif not self._final_done:
            self._ledger.record(purpose, len(self.__idx), where, ok=False, reason="final_eval 전 report")
            raise TestLeak("report 는 final_eval 뒤에만")
        self._ledger.record(purpose, len(self.__idx), where, ok=True)
        return frame.iloc[list(self.__idx)]


def assert_not_in_sample(fit_idx: Sequence[int], test: GuardedTest) -> None:
    """재적합 구간과 평가 구간이 겹치면 InSampleEvaluation."""
    if test.overlaps(fit_idx):
        raise InSampleEvaluation("평가 구간이 학습 구간과 겹친다 (표본 내 평가 금지)")
