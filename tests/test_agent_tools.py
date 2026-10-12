"""G2-I01 — Agent `ml.*` 도구 4 (contracts/agent-tools.md · D2-08 · D2-16). 소유 개발2.

1. 계약 `agent-tool-args` 블록의 4 스키마가 유효하고 어댑터 pydantic 모델이 같은 스키마(필수 · 속성 · extra 금지)를 낸다.
2. 이름이 Agent 규칙 정규식에 맞고, 별칭 4 → 이름 4, ToolMeta 넷 다 readonly.
3. FastAPI TestClient 를 transport 로 꽂아 4 도구를 실제 API 로 호출 → 결과 봉투 · cite 불변식(registry.py:62-76 재구현) ·
   production 없음 → disconnected(model_not_ready) · 다른 회사 과제 → denied · 모르는 인자 키 → error · 합성 → demo_data.
4. 쓰기 0 — 4 도구 호출 전후 mlp_approval · mlp_model_version(stage) · mlp_train_run · mlp_actual · mlp_review_item · mlp_quote 가 같다.
덧붙여 optimize `request_approval: false`(승인 요청 0) · 2차 유형/비최적화 과제 `/optimize` 404 type_route · trace `?view=explain` 역할.
"""

from __future__ import annotations

import json
import re

import jsonschema
import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.integrations import agent_tools as at

pytestmark = [pytest.mark.gate("G2-I01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

BLOCK = re.compile(r"```json agent-tool-args\n(.*?)```", re.S)


def contract_args() -> dict:
    return json.loads(BLOCK.search((h.ROOT / "contracts" / "agent-tools.md").read_text(encoding="utf-8")).group(1))


# ── 1 · 2 정적 ────────────────────────────────────────────────────────────────────────────────
def test_contract_schemas_valid_and_match_adapter():
    want = contract_args()
    assert set(want) == set(at.TOOLS) == set(at.NAMES)
    for name, schema in want.items():
        jsonschema.Draft202012Validator.check_schema(schema)
        got = at.TOOLS[name].schema()
        assert "title" not in got
        assert set(got.get("required", [])) == set(schema["required"]), name
        assert set(got["properties"]) == set(schema["properties"]), name
        assert got.get("additionalProperties") is False and schema["additionalProperties"] is False


def test_names_aliases_meta():
    assert at.ALIASES == {"ml.predict": "ml.calculate_prediction", "ml.explain": "ml.get_explanation",
                          "ml.recommend": "ml.calculate_recommendation", "ml.monitor_summary": "ml.get_monitor_summary"}
    for alias, name in at.ALIASES.items():
        assert at.NAME_RE.match(name) and not at.NAME_RE.match(alias)
        assert at.resolve(alias) == name == at.resolve(name.replace(".", "__"))
        assert at.TOOLS[name].alias == alias
        meta = at.TOOLS[name].meta
        assert meta.readonly is True and meta.sources == ["ml"] and meta.pii is False and meta.label
    assert at.TOOLS["ml.calculate_recommendation"].meta.roles == ["admin", "manager"]


def test_envelope_invariants():
    with pytest.raises(ValueError):
        at.ToolResult("ok", "ml")                                    # ok 인데 cite 0
    with pytest.raises(ValueError):
        at.ToolResult("empty", "ml", cite=[at.Cite("row", "x", {"a": "b"}, {})])
    with pytest.raises(ValueError):
        at.ToolResult("disconnected", "ml", complete=False,
                      cite=[at.Cite("query", "q", {"a": "b"}, {"connector": "ml", "complete": False})])
    d = at.disconnected("ml.get_monitor_summary", "model_not_ready")
    assert d.status == "disconnected" and d.cite[0].snapshot == {"connector": "ml", "query": "ml.get_monitor_summary",
                                                                "complete": False, "error_code": "model_not_ready"}


# ── 3 · 4 API 경유 ───────────────────────────────────────────────────────────────────────────
def _transport(tc, key):
    def send(method, path, body):
        r = tc.request(method, path, headers=h.hdr(key), json=body)
        return r.status_code, (r.json() if r.content else {})
    return send


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    m = h.make_tenant("ks", tmp_path_factory.mktemp("agent"))
    opt = next(t for t, td in m.tasks.items() if td.type == "optimize")
    refs = {}
    for pack_id in m.tasks[opt].raw["uses"]:
        tid = next(t for t, d in m.tasks.items() if d.pack_id == pack_id)
        refs[tid], _ = h.real_production(m, tid)
    reg = next(t for t in refs if m.tasks[t].type == "regression")
    k = h.keys(m)
    tc = h.client(m)
    return m, opt, reg, refs, k, tc


def _writes(code: str) -> tuple:
    with connect() as c:
        n = lambda sql: c.execute(sql, (code,)).fetchone()["n"]  # noqa: E731
        return (n("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id=%s"),
                tuple(r["stage"] for r in c.execute("SELECT stage FROM mlp_model_version WHERE tenant_id=%s ORDER BY task_id, version",
                                                    (code,)).fetchall()),
                n("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id=%s"),
                n("SELECT count(*) AS n FROM mlp_actual WHERE tenant_id=%s"),
                n("SELECT count(*) AS n FROM mlp_review_item WHERE tenant_id=%s"),
                n("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id=%s"))


def test_four_tools_ok_and_write_nothing(world):
    m, opt, reg, refs, k, tc = world
    code = m.tenant.code
    tp = _transport(tc, k["operator"])
    before = _writes(code)
    lock = h.lock_of(refs[reg])
    inputs = h.mid_inputs(lock, lock["order"])

    p = at.call("ml.predict", {"task": reg, "inputs": inputs, "explain": True}, tenant=code, transport=tp)
    assert p.status == "ok", p.summary
    row = p.rows[0]
    assert set(row) == {"prediction_id", "task", "type", "value", "unit", "interval", "probability", "grade",
                        "anomaly_flag", "status", "warnings", "model_version", "synthetic"}
    assert row["prediction_id"].startswith("prd_") and row["model_version"] == refs[reg].version
    assert p.cite[0].kind == "row" and p.cite[0].ref == f"ml:mlp_prediction/{row['prediction_id']}"
    assert p.cite[0].subject == {"task": reg, "entity": "-"}
    assert p.demo_data is True and row["synthetic"] is True                       # 합성 스냅숏 모델 — 숨기지 않는다
    assert all(str(v) not in p.summary for v in inputs.values() if isinstance(v, (int, float)) and abs(v) > 9)

    e = at.call("ml.explain", {"prediction_id": row["prediction_id"]}, tenant=code, transport=tp)
    assert e.status == "ok", e.summary
    er = e.rows[0]
    assert er["prediction_id"] == row["prediction_id"] and er["model_version"] == refs[reg].version
    assert er["snapshot_id"] == refs[reg].snapshot_id and er["contributors"] and "sources" not in er
    assert e.cite[0].ref == f"ml:mlp_prediction/{row['prediction_id']}" and e.cite[0].subject["model"] == refs[reg].version

    fixed = h.mid_inputs(lock, [n for n in m.tasks[opt].raw["fixed"] if n in lock["features"]])
    r = at.call("ml.recommend", {"task": opt, "fixed": fixed}, tenant=code, transport=tp)
    assert r.status == "ok", r.summary
    assert 1 <= len(r.rows) <= 5 and r.rows[0]["rank"] == 1
    assert set(r.rows[0]) == {"rank", "conditions", "predictions", "constraints_met", "violation", "in_train_range"}
    assert r.cite[0].ref.startswith("ml:mlp_recommendation/rec_") and "rec_id=rec_" in r.summary
    assert {c.ref for c in r.cite[1:]} == {f"ml:mlp_model_version/{t}@{ref.version}" for t, ref in refs.items()}

    s = at.call("ml.monitor_summary", {}, tenant=code, transport=tp)
    assert s.status == "ok", s.summary
    assert {x["task"] for x in s.rows} == set(m.tasks)
    assert set(s.rows[0]) == {"task", "type", "production_version", "synthetic", "predictions_yesterday",
                              "monitor_level", "alerts", "pending_approvals"}
    assert all(c.ref.startswith("ml:mlp_monitor_daily/") and c.subject["range"] for c in s.cite)
    one = at.call("ml.get_monitor_summary", {"task": reg, "days": 3}, tenant=code, transport=tp)
    assert one.status == "ok" and [x["task"] for x in one.rows] == [reg]

    for res in (p, e, r, s):
        assert len(res.summary) <= 200 and res.source == "ml"
    assert _writes(code) == before                                                 # 쓰기 0 (§4)
    with connect() as c:                                                             # 추천은 기록만, 승인 요청 0
        rec_id = r.cite[0].ref.split("/")[-1]
        assert c.execute("SELECT count(*) AS n FROM mlp_recommendation WHERE rec_id=%s", (rec_id,)).fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM mlp_approval WHERE ref_id=%s", (rec_id,)).fetchone()["n"] == 0


def test_disconnected_denied_error(world, tmp_path):
    m, opt, reg, refs, k, tc = world
    code = m.tenant.code
    tp = _transport(tc, k["operator"])
    # production 없음 → disconnected(model_not_ready) — 대체 예측 0
    fresh = h.make_tenant("ks", tmp_path)
    kf = h.keys(fresh)
    tcf = h.client(fresh)
    ftask = f"{fresh.tenant.code}.{reg.split('.', 1)[1]}"
    lock = h.lock_of(refs[reg])
    try:
        d = at.call("ml.predict", {"task": ftask, "inputs": h.mid_inputs(lock, lock["order"])}, tenant=fresh.tenant.code,
                    transport=_transport(tcf, kf["operator"]))
    finally:
        h.client(m)                                                                   # 앱 등록부를 원래 회사로
    assert d.status == "disconnected" and not d.rows and d.complete is False, d.summary
    assert d.cite[0].snapshot == {"connector": "ml", "query": "ml.calculate_prediction", "complete": False,
                                  "error_code": "model_not_ready"}
    # 다른 회사 과제 → denied
    other = ftask
    assert at.call("ml.predict", {"task": other, "inputs": {}}, tenant=code, transport=tp).status == "denied"
    assert at.call("ml.recommend", {"task": other, "fixed": {}}, tenant=code, transport=tp).status == "denied"
    # 모르는 인자 키 → error (입력값을 되풀이하지 않는다)
    bad = at.call("ml.predict", {"task": reg, "inputs": {}, "secret": "CANARY-991"}, tenant=code, transport=tp)
    assert bad.status == "error" and "CANARY" not in bad.summary
    # 모르는 변수 → API 422 → error
    e = at.call("ml.predict", {"task": reg, "inputs": {"nope_var": 1}}, tenant=code, transport=tp)
    assert e.status == "error" and e.summary.startswith("인자 오류")
    # 없는 예측 ID → error, 키 틀림 → denied
    assert at.call("ml.explain", {"prediction_id": "prd_" + "0" * 26}, tenant=code, transport=tp).status == "error"
    assert at.call("ml.monitor_summary", {}, tenant=code, transport=_transport(tc, "mlp_wrong")).status == "denied"
    # 연결 실패 → disconnected unreachable
    def down(method, path, body):
        raise ConnectionRefusedError()
    u = at.call("ml.monitor_summary", {}, tenant=code, transport=down)
    assert u.status == "disconnected" and u.cite[0].snapshot["error_code"] == "unreachable"
    assert at.call("ml.nope", {}, tenant=code, transport=tp).status == "error"


# ── 덧붙임: optimize request_approval · type_route · trace view=explain ───────────────────────
def test_optimize_request_approval_flag_and_type_route(world):
    m, opt, reg, refs, k, tc = world
    base = f"/api/v1/tenants/{m.tenant.code}/tasks"
    lock = h.lock_of(refs[reg])
    fixed = h.mid_inputs(lock, [n for n in m.tasks[opt].raw["fixed"] if n in lock["features"]])
    with connect() as c:
        n0 = c.execute("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id=%s", (m.tenant.code,)).fetchone()["n"]
    r = tc.post(f"{base}/{opt}/optimize", headers=h.hdr(k["operator"]), json={"fixed": fixed, "request_approval": False})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 18 and r.json()["status"] in ("needs_approval", "review")
    rec_id = r.json()["recommendation"]["rec_id"]
    with connect() as c:
        assert c.execute("SELECT count(*) AS n FROM mlp_approval WHERE tenant_id=%s", (m.tenant.code,)).fetchone()["n"] == n0
        a = c.execute("SELECT detail FROM mlp_audit WHERE tenant_id=%s AND action='recommendation.create' AND target LIKE %s",
                      (m.tenant.code, f"%{rec_id}")).fetchone()
        assert a and a["detail"]["approval_id"] is None
    r = tc.post(f"{base}/{opt}/optimize", headers=h.hdr(k["operator"]), json={"fixed": fixed})
    with connect() as c:
        assert c.execute("SELECT count(*) AS n FROM mlp_approval WHERE ref_id=%s",
                         (r.json()["recommendation"]["rec_id"],)).fetchone()["n"] == 1   # 기본값 true 는 그대로
    bad = tc.post(f"{base}/{opt}/optimize", headers=h.hdr(k["operator"]), json={"fixed": fixed, "request_approval": "no"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_input"
    nf = tc.post(f"{base}/{reg}/optimize", headers=h.hdr(k["operator"]), json={"fixed": fixed})
    assert nf.status_code == 404 and nf.json()["error"]["detail"]["rule"] == "type_route"


def test_trace_explain_view_roles(world):
    m, opt, reg, refs, k, tc = world
    lock = h.lock_of(refs[reg])
    pid = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{reg}/predict", headers=h.hdr(k["operator"]),
                  json={"inputs": h.mid_inputs(lock, lock["order"]), "explain": True}).json()["prediction_id"]
    url = f"/api/v1/predictions/{pid}/trace"
    for role in ("operator", "approver", "admin"):
        r = tc.get(url + "?view=explain", headers=h.hdr(k[role]))
        assert r.status_code == 200, (role, r.text)
        body = r.json()
        assert set(body) == {"view", "prediction", "model", "snapshot", "notice"}
        assert "inputs" not in body["prediction"] and "sources" not in body and "run" not in body
        assert body["prediction"]["explain"]["top"]
    assert tc.get(url + "?view=explain", headers=h.hdr(k["viewer"])).status_code == 403
    for role in ("viewer", "operator", "approver"):
        assert tc.get(url, headers=h.hdr(k[role])).status_code == 403                  # 전체 추적은 admin 만 그대로
    assert tc.get(url, headers=h.hdr(k["admin"])).status_code == 200
    r = tc.get(url + "?view=raw", headers=h.hdr(k["admin"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
