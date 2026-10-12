"""G2-C01 — 코어 동결 (goal2 §2 · §4).

판정:
  1. 로컬 태그 `core-freeze-2` 가 있어야 한다. **태그 전에는 판정 대상이 없다 → FAIL**(사유 "태그 전"). 대기 · WARN 으로
     낮추지 않는다(goal §4.3 가짜 PASS 금지). 태그는 웨이브 P 끝(1차 게이트 PASS + G2-T01 · G2-R01 · G2-H01 PASS)에
     오케스트레이터가 찍는다.
  2. `git diff core-freeze-2 -- src/mlcore web/src/components std contracts` = **0줄**(커밋 안 한 작업 트리 변경 포함).
  3. 태그 뒤 커밋이 바꾼 파일은 허용 경로뿐: packs/ · tenants/ · web/src/screens/ · tests/ · docs/ · migration/
     (+ 상태 파일 progress*.md · decisions.md · outputs/ — 코드가 아닌 루프 기록, decisions.md D2-18).
  4. 태그를 다시 찍었다면(웨이브 P 로 되돌아감) 그 사유가 decisions.md 에 `core-freeze-2` 재태그로 있어야 한다 —
     태그 메시지에 `retag` 가 있으면 decisions.md 에서 `재태그` 를 찾는다.
"""
from __future__ import annotations

import subprocess

from gatelib import ROOT, Line, read, show

TAG = "core-freeze-2"
FROZEN = ["src/mlcore", "web/src/components", "std", "contracts"]
ALLOWED = ("packs/", "tenants/", "web/src/screens/", "tests/", "docs/", "migration/",
           "progress.md", "progress-dev1.md", "progress-dev2.md", "progress-dev3.md", "decisions.md", "outputs/")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def run() -> list[Line]:
    if _git("rev-parse", "-q", "--verify", f"refs/tags/{TAG}").returncode != 0:
        head = _git("rev-parse", "--short", "HEAD").stdout.strip()
        return [Line("G2-C01", "코어 동결", "FAIL",
                     f"태그 전 — `{TAG}` 없음(HEAD {head}). 판정 대상 없음: 웨이브 P(유형 3 · B09~B11 · 화면 7~10 공용부 · 연동 · 1차 잔여)가 끝나고 "
                     f"1차 게이트 + G2-T01 · G2-R01 · G2-H01 PASS 뒤 오케스트레이터가 찍는다")]
    probs = []
    diff = _git("diff", "--numstat", TAG, "--", *FROZEN).stdout.strip().splitlines()
    untracked = [p for p in _git("ls-files", "--others", "--exclude-standard", "--", *FROZEN).stdout.split("\n") if p]
    changed = 0
    for row in diff:
        a, d, _ = row.split("\t", 2)
        changed += (int(a) if a.isdigit() else 1) + (int(d) if d.isdigit() else 1)
    if changed or untracked:
        probs.append(f"동결 경로 변경 {changed}줄 · 새 파일 {len(untracked)} ({', '.join([r.split(chr(9))[-1] for r in diff][:3] + untracked[:2])})")
    files = [p for p in _git("diff", "--name-only", f"{TAG}..HEAD").stdout.split("\n") if p]
    bad = [p for p in files if not p.startswith(ALLOWED)]
    if bad:
        probs.append(f"태그 뒤 허용 밖 파일 {len(bad)} ({', '.join(bad[:4])})")
    msg = _git("tag", "-l", "--format=%(contents)", TAG).stdout
    if "retag" in msg.lower() and "재태그" not in read(ROOT / "decisions.md"):
        probs.append("재태그 사유가 decisions.md 에 없음")
    commits = _git("rev-list", "--count", f"{TAG}..HEAD").stdout.strip()
    if probs:
        return [Line("G2-C01", "코어 동결", "FAIL", "; ".join(probs))]
    return [Line("G2-C01", "코어 동결", "PASS",
                 f"`{TAG}` 이후 커밋 {commits} · 동결 경로({' · '.join(FROZEN)}) diff 0줄 · 바뀐 파일 {len(files)} 전부 허용 경로")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
