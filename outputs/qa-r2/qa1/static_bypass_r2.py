"""QA-R2 — check_leakage.scan_bypass 가 새 우회 문법을 잡는가 (src 에 파일을 쓰지 않고 함수에 문자열로 넣는다)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT / "gates")); sys.path.insert(0, str(ROOT))
from check_leakage import scan_bypass
cases = {
 "원: test._GuardedTest__idx": "x = test._GuardedTest__idx",
 "원: vars(test)": "x = vars(test)",
 "원: 여집합": "te = set(range(len(f))) - set(sp.train_idx) - set(sp.valid_idx)",
 "원: test_ts": "c = sp.boundaries['test_ts']",
 "신규: getattr 문자열 조립": "x = getattr(test, '_Guarded' + 'Test__idx')",
 "신규: gc.get_referents": "import gc\nx = gc.get_referents(test)",
 "신규: 여집합 np.setdiff1d": "te = np.setdiff1d(np.arange(len(f)), np.r_[sp.train_idx, sp.valid_idx])",
 "신규: 여집합 리스트 내포": "fit = set(sp.fit_idx)\nte = [i for i in range(len(f)) if i not in fit]",
 "신규: boundaries 키 변수": "k = 'test' + '_ts'\nc = sp.boundaries[k]",
}
for n, src in cases.items():
    v = scan_bypass("src/mlcore/train/x.py", src)
    print(f"{n:32s} {'잡음' if v else '못 잡음'} {v[:1]}")
