"""QA1 G-M03 — 회사 덮어쓰기로 누수 규칙 · 승인 지점 · 시드를 바꿀 수 있는가 (임시 등록부 루트, 저장소 tenants/ 는 읽기만).
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/override_probe.py"""
import shutil, sys, tempfile
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.registry import tenants
cases = [
    ("type 변경", {"type": "risk"}, True),
    ("split 변경", {"split": "random_60_20_20"}, True),
    ("time_key 지우기", {"time_key": None}, True),
    ("group_key 바꾸기", {"group_key": "machine_code"}, True),
    ("approver_role 지우기", {"approver_role": None}, True),
    ("approver_role 다른 역할로 바꾸기", {"approver_role": "line_lead"}, True),
    ("interval 바꾸기", {"interval": {"method": "split_conformal", "alpha": 0.5}}, True),
    ("seed 바꾸기(시드 골라 쓰기)", {"seed": 7}, None),
    ("features 에 목표 열 추가", {"features": ["press_force", "vibration", "motor_current", "equip_temp", "mold_temp", "cycle_time", "shot_count", "machine_code", "product_type", "remaining_hours"]}, None),
    ("target.name 바꾸기", {"target": {"name": "shot_count"}}, None),
]
for name, over, expect_reject in cases:
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "tenants" / "ks.yaml", d / "ks.yaml")
    (d / "ks" / "tasks").mkdir(parents=True)
    (d / "ks" / "tasks" / "remaining_hours.yaml").write_text(yaml.safe_dump(over, allow_unicode=True))
    try:
        m = tenants.load_and_merge("ks", tenants_base=d)
        t = m.tasks["ks.remaining_hours"]
        got = {k: t.raw.get(k) for k in over}
        res = "통과(적용됨)"
        st = "FAIL" if expect_reject else "WARN"
        detail = f"적용 값 {got}"
    except Exception as e:
        res = "거부"; st = "PASS" if expect_reject in (True, None) else "FAIL"; detail = f"{type(e).__name__}: {str(e)[:90]}"
        if expect_reject is None: st = "PASS"
    print(f"G-M03  덮어쓰기 {name:28s} {st:5s} {res} · {detail}")
    shutil.rmtree(d)
