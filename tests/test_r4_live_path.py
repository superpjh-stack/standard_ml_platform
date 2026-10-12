"""G-S02 R4 실경로 — live 회사 + 합성 스냅숏 production 은 그 과제를 끈다 (DEF-QA3-001 · 이슈 #17 · D-120).

QA3 재현(outputs/qa3/t09_r4_real.py)을 그대로 시험으로 옮겼다:
tmp 등록부에 sw 사본(mode demo) → delta_e 는 demo(합성) 학습 · defect_risk 는 eval(CSV, 합성 아님) 학습 → 승인(decide) →
YAML 만 `mode: live` 로 바꾸고(합성 소스 제거, DB 의 mlp_tenant.mode 는 demo 그대로 — seed 를 다시 돌리지 않은 운영) →
**실기동 경로**(lifespan) 로 API 를 띄운다. 콜백 주입 없이 등록부 DB 에서 production 스냅숏의 synthetic 을 읽어야 한다.
기대: delta_e 는 disabled(model_ready false) · 예측 200 금지 · defect_risk 는 그대로 운영. 소유 개발3.
"""

from __future__ import annotations

import re

import pytest

import _dev3 as h
from mlcore.registry import packs, tenants
from mlcore.settings import get_settings

pytestmark = [pytest.mark.gate("G-S02"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

SW_ROW = {"absorb_rate": 82.0, "fabric_strength": 340.0, "set_temp": 182.0, "set_pressure": 4.1, "line_speed": 14.0,
          "ink_usage": 21.0, "dwell_time": 46.0, "print_type": "나염", "color_tone": "중간 색상"}


@pytest.fixture(scope="module")
def live_world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("r4")
    base = tmp / "tenants"
    mp.setenv("MLP_TENANTS_DIR", str(base))
    mp.setenv("MLP_SNAPSHOT_DIR", str(tmp / "var" / "snapshots"))
    mp.setenv("MLP_ARTIFACT_DIR", str(tmp / "var" / "artifacts"))
    get_settings.cache_clear()
    code = h.copy_tenant("sw", base, h.new_code("r"))
    m = h.register_db(code)
    keys = h.keys(m)
    v_syn = h.train_to_production(code, f"{code}.delta_e")                         # demo = 합성 스냅숏
    v_csv = h.train_to_production(code, f"{code}.defect_risk", source_role="eval")  # CSV = 합성 아님
    path = base / f"{code}.yaml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^mode: \w+", "mode: live", text, flags=re.M)
    text = re.sub(r"^  demo: .*\n", "", text, flags=re.M)                          # 합성 소스 제거 (QA3 와 같다)
    # live 는 합성 소스가 없으니 필수 변수가 전부 원천 열에 대응해야 한다(R2) — 시험용 열 이름 2개를 붙인다
    text = text.replace("feature_map:", "feature_map:\n  T_COND.DWELL: dwell_time\n  T_COND.TONE: color_tone", 1)
    path.write_text(text, encoding="utf-8")
    tc = h.client(code)
    yield {"code": code, "tc": tc, "k": keys, "v_syn": v_syn, "v_csv": v_csv, "base": base}
    tc.__exit__(None, None, None)
    mp.undo()
    get_settings.cache_clear()


def test_production_snapshot_flags_from_db(live_world):
    code = live_world["code"]
    cb = tenants.db_production_synthetic(code)
    assert cb(f"{code}.delta_e") is True
    assert cb(f"{code}.defect_risk") is False
    assert cb(f"{code}.print_ood") is None                                         # production 없음


def test_live_boot_disables_synthetic_production(live_world):
    code, tc, k = live_world["code"], live_world["tc"], live_world["k"]
    health = tc.get("/api/v1/health").json()
    by = {t["task"]: t for t in health["tasks"]}
    assert by[f"{code}.delta_e"]["model_ready"] is False and "disabled" in by[f"{code}.delta_e"]
    assert by[f"{code}.defect_risk"]["model_ready"] is True and by[f"{code}.defect_risk"]["version"] == live_world["v_csv"]
    listing = tc.get(f"/api/v1/tenants/{code}/tasks", headers=h.hdr(k["viewer"])).json()
    assert [d["task"] for d in listing["disabled"]] == [f"{code}.delta_e"]


def test_live_boot_refuses_synthetic_prediction(live_world):
    code, tc, k = live_world["code"], live_world["tc"], live_world["k"]
    r = tc.post(f"/api/v1/tenants/{code}/tasks/delta_e/predict", headers=h.hdr(k["operator"]), json={"inputs": SW_ROW})
    assert r.status_code != 200, r.text                                            # QA3: 200 · v1 synthetic=true 였다
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_ready"   # D-120a (개발2 require_servable)
    ok = tc.post(f"/api/v1/tenants/{code}/tasks/defect_risk/predict", headers=h.hdr(k["operator"]), json={"inputs": SW_ROW})
    assert ok.status_code == 200 and ok.json()["synthetic"] is False and ok.json()["model"]["version"] == live_world["v_csv"]


def test_serving_loader_is_default_on_real_path(live_world):
    """기동 경로는 콜백을 따로 넘기지 않는다 — 기본이 DB 조회다."""
    code = live_world["code"]
    m = tenants.load_for_serving(code)
    assert f"{code}.delta_e" in m.disabled and f"{code}.defect_risk" in m.tasks


def test_db_unreachable_fails_closed(live_world, monkeypatch):
    """production 을 확인할 수 없으면 live 과제를 켜지 않는다(합성 모델이 새어 나가지 않게)."""
    code = live_world["code"]
    monkeypatch.setenv("MLP_DB_DSN", "dbname=mlp_no_such_db_r4 host=/tmp connect_timeout=2")
    get_settings.cache_clear()
    try:
        m = tenants.load_for_serving(code)
    finally:
        get_settings.cache_clear()
    assert not m.tasks and set(m.disabled) == {f"{code}.{t}" for t in ("delta_e", "defect_risk", "print_ood", "print_setpoint")}
    assert all("확인할 수 없다" in why for why in m.disabled.values())


def test_non_live_never_queries_db(monkeypatch):
    """demo · eval 회사는 R4 대상이 아니다 — DB 가 없어도 기동한다."""
    monkeypatch.setenv("MLP_DB_DSN", "dbname=mlp_no_such_db_r4 host=/tmp connect_timeout=2")
    get_settings.cache_clear()
    try:
        m = tenants.load_for_serving("sw")
    finally:
        get_settings.cache_clear()
    assert not m.disabled and len(m.tasks) == 4


def test_bad_fixture_r4_with_db_callback():
    """불량 픽스처 r4 를 DB 콜백(실경로와 같은 함수) 형태로 판정 — production 합성이면 끄고, 아니면 켠다."""
    path = h.ROOT / "tests" / "fixtures" / "bad_registry" / "r4_live_synthetic" / "tenant.yaml"
    t = tenants.load_tenant(path)
    pk = packs.load_pack(t.config["pack"])
    m = tenants.merge(pk, t, production_synthetic=tenants.ProductionLookup(t.code, rows={"zz4.delta_e": True}))
    assert not m.tasks and "zz4.delta_e" in m.disabled
    m = tenants.merge(pk, t, production_synthetic=tenants.ProductionLookup(t.code, rows={"zz4.delta_e": False}))
    assert "zz4.delta_e" in m.tasks and not m.disabled
