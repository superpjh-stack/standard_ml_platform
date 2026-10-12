"""QA-R2 — R1 덮어쓰기 회귀(정상 덮어쓰기는 통과하는가) + 새 우회 시도(목표 누수 · 승인 지점)."""
import shutil, sys, tempfile
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.registry import tenants
pack = yaml.safe_load((ROOT / "packs/press/tasks/remaining_hours.yaml").read_text())
cases = [
  ("[정상] approver_role 같은 값 재기입", {"approver_role": pack["approver_role"]}, False),
  ("[정상] target 같은 값 재기입", {"target": pack["target"]}, False),
  ("[정상] candidates 줄이기", {"candidates": (pack.get("candidates") or ["ridge"])[:1]}, False),
  ("[정상] out_of_range 정책 reject", {"out_of_range": "reject"}, False),
  ("[정상] max_imputed 2", {"max_imputed": 2}, False),
  ("[정상] features 하나 빼기(선택 변수)", {"features": [f for f in pack["features"] if f != "vibration"]}, False),
  ("[우회] target 대소문자 다른 이름", {"target": {**pack["target"], "name": pack["target"]["name"].upper()}}, True),
  ("[우회] target 에 공백", {"target": {**pack["target"], "name": pack["target"]["name"] + " "}}, True),
  ("[우회] approver_role 대소문자", {"approver_role": str(pack["approver_role"]).upper()}, True),
  ("[우회] approver_role 목록으로", {"approver_role": [pack["approver_role"], "line_lead"]}, True),
  ("[우회] fixed 에 목표 열", {"fixed": [pack["target"]["name"]]}, True),
  ("[우회] uses 에 자기 자신", {"uses": ["press.remaining_hours"]}, True),
  ("[우회] approval 키 추가(자동 승인?)", {"auto_promote": True}, True),
  ("[우회] split 같은 이름 다른 대소문자", {"split": str(pack.get("split", "time_60_20_20")).upper()}, True),
]
for name, over, expect_reject in cases:
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "tenants" / "ks.yaml", d / "ks.yaml")
    (d / "ks" / "tasks").mkdir(parents=True)
    (d / "ks" / "tasks" / "remaining_hours.yaml").write_text(yaml.safe_dump(over, allow_unicode=True))
    try:
        m = tenants.load_and_merge("ks", tenants_base=d)
        t = m.tasks.get("ks.remaining_hours")
        got = {k: (t.raw.get(k) if t else "과제 꺼짐") for k in over}
        st = "FAIL" if expect_reject else "PASS"; res = f"통과 {str(got)[:110]}"
    except Exception as e:
        st = "PASS" if expect_reject else "FAIL"; res = f"거부 {type(e).__name__}: {str(e)[:100]}"
    print(f"G-M03  {name:34s} {st:5s} {res}")
    shutil.rmtree(d)
