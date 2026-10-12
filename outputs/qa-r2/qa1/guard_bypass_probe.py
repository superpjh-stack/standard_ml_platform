"""QA1 — guard 래퍼 우회 경로 (코드 읽기 결과를 실제로 확인). 학습기가 이 경로를 쓰는지는 정적 검색으로 따로 본다.
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/guard_bypass_probe.py"""
import copy, pickle, sys, re
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.train import guard, split
from tests._dev1 import raw_rows, std_frame, task
t = task(); f = std_frame(t, raw_rows(1000, 1)); sp, test = split.plan(f, t, seed=1)
true_te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
res = []
def rec(name, got, led):
    leaked = got == true_te
    res.append((name, "WARN" if leaked else "PASS", f"시험 인덱스 복원={leaked} · ledger 기록 {len(led.events())}건"))
led = test._ledger
rec("여집합(전체 − 학습 − 검증)", sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx)), led)
rec("vars(test) 이름 맹글링 속성", sorted(next(v for k, v in vars(test).items() if k.endswith("__idx"))), led)
rec("overlaps() 질의로 한 행씩", [i for i in range(len(f)) if test.overlaps([i])], led)
pass  # pickle: AccessLedger 의 Lock 때문에 직렬화 불가 — 우회 경로 아님
rec("boundaries.test_ts 로 시각 자르기", sorted(f.index[f["ts"] >= pd.Timestamp(sp.boundaries["test_ts"][0])].tolist()), led)
# final_eval 2회: 복사본
l2 = guard.AccessLedger(); g = guard.GuardedTest(true_te, l2); c = copy.copy(g)
g.take(f, "final_eval"); 
try:
    c.take(f, "final_eval"); twice = True
except guard.TestLeak:
    twice = False
res.append(("copy.copy 로 final_eval 2회", "WARN" if twice else "PASS", f"2회째 허용={twice} · ledger final_eval {l2.final_eval_count()}회(위반 기록 {len(l2.violations())})"))
# report 는 final_eval 뒤 무제한 · 다른 프레임
l3 = guard.AccessLedger(); g3 = guard.GuardedTest(true_te, l3); g3.take(f, "final_eval")
n = 0
for _ in range(5): g3.take(f, "report"); n += 1
res.append(("final_eval 뒤 report 무제한", "INFO", f"report {n}회 허용(설계상 허용 목적)"))
# 정적: src/mlcore 에서 위 경로를 쓰는 곳
pat = re.compile(r"vars\(|__dict__|\.overlaps\(|copy\.copy\(|deepcopy\(|pickle|test_ts|set\(range\(len")
hits = []
for p in (ROOT / "src" / "mlcore").rglob("*.py"):
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if pat.search(line):
            hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:90]}")
res.append(("src/mlcore 의 우회 패턴 사용처", "INFO", f"{len(hits)}건"))
for n_, s, m in res:
    print(f"G-M05  guard 우회 {n_:34s} {s:5s} {m}")
for h in hits: print("       ", h)
