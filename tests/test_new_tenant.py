"""G-M10 — 새 회사: 빈 등록부 → `make tenant NEW=yn PACK=_template` + CSV(tmp) → doctor → train → 승인 → predict.

코드 수정 0줄: 이 시험은 저장소 코드 · 팩 · 등록부 파일을 하나도 쓰지 않는다. 등록부 루트(`MLP_TENANTS_DIR`) ·
스냅숏 · 산출물 폴더는 tmp 다(D-51 — CSV 도 tmp 에서 만들고 커밋하지 않는다). 생성 파일은 `<root>/<code>.yaml` 하나뿐.
시험 DB 의 추가만 테이블과 섞이지 않도록 회사 코드는 `yn` + 4 hex 를 쓴다(`yn` 자체는 파일 생성만 따로 본다).
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

import _dev3 as h
from migration import make_fixtures, make_tenant
from mlcore.registry import tenants
from mlcore.settings import get_settings

pytestmark = pytest.mark.gate("G-M10")
ROOT = Path(__file__).resolve().parents[1]
KEYS_18 = {"task", "type", "tenant", "entity_id", "prediction", "probability", "anomaly", "recommendation", "status",
           "warnings", "imputed_fields", "out_of_range_fields", "explain", "model", "uses", "prediction_id",
           "synthetic", "notice"}


@pytest.fixture
def empty_root(tmp_path, monkeypatch):
    root = tmp_path / "tenants"
    root.mkdir()
    monkeypatch.setenv("MLP_TENANTS_DIR", str(root))
    monkeypatch.setenv("MLP_SNAPSHOT_DIR", str(tmp_path / "var" / "snapshots"))
    monkeypatch.setenv("MLP_ARTIFACT_DIR", str(tmp_path / "var" / "artifacts"))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def _csv(tmp_path) -> Path:
    assert make_fixtures.main(["--kind", "template_csv", "--out", str(tmp_path / "upload")]) == 0
    return tmp_path / "upload" / "snapshot.csv"


def test_make_tenant_yn_creates_only_one_file(empty_root, tmp_path):
    csv = _csv(tmp_path)
    assert make_tenant.main(["--new", "yn", "--pack", "_template", "--csv", str(csv)]) == 0
    assert sorted(p.name for p in empty_root.iterdir()) == ["yn.yaml"]
    m = tenants.load_and_merge("yn")
    assert list(m.tasks) == ["yn.target_value", "yn.target_risk"] and m.tenant.config["mode"] == "eval"
    assert m.tenant.config["sources"]["eval"]["path"] == str(csv.resolve())
    assert make_tenant.main(["--new", "yn"]) == 2                                 # 덮어쓰지 않는다
    assert not (ROOT / "tenants" / "yn.yaml").exists() and not (ROOT / "tests" / "fixtures" / "yn").exists()


def test_make_tenant_rejects_bad_input(empty_root):
    assert make_tenant.main(["--new", "Bad-Code"]) == 2
    assert make_tenant.main(["--new", "pz", "--pack", "press"]) == 2               # 설비 · 품목 범주 값 없음 → R2 거부
    assert list(empty_root.iterdir()) == []                                       # 거부되면 파일을 남기지 않는다


def test_new_tenant_end_to_end(empty_root, tmp_path):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    from mlcore.db import seed_std
    from mlcore.monitor import doctor
    from mlcore.serve import training

    code = "yn" + secrets.token_hex(2)
    csv = _csv(tmp_path)
    # 1) make tenant — 빈 등록부에서
    assert make_tenant.main(["--new", code, "--pack", "_template", "--csv", str(csv)]) == 0
    # 2) db-seed (등록부 루트의 회사만)
    out = seed_std.seed()
    assert out["tenants"] == 1 and out["tasks"] == 2
    # 3) doctor — CSV 소스 연결 · 600행 · 대응률 100% · 목표 있음
    rep = {s["role"]: s for s in doctor.doctor(code)["sources"]}
    assert rep["eval"]["status"] == "연결" and rep["eval"]["rows"] == 600 and rep["eval"]["coverage"] == 1.0
    assert rep["eval"]["target"] == "있음"
    assert rep["train"]["status"] == "미연결"                                       # 미확인 소스는 미연결 그대로

    m = tenants.load_and_merge(code)
    k = h.keys(m)
    tc = h.client(code)
    try:
        for short in ("target_value", "target_risk"):
            task = f"{code}.{short}"
            base = f"/api/v1/tenants/{code}/tasks/{task}"
            # 4) train (CSV = eval 소스) → 작업자 → candidate
            r = tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={"source_role": "eval"})
            assert r.status_code == 202, r.text
            result, ref = training.run_and_register(r.json()["run_id"])
            assert result.status == "succeeded" and ref.stage == "candidate" and ref.synthetic is False
            assert ref.beats_baseline is True, result.report.get("beats_baseline_rule")
            # 5) 승인: stage(admin) → promote(approver, 요청만) → decide(approver)
            assert tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["admin"])).status_code == 200
            r = tc.post(f"{base}/models/{ref.version}/promote", headers=h.hdr(k["approver"]), json={"reason": "새 회사"})
            assert r.status_code == 202
            assert h.production_version(code, task) is None                         # 승인 전 운영 모델 없음
            r = tc.post(f"/api/v1/approvals/{r.json()['approval_id']}/decide", headers=h.hdr(k["approver"]),
                        json={"decision": "approve", "reason": "새 회사 연습"})
            assert r.status_code == 200 and r.json()["production_version"] == ref.version
            # 6) predict — 표준 18키
            lock = json.loads((Path(result.artifact_dir) if Path(result.artifact_dir).is_absolute()
                               else ROOT / result.artifact_dir).joinpath("features.lock.json").read_text(encoding="utf-8"))
            inputs = {n: f["fill"] for n, f in lock["features"].items()}
            r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": inputs, "entity_id": "YN-1"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert set(body) == KEYS_18 and body["task"] == task and body["tenant"] == code
            assert body["synthetic"] is False and body["prediction"]["value"] is not None
    finally:
        tc.__exit__(None, None, None)
    # 생성 파일은 등록부 루트의 <code>.yaml 하나 — 저장소에는 아무것도 생기지 않는다
    assert sorted(p.name for p in empty_root.iterdir()) == [f"{code}.yaml"]
    assert not list((ROOT / "tenants").glob(f"{code}*"))
    for d in ("var/snapshots", "var/artifacts", "tests/fixtures"):
        assert not (ROOT / d / code).exists(), d
    assert (tmp_path / "var" / "snapshots" / code).is_dir() and (tmp_path / "var" / "artifacts" / code).is_dir()
