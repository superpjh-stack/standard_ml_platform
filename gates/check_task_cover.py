"""G-M02 — 과제 대응. migration/source_inventory.md §5 의 기능 단위(분모 — ks 16 · sw 16 = 32) 전부가
docs/task-map.md 에서 표준 과제 · 경로 · 화면에 대응된다. 미대응 0."""
import re

from gatelib import ROOT, Line, read, show


def units() -> list[str]:
    text = read(ROOT / "migration" / "source_inventory.md")
    sec = text[text.index("## 5."): text.index("## 6.")]
    ids = []
    for m in re.finditer(r"^\| ((KS|SW)-[A-Z]\d)(~[A-Z](\d))? \|", sec, re.M):
        if m.group(3):
            letter = m.group(1)[3]
            ids += [f"{m.group(2)}-{letter}{i}" for i in range(int(m.group(1)[4:]), int(m.group(4)) + 1)]
        else:
            ids.append(m.group(1))
    # "SW-E1~E7 위와 같은 7" 표기 처리
    return sorted(set(ids))


def run() -> list[Line]:
    u = units()
    expected = 32
    tm = ROOT / "docs" / "task-map.md"
    if len(u) != expected:
        return [Line("G-M02", "과제 대응", "FAIL", f"인벤토리 분모 {len(u)} (기대 {expected}) — migration/source_inventory.md §5 확인")]
    if not tm.is_file():
        return [Line("G-M02", "과제 대응", "FAIL", f"docs/task-map.md 없음 — 대응 0/{len(u)} (분모 ks 16 · sw 16)")]
    txt = read(tm)
    mapped, missing = [], []
    for i in u:
        m = re.search(rf"^\| {re.escape(i)} \|([^\n]*)$", txt, re.M)
        cells = [c.strip() for c in m.group(1).split("|")] if m else []
        if m and any(re.search(r"[a-z]{2,}\.[a-z_]+|/api/|화면 \d", c) for c in cells) and "미대응" not in m.group(1):
            mapped.append(i)
        else:
            missing.append(i)
    if missing:
        return [Line("G-M02", "과제 대응", "FAIL", f"대응 {len(mapped)}/{len(u)} · 미대응 {missing[:8]}")]
    return [Line("G-M02", "과제 대응", "PASS", f"대응 {len(u)}/{len(u)} (ks 16 · sw 16) · 미대응 0")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
