"""G2-V01 — 2차 수직 관통 (goal2 §1-2 · §2 G2-V01 · 웨이브 A0-2). 소유 개발2.

같은 mlcore 코드 · 다른 팩/회사 등록부로 2차 유형 두 흐름이 **API 로 끝까지** 돈다. API 키 · 역할은 실제 auth 경로
(mlp_api_key 해시 → 미들웨어 → auth.require · require_own_task)로 보낸다 — 우회 없음.

(a) `kd.quote` (팩 eto · 회사 kd)
    labor_hours 학습(POST train admin → 작업자 진입점) → stage → promote(approver) → decide(approver) = production
    → DXF 업로드(operator) → cad_regions 3종 · bom_text BOM 추출 (labels none · 지표 null)
    → 사람 검토 · 수정: 초안(수량 수정 → overrides 1) → 개정(원천 BOM · 단가로 되돌림 — overrides 이력은 남는다)
    → labor_hours production 예측(channel quote) → 견적식(Decimal · HALF_UP) → 확정 요청(operator, reviewed + 메모)
    → 승인(approver — B13 decide) → 확정 스냅숏 → CSV(UTF-8 BOM) → 확정 뒤 수정 · 재확정 409 quote_locked.
    금액 대조: 기대값 = 원천 앱이 저장한 견적 `tests/fixtures/kd/source_quotes.json`(migration/source_expected.py —
    원천 SQLite 읽기 전용). 공수와 무관한 칸(품목 금액 · 소재비 · 외주비)은 원천 값과 원 단위로 같고, 공수에 걸린 칸은
    원천 식(`KyungDong ML AI/api/quote.py:5-17`)을 이 시험에서 Decimal 로 다시 세운 값과 같다. 원천 공수(58.146 h)를
    넣으면 같은 확정 스냅숏(입력 · 단가 · BOM)에서 원천 합계 8,486,493 원이 그대로 나온다.
    확정 스냅숏: 새 모델 버전으로 운영을 바꿔도 확정 견적 금액 · 예측 ID · 모델 버전은 그대로다.

(b) `pc.residual_review` (팩 kimchi · 회사 pc)
    sensory_score 학습 → 승인 → production → 운영 예측(operator, entity_id) → 실측(POST actuals)
    → 대기열 일정 작업(`monitor.review.run_review` — 감시 일일 작업 뒤 단계의 진입점, D2-45 ⑦)
    → GET review: 항목 출처는 test_split(시험 구간 행만 — 스냅숏의 시간순 마지막 20%) · live_residual(실측이 붙은
    운영 예측만, prediction_id 근거) 뿐 · 학습/검증 구간 행 0 · 임계값 = 검증 구간 잔차 분위(운영 묶음으로 재지 않음)
    → PATCH 검토(approver) → 재검토 409 already_decided · operator 는 조회만(403).

**우회 (D-57 — 1차와 같다):** POST …/train 은 queued 작업만 만든다. 이 시험은 작업자 진입점
`serve.training.run_and_register(run_id)` 를 직접 부른다. 대기열 일정 작업도 스케줄러가 부를 진입점을 직접 부른다.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

import _dev2 as h
from mlcore.db.conn import connect
from mlcore.serve import training

pytestmark = [pytest.mark.gate("G2-V01"), pytest.mark.skipif(not h.db_ok(), reason="ml_test_db 없음 — make setup")]

KST = timezone(timedelta(hours=9))
SOURCE_QUOTES = json.loads((h.ROOT / "tests" / "fixtures" / "kd" / "source_quotes.json").read_text(encoding="utf-8"))["rows"]
SOURCE_DRAWINGS = json.loads((h.ROOT / "tests" / "fixtures" / "kd" / "source_drawing.json").read_text(encoding="utf-8"))["rows"]
SAMPLE = next(r for r in SOURCE_QUOTES if r["total"] == 8486493)       # 원천 docs/verification.md:29 샘플 견적
WON = Decimal("1")


def dec(obj):
    """JSON → Decimal (코어와 같이 parse_float=Decimal — float 를 거치지 않는다)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def half_up(x: Decimal, q: Decimal = WON) -> Decimal:
    return x.quantize(q, rounding=ROUND_HALF_UP)


def source_formula(inp: dict, bom: list[dict], hours: Decimal, cost: dict) -> dict:
    """원천 `api/quote.py:5-17 calculate()` 를 **읽어** 이 시험에서 다시 세운 식(Decimal · HALF_UP — D2-07 · D2-07a).
    팩 견적식(packs/eto/formulas/quote.py)을 부르지 않는다 — 독립 기대값."""
    qty = Decimal(inp["quantity"])
    h4 = half_up(hours, Decimal("0.0001"))                                              # :9 round(…, 4)
    lines = [half_up(r["mass_kg"] * r["quantity"] * r["price_kg"] * (1 + cost["scrap_rate"]) * qty) for r in bom]   # :11
    material = sum(lines, Decimal(0))                                                    # :12
    labor = half_up(h4 * inp["labor_rate"] * qty)                                        # :13
    outsource = half_up(inp["outsource_cost"] * qty)                                     # :14
    markup = half_up((material + labor + outsource) * cost["markup"])                    # :15
    subtotal = material + labor + outsource + markup                                     # :16
    vat = half_up(subtotal * cost["vat_rate"])                                           # :17
    return {"lines": lines, "material": material, "labor": labor, "outsource": outsource, "markup": markup,
            "subtotal": subtotal, "vat": vat, "total": subtotal + vat, "hours": h4}


def _promote_via_api(tc, k, t: str, task: str, *, seed: int | None = None) -> str:
    """POST train(admin) → 작업자 진입점 → stage(admin) → promote(approver) → decide(approver). → production 버전."""
    base = f"/api/v1/tenants/{t}/tasks/{task}"
    assert tc.post(f"{base}/train", headers=h.hdr(k["operator"]), json={}).status_code == 403
    r = tc.post(f"{base}/train", headers=h.hdr(k["admin"]), json={} if seed is None else {"seed": seed})
    assert r.status_code == 202, r.text
    result, ref = training.run_and_register(r.json()["run_id"])
    assert result.status == "succeeded" and ref is not None and ref.stage == "candidate"
    r = tc.post(f"{base}/models/{ref.version}/stage", headers=h.hdr(k["admin"]))
    assert r.status_code == 200, r.text
    r = tc.post(f"{base}/models/{ref.version}/promote", headers=h.hdr(k["approver"]), json={"reason": "수직 관통 2"})
    assert r.status_code == 202 and r.json()["state"] == "pending", r.text
    aid = r.json()["approval_id"]
    assert tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["operator"]),
                   json={"decision": "approve", "reason": "x"}).status_code == 403
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]),
                json={"decision": "approve", "reason": "수직 관통 2 승인"})
    assert r.status_code == 200 and r.json()["production_version"] == ref.version, r.text
    return ref.version


def _json(tc, method: str, url: str, key: str, body) -> "object":
    return tc.request(method, url, headers={**h.hdr(key), "Content-Type": "application/json"}, content=json.dumps(body))


# ═══════════════════════════════════════════ (a) kd.quote ═══════════════════════════════════════════
@pytest.fixture(scope="module")
def kd(tmp_path_factory):
    m = h.make_tenant("kd", tmp_path_factory.mktemp("vs2-kd"))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        yield SimpleNamespace(m=m, t=m.tenant.code, k=k, tc=tc)


def test_kd_quote_end_to_end(kd):
    m, t, k, tc = kd.m, kd.t, kd.k, kd.tc
    qbase = f"/api/v1/tenants/{t}/tasks/{t}.quote"
    dbase = f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions"
    src_in = SAMPLE["input"]
    bom_src = [{kk: v for kk, v in b.items()} for b in src_in["bom"]]            # 원천 확정 BOM(단가 포함)
    inputs = {"cut_m": src_in["cut_m"], "weld_m": src_in["weld_m"], "thickness_mm": src_in["thickness_mm"],
              "complexity": src_in["complexity"], "main_material": src_in["material"], "product_family": src_in["product"],
              "quantity": src_in["quantity"], "labor_rate": src_in["labor_rate"], "outsource_cost": src_in["outsource_cost"]}

    # ── 1. DXF 업로드 → 규칙 추출(영역 3종 · BOM 텍스트) — 권한 · 라벨 없음 ─────────────────────────────
    from importlib.util import module_from_spec, spec_from_file_location
    sp = spec_from_file_location("eto_sample_dxf_vs2", h.ROOT / "packs" / "eto" / "synth" / "sample_dxf.py")
    sample = module_from_spec(sp)
    sp.loader.exec_module(sample)
    raw = sample.sample_bytes(m.tenant.config["categories"]["main_material"])
    files = {"file": ("KD-demo-reactor.dxf", raw, "application/dxf")}
    assert tc.post(f"{dbase}/documents", headers=h.hdr(k["viewer"]), files=files).status_code == 403
    assert tc.post(f"{dbase}/documents", files=files).status_code == 401
    r = tc.post(f"{dbase}/documents", headers=h.hdr(k["operator"]), files=files)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["labels"] == "none" and doc["metrics"] is None                    # 정답 라벨 없음 → 지표 없음
    src_draw = SOURCE_DRAWINGS[-1]
    labels = sorted(x["label"] for x in doc["regions"])
    assert labels == sorted(kk for kk, n in src_draw["counts"].items() for _ in range(n))   # title_block · bom_table · rev_table
    recognized = [{kk: b[kk] for kk in ("name", "material", "quantity", "mass_kg")} for b in doc["bom_rows"]]
    assert dec(recognized) == dec([{kk: b[kk] for kk in ("name", "material", "quantity", "mass_kg")} for b in src_draw["bom"]])
    assert {e["name"] for e in doc["extractor"]} == {"cad_regions", "bom_text"}

    # ── 2. 운영 모델 없음 → 견적 503 (대체 금액 0 — 초안을 만들지 않는다) ────────────────────────────────
    body = {"doc_id": doc["doc_id"], "inputs": inputs, "lines": bom_src}
    r = _json(tc, "POST", f"{qbase}/quotes", k["operator"], body)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_ready", r.text
    assert h.count("SELECT count(*) AS n FROM mlp_quote WHERE tenant_id = %s", (t,)) == 0

    # ── 3. labor_hours 학습 → 승인 → production (API) ───────────────────────────────────────────
    v1 = _promote_via_api(tc, k, t, f"{t}.labor_hours")

    # ── 4. 사람 검토 · 수정 — 초안(수량을 고침 → overrides 1) ────────────────────────────────────
    edited = [dict(b) for b in bom_src]
    edited[3]["quantity"] = 5                                                    # SUPPORT 4 → 5 (사람 수정)
    assert _json(tc, "POST", f"{qbase}/quotes", k["viewer"], {**body, "lines": edited}).status_code == 403
    r = _json(tc, "POST", f"{qbase}/quotes", k["operator"], {**body, "lines": edited})
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["status"] == "draft" and draft["revision"] == 1
    assert [o["field"] for o in draft["overrides"]] == ["bom"]
    assert dec(draft["overrides"][0]["confirmed"])[3]["quantity"] == 5

    # ── 5. 개정 — 원천 확정 BOM 으로 (인식값과 같다 → 새 수정 없음, 이력은 남는다) ─────────────────────
    r = _json(tc, "POST", f"{qbase}/quotes/{draft['quote_id']}/revisions", k["operator"], body)
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["revision"] == 2 and q["supersedes"] == draft["quote_id"] and q["status"] == "draft"
    assert q["overrides"] == draft["overrides"]                                 # 사람 수정 이력은 지우지 않는다

    # ── 6. 금액 — Decimal 문자열 · 원천 저장 견적과 원 단위 대조 ──────────────────────────────────────
    assert isinstance(q["total"], str) and all(isinstance(v, str) for v in q["costs"].values())
    (pred,) = q["predictions"]
    assert pred["task"] == f"{t}.labor_hours" and q["model_versions"][0]["version"] == v1
    with connect() as c:
        row = c.execute("SELECT channel, version FROM mlp_prediction WHERE prediction_id = %s",
                        (pred["prediction_id"],)).fetchone()
    assert (row["channel"], row["version"]) == ("quote", v1)                    # labor_hours production 예측 1행
    hours = Decimal(pred["value"])
    cost = {kk: Decimal(v) for kk, v in q["rates"].items()}
    assert cost == {kk: Decimal(str(v)) for kk, v in SAMPLE["cost_snapshot"].items()}   # 원천 COST 스냅숏(config.py)
    dsrc = dec(src_in)
    want = source_formula(dsrc, dsrc["bom"], hours, cost)
    got = {kk: Decimal(v) for kk, v in q["costs"].items()}
    # 공수와 무관한 칸 — 원천 저장 값 그대로
    assert [Decimal(ln["amount"]) for ln in q["lines"]] == [Decimal(ln["cost"]) for ln in SAMPLE["lines"]]
    assert got["material"] == Decimal(SAMPLE["material_cost"]) == Decimal("4092120")
    assert got["outsource"] == Decimal(SAMPLE["outsource_cost"])
    # 공수에 걸린 칸 — 원천 식(같은 공수) 원 단위
    assert (got["labor"], got["markup"], got["subtotal"], got["vat"], Decimal(q["total"])) == \
        (want["labor"], want["markup"], want["subtotal"], want["vat"], want["total"])
    assert hours == want["hours"]                                                # 견적에 쓴 공수 = 소수 4자리
    # 원천 공수(58.146 h)를 같은 스냅숏(입력 · 단가 · BOM)에 넣으면 원천 합계 8,486,493 원 — 원 단위 일치
    replay = source_formula(dec(q["inputs"]) | {"labor_rate": dsrc["labor_rate"]}, dsrc["bom"],
                            Decimal(str(SAMPLE["hours_per_unit"])), cost)
    assert replay["total"] == Decimal(SAMPLE["total"]) == Decimal("8486493")
    assert (replay["labor"], replay["markup"], replay["vat"]) == (Decimal(SAMPLE["labor_cost"]),
                                                                  Decimal(SAMPLE["markup_cost"]), Decimal(SAMPLE["vat"]))
    assert dec(q["inputs"])["total_mass_kg"] == Decimal(str(SAMPLE["mass_kg"]))  # Σ BOM 중량 650 kg = 원천 features.mass_kg

    # ── 7. 확정 요청 — 검토 없으면 422 · operator 요청 202 · 대기 중 수정 409 ─────────────────────────
    qid = q["quote_id"]
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/confirm", k["operator"], {"reviewed": False, "review_note": "검토 완료함"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "missing_required"
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/confirm", k["operator"], {"reviewed": True, "review_note": "짧음"})
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"] == "review_note"
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/confirm", k["operator"],
              {"reviewed": True, "review_note": "도면 BOM · 단가 검토 완료"})
    assert r.status_code == 202 and r.json()["state"] == "pending", r.text
    aid = r.json()["approval_id"]
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/revisions", k["operator"], body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_locked"
    pending = tc.get(qbase + f"/quotes/{qid}", headers=h.hdr(k["viewer"]))
    assert pending.status_code == 403                                            # viewer 는 견적 화면 ✕ (goal2 §6)
    pending = tc.get(qbase + f"/quotes/{qid}", headers=h.hdr(k["operator"])).json()
    assert pending["status"] == "pending_confirm" and pending["total"] == q["total"]

    # ── 8. 승인(approver 이상 — B13 decide → approval.decide()) → 확정 스냅숏 ───────────────────────
    assert tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["operator"]),
                   json={"decision": "approve", "reason": "x"}).status_code == 403
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]),
                json={"decision": "approve", "reason": "견적 확정"})
    assert r.status_code == 200 and r.json()["state"] == "approved", r.text
    conf = tc.get(f"{qbase}/quotes/{qid}", headers=h.hdr(k["operator"])).json()
    assert conf["status"] == "confirmed" and conf["confirmed_by"] and conf["confirmed_at"]
    assert (conf["total"], conf["costs"], conf["lines"]) == (q["total"], q["costs"], q["lines"])
    assert conf["overrides"] == draft["overrides"] and conf["review_note"] == "도면 BOM · 단가 검토 완료"
    r = tc.post(f"/api/v1/approvals/{aid}/decide", headers=h.hdr(k["approver"]), json={"decision": "approve", "reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"

    # ── 9. CSV — UTF-8 BOM · 금액 문자열 그대로 · 수식 주입 방지 ─────────────────────────────────────
    r = tc.get(f"{qbase}/quotes/{conf['quote_id']}.csv", headers=h.hdr(k["operator"]))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    head = next(i for i, row in enumerate(rows) if row[:1] == ["name"] and "amount" in row)   # 품목 표 머리
    col = rows[head].index("amount")
    amounts = [Decimal(row[col]) for row in rows[head + 1:] if row]
    assert amounts == [Decimal(ln["cost"]) for ln in SAMPLE["lines"]]                     # 품목 금액 = 원천 저장 값
    assert not any(cell.startswith(("=", "+", "@")) for row in rows for cell in row)

    # ── 10. 확정 뒤 수정 · 재확정 409 quote_locked ─────────────────────────────────────────────────
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/revisions", k["operator"], {**body, "lines": edited})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_locked"
    r = _json(tc, "POST", f"{qbase}/quotes/{qid}/confirm", k["operator"], {"reviewed": True, "review_note": "다시 확정 시도"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_locked"

    # ── 11. 스냅숏 — 운영 모델이 바뀌어도 확정 금액 · 근거는 그대로 ───────────────────────────────────
    v2 = _promote_via_api(tc, k, t, f"{t}.labor_hours", seed=7)
    assert v2 != v1
    again = tc.get(f"{qbase}/quotes/{qid}", headers=h.hdr(k["operator"])).json()
    assert (again["status"], again["total"], again["costs"], again["predictions"], again["model_versions"]) == \
        ("confirmed", conf["total"], conf["costs"], conf["predictions"], conf["model_versions"])
    fresh = _json(tc, "POST", f"{qbase}/quotes", k["operator"], body).json()     # 새 초안은 새 모델을 쓴다
    assert fresh["model_versions"][0]["version"] == v2
    audit = h.count("SELECT count(*) AS n FROM mlp_audit WHERE tenant_id = %s AND action = 'quote.confirm_requested'", (t,))
    assert audit == 1


def test_kd_quote_csv_has_total(kd):
    """원천 CSV(`KyungDong ML AI/api/main.py:142-150`)는 소재비 · 가공비 · … · 합계(원) 행을 낸다. 표준 CSV 도 확정 합계를 내야 한다.
    D2-A2-01(웨이브 P 재진입 D2-70): 과제 `csv` 는 품목 열 순서 — 요약 행을 거르지 않는다."""
    m, t, k, tc = kd.m, kd.t, kd.k, kd.tc
    qbase = f"/api/v1/tenants/{t}/tasks/{t}.quote"
    items = tc.get(f"{qbase}/quotes", headers=h.hdr(k["operator"]), params={"status": "confirmed"}).json()["items"]
    assert items, "앞 시험이 확정 견적을 만든다"
    q = items[0]
    r = tc.get(f"{qbase}/quotes/{q['quote_id']}.csv", headers=h.hdr(k["operator"]))
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    summary = {row[0]: row[1] for row in rows if len(row) == 2}
    assert summary.get("total") == q["total"]
    assert all(summary.get(f"costs.{c}") == v for c, v in q["costs"].items())          # 구성 금액 행도 다 있다
    head = next(row for row in rows if row and row[0] == "name")                        # 품목 머리 = 과제 csv 순서
    assert head == kd.m.tasks[f"{kd.t}.quote"].raw["csv"]


# ═══════════════════════════════════════ (b) pc.residual_review ═══════════════════════════════════════
DAY = date(2026, 10, 2)


@pytest.fixture(scope="module")
def pc(tmp_path_factory):
    m = h.make_tenant("pc", tmp_path_factory.mktemp("vs2-pc"))
    with h.use_tenants_dir(m):
        k, tc = h.keys(m), h.client(m)
        yield SimpleNamespace(m=m, t=m.tenant.code, k=k, tc=tc)


def _pc_inputs(i: int) -> dict:
    return {"cabbage_pct": 70.0, "radish_pct": 8.0, "seasoning_pct": 20.0, "salt_pct": 2.0, "brine_salinity_pct": 11.0,
            "brining_hours": 12.0, "fermentation_temp_c": 5.0, "fermentation_hours": 36.0 + i, "storage_temp_c": 1.0,
            "cabbage_origin": m_origin(i), "prod_line": "K1" if i % 2 else "K2"}


def m_origin(i: int) -> str:
    return ["평창", "강릉", "기타계약"][i % 3]


def test_pc_residual_review_end_to_end(pc):
    from mlcore.monitor import review as job
    m, t, k, tc = pc.m, pc.t, pc.k, pc.tc
    uses, queue = f"{t}.sensory_score", f"{t}.residual_review"
    ubase, qbase = f"/api/v1/tenants/{t}/tasks/{uses}", f"/api/v1/tenants/{t}/tasks/{queue}"

    # ── 1. 대기열 과제는 predict 경로가 아니다 · 운영 모델 없으면 항목 0 ───────────────────────────────
    r = tc.post(f"{qbase}/predict", headers=h.hdr(k["operator"]), json={"inputs": {}})
    assert r.status_code == 404 and r.json()["error"]["detail"]["rule"] == "type_route"
    (s,) = [x for x in job.run_review(t, DAY, merged=m) if x["task_id"] == queue]
    assert s["created"] == 0 and "운영 모델 없음" in s["skipped"]

    # ── 2. 학습 → 승인 → production ────────────────────────────────────────────────────────────
    version = _promote_via_api(tc, k, t, uses)

    # ── 3. 운영 예측(operator · entity_id) → 실측(POST actuals) — 실측은 8건에만 ─────────────────────────
    preds = {}
    for i in range(12):
        r = tc.post(f"{ubase}/predict", headers=h.hdr(k["operator"]),
                    json={"inputs": _pc_inputs(i), "entity_id": f"VS2-LOT-{i:02d}"})
        assert r.status_code == 200, r.text
        preds[f"VS2-LOT-{i:02d}"] = r.json()
    offsets = {f"VS2-LOT-{i:02d}": (i - 3) * 3.0 for i in range(8)}             # 잔차 −9 ~ +12 점
    for e, off in offsets.items():
        r = tc.post(f"{ubase}/actuals", headers=h.hdr(k["operator"]),
                    json={"entity_id": e, "value": preds[e]["prediction"]["value"] + off,
                          "observed_at": datetime.now(KST).isoformat()})
        assert r.status_code in (200, 201), r.text
        assert preds[e]["prediction_id"] in r.json()["linked_prediction_ids"]

    # ── 4. 대기열 일정 작업(감시 뒤) → 항목 ───────────────────────────────────────────────────────
    (s,) = [x for x in job.run_review(t, DAY, merged=m) if x["task_id"] == queue]
    assert s["version"] == version and s["rule"] == "top_quantile" and s["threshold_from"] == "valid"
    assert s["pairs"] == 8 and s["test_split"]["created"] > 0
    thr = s["threshold"]

    # ── 5. GET review — 조회(operator ○ · viewer ✕) · 출처는 시험 구간 · 운영 잔차뿐 ─────────────────────
    assert tc.get(f"{qbase}/review", headers=h.hdr(k["viewer"])).status_code == 403
    items, cursor = [], None
    while True:
        r = tc.get(f"{qbase}/review", headers=h.hdr(k["operator"]),
                   params={"limit": 100, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        page = r.json()
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert items and {i["origin"] for i in items} == {"test_split", "live_residual"}
    assert all(i["state"] == "open" and i["model_version"] == version and i["rule"] == "top_quantile" for i in items)
    assert all(abs(i["residual"]) >= i["threshold"] - 1e-9 for i in items)

    #   live_residual = 실측이 붙은 운영 예측만(prediction_id 근거) — 실측 없는 4건 · 임계값 미만 0
    live = [i for i in items if i["origin"] == "live_residual"]
    by_pid = {p["prediction_id"]: e for e, p in preds.items()}
    assert all(i["prediction_id"] in by_pid and by_pid[i["prediction_id"]] in offsets for i in live)
    assert {i["entity_id"] for i in live} == {e for e, off in offsets.items() if abs(off) >= thr}
    for i in live:
        assert i["residual"] == pytest.approx(offsets[i["entity_id"]], abs=1e-6)

    #   test_split = 학습 스냅숏의 시험 구간(시간순 마지막 20%) 행만 — 학습 · 검증 구간 행 0
    test_items = [i for i in items if i["origin"] == "test_split"]
    assert all(i["prediction_id"] is None for i in test_items)
    with connect() as c:
        snap = c.execute("SELECT s.path, s.rows, r.report FROM mlp_model_version mv JOIN mlp_train_run r ON r.run_id = mv.run_id "
                         "JOIN mlp_snapshot s ON s.snapshot_id = mv.snapshot_id WHERE mv.tenant_id = %s AND mv.task_id = %s "
                         "AND mv.version = %s", (t, uses, version)).fetchone()
    p = h.ROOT / snap["path"] if not str(snap["path"]).startswith("/") else snap["path"]
    frame = pd.read_parquet(p).sort_values("ts", kind="stable").reset_index(drop=True)
    n_test = snap["report"]["split"]["boundaries"]["sizes"]["test"]
    assert n_test == round(len(frame) * 0.2)
    test_ids = set(frame["entity_id"].iloc[len(frame) - n_test:].astype(str))
    fit_ids = set(frame["entity_id"].iloc[:len(frame) - n_test].astype(str))
    assert {i["entity_id"] for i in test_items} <= test_ids
    assert not {i["entity_id"] for i in test_items} & fit_ids
    #   임계값 = 검증 구간 잔차 분위(운영 묶음 · 시험 구간으로 재지 않는다)
    from mlcore.train import review as tr
    assert thr == pytest.approx(tr.threshold({"top_quantile": 0.10}, snap["report"])["value"])

    # ── 6. PATCH 검토 — operator ✕ · approver ○ · 재검토 409 already_decided ─────────────────────────
    target = live[0] if live else test_items[0]
    url = f"{qbase}/review/{target['item_id']}"
    assert _json(tc, "PATCH", url, k["operator"], {"state": "confirmed_issue", "note": "x"}).status_code == 403
    assert _json(tc, "PATCH", url, k["approver_other"], {"state": "confirmed_issue", "note": "x"}).status_code == 403
    r = _json(tc, "PATCH", url, k["approver"], {"state": "confirmed_issue", "note": "배추 절임 시간 확인 필요"})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["state"] == "confirmed_issue" and done["decided_by"] and done["decided_at"]
    r = _json(tc, "PATCH", url, k["approver"], {"state": "false_alarm", "note": "다시"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"
    closed = tc.get(f"{qbase}/review", headers=h.hdr(k["operator"]), params={"state": "confirmed_issue"}).json()
    assert [i["item_id"] for i in closed["items"]] == [target["item_id"]]
    # 같은 날 다시 돌려도 새 항목 0 (같은 예측 · 같은 버전은 한 번만) · production 그대로
    (s2,) = [x for x in job.run_review(t, DAY, merged=m) if x["task_id"] == queue]
    assert s2["created"] == 0 and s2["test_split"]["created"] == 0
    stages = {i["version"]: i["stage"] for i in tc.get(f"{ubase}/models", headers=h.hdr(k["admin"])).json()["items"]}
    assert stages[version] == "production"
