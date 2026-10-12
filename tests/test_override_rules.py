"""G-M03 덮어쓰기 불변 — 승인 지점(approver_role) · 목표(target) (DEF-QA1-003 #10 · DEF-QA1-004 #11 · D-121). 소유 개발3.

재현(outputs/qa1/override_probe.py): 회사 덮어쓰기 `approver_role: line_lead` 가 그대로 적용됐고,
`target: {name: shot_count}`(입력 변수)도 적용돼 학습이 기준선을 이겼다(목표 누수).
기대: 둘 다 병합 규칙 R1 로 기동 거부. 팩 자체에서도 목표가 입력 변수에 있으면 거부.
"""

from __future__ import annotations

import copy

import pytest

from mlcore.registry import packs, tenants

pytestmark = pytest.mark.gate("G-M03")


def _merge(code: str, short: str, over: dict):
    t = tenants.load_tenant(code)
    t = copy.deepcopy(t)
    t.overrides = {short: over}
    return tenants.merge(packs.load_pack(t.config["pack"]), t)


@pytest.mark.parametrize("code,short,role", [("sw", "delta_e", "line_lead"), ("ks", "remaining_hours", "quality"),
                                             ("sw", "print_setpoint", "admin")])
def test_approver_role_change_rejected(code, short, role):
    with pytest.raises(tenants.RegistryRejected) as e:
        _merge(code, short, {"approver_role": role})
    assert e.value.rule == "R1" and "approver_role" in e.value.detail


def test_approver_role_same_value_allowed():
    base = packs.load_pack("textile").tasks["delta_e"]["approver_role"]
    m = _merge("sw", "delta_e", {"approver_role": base})
    assert m.tasks["sw.delta_e"].raw["approver_role"] == base


@pytest.mark.parametrize("code,short,over", [
    ("ks", "remaining_hours", {"target": {"name": "shot_count"}}),              # QA1 재현 그대로 — 입력 변수
    ("ks", "remaining_hours", {"target": {"name": "remaining_hours", "unit": "min"}}),   # 목표 정의 자체 변경
    ("sw", "defect_risk", {"target": {"name": "delta_e", "positive": 1}}),       # 다른 과제 목표로 바꾸기
    ("sw", "delta_e", {"target": None}),                                          # 지우기
])
def test_target_change_rejected(code, short, over):
    with pytest.raises(tenants.RegistryRejected) as e:
        _merge(code, short, over)
    assert e.value.rule == "R1" and "target" in e.value.detail


def test_target_in_features_rejected_even_without_target_override():
    """덮어쓰기로 목표 열을 입력 변수에 넣는 것도 누수 — 거부."""
    t = copy.deepcopy(tenants.load_tenant("sw"))
    pk = copy.deepcopy(packs.load_pack("textile"))
    pk.tasks["delta_e"]["features"] = list(pk.tasks["delta_e"]["features"]) + ["delta_e"]
    with pytest.raises(tenants.RegistryRejected) as e:
        tenants.merge(pk, t)
    assert e.value.rule == "R1" and "target" in e.value.detail


def test_allowed_overrides_still_work():
    m = _merge("ks", "remaining_hours", {"notice": "회사 안내", "title": "남은 수명"})
    assert m.tasks["ks.remaining_hours"].raw["notice"] == "회사 안내"


def test_warn_with_task_must_be_enabled():
    """D-76 — warn_with 의 anomaly 과제도 병합 규칙 3(의존 과제 켜짐)을 받는다."""
    t = copy.deepcopy(tenants.load_tenant("sw"))
    t.config["tasks"]["enable"] = ["sw.delta_e", "sw.defect_risk", "sw.print_setpoint"]
    with pytest.raises(tenants.RegistryRejected) as e:
        tenants.merge(packs.load_pack("textile"), t)
    assert e.value.rule == "R3" and "print_ood" in e.value.detail
