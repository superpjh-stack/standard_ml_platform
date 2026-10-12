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
- 다른 문법(F13-1 · QA-R2): 인덱스는 속성이 아니라 클로저에 있다(getattr 문자열 조립 · slot 서술자 · gc 참조로 시퀀스가
  나오지 않는다) · 모르는 속성 조회는 기록 후 TestLeak · 시험 시각 범위는 SplitPlan 이 아니라 래퍼가 갖고 final_eval 뒤에만.
"""

from __future__ import annotations

import inspect
import threading
from typing import Literal, Sequence

Purpose = Literal["final_eval", "report", "selection", "calibration", "interval", "threshold", "baseline", "queue",
                  "queue_scoring"]
ALLOWED: frozenset[str] = frozenset({"final_eval", "report"})
FORBIDDEN: frozenset[str] = frozenset({"selection", "calibration", "interval", "threshold", "baseline", "queue",
                                       "queue_scoring"})   # queue_scoring = std/split_policies.yaml 이름 (G2-R01)


class TestLeak(Exception):
    """시험 구간이 선정 · 보정 · 구간 · 임계값 · 기준선 · 대기열에 쓰이려 했다 — 치명 결함."""

    __test__ = False  # pytest 수집 대상 아님


class InSampleEvaluation(Exception):
    """평가 구간이 학습(재적합) 구간과 겹친다 — 표본 내 평가 (spec §5.3 · F5)."""


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


def _seal(idx: tuple[int, ...], bounds: dict):
    """인덱스 · 시험 시각 범위를 클로저에 가둔다 — 래퍼 속성(slot · getattr · gc 참조)에 시퀀스가 없다(F13-1)."""
    def rows(frame):
        return frame.iloc[list(idx)]

    def reveal():
        return dict(bounds)

    def overlap(other) -> bool:
        member = frozenset(idx)
        return any(int(i) in member for i in other)

    return rows, reveal, overlap


class GuardedTest:
    __test__ = False
    __slots__ = ("_n", "_rows", "_reveal", "_overlap", "_ledger", "_final_done", "_overlap_done")

    def __init__(self, idx: Sequence[int], ledger: AccessLedger, *, bounds: dict | None = None):
        sealed = tuple(int(i) for i in idx)
        self._n = len(sealed)
        self._rows, self._reveal, self._overlap = _seal(sealed, bounds or {})
        self._ledger = ledger
        self._final_done = False
        self._overlap_done = False

    def __len__(self) -> int:  # 길이 조회는 접근이 아니다
        return self._n

    def __getattr__(self, name: str):
        """정의되지 않은 속성 조회(getattr 문자열 조립 · 이름 맹글링 추측 등)는 기록 후 TestLeak (F13-1).
        dunder 는 파이썬 · 라이브러리의 정상 탐색이라 AttributeError 그대로."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        self._deny(f"getattr:{name}")

    def _deny(self, what: str):
        self._ledger.record(what, self._n, _caller(), ok=False, reason="직접 인덱스 접근")
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
            self._ledger.record("overlaps", self._n, _caller(), ok=False, reason="overlaps 2회째")
            raise TestLeak("시험 구간 겹침 질의는 1회만(표본 내 평가 판정)")
        self._overlap_done = True
        return self._overlap(other_idx)

    def bounds(self) -> dict:
        """시험 구간 시각 범위(`test_ts`) — final_eval 뒤 보고서용으로만. 그 전에는 기록 후 TestLeak (F13-1:
        SplitPlan.boundaries 에 test_ts 를 두지 않아 변수 키로 시험 행을 자를 수 없다)."""
        if not self._final_done:
            self._ledger.record("bounds", self._n, _caller(), ok=False, reason="final_eval 전 시험 경계")
            raise TestLeak("시험 구간 경계는 final_eval 뒤에만")
        return self._reveal()

    def take(self, frame, purpose: str):
        where = _caller()
        if purpose in FORBIDDEN or purpose not in ALLOWED:
            self._ledger.record(purpose, self._n, where, ok=False, reason="금지 목적")
            raise TestLeak(f"시험 구간을 {purpose} 에 쓸 수 없다")
        if purpose == "final_eval":
            if self._final_done or self._ledger.final_eval_count():
                self._ledger.record(purpose, self._n, where, ok=False, reason="final_eval 2회째")
                raise TestLeak("시험 구간 평가는 1회만")
            self._final_done = True
        elif not self._final_done:
            self._ledger.record(purpose, self._n, where, ok=False, reason="final_eval 전 report")
            raise TestLeak("report 는 final_eval 뒤에만")
        self._ledger.record(purpose, self._n, where, ok=True)
        return self._rows(frame)


def assert_not_in_sample(fit_idx: Sequence[int], test: GuardedTest) -> None:
    """재적합 구간과 평가 구간이 겹치면 InSampleEvaluation."""
    if test.overlaps(fit_idx):
        raise InSampleEvaluation("평가 구간이 학습 구간과 겹친다 (표본 내 평가 금지)")
