"""make gate — 전 게이트 판정표 (goal §2 · §4.2). 결과는 화면과 outputs/gate-latest.md.

순서: 수직 관통(G-V01) → 구조(G-S01~07) → ML(G-M01~14). 형식 `G-nn  항목  PASS|FAIL|WARN|BLOCKED  실측`.
검사기 자체 오류도 FAIL 로 보인다. 종료 코드 0 = FAIL 0.
"""
from __future__ import annotations

import datetime
import importlib
import sys

from gatelib import ROOT, Line, pytest_gate

CHECKS = [
    lambda: [pytest_gate("G-V01", "수직 관통", "tests/test_vertical_slice.py")],
    "check_schema", "check_registry", "check_routes", "check_sources", "check_secrets", "check_tenant_bleed", "check_pins",
    "check_core_terms", "check_task_cover", "check_tasks", "check_contract", "check_leakage", "check_determinism",
    lambda: [pytest_gate("G-M07", "예측 추적", "tests/test_trace.py")],
    lambda: [pytest_gate("G-M08", "소스·doctor", "tests/test_doctor.py"),
             Line("G-M08", "doctor-live", "BLOCKED", "실연결은 사람이 .env 에 키를 넣은 뒤 (D-13)")],
    "check_no_autopromote",
    lambda: [pytest_gate("G-M10", "새 회사", "tests/test_new_tenant.py")],
    "check_deploy", "check_migration",
    lambda: [pytest_gate("G-M13", "최적화", "tests/test_optimize.py")],
    lambda: importlib.import_module("bench").run(compose=importlib.import_module("bench")._docker_up()),   # make bench 와 같다
]
ORDER = ["G-V01"] + [f"G-S0{i}" for i in range(1, 8)] + [f"G-M{i:02d}" for i in range(1, 15)]


def main() -> int:
    lines: list[Line] = []
    for c in CHECKS:
        try:
            got = c() if callable(c) else importlib.import_module(c).run()
        except Exception as e:  # noqa: BLE001
            name = c if isinstance(c, str) else "check"
            got = [Line("G-??", name, "FAIL", f"검사기 오류 {type(e).__name__}: {str(e)[:120]}")]
        lines.extend(got)
    lines.sort(key=lambda ln: ORDER.index(ln.gate) if ln.gate in ORDER else 99)
    out = [ln.render() for ln in lines]
    counts = {s: sum(ln.status == s for ln in lines) for s in ("PASS", "FAIL", "WARN", "BLOCKED")}
    summary = " · ".join(f"{k} {v}" for k, v in counts.items() if v)
    print("\n".join(out))
    print(f"\n합계 {len(lines)}행 — {summary}")
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "gate-latest.md").write_text(
        f"# make gate — {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n\n```\n" + "\n".join(out)
        + f"\n```\n\n합계 {len(lines)}행 — {summary}\n", encoding="utf-8")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
