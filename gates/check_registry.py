"""G-S02 — 팩 · 등록부 로드. packs/{press,textile,_template} · tenants/{ks,sw,_template}.yaml 이 로드 · 병합되고,
병합 규칙 5 를 어긴 불량 픽스처 5종(tests/fixtures/bad_registry/)이 전부 기대대로 거부된다 (spec §11.3).
R4 는 spec §11.3-4 대로 "그 과제만 끄기"(model_not_ready)를 기대한다 — decisions.md D-27.
R4 는 콜백을 주입하지 않고 **실기동 경로**로 판정한다(D-120 · DEF-QA3-001): tests/test_r4_live_path.py 가 시험 DB 에
합성 production 을 승인으로 올린 뒤 YAML 만 live 로 바꿔 lifespan 으로 기동 → 과제 disabled · 예측 200 금지를 본다.
"""
from gatelib import ROOT, Line, expected_scope, pytest_gate, registered_packs, registered_tenants, show

R4_TEST = "tests/test_r4_live_path.py"

EXPECTED_PACKS, EXPECTED_TENANTS = expected_scope("phase1")   # 1차 기대값 — gate2 는 run(scope="phase2")
BAD = {"r1_override_type": "R1", "r2_missing_required_feature": "R2", "r3_uses_disabled": "R3",
       "r4_live_synthetic": "R4", "r5_plugin_conflict": "R5"}


def run(scope: str = "phase1") -> list[Line]:
    """등록부에 있는 팩 · 회사 **전부**를 로드한다. 기대 목록(scope)이 등록부에 없으면 FAIL.
    phase1 = 1차(팩 3 · 회사 3), phase2 = goal2 6개사(팩 6 + _template · 회사 6 + _template)."""
    from mlcore.registry import packs, tenants
    exp_packs, exp_tenants = expected_scope(scope)
    reg_packs, reg_tenants = registered_packs(), registered_tenants()
    problems, loaded = [], []
    if exp_packs - reg_packs:
        problems.append(f"팩 없음 {sorted(exp_packs - reg_packs)}")
    if exp_tenants - reg_tenants:
        problems.append(f"회사 없음 {sorted(exp_tenants - reg_tenants)}")
    for code in sorted(reg_packs):
        try:
            p = packs.load_pack(code)
            loaded.append(f"{code}({len(p.tasks)})")
        except Exception as e:  # noqa: BLE001
            problems.append(f"팩 {code}: {e}")
    n_tasks = 0
    for code in sorted(reg_tenants):
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
        if rule == "R4":                       # 실경로 — 시험 DB · lifespan 기동 (주입 콜백 아님)
            r4 = pytest_gate("G-S02", "R4 실경로", R4_TEST)
            if r4.status == "PASS" and "passed" in r4.measured and "skipped" not in r4.measured:   # 건너뜀은 PASS 아님
                rejected += 1
            else:
                problems.append(f"{d}: R4 실경로 {r4.measured}")
            continue
        try:
            t = tenants.load_tenant(path)
            m = tenants.merge(packs.load_pack(t.config["pack"]), t)
            problems.append(f"{d}: 거부되지 않음 ({len(m.tasks)} 과제 켜짐)")
        except tenants.RegistryRejected as e:
            if e.rule == rule:
                rejected += 1
            else:
                problems.append(f"{d}: 다른 규칙 {e.rule} 로 거부 ({e.detail})")
    item = "팩·등록부 로드" if scope == "phase1" else "팩·등록부(6사)"
    if problems:
        return [Line("G-S02", item, "FAIL", f"{len(problems)}건: " + "; ".join(problems[:5]))]
    return [Line("G-S02", item, "PASS",
                 f"팩 {len(loaded)} ({' · '.join(loaded)}) · 회사 {len(reg_tenants)} 로드 · 켜진 과제 {n_tasks} · 불량 픽스처 {rejected}/5 거부(R4=과제 끄기 · 실기동 경로 {R4_TEST}, D-27 · D-120)")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
