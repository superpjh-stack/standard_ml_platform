"""G2-I02 — `make export-hub` 출력 `mlp-hub-export/1` (contracts/hub-export.md §4). 소유 개발3.

1. 계약 `hub-export-schema` 블록(Draft 2020-12)으로 출력 검증.
2. 허브 저장소 파일을 **읽어** 대조: `../Standard Data Hub/src/datahub/db/schema.sql` 의 hub_consumer.kind · hub_dataset.layer ·
   hub_usage_daily.basis CHECK 값 ⊇ 우리 enum. 허브 저장소가 없으면 FAIL(건너뜀 0 — 가짜 PASS 금지).
3. 허브 검증 함수 **읽기 전용 import**: `datahub.core.registry.validate`(DB 연결 없음)로 우리 회사들의 허브 등록부가 통과하고
   `kind: ML` 시스템이 있는지 · 우리 `hub_company` 와 코드가 같은지. bytecode 를 쓰지 않는다 — 허브 폴더 mtime · 파일 목록 불변.
4. 출력에 비밀값(check_secrets 패턴) · 실데이터 행 · 입력값 · 예측값 0, 등록부 회사 전부 있음, 같은 DB · 날짜 → 같은 바이트.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

import _dev3 as h

pytestmark = [pytest.mark.gate("G2-I02")]

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT.parent / "Standard Data Hub"
KST = timezone(timedelta(hours=9))
DAY = date(2026, 10, 2)


def schema() -> dict:
    text = (ROOT / "contracts" / "hub-export.md").read_text(encoding="utf-8")
    m = re.search(r"```json hub-export-schema\n(.*?)```", text, re.S)
    assert m, "contracts/hub-export.md 에 hub-export-schema 블록이 없다"
    return json.loads(m.group(1))


def hub_required() -> Path:
    if not (HUB / "src" / "datahub").is_dir():
        pytest.fail(f"허브 저장소 없음({HUB.name}) — 형식 대조를 할 수 없다(건너뛰지 않는다)")
    return HUB


def snapshot_tree(base: Path) -> dict[str, float]:
    out = {}
    for sub in ("src", "companies"):
        for p in sorted((base / sub).rglob("*")):
            out[str(p.relative_to(base))] = p.stat().st_mtime_ns if p.is_file() else -1
    return out


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    from mlcore.monitor import hub_export

    out = tmp_path_factory.mktemp("hub")
    path = hub_export.write(DAY, out_dir=out)
    return {"path": path, "doc": json.loads(path.read_text(encoding="utf-8")), "text": path.read_text(encoding="utf-8")}


def test_output_matches_contract_schema(doc):
    v = Draft202012Validator(schema(), format_checker=FormatChecker())
    errs = sorted(v.iter_errors(doc["doc"]), key=lambda e: list(e.path))
    assert not errs, [f"{list(e.path)}: {e.message}" for e in errs[:5]]
    d = doc["doc"]
    assert d["format"] == "mlp-hub-export/1" and d["date"] == DAY.isoformat() and d["system"]["kind"] == "ML"
    assert doc["path"].name == f"{DAY.isoformat()}.json"


def test_all_registry_companies_present(doc):
    from mlcore.registry import tenants

    want = {(tenants.load_tenant(c).config.get("hub_company") or c) for c in tenants.all_codes()}
    got = [c["company"] for c in doc["doc"]["companies"]]
    assert sorted(got) == sorted(want) and len(got) == len(set(got))
    assert "_template" not in got and "tpl" not in got


def test_consumers_cover_enabled_tasks_screens_tools(doc):
    from mlcore.registry import tenants

    for c in doc["doc"]["companies"]:
        m = tenants.load_and_merge(c["company"])
        models = {x["code"] for x in c["consumers"] if x["kind"] == "MODEL"}
        assert models == {f"ML:{t}" for t in m.tasks}
        screens = {x["code"] for x in c["consumers"] if x["kind"] == "SCREEN"}
        assert {"ML-S1", "ML-S5", "ML-S7", "ML-S10"} <= screens
        types = {td.type for td in m.tasks.values()}
        assert ("ML-S8" in screens) == ("review_queue" in types) and ("ML-S9" in screens) == bool(types & {"extract", "quote"})
        tools = {x["code"] for x in c["consumers"] if x["kind"] == "TOOL"}
        assert "tool:ml.get_monitor_summary" in tools and all(t.startswith("tool:ml.") for t in tools)
        for x in c["consumers"]:
            ref, _, line = x["source_ref"].rpartition(":")
            assert (ROOT / ref).is_file() and int(line) >= 1, x["source_ref"]       # 근거 파일:줄 이 실재
        for x in (x for x in c["consumers"] if x["kind"] == "MODEL"):
            assert x["synthetic"] is True or c["mode"] == "live"                   # demo 회사는 합성


def test_features_use_pack_std_names_and_source_columns(doc):
    from mlcore.registry import tenants

    ks = next(c for c in doc["doc"]["companies"] if c["company"] == "ks")
    m = tenants.load_and_merge("ks")
    fmap = m.tenant.config["feature_map"]
    row = next(f for f in ks["features"] if f["task"] == "ks.remaining_hours" and f["std_name"] == "press.press_force")
    assert row["role"] == "feature" and row["mapped"] and fmap[row["source_column"]] == "press_force"
    unmapped = next(f for f in ks["features"] if f["std_name"] == "press.motor_current" and f["task"] == "ks.remaining_hours")
    assert unmapped["source_column"] is None and unmapped["mapped"] is False      # 대응 없으면 null(지어내지 않음)
    tgt = [f for f in ks["features"] if f["role"] == "target" and f["task"] == "ks.remaining_hours"]
    assert [t["std_name"] for t in tgt] == ["press.remaining_hours"]
    # 데이터셋 = 등록부 원천 테이블(합성 · CSV 제외) · 사용 = 그 테이블을 읽는 과제
    names = {d["physical_name"] for d in ks["datasets"]}
    assert {"PRS_PROCESS_DATA", "PRS_MOLD_SHOTS", "BAS_EQUIPMENTS", "EIF_PLC_RAW"} <= names
    assert all(d["layer"] == "L5" for d in ks["datasets"])
    used = {(u["consumer_code"], u["physical_name"]) for u in ks["usages"]}
    assert ("ML:ks.remaining_hours", "PRS_PROCESS_DATA") in used
    kd = next(c for c in doc["doc"]["companies"] if c["company"] == "kd")
    assert kd["datasets"] == [] and all(u["physical_name"] is None and u["declared_in"] == "packs" for u in kd["usages"])


def test_api_usage_counts_predictions_and_marks_unrecorded(tmp_path, monkeypatch):
    """그날 기록이 없으면 basis 미확인 · 숫자 null(0 아님). 기록이 있으면 mlp_prediction 수 · 감사 4xx/5xx 수."""
    if not h.db_ok():
        pytest.skip("ml_test_db 없음")
    from mlcore.db.conn import connect
    from mlcore.monitor import hub_export
    from mlcore.registry import tenants

    monkeypatch.setenv("MLP_TENANTS_DIR", str(tmp_path))
    code = h.copy_tenant("sw", tmp_path)
    m = h.register_db(code)
    empty = hub_export.build(DAY, codes=[code])["companies"][0]["api_usage"][DAY.isoformat()]
    assert empty and all(v == {"calls": None, "errors": None, "p95_ms": None, "ref": f"mlp_prediction@{DAY}", "basis": "미확인"}
                         for v in empty.values())
    version = h.train_to_production(code, f"{code}.delta_e")
    ts = datetime(2026, 10, 2, 10, tzinfo=KST)
    sql = ("INSERT INTO mlp_prediction (prediction_id, tenant_id, task_id, version, inputs, outputs, status, caller, channel, ts, "
           "synthetic) VALUES (%s,%s,%s,%s,'{}','{}','ok','test',%s,%s,true)")
    from mlcore.serve.ids import new_id
    with connect() as c:
        for ch in ["api", "api", "batch"]:
            c.execute(sql, (new_id("prd"), code, f"{code}.delta_e", version, ch, ts))
        c.execute(sql, (new_id("prd"), code, f"{code}.delta_e", version, "api", ts + timedelta(days=1)))   # 다음 날 — 세지 않는다
        c.execute("INSERT INTO mlp_audit (tenant_id, ts, actor, action, target, detail) VALUES (%s,%s,'t','POST x',%s,%s::jsonb)",
                  (code, ts, f"/api/v1/tenants/{code}/tasks/delta_e/predict", json.dumps({"status": 422})))
    got = hub_export.build(DAY, codes=[code])["companies"][0]["api_usage"][DAY.isoformat()]
    p = got[f"/api/v1/tenants/{code}/tasks/delta_e/predict"]
    assert (p["calls"], p["errors"], p["p95_ms"], p["basis"]) == (3, 1, None, "실측") and "api 2 · batch 1" in p["ref"]
    other = got[f"/api/v1/tenants/{code}/tasks/defect_risk/predict"]
    assert (other["calls"], other["errors"], other["basis"]) == (0, 0, "실측")     # 그날 기록이 있는 회사의 0 은 실측 0
    assert set(got) == {hub_export.api_path(code, td) for td in m.tasks.values()}


def test_no_secrets_real_rows_inputs_or_predictions(doc):
    sys.path.insert(0, str(ROOT / "gates"))
    import check_secrets                                                           # noqa: E402

    text = doc["text"]
    hits = [k for k, rx in check_secrets.KEY_RE.items() if rx.search(text)]
    hits += [m.group(0) for m in check_secrets.IPV4.finditer(text)]
    hits += [m.group(0) for m in check_secrets.URL.finditer(text)] + [m.group(0) for m in check_secrets.HOSTLIKE.finditer(text)]
    assert not hits, hits
    for bad in ("_env", "MLP_", "dsn", "://", "inputs", "outputs", "prediction_id", "/Users/", "tests/fixtures"):
        assert bad not in text, bad
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)                      # IP 0
    for c in doc["doc"]["companies"]:
        for f in c["features"]:
            assert set(f) == {"task", "std_name", "role", "source_column", "mapped"}   # 값 칸 없음


def test_deterministic_bytes(doc, tmp_path):
    from mlcore.monitor import hub_export

    again = hub_export.write(DAY, out_dir=tmp_path)
    assert again.read_bytes() == doc["path"].read_bytes()
    assert doc["doc"]["generated_at"] == "2026-10-03T00:00:00+09:00"            # 집계 창 끝(KST) — D2-32


def test_hub_schema_check_values_are_superset():
    base = hub_required()
    sql = (base / "src" / "datahub" / "db" / "schema.sql").read_text(encoding="utf-8")

    def check_values(table: str, col: str) -> set[str]:
        m = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.S)
        assert m, table
        c = re.search(rf"\b{col}\b[^\n]*CHECK \({col} IN \(([^)]*)\)\)", m.group(1))
        assert c, (table, col)
        return set(re.findall(r"'([^']+)'", c.group(1)))

    s = schema()["properties"]["companies"]["items"]["properties"]
    ours_kind = set(s["consumers"]["items"]["properties"]["kind"]["enum"])
    ours_layer = set(s["datasets"]["items"]["properties"]["layer"]["enum"])
    ours_basis = set(s["api_usage"]["additionalProperties"]["additionalProperties"]["properties"]["basis"]["enum"])
    assert ours_kind <= check_values("hub_consumer", "kind")
    assert ours_layer <= check_values("hub_dataset", "layer")
    assert ours_basis <= check_values("hub_usage_daily", "basis")


def test_hub_registry_validate_readonly_import():
    """허브 `datahub.core.registry.validate` 를 읽기 전용으로 import — 별도 프로세스(바이트코드 쓰기 0 · 우리 sys.path 오염 0)."""
    base = hub_required()
    from mlcore.registry import tenants

    codes = {c: (tenants.load_tenant(c).config.get("hub_company") or c) for c in tenants.all_codes()}
    before = snapshot_tree(base)
    script = (
        "import json, sys, yaml\n"
        "from pathlib import Path\n"
        "from datahub.core import registry\n"
        "base = Path(sys.argv[1]); out = {}\n"
        "for code in json.loads(sys.argv[2]):\n"
        "    f = base / 'companies' / f'{code}.yaml'\n"
        "    data = yaml.safe_load(f.read_text(encoding='utf-8'))\n"
        "    registry.validate(data, f)\n"
        "    out[code] = sorted(s.get('name', '') for s in data.get('systems') or [] if s.get('kind') == 'ML')\n"
        "print(json.dumps(out, ensure_ascii=False))\n")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(base / "src")}
    env.pop("MLP_DB_DSN", None)
    r = subprocess.run([sys.executable, "-B", "-c", script, str(base), json.dumps(sorted(set(codes.values())))],
                       capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert set(got) == set(codes.values())
    assert all(got[c] for c in got), got                                          # 회사마다 kind: ML 시스템이 있다
    for ours, hub in codes.items():
        assert ours == hub                                                         # 우리 코드 = 허브 회사 코드
    assert snapshot_tree(base) == before                                          # 허브 폴더 쓰기 0


def test_hub_has_all_six_companies_we_will_export():
    """2차 끝 6개사(goal2 §1) — 허브 등록부에는 이미 6개 모두 있다(우리 쪽 krs · ot 등록부는 웨이브 A2)."""
    base = hub_required()
    for code in ("ks", "sw", "krs", "pc", "ot", "kd"):
        data = yaml.safe_load((base / "companies" / f"{code}.yaml").read_text(encoding="utf-8"))
        assert data["code"] == code and any(s.get("kind") == "ML" for s in data.get("systems") or [])


def test_make_export_hub_target_runs(tmp_path):
    """make export-hub 대상이 같은 함수를 부른다(미구현 문구 0)."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    block = re.search(r"^export-hub:.*\n((?:\t.*\n)+)", mk, re.M)
    assert block and "미구현" not in block.group(1) and "mlcore.monitor.hub_export" in block.group(1)


SIX = ("ks", "sw", "krs", "pc", "ot", "kd")


def test_six_companies_exported_with_tasks_features_and_usage(doc):
    """2차 끝 6개사(goal2 §1 · G2-I02) — 회사 6 전부 · 켜진 과제마다 MODEL 소비자 · 학습 과제 변수 · 일 호출 수 행.
    등록부 · 허브 회사 코드가 같고(hub_company), 합성 소스 회사(krs · pc · ot · kd)는 원천 테이블 · 열 대응이 없다(지어내지 않음)."""
    from mlcore.registry import tenants

    by = {c["company"]: c for c in doc["doc"]["companies"]}
    assert set(SIX) <= set(by), sorted(by)
    hub = {code: yaml.safe_load((hub_required() / "companies" / f"{code}.yaml").read_text(encoding="utf-8")) for code in SIX}
    for code in SIX:
        c, m = by[code], tenants.load_and_merge(code)
        assert hub[code]["code"] == (m.tenant.config.get("hub_company") or code) == code
        assert {x["code"] for x in c["consumers"] if x["kind"] == "MODEL"} == {f"ML:{t}" for t in m.tasks}
        learned = [td for td in m.tasks.values() if td.type in ("regression", "risk", "anomaly")]
        for td in learned:                                              # 학습 과제의 변수 · 목표가 std_name 으로 다 나간다
            got = {f["std_name"] for f in c["features"] if f["task"] == td.id}
            tgt = (td.raw.get("target") or {}).get("name")
            std = lambda n: str((m.pack.std_name or {}).get(n) or f"{m.pack.code}.{n}")   # noqa: E731 — 팩 std_name 우선
            want = {std(n) for n in td.raw["features"]} | ({std(tgt)} if tgt else set())
            assert want <= got, (td.id, sorted(want - got))
        assert {u["consumer_code"] for u in c["usages"]} == {f"ML:{t}" for t in m.tasks}
        assert DAY.isoformat() in c["api_usage"] and c["api_usage"][DAY.isoformat()]   # 일 호출 수 칸(기록 없으면 미확인 · null)
        if code in ("krs", "pc", "ot", "kd"):
            assert c["datasets"] == [] and all(not f["mapped"] and f["source_column"] is None for f in c["features"])
    ot = by["ot"]
    assert any(f["std_name"] == "rollform-quote.machining_minutes" and f["role"] == "target" for f in ot["features"])
    assert {x["code"] for x in ot["consumers"] if x["kind"] == "SCREEN"} >= {"ML-S9"}             # 도면 · 견적 화면
    assert {x["code"] for x in by["krs"]["consumers"] if x["kind"] == "SCREEN"} >= {"ML-S8"}      # 검토 대기열 화면
