"""QA-R2 — DEF-QA1-006 재검증: 원 우회 5경로 + 새 경로(getattr 문자열 조립 · gc.get_referents · slot 서술자) · 정적 검사."""
import copy, pickle, sys, gc, subprocess
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.train import guard, split
from tests._dev1 import raw_rows, std_frame, task
t = task(); f = std_frame(t, raw_rows(1000, 1)); sp, test = split.plan(f, t, seed=1)
true_te = sorted(set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
led = test._ledger
def tryit(name, fn):
    n0 = len(led.events())
    try:
        got = fn(); leaked = sorted(got) == true_te
        st = "WARN" if leaked else "PASS"; m = f"복원={leaked}"
    except guard.TestLeak as e:
        st, m = "PASS", f"TestLeak({str(e)[:40]})"
    except Exception as e:
        st, m = "PASS", f"{type(e).__name__}"
    print(f"G-M05  guard 우회 {name:36s} {st:5s} {m} · ledger +{len(led.events())-n0}")
tryit("여집합(전체 − 학습 − 검증)", lambda: set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx))
tryit("vars(test)", lambda: next(v for k, v in vars(test).items() if k.endswith("__idx")))
tryit("overlaps() 한 행씩", lambda: [i for i in range(len(f)) if test.overlaps([i])])
tryit("boundaries.test_ts", lambda: f.index[f["ts"] >= pd.Timestamp(sp.boundaries["test_ts"][0])].tolist())
tryit("copy.copy", lambda: copy.copy(test) and [])
tryit("pickle.dumps", lambda: pickle.dumps(test) and [])
tryit("[신규] getattr 문자열 조립", lambda: getattr(test, "_Guarded" + "Test__idx"))
tryit("[신규] gc.get_referents", lambda: next(x for x in gc.get_referents(test) if isinstance(x, (list, tuple)) and len(x) == len(true_te)))
tryit("[신규] slot 서술자", lambda: [d for k, d in type(test).__dict__.items() if k.endswith("idx")][0].__get__(test))
# final_eval 2회 (ledger 단위)
l2 = guard.AccessLedger(); g = guard.GuardedTest(true_te, l2); g2 = guard.GuardedTest(true_te, l2)
g.take(f, "final_eval")
try: g2.take(f, "final_eval"); tw = True
except guard.TestLeak: tw = False
print(f"G-M05  guard 우회 같은 ledger 다른 래퍼 final_eval 2회       {'WARN' if tw else 'PASS':5s} 허용={tw}")
r = subprocess.run([sys.executable, str(ROOT / "gates" / "check_leakage.py")], capture_output=True, text=True, cwd=ROOT)
print("check_leakage:", (r.stdout.strip().splitlines() or [""])[-1][:300])
