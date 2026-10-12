"""G-S02 — 팩 · 등록부 로드. packs/{press,textile,_template} · tenants/{ks,sw,_template}.yaml 이 로드 · 병합되고,
병합 규칙 5 를 어긴 불량 픽스처 5종(tests/fixtures/bad_registry/)이 전부 기대대로 거부된다 (spec §11.3).
R4 는 spec §11.3-4 대로 "그 과제만 끄기"(model_not_ready)를 기대한다 — decisions.md D-27.
"""
from gatelib import ROOT, Line, show

EXPECTED_PACKS = {"press", "textile", "_template"}
EXPECTED_TENANTS = {"ks", "sw", "_template"}
BAD = {"r1_override_type": "R1", "r2_missing_required_feature": "R2", "r3_uses_disabled": "R3",
       "r4_live_synthetic": "R4", "r5_plugin_conflict": "R5"}


def run() -> list[Line]:
    from mlcore.registry import packs, tenants
    problems, loaded = [], []
    for code in sorted(EXPECTED_PACKS):
        try:
            p = packs.load_pack(code)
            loaded.append(f"{code}({len(p.tasks)})")
        except Exception as e:  # noqa: BLE001
            problems.append(f"팩 {code}: {e}")
    n_tasks = 0
    for code in sorted(EXPECTED_TENANTS):
        try:
            m = tenants.load_and_merge(code)
            n_tasks += len(m.tasks) if code != "_template" else 0
            if m.disabled:
                problems.append(f"{code}: 꺼진 과제 {list(m.disabled)}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"회사 {code}: {e}")
    rejected = 0
    base = ROOT / "tests" / "fixtures" / "bad_registry"
    for d, rule in BAD.items():
        path = base / d / "tenant.yaml"
        if not path.is_file():
            problems.append(f"불량 픽스처 {d} 없음")
            continue
        try:
            t = tenants.load_tenant(path)
            m = tenants.merge(packs.load_pack(t.config["pack"]), t, production_synthetic=lambda tid: True)
            if rule == "R4" and m.disabled and not m.tasks:
                rejected += 1
            else:
                problems.append(f"{d}: 거부되지 않음")
        except tenants.RegistryRejected as e:
            if e.rule == rule:
                rejected += 1
            else:
                problems.append(f"{d}: 다른 규칙 {e.rule} 로 거부 ({e.detail})")
    if problems:
        return [Line("G-S02", "팩·등록부 로드", "FAIL", f"{len(problems)}건: " + "; ".join(problems[:5]))]
    return [Line("G-S02", "팩·등록부 로드", "PASS",
                 f"팩 {len(loaded)} ({' · '.join(loaded)}) · 회사 3 로드 · 켜진 과제 {n_tasks} · 불량 픽스처 {rejected}/5 거부(R4=과제 끄기, D-27)")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
