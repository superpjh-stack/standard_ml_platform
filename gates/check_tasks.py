"""G-M03 — 과제 정의. 팩마다 features.yaml · 과제 ≥ 2 · synth/*.py · baselines.yaml.
과제 YAML 은 스키마 · 변수 존재 · uses 존재 · 누수 규칙(time_key → 시간순) · approver_role 을 갖춘다(로더가 검사).
회사 덮어쓰기로 type · 분할 · 승인 지점 · 목표를 바꾸면 거부(불량 픽스처 R1 + 추가 변형 시험). 코드 안 FEATURE_META dict 0."""
import copy
import re

import yaml

from gatelib import ROOT, Line, read, show

PACKS = ("press", "textile", "_template")


def run() -> list[Line]:
    from mlcore.registry import packs, tenants
    problems, ok_tasks = [], 0
    for code in PACKS:
        d = ROOT / "packs" / code
        try:
            p = packs.load_pack(code)
            ok_tasks += len(p.tasks)
        except packs.PackInvalid as e:
            problems += [f"{code}: {x}" for x in e.problems[:3]]
            continue
        synth = [f for f in (d / "synth").glob("*.py") if f.stem != "__init__"]
        if not synth:
            problems.append(f"{code}: synth/*.py 없음(합성 생성기 미이관)")
        if not (d / "baselines.yaml").is_file():
            problems.append(f"{code}: baselines.yaml 없음")
        else:
            b = yaml.safe_load(read(d / "baselines.yaml")) or {}
            if set(b) != set(p.tasks):
                problems.append(f"{code}: baselines 과제 {sorted(b)} ≠ {sorted(p.tasks)}")
    # 덮어쓰기 불변 — 변형 시험
    base = packs.load_pack("textile")
    t = tenants.load_tenant("sw")
    rejected = 0
    variants = (("type", "risk"), ("split", "random_60_20_20"), ("time_key", None), ("approver_role", None),
                ("approver_role", "line_lead"),                       # 승인 지점 바꾸기 (DEF-QA1-003 · D-121)
                ("target", {"name": "set_temp"}),                     # 목표를 입력 변수로 (DEF-QA1-004 · D-121)
                ("target", {"name": "delta_e", "unit": "dE00"}))      # 목표 정의 바꾸기
    for key, val in variants:
        tt = copy.deepcopy(t)
        tt.overrides = {"delta_e": {key: val}}
        try:
            tenants.merge(base, tt)
            problems.append(f"덮어쓰기 {key}={val!r} 가 허용됨")
        except tenants.RegistryRejected:
            rejected += 1
    # 코드 안 변수 dict
    for f in (ROOT / "src").rglob("*.py"):
        if re.search(r"FEATURE_META\s*=|CONTROL_META\s*=", read(f)):
            problems.append(f"{f.relative_to(ROOT)}: 코드 안 변수 사전")
    msg = f"팩 {len(PACKS)} · 과제 YAML {ok_tasks} 스키마 통과 · 덮어쓰기 불변 {rejected}/{len(variants)} 거부"
    if problems:
        return [Line("G-M03", "과제 정의", "FAIL", msg + f" · 위반 {len(problems)}: " + "; ".join(problems[:4]))]
    return [Line("G-M03", "과제 정의", "PASS", msg + " · synth · baselines 있음")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
