"""G-M12 — 이관 대조. docs/migration-report.md 에 ks 4 · sw 4 과제가 같은 합성 시드로 원천 보고 지표와 비교되고
±10%(D-17, 넓힐 수 없다) 안이거나 행마다 사유가 있다. 원천 demo_data() 와 팩 synth/ 의 행 일치 100%.
대조값은 migration/source_inventory.md §1.4 · §2.4 (원천 docs/verification.md 실측)."""
import re

from gatelib import ROOT, Line, read, show

REPORTED = {  # source_inventory.md §1.4 · §2.4 — 원천 파일에서 센 값
    "ks.remaining_hours": {"mae": 5.568, "rmse": 6.979, "r2": 0.9199},
    "ks.failure_24h": {"roc_auc": 0.6444, "pr_auc": 0.1426, "brier": 0.0576},
    "sw.delta_e": {"mae": 0.557, "rmse": 0.709, "r2": 0.722},
    "sw.defect_risk": {"roc_auc": 0.868, "pr_auc": 0.781, "brier": 0.127},
}
TOLERANCE = 0.10
TASKS8 = ["ks.remaining_hours", "ks.failure_24h", "ks.sensor_ood", "ks.maintenance_timing",
          "sw.delta_e", "sw.defect_risk", "sw.print_ood", "sw.print_setpoint"]


def _inventory_has_values() -> bool:
    inv = read(ROOT / "migration" / "source_inventory.md")
    return all(str(v) in inv for m in REPORTED.values() for v in m.values())


def run() -> list[Line]:
    if not _inventory_has_values():
        return [Line("G-M12", "이관 대조", "FAIL", "source_inventory.md 대조값이 REPORTED 와 다르다")]
    synth = {c: list((ROOT / "packs" / c / "synth").glob("*.py")) for c in ("press", "textile")}
    no_synth = [c for c, v in synth.items() if not v]
    rep = ROOT / "docs" / "migration-report.md"
    if not rep.is_file():
        return [Line("G-M12", "이관 대조", "FAIL", f"docs/migration-report.md 없음 — 대조 0/8 · 합성 생성기 미이관 {no_synth} (대조값 {len(REPORTED)}과제 준비됨)")]
    txt = read(rep)
    missing = [t for t in TASKS8 if not re.search(rf"^\|\s*{re.escape(t)}\s*\|", txt, re.M)]
    row_match = re.search(r"행 일치\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", txt)
    probs = []
    if missing:
        probs.append(f"과제 행 없음 {missing}")
    if no_synth:
        probs.append(f"합성 생성기 없음 {no_synth}")
    if not row_match or float(row_match.group(1)) != 100.0:
        probs.append(f"행 일치 {row_match.group(1) if row_match else '미기재'}%")
    for t, metrics in REPORTED.items():
        m = re.search(rf"^\|\s*{re.escape(t)}\s*\|([^\n]*)$", txt, re.M)
        if not m:
            continue
        row = m.group(1)
        for name, ref in metrics.items():
            mm = re.search(rf"{name}\s*=?\s*([0-9.]+)", row)
            if mm and abs(float(mm.group(1)) - ref) / abs(ref) > TOLERANCE and "사유" not in row:
                probs.append(f"{t}.{name} ±10% 밖 · 사유 없음")
    return [Line("G-M12", "이관 대조", "FAIL" if probs else "PASS", "; ".join(probs[:4]) if probs else "과제 8 대조 · 행 일치 100%")]


# ── 2차 (gate2) — goal2 §2 "G-M12 는 6개사 이관 대조" · §1-4 ────────────────────────────────────
# 대조값: migration/source_inventory.md §8.4 · §9.4 · §10.4 · §11.4. 원천 문서에 수치가 있는 것은 kd 공수 회귀뿐이다.
# krs · ot 는 원천 절차 재현값(D2-12), pc 는 표준 재측정이 정본 · 원천 값 병기만(D2-02, ±10% 대조 제외).
REPORTED2 = {"kd.labor_hours": {"mae": 4.1071, "rmse": 5.0456, "r2": 0.9956}}
TASKS2 = ["krs.joint_strength", "krs.recipe_optimize", "krs.residual_review",
          "pc.sensory_score", "pc.recipe_optimize", "pc.residual_review",
          "ot.machining_minutes", "ot.cad_objects", "ot.quote",
          "kd.labor_hours", "kd.drawing_regions", "kd.quote"]
SYNTH2 = ("solder", "kimchi", "rollform-quote", "eto")


def run_phase2() -> list[Line]:
    """6개사 이관 대조 — 1차 8 + 2차 12 과제 행 · 4 팩 합성 생성기 · kd 원천 보고값 ±10% · pc 재측정 병기."""
    probs = []
    inv = read(ROOT / "migration" / "source_inventory.md")
    if not all(str(v) in inv for m in REPORTED2.values() for v in m.values()):
        probs.append("source_inventory.md 2차 대조값 ≠ REPORTED2")
    no_synth = [c for c in SYNTH2 if not list((ROOT / "packs" / c / "synth").glob("*.py"))]
    if no_synth:
        probs.append(f"합성 생성기 없음 {no_synth}")
    rep = ROOT / "docs" / "migration-report.md"
    txt = read(rep) if rep.is_file() else ""
    missing = [t for t in TASKS8 + TASKS2 if not re.search(rf"^\|\s*{re.escape(t)}\s*\|", txt, re.M)]
    if missing:
        probs.append(f"과제 행 없음 {len(missing)}/{len(TASKS8) + len(TASKS2)} ({', '.join(missing[:3])} …)")
    for t, metrics in REPORTED2.items():
        m = re.search(rf"^\|\s*{re.escape(t)}\s*\|([^\n]*)$", txt, re.M)
        if not m:
            continue
        for name, ref in metrics.items():
            mm = re.search(rf"{name}\s*=?\s*([0-9.]+)", m.group(1))
            if mm and abs(float(mm.group(1)) - ref) / abs(ref) > TOLERANCE and "사유" not in m.group(1):
                probs.append(f"{t}.{name} ±10% 밖 · 사유 없음")
    pc = re.search(r"^\|\s*pc\.sensory_score\s*\|([^\n]*)$", txt, re.M)
    if pc and not ("재측정" in pc.group(1) and "원천" in pc.group(1)):
        probs.append("pc.sensory_score 재측정 · 원천 값 병기 없음(D2-02)")
    return [Line("G-M12", "이관 대조(6사)", "FAIL" if probs else "PASS",
                 "; ".join(probs[:4]) if probs else f"과제 {len(TASKS8) + len(TASKS2)} 대조 · kd 원천 ±10% · pc 재측정 병기")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
