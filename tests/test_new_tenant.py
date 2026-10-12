"""G-M10 — 새 회사: 빈 등록부 → `make tenant NEW=yn PACK=_template` + CSV(tmp) → doctor → train → 승인 → predict.
2차(D2-100 · #28): 6개 팩 모두 빈 등록부 → `make tenant CATEGORIES=<채움 파일>` → seed → doctor → train → 승인 → predict.
범주 값이 모자라면 거부하되 `<code>.yaml.draft` 초안을 남기고 채울 칸을 알린다.

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
    assert list(empty_root.iterdir()) == []                                       # 코드가 틀리면 아무것도 만들지 않는다


# ── 2차: 6개 팩 (D2-100 · #28) — 채움 파일 값은 저장소 회사 등록부에서 읽는다(사람이 적은 값 흉내, 원천 아님) ─────────

PACK_SRC = {"press": "ks", "textile": "sw", "solder": "krs", "kimchi": "pc", "rollform-quote": "ot", "eto": "kd"}
PACK_TRAIN = {"press": "remaining_hours", "textile": "delta_e", "solder": "joint_strength", "kimchi": "sensory_score",
              "rollform-quote": "machining_minutes", "eto": "labor_hours"}


def _fill(tmp_path, pack: str, *, rates: bool = True) -> Path:
    """그 팩을 쓰는 저장소 회사의 categories · material_aliases · 과제 덮어쓰기를 채움 파일 하나로."""
    import yaml
    src = PACK_SRC[pack]
    cfg = yaml.safe_load((ROOT / "tenants" / f"{src}.yaml").read_text(encoding="utf-8"))
    fill = {"categories": cfg.get("categories") or {}}
    if cfg.get("material_aliases"):
        fill["material_aliases"] = cfg["material_aliases"]
    od = ROOT / "tenants" / src / "tasks"
    if rates and od.is_dir():
        fill["tasks"] = {f.stem: yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(od.glob("*.yaml"))}
    out = tmp_path / f"fill-{pack}.yaml"
    out.write_text(yaml.safe_dump(fill, allow_unicode=True), encoding="utf-8")
    return out


@pytest.mark.parametrize("pack", [p for p in PACK_SRC if p != "textile"])
def test_make_tenant_missing_categories_keeps_draft(empty_root, pack, capsys):
    """범주 값 없이 → 거부(2) · `<code>.yaml` 없음 · 초안 `<code>.yaml.draft` 남김 · 채울 칸 안내 (1차는 초안까지 지웠다)."""
    assert make_tenant.main(["--new", "pz", "--pack", pack]) == 2
    err = capsys.readouterr().err
    assert sorted(p.name for p in empty_root.iterdir()) == ["pz.yaml.draft"]
    assert "채울 칸: categories." in err and "CATEGORIES=" in err and "pz.yaml.draft" in err
    assert tenants.all_codes() == []                                              # 초안은 회사 목록 · 시드에 잡히지 않는다
    draft = (empty_root / "pz.yaml.draft").read_text(encoding="utf-8")
    assert "# 미확인 — 회사 값 목록" in draft and f"pack: {pack}" in draft


def test_make_tenant_rates_missing_keeps_draft(empty_root, tmp_path, capsys):
    """단가표 회사 칸(rollform-quote rates.density)이 없으면 범주가 있어도 R2 — 초안을 남기고 덮어쓰기 폴더는 남기지 않는다."""
    fill = _fill(tmp_path, "rollform-quote", rates=False)
    assert make_tenant.main(["--new", "pz", "--pack", "rollform-quote", "--categories", str(fill)]) == 2
    assert "R2" in capsys.readouterr().err
    assert sorted(p.name for p in empty_root.iterdir()) == ["pz.yaml.draft"]
    # 채움 파일을 고쳐 다시 실행하면 통과하고 초안은 지운다
    fill = _fill(tmp_path, "rollform-quote")
    assert make_tenant.main(["--new", "pz", "--pack", "rollform-quote", "--categories", str(fill)]) == 0
    assert sorted(str(p.relative_to(empty_root)) for p in empty_root.rglob("*") if p.is_file()) == \
        ["pz.yaml", "pz/tasks/quote.yaml"]


def test_make_tenant_rejects_unknown_category(empty_root, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("categories: {no_such_var: [a]}\n", encoding="utf-8")
    assert make_tenant.main(["--new", "pz", "--pack", "press", "--categories", str(bad)]) == 2
    bad.write_text("rates: {}\n", encoding="utf-8")                                 # 받지 않는 최상위 키
    assert make_tenant.main(["--new", "pz", "--pack", "press", "--categories", str(bad)]) == 2
    assert list(empty_root.iterdir()) == []


@pytest.mark.parametrize("pack", list(PACK_SRC))
def test_new_tenant_each_pack_end_to_end(empty_root, tmp_path, pack):
    """빈 등록부 → make tenant(채움 파일) → seed → doctor → train(demo) → stage → 승인 → predict 18키."""
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    from mlcore.db import seed_std
    from mlcore.monitor import doctor
    from mlcore.serve import training

    code = "yp" + secrets.token_hex(2)
    args = ["--new", code, "--pack", pack]
    import yaml
    fill = _fill(tmp_path, pack)
    if (yaml.safe_load(fill.read_text(encoding="utf-8")) or {}).get("categories"):
        args += ["--categories", str(fill)]
    assert make_tenant.main(args) == 0
    assert not list(empty_root.glob("*.draft"))
    out = seed_std.seed()
    m = tenants.load_and_merge(code)
    assert out["tenants"] == 1 and out["tasks"] == len(m.tasks)
    rep = {s["role"]: s for s in doctor.doctor(code)["sources"]}
    assert rep["demo"]["status"] == "연결", rep["demo"]

    task = f"{code}.{PACK_TRAIN[pack]}"
    k = h.keys(m)
    tc = h.client(code)
    try:
        base = f"/api/v1/tenants/{code}/tasks/{task}"
        r = tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={"source_role": "demo"})
        assert r.status_code == 202, r.text
        result, ref = training.run_and_register(r.json()["run_id"])
        assert result.status == "succeeded" and ref.stage == "candidate", result.report
        assert tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["admin"])).status_code == 200
        r = tc.post(f"{base}/models/{ref.version}/promote", headers=h.hdr(k["approver"]), json={"reason": "새 회사"})
        assert r.status_code == 202, r.text
        r = tc.post(f"/api/v1/approvals/{r.json()['approval_id']}/decide", headers=h.hdr(k["approver"]),
                    json={"decision": "approve", "reason": "새 회사 연습"})
        assert r.status_code == 200 and r.json()["production_version"] == ref.version, r.text
        lock = json.loads((Path(result.artifact_dir) if Path(result.artifact_dir).is_absolute()
                           else ROOT / result.artifact_dir).joinpath("features.lock.json").read_text(encoding="utf-8"))
        inputs = {n: (round(f["fill"]) if f["dtype"] in ("int", "integer") else f["fill"])
                  for n, f in lock["features"].items()}
        r = tc.post(f"{base}/predict", headers=h.hdr(k["operator"]), json={"inputs": inputs, "entity_id": "YP-1"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == KEYS_18 and body["task"] == task and body["prediction"]["value"] is not None
    finally:
        tc.__exit__(None, None, None)
    assert not list((ROOT / "tenants").glob(f"{code}*"))


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
