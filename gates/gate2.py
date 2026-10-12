"""make gate2 — 2차 판정표 (goal2 §2 · §4). 결과는 화면과 outputs/gate2-latest.md.

구성: (1) 1차 게이트 전부(gates/gate.py 의 CHECKS 그대로 — 1차 기대값) → (2) 1차 게이트 중 판정 대상이 6개사로 넓어지는 것
(G-S02 · G-M03 · G-M02 · G-M12 의 `(6사)` 행 — 기대 목록은 goal2, 실제 목록은 등록부) → (3) 2차 게이트 G2-*.
**대상이 없는 2차 게이트는 FAIL + 사유**(가짜 PASS 금지). BLOCKED 는 실연결 D-13 만. 종료 코드 0 = FAIL 0.
"""
from __future__ import annotations

import datetime
import importlib
import re
import sys

from gatelib import ROOT, Line, pytest_gate, read

import gate as gate1


def _registry6() -> list[Line]:
    return importlib.import_module("check_registry").run("phase2")


def _tasks6() -> list[Line]:
    return importlib.import_module("check_tasks").run("phase2")


def _cover6() -> list[Line]:
    return importlib.import_module("check_task_cover").run("phase2")


def _migration6() -> list[Line]:
    return importlib.import_module("check_migration").run_phase2()


def _g2_r01() -> list[Line]:
    t = pytest_gate("G2-R01", "대기열 누수", "tests/test_review_queue.py")
    leak = importlib.import_module("check_leakage").run()
    bad = [ln for ln in leak if ln.status != "PASS"]
    if t.status != "PASS" or bad:
        return [Line("G2-R01", "대기열 누수", "FAIL", t.measured + ("" if not bad else f" · check_leakage {bad[0].status}"))]
    return [Line("G2-R01", "대기열 누수", "PASS", f"{t.measured} · check_leakage PASS")]


def _g2_q01() -> list[Line]:
    static = importlib.import_module("check_decimal").run()[0]
    t = pytest_gate("G2-Q01", "견적", "tests/test_quote.py")
    ok = static.status == t.status == "PASS"
    return [Line("G2-Q01", "견적", "PASS" if ok else "FAIL", f"정적 {static.status}: {static.measured} · {t.measured}")]


def _g2_p01() -> list[Line]:
    reg = _registry6()[0]
    tasks = _tasks6()[0]
    synth = pytest_gate("G2-P01", "", "tests/test_synth.py")
    import yaml
    empty = []
    for pack in ("solder", "kimchi", "rollform-quote", "eto"):
        f = ROOT / "packs" / pack / "baselines.yaml"
        vals = (yaml.safe_load(read(f)) or {}) if f.is_file() else {}
        if not vals or any((v or {}).get("value") is None for v in vals.values()):
            empty.append(pack)
    probs = [x.measured for x in (reg, tasks, synth) if x.status != "PASS"]
    if empty:
        probs.append(f"baselines 비었음 {empty}")
    return [Line("G2-P01", "팩·회사 4", "FAIL" if probs else "PASS",
                 "; ".join(p[:110] for p in probs[:4]) if probs else f"{reg.measured[:80]} · {synth.measured}")]


def _g2_s01() -> list[Line]:
    rows = [ln for ln in read(ROOT / "contracts" / "screen-map.md").splitlines() if re.match(r"^\| (7|8|9|10) \|", ln)]
    on = [ln for ln in rows if re.search(r"\| ○[^|]*\|$", ln)]
    e2e = pytest_gate("G2-S01", "", "tests/e2e/test_console.py")
    probs = []
    if len(on) != 4:
        probs.append(f"screen-map 화면 7~10 중 판정 대상(○) {len(on)}/4 — 웨이브 P 끝에 아키텍트가 켠다")
    if e2e.status != "PASS":
        probs.append(e2e.measured)
    missing = [m.group(1) for ln in rows if (m := re.search(r"`(web/src/screens/[A-Za-z]+\.tsx)`", ln)) and not (ROOT / m.group(1)).is_file()]
    if missing:
        probs.append(f"화면 파일 없음 {missing}")
    return [Line("G2-S01", "화면 7~10", "FAIL" if probs else "PASS", "; ".join(probs) if probs else f"화면 7~10 ○ 4/4 · {e2e.measured}")]


def _g2_a01() -> list[Line]:
    rows = [re.match(r"^\| (B\d\d) [a-z]+ \| ([12]) \|", ln) for ln in read(ROOT / "contracts" / "api-contract.md").splitlines()]
    p1 = {m.group(1) for m in rows if m and m.group(2) == "1"}
    t = pytest_gate("G2-A01", "", "tests/test_api_contract.py")
    probs = []
    if len(p1) != 15:
        probs.append(f"계약 §1 단계 1 묶음 {len(p1)}/15 (B09~B11 은 웨이브 P 끝에 단계 1 로)")
    if t.status != "PASS":
        probs.append(t.measured)
    return [Line("G2-A01", "API 15", "FAIL" if probs else "PASS", "; ".join(probs) if probs else f"15/15 · {t.measured}")]


def _g2_i02() -> list[Line]:
    t = pytest_gate("G2-I02", "허브 내보내기", "tests/test_export_hub.py")
    mk = read(ROOT / "Makefile")
    real = re.search(r"^export-hub:.*\n\t(?!@echo \"미구현)", mk, re.M)
    probs = [] if real else ["make export-hub 미구현"]
    if t.status != "PASS":
        probs.append(t.measured)
    return [Line("G2-I02", "허브 내보내기", "FAIL" if probs else "PASS", "; ".join(probs) if probs else t.measured)]


CHECKS2 = [
    _registry6, _tasks6, _cover6, _migration6,
    lambda: importlib.import_module("check_core_freeze").run(),
    lambda: [pytest_gate("G2-V01", "2차 수직 관통", "tests/test_vertical_slice_2.py")],
    lambda: importlib.import_module("check_contract").run_phase2(),
    _g2_r01,
    lambda: [pytest_gate("G2-E01", "추출", "tests/test_extract.py")],
    _g2_q01, _g2_p01, _g2_s01, _g2_a01,
    lambda: [pytest_gate("G2-I01", "Agent 도구", "tests/test_agent_tools.py")],
    _g2_i02,
    lambda: importlib.import_module("check_followups").run(),
    lambda: [Line("G2-L01", "실데이터", "BLOCKED", "키가 없다 — 사람이 .env 에 넣은 뒤 make train-live (D-13)")],
]
ORDER2 = ["G2-C01", "G2-V01", "G2-T01", "G2-R01", "G2-E01", "G2-Q01", "G2-P01", "G2-S01", "G2-A01", "G2-I01", "G2-I02", "G2-H01", "G2-L01"]


def _collect(checks) -> list[Line]:
    out: list[Line] = []
    for c in checks:
        try:
            got = c() if callable(c) else importlib.import_module(c).run()
        except Exception as e:  # noqa: BLE001
            name = c if isinstance(c, str) else getattr(c, "__name__", "check")
            got = [Line("G-??", str(name)[:16], "FAIL", f"검사기 오류 {type(e).__name__}: {str(e)[:120]}")]
        out.extend(got)
    return out


def main() -> int:
    first = _collect(gate1.CHECKS)
    first.sort(key=lambda ln: gate1.ORDER.index(ln.gate) if ln.gate in gate1.ORDER else 99)
    second = _collect(CHECKS2)
    widened = [ln for ln in second if ln.gate.startswith("G-")]
    g2 = sorted([ln for ln in second if not ln.gate.startswith("G-")],
                key=lambda ln: ORDER2.index(ln.gate) if ln.gate in ORDER2 else 99)

    def counts(lines):
        return {s: sum(ln.status == s for ln in lines) for s in ("PASS", "FAIL", "WARN", "BLOCKED")}

    def summary(lines):
        return " · ".join(f"{k} {v}" for k, v in counts(lines).items() if v)

    blocks = [("1차 게이트 (gates/gate.py — 1차 기대값)", first),
              ("1차 게이트 · 6개사로 넓힌 판정 (goal2 §2 머리말)", widened),
              ("2차 게이트 G2-*", g2)]
    out = []
    for title, lines in blocks:
        out += [f"## {title}", *[ln.render() for ln in lines], f"소계 {len(lines)}행 — {summary(lines)}", ""]
    total = first + widened + g2
    tail = f"합계 {len(total)}행 — {summary(total)}"
    print("\n".join(out) + tail)
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "gate2-latest.md").write_text(
        f"# make gate2 — {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n\n```\n" + "\n".join(out) + tail + "\n```\n",
        encoding="utf-8")
    return 0 if counts(total)["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
