"""G-M02 — 과제 대응. migration/source_inventory.md 의 기능 단위(분모) 전부가 docs/task-map.md 에서
표준 과제 · 경로 · 화면에 대응된다. 미대응 0.

phase1(1차 게이트) = §5 의 ks 16 · sw 16 = 32.
phase2(gate2, goal2 §2 "G-M02 는 6개사 task-map") = §5 + §12 — ks · sw · krs · pc · ot · kd = 100 (§12 표의 합).
"""
import re

from gatelib import ROOT, Line, read, show

PHASE1 = {"prefixes": ("KS", "SW"), "sections": (("## 5.", "## 6."),), "expected": 32, "label": "ks 16 · sw 16"}
PHASE2 = {"prefixes": ("KS", "SW", "KRS", "PC", "OT", "KD"), "sections": (("## 5.", "## 6."), ("## 12.", "## 13.")),
          "expected": 100, "label": "6개사 — ks 16 · sw 16 · krs 14 · pc 14 · ot 20 · kd 20"}
UNIT_RE = re.compile(r"^\| ((KS|SW|KRS|PC|OT|KD)-([A-Z])(\d+))(~([A-Z])(\d+))? \|", re.M)


def units(scope: str = "phase1") -> list[str]:
    cfg = PHASE2 if scope == "phase2" else PHASE1
    text = read(ROOT / "migration" / "source_inventory.md")
    ids = []
    for start, end in cfg["sections"]:
        if start not in text:
            continue
        sec = text[text.index(start): text.index(end, text.index(start))]
        for m in UNIT_RE.finditer(sec):
            if m.group(2) not in cfg["prefixes"]:
                continue
            if m.group(5):   # "KS-S1~S5" · "SW-E1~E7" 범위 표기
                ids += [f"{m.group(2)}-{m.group(3)}{i}" for i in range(int(m.group(4)), int(m.group(7)) + 1)]
            else:
                ids.append(m.group(1))
    return sorted(set(ids))


def run(scope: str = "phase1") -> list[Line]:
    cfg = PHASE2 if scope == "phase2" else PHASE1
    item = "과제 대응" if scope == "phase1" else "과제 대응(6사)"
    u = units(scope)
    expected = cfg["expected"]
    tm = ROOT / "docs" / "task-map.md"
    if len(u) != expected:
        return [Line("G-M02", item, "FAIL", f"인벤토리 분모 {len(u)} (기대 {expected}) — migration/source_inventory.md 확인")]
    if not tm.is_file():
        return [Line("G-M02", item, "FAIL", f"docs/task-map.md 없음 — 대응 0/{len(u)} (분모 {cfg['label']})")]
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
        return [Line("G-M02", item, "FAIL", f"대응 {len(mapped)}/{len(u)} · 미대응 {len(missing)} {missing[:6]}")]
    return [Line("G-M02", item, "PASS", f"대응 {len(u)}/{len(u)} ({cfg['label']}) · 미대응 0")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
