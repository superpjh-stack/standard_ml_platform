"""G2-H01 — 1차 잔여 (goal2 §2). 이슈 #7 · #13 · #16 · #19 · #20 의 항목 목록 대조.

항목 목록은 Phase P0 아키텍트가 `gh issue view` 로 읽어 `docs/followups.md` 에 고정했다 — 이 검사기의 FIXED 와 같아야 한다
(행을 빼거나 ID 를 바꾸면 FAIL). 행마다:
  해결 = 근거 열의 `tests/…py` 파일이 있다(회귀 시험) · 사유 = 근거 열의 `D-nn` / `D2-nn` 이 decisions.md 에 있다 · 열림 = FAIL.
추가로 D-123(compose 앱 계정 = mlp_app 구성원 LOGIN — F7-7)은 '사유' 로 넘길 수 없다(goal2 G2-H01 "D-123 해결").
네트워크(gh)는 쓰지 않는다 — 판정이 재현되게.
"""
from __future__ import annotations

import re

from gatelib import ROOT, Line, read, show

FIXED = (["F7-%d" % i for i in range(1, 13)] + ["F13-%d" % i for i in range(1, 5)] + ["F16-%d" % i for i in range(1, 10)]
         + ["F19-%d" % i for i in range(1, 4)] + ["F20-%d" % i for i in range(1, 6)])
MUST_FIX = {"F7-7"}          # D-123
ROW = re.compile(r"^\| (F\d+-\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (해결|사유|열림) \| ([^|]*) \|$", re.M)


def rows() -> dict[str, dict]:
    p = ROOT / "docs" / "followups.md"
    if not p.is_file():
        return {}
    return {m.group(1): {"issue": m.group(2).strip(), "item": m.group(3).strip(), "state": m.group(5), "evidence": m.group(6).strip()}
            for m in ROW.finditer(read(p))}


def run() -> list[Line]:
    r = rows()
    if not r:
        return [Line("G2-H01", "1차 잔여", "FAIL", "docs/followups.md 없음 — 항목 0/" + str(len(FIXED)))]
    probs = []
    if set(r) != set(FIXED):
        probs.append(f"고정 목록과 다름 (빠짐 {sorted(set(FIXED) - set(r))[:3]} · 더함 {sorted(set(r) - set(FIXED))[:3]})")
    dec = read(ROOT / "decisions.md")
    open_, bad = [], []
    for fid, row in sorted(r.items()):
        if row["state"] == "열림":
            open_.append(fid)
        elif row["state"] == "해결":
            tests = re.findall(r"tests/[\w/]+\.py", row["evidence"])
            if not tests or not all((ROOT / t).is_file() for t in tests):
                bad.append(f"{fid} 시험 없음")
        else:  # 사유
            ds = re.findall(r"D2?-\d{2,3}", row["evidence"])
            if fid in MUST_FIX:
                bad.append(f"{fid} 는 사유 불가(D-123 해결 필요)")
            elif not ds or not all(re.search(rf"\| {re.escape(d)} \|", dec) for d in ds):
                bad.append(f"{fid} 사유 D-번호 없음")
    n_fixed = sum(v["state"] == "해결" for v in r.values())
    n_reason = sum(v["state"] == "사유" for v in r.values())
    head = f"항목 {len(r)} — 해결 {n_fixed} · 사유 {n_reason} · 열림 {len(open_)}"
    if open_:
        probs.append(f"열림 {open_[:6]}{' …' if len(open_) > 6 else ''}")
    probs += bad
    if probs:
        return [Line("G2-H01", "1차 잔여", "FAIL", head + " · " + "; ".join(probs[:4]))]
    return [Line("G2-H01", "1차 잔여", "PASS", head + " · D-123 해결")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
