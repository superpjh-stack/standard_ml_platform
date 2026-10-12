"""표준 AI Agent 플랫폼용 `ml.*` 도구 어댑터 (contracts/agent-tools.md — 정본, G2-I01 · D2-08 · D2-16). 소유 개발2.

공개 API(B02 · B03 · B04 · B06 · B15) 위의 얇은 층이다. 새 HTTP 경로를 만들지 않고, 쓰기를 하지 않는다:
4 도구 모두 readonly — 승인 요청 · 승격 · 되돌리기 · 학습 · 실측 · 대기열 판정 · 견적 확정을 부르지 않는다.
`ml.calculate_recommendation` 은 optimize 에 `request_approval: false` 를 보내 추천만 받는다(mlp_approval 0).

결과 봉투 `ToolResult` · `Cite` · `ToolMeta` 는 Agent 저장소(`src/agentcore/tools/registry.py:26-90`)의 모양 · 불변식을
**우리 쪽에서 다시 구현**한 것이다 — Agent 저장소를 import 하지 않는다(읽기만, 쓰기 0).

transport = `(method, path, json | None) -> (status, body)`. 기본은 표준 라이브러리 HTTP 로 환경변수
`MLP_ML_BASE_URL` · `MLP_ML_API_KEY` 를 쓴다(값은 코드 · 문서 · 로그에 적지 않는다). 시험은 FastAPI TestClient 를 꽂는다.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError

KST = timezone(timedelta(hours=9))
CONNECTOR = "ml"
TIMEOUT_S = 5.0
ROWS_MAX = 200
SUMMARY_MAX = 200
NAME_RE = re.compile(r"^_?[a-z][a-z0-9-]*\.(get|list|find|compare|calculate|draft)_[a-z0-9_]+$")   # tool-contract.md:7
TASK_RE = r"^[a-z][a-z0-9]{1,7}\.[a-z][a-z0-9_]*$"

ALIASES = {                                   # 정본 이름(spec §13) → Agent 이름 (agent-tools §0, D2-16)
    "ml.predict": "ml.calculate_prediction",
    "ml.explain": "ml.get_explanation",
    "ml.recommend": "ml.calculate_recommendation",
    "ml.monitor_summary": "ml.get_monitor_summary",
}
NAMES = tuple(ALIASES.values())

Transport = Callable[[str, str, Optional[dict]], "tuple[int, dict]"]


# ── 봉투 (registry.py:26-90 모양 · 불변식) ─────────────────────────────────────────────────────────
@dataclass
class ToolMeta:
    readonly: bool = True
    sources: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=lambda: ["admin", "manager", "staff"])
    pii: bool = False
    queries: list[str] = field(default_factory=list)
    label: str = ""


@dataclass
class Cite:
    kind: str
    ref: str
    subject: dict[str, str]
    snapshot: dict[str, Any]
    demo_data: bool = False


DISCONNECTED_SNAPSHOT_KEYS = {"connector", "query", "complete", "error_code"}


@dataclass
class ToolResult:
    status: str                                   # ok | empty | disconnected | denied | error
    source: str
    rows: list[dict] = field(default_factory=list)
    demo_data: bool = False
    truncated: bool = False
    complete: bool = True
    last_collected_at: str | None = None
    cite: list[Cite] = field(default_factory=list)
    summary: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("ok", "empty", "disconnected", "denied", "error"):
            raise ValueError("unknown status")
        if len(self.summary) > SUMMARY_MAX:
            raise ValueError("summary too long")
        if len(self.rows) > ROWS_MAX:
            raise ValueError("too many rows")
        if any(not c.subject for c in self.cite):
            raise ValueError("cite subject must not be empty")
        if self.status == "ok" and not self.cite:
            raise ValueError("ok result needs at least one cite")
        if self.status == "empty" and (len(self.cite) != 1 or self.cite[0].kind != "query"):
            raise ValueError("empty result needs exactly one query cite")
        if self.status == "empty" and not self.complete:
            raise ValueError("incomplete result cannot be 'empty'")
        if self.status == "disconnected":
            if len(self.cite) != 1 or self.cite[0].kind != "query":
                raise ValueError("disconnected result needs exactly one query cite")
            snap = self.cite[0].snapshot or {}
            if set(snap) != DISCONNECTED_SNAPSHOT_KEYS or snap.get("complete") is not False or self.complete or self.rows:
                raise ValueError("disconnected cite snapshot must be {connector, query, complete: false, error_code}")


_seq = itertools.count(1)


def _call_id() -> str:
    return f"{int(time.time() * 1000):x}-{next(_seq)}"


def disconnected(query: str, error_code: str, *, subject: dict | None = None) -> ToolResult:
    subj = {str(k): str(v) for k, v in (subject or {}).items() if v not in (None, "")} or {"connector": CONNECTOR}
    cite = Cite("query", f"query:{query}@disconnected-{_call_id()}", subj,
                {"connector": CONNECTOR, "query": query, "complete": False, "error_code": error_code})
    return ToolResult("disconnected", CONNECTOR, complete=False, cite=[cite], summary=f"미연결: {CONNECTOR} ({error_code})")


# ── 인자 모델 (agent-tools §2) ─────────────────────────────────────────────────────────────────────
_ARGS = ConfigDict(extra="forbid", allow_inf_nan=False)
Value = Union[StrictInt, StrictFloat, StrictStr, None]


class PredictionArgs(BaseModel):
    model_config = _ARGS
    task: StrictStr = Field(pattern=TASK_RE, description="<회사>.<과제> — ctx.tenant.code 와 회사가 같아야 한다")
    inputs: dict[str, Value]
    entity_id: Optional[StrictStr] = Field(default=None, max_length=64)
    explain: StrictBool = False


class ExplanationArgs(BaseModel):
    model_config = _ARGS
    prediction_id: StrictStr = Field(pattern=r"^prd_[0-9A-Z]{26}$")


class RecommendationArgs(BaseModel):
    model_config = _ARGS
    task: StrictStr = Field(pattern=TASK_RE)
    fixed: dict[str, Value]
    current: Optional[dict[str, Value]] = None
    params: Optional[dict[str, Union[StrictInt, StrictFloat]]] = None


class MonitorSummaryArgs(BaseModel):
    model_config = _ARGS
    task: Optional[StrictStr] = Field(default=None, pattern=TASK_RE, description="없으면 회사의 켜진 과제 전부")
    days: StrictInt = Field(default=7, ge=1, le=30)


@dataclass(frozen=True)
class ToolDef:
    name: str
    alias: str
    args_model: type[BaseModel]
    meta: ToolMeta
    description: str

    def schema(self, tasks: list[str] | None = None) -> dict:
        """Agent 가 LLM 에 주는 인자 스키마(title 을 뗀다, registry.py:113-117). tasks 가 있으면 task enum(choices)."""
        s = self.args_model.model_json_schema()
        s.pop("title", None)
        for p in s.get("properties", {}).values():
            p.pop("title", None)
        if tasks and "task" in s.get("properties", {}):
            s["properties"]["task"]["enum"] = list(tasks)
        return s


TOOLS: dict[str, ToolDef] = {
    "ml.calculate_prediction": ToolDef("ml.calculate_prediction", "ml.predict", PredictionArgs,
                                       ToolMeta(True, ["ml"], ["admin", "manager", "staff"], False, [], "ML 예측"),
                                       "표준 ML 과제로 예측한다(읽기 전용 — 예측 기록만 남는다)."),
    "ml.get_explanation": ToolDef("ml.get_explanation", "ml.explain", ExplanationArgs,
                                  ToolMeta(True, ["ml"], ["admin", "manager", "staff"], False, [], "예측 근거"),
                                  "예측 ID 의 모델 · 스냅숏 · 기여(축약 추적)를 돌려준다."),
    "ml.calculate_recommendation": ToolDef("ml.calculate_recommendation", "ml.recommend", RecommendationArgs,
                                           ToolMeta(True, ["ml"], ["admin", "manager"], False, [], "조건 추천"),
                                           "고정 조건에서 추천 조건 후보를 계산한다(승인 요청을 만들지 않는다)."),
    "ml.get_monitor_summary": ToolDef("ml.get_monitor_summary", "ml.monitor_summary", MonitorSummaryArgs,
                                      ToolMeta(True, ["ml"], ["admin", "manager", "staff"], False, [], "모델 감시 요약"),
                                      "회사 과제별 운영 버전 · 감시 수준 · 경고 · 대기 승인 수를 요약한다."),
}


def resolve(name: str) -> str:
    """정본 이름(별칭) · Agent 이름 · LLM 이름(`ml__x`) → Agent 이름. 모르면 KeyError."""
    n = name.replace("__", ".")
    n = ALIASES.get(n, n)
    if n not in TOOLS:
        raise KeyError(name)
    return n


# ── 기본 transport ─────────────────────────────────────────────────────────────────────────────
def http_transport(base_url: str | None = None, api_key: str | None = None, timeout: float = TIMEOUT_S) -> Transport:
    base = (base_url or os.environ.get("MLP_ML_BASE_URL") or "").rstrip("/")
    key = api_key or os.environ.get("MLP_ML_API_KEY") or ""

    def send(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"X-API-Key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}
    return send


# ── 호출 ───────────────────────────────────────────────────────────────────────────────────────
class _Fail(Exception):
    def __init__(self, result: ToolResult):
        self.result = result


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _tenant_code(tenant: Any) -> str:
    return tenant if isinstance(tenant, str) else getattr(tenant, "code")


def _field_of(err: dict) -> str:
    d = err.get("detail") or {}
    if d.get("field"):
        return str(d["field"])
    errs = d.get("errors") or []
    if errs and isinstance(errs[0], dict) and errs[0].get("field"):
        return str(errs[0]["field"])
    return d.get("rule") or "-"


def _send(transport: Transport, name: str, method: str, path: str, body: dict | None, subject: dict) -> dict:
    """HTTP 1회 → 성공 body. 실패는 봉투(_Fail)로 — 기본값 · 대체 예측을 만들지 않는다."""
    t0 = time.perf_counter()
    try:
        status, data = transport(method, path, body)
    except TimeoutError:
        raise _Fail(disconnected(name, "timeout", subject=subject))
    except (OSError, urllib.error.URLError):
        raise _Fail(disconnected(name, "unreachable", subject=subject))
    if time.perf_counter() - t0 > TIMEOUT_S:
        raise _Fail(disconnected(name, "timeout", subject=subject))
    if 200 <= status < 300:
        return data or {}
    err = (data or {}).get("error") or {}
    code = err.get("code") or f"http_{status}"
    if status == 503 or status >= 500:
        raise _Fail(disconnected(name, code, subject=subject))
    if status in (401, 403):
        raise _Fail(ToolResult("denied", CONNECTOR, summary="권한 밖 요청"))
    if status in (404, 422, 409):
        raise _Fail(ToolResult("error", CONNECTOR, summary=f"인자 오류: {_field_of(err)}"[:SUMMARY_MAX]))
    raise _Fail(ToolResult("error", CONNECTOR, summary=f"요청 실패 ({code})"[:SUMMARY_MAX]))


def _own_task(task: str, tenant: str) -> None:
    if task.split(".", 1)[0] != tenant:
        raise _Fail(ToolResult("denied", CONNECTOR, summary="다른 회사의 과제입니다"))


def call(name: str, args: dict, *, tenant: Any, transport: Transport | None = None) -> ToolResult:
    """도구 1회 호출 → ToolResult. 예외를 던지지 않는다(registry.call 과 같다)."""
    try:
        tool = TOOLS[resolve(name)]
    except KeyError:
        return ToolResult("error", "registry", summary="모르는 도구")
    try:
        parsed = tool.args_model.model_validate(args or {})
    except ValidationError as e:
        loc = ".".join(str(x) for x in (e.errors()[0].get("loc") or ())) or "-"
        return ToolResult("error", CONNECTOR, summary=f"인자 오류: {loc}"[:SUMMARY_MAX])
    code = _tenant_code(tenant)
    tp = transport or http_transport()
    try:
        return _RUN[tool.name](parsed, code, tp)
    except _Fail as f:
        return f.result
    except Exception as e:  # noqa: BLE001 — 도구는 예외를 밖으로 내지 않는다(키 · 경로를 요약에 넣지 않는다)
        return ToolResult("error", CONNECTOR, summary=f"내부 오류 ({type(e).__name__})")


def _prediction(a: PredictionArgs, tenant: str, tp: Transport) -> ToolResult:
    name = "ml.calculate_prediction"
    _own_task(a.task, tenant)
    subject = {"task": a.task}
    body = {"inputs": a.inputs, "explain": a.explain}
    if a.entity_id is not None:
        body["entity_id"] = a.entity_id
    r = _send(tp, name, "POST", f"/api/v1/tenants/{tenant}/tasks/{a.task}/predict", body, subject)
    pred = r.get("prediction") or {}
    anom = r.get("anomaly") or {}
    model = r.get("model") or {}
    row = {"prediction_id": r.get("prediction_id"), "task": r.get("task"), "type": r.get("type"),
           "value": pred.get("value"), "unit": pred.get("unit"), "interval": pred.get("interval"),
           "probability": r.get("probability"), "grade": pred.get("grade"), "anomaly_flag": anom.get("flag"),
           "status": r.get("status"), "warnings": [w.get("code") for w in r.get("warnings") or []],
           "model_version": model.get("version"), "synthetic": bool(r.get("synthetic"))}
    cite = Cite("row", f"ml:mlp_prediction/{row['prediction_id']}", {"task": a.task, "entity": a.entity_id or "-"},
                {"value": row["value"] if row["value"] is not None else row["probability"], "unit": row["unit"],
                 "status": row["status"], "model_version": row["model_version"]}, demo_data=row["synthetic"])
    st = row["status"]
    summary = f"{a.task} 예측 상태 {st} (모델 {row['model_version']})"
    if st in ("out_of_range", "rejected"):
        summary += " — 학습 범위 밖"
    if row["synthetic"]:
        summary += " · 합성 데이터 모델"
    return ToolResult("ok", CONNECTOR, rows=[row], demo_data=row["synthetic"], last_collected_at=_now(),
                      cite=[cite], summary=summary[:SUMMARY_MAX])


def _explanation(a: ExplanationArgs, tenant: str, tp: Transport) -> ToolResult:
    name = "ml.get_explanation"
    r = _send(tp, name, "GET", f"/api/v1/predictions/{a.prediction_id}/trace?view=explain", None,
              {"prediction": a.prediction_id})
    p, m, s = r.get("prediction") or {}, r.get("model") or {}, r.get("snapshot") or {}
    ex = p.get("explain") or None
    contributors = ([{"feature": t.get("field"), "contribution": t.get("contribution")} for t in ex.get("top") or []]
                    if isinstance(ex, dict) else None)
    synthetic = bool(p.get("synthetic") or s.get("synthetic"))
    row = {"prediction_id": p.get("prediction_id"), "task": p.get("task"), "model_version": m.get("version"),
           "algo": m.get("algo"), "trained_at": m.get("trained_at"), "snapshot_id": s.get("snapshot_id"),
           "snapshot_rows": s.get("rows"), "snapshot_range": f"{s.get('ts_from')}~{s.get('ts_to')}" if s else None,
           "synthetic": synthetic, "contributors": contributors, "notice": r.get("notice") or ""}
    cite = Cite("row", f"ml:mlp_prediction/{row['prediction_id']}", {"task": str(row["task"]), "model": str(row["model_version"])},
                {"snapshot_id": row["snapshot_id"], "algo": row["algo"]}, demo_data=synthetic)
    summary = f"{row['task']} 예측 근거 — 모델 {row['model_version']}({row['algo']}) · 스냅숏 {row['snapshot_rows']}행"
    if contributors is None:
        summary += " · 기여 기록 없음"
    return ToolResult("ok", CONNECTOR, rows=[row], demo_data=synthetic, last_collected_at=row["trained_at"],
                      cite=[cite], summary=summary[:SUMMARY_MAX])


def _recommendation(a: RecommendationArgs, tenant: str, tp: Transport) -> ToolResult:
    name = "ml.calculate_recommendation"
    _own_task(a.task, tenant)
    body: dict = {"fixed": a.fixed, "request_approval": False}       # 추천만 — 승인 요청 0 (D2-08)
    if a.current is not None:
        body["current"] = a.current
    if a.params is not None:
        body["params"] = a.params
    r = _send(tp, name, "POST", f"/api/v1/tenants/{tenant}/tasks/{a.task}/optimize", body, {"task": a.task})
    rec = r.get("recommendation") or {}
    rate = rec.get("in_train_range_rate")
    rows = []
    for i, c in enumerate((rec.get("candidates") or [])[:5], start=1):
        rows.append({"rank": i, "conditions": c.get("conditions"), "predictions": c.get("predictions"),
                     "constraints_met": all(x.get("satisfied") for x in c.get("constraints") or []),
                     "violation": c.get("violation"), "in_train_range": True if rate == 1 else None})
    synthetic = bool(r.get("synthetic"))
    cites = [Cite("row", f"ml:mlp_recommendation/{rec.get('rec_id')}", {"task": a.task},
                  {"feasible": rec.get("feasible"), "best": (rec.get("best") or {}).get("conditions")}, demo_data=synthetic)]
    for u in r.get("uses") or []:
        cites.append(Cite("row", f"ml:mlp_model_version/{u.get('task')}@{u.get('version')}",
                          {"task": str(u.get("task")), "model": str(u.get("version"))},
                          {"version": u.get("version"), "synthetic": u.get("synthetic")}, demo_data=bool(u.get("synthetic"))))
    summary = f"{a.task} 추천 후보 {len(rows)} · feasible={rec.get('feasible')} · rec_id={rec.get('rec_id')} — 설비에 적용하지 않음"
    return ToolResult("ok", CONNECTOR, rows=rows, demo_data=synthetic, last_collected_at=_now(), cite=cites,
                      summary=summary[:SUMMARY_MAX])


def _monitor_summary(a: MonitorSummaryArgs, tenant: str, tp: Transport) -> ToolResult:
    name = "ml.get_monitor_summary"
    if a.task:
        _own_task(a.task, tenant)
    today = date.today()
    rng = f"{(today - timedelta(days=a.days)).isoformat()}~{today.isoformat()}"
    listing = _send(tp, name, "GET", f"/api/v1/tenants/{tenant}/tasks", None, {"tenant": tenant})
    tasks = [t["task"] for t in listing.get("items") or []]
    if a.task:
        if a.task not in tasks:
            return ToolResult("error", CONNECTOR, summary="인자 오류: task")
        tasks = [a.task]
    if not tasks:
        cite = Cite("query", f"ml:monitor_summary@{_call_id()}", {"tenant": tenant, "range": rng},
                    {"tasks": 0, "complete": True})
        return ToolResult("empty", CONNECTOR, cite=[cite], summary="감시할 켜진 과제가 없습니다")
    truncated = len(tasks) > ROWS_MAX
    rows, cites, days = [], [], []
    for tid in tasks[:ROWS_MAX]:
        o = _send(tp, name, "GET", f"/api/v1/tenants/{tenant}/tasks/{tid}/overview", None, {"task": tid})
        prod = o.get("production") or {}
        mon = o.get("monitor") or {}
        row = {"task": tid, "type": o.get("type"), "production_version": prod.get("version"),
               "synthetic": prod.get("synthetic"), "predictions_yesterday": o.get("predictions_yesterday"),
               "monitor_level": mon.get("level"), "alerts": mon.get("alerts") or [],
               "pending_approvals": o.get("pending_approvals")}
        rows.append(row)
        if mon.get("day"):
            days.append(mon["day"])
        cites.append(Cite("row", f"ml:mlp_monitor_daily/{tid}@{mon.get('day') or '-'}", {"task": tid, "range": rng},
                          {"level": mon.get("level"), "alerts": row["alerts"]}, demo_data=bool(prod.get("synthetic"))))
    demo = any(bool(r["synthetic"]) for r in rows)
    warn = sum(1 for r in rows if r["monitor_level"] in ("warn", "retrain"))
    no_prod = sum(1 for r in rows if r["production_version"] is None)
    summary = f"과제 {len(rows)} — 경고 {warn} · 운영 모델 없음 {no_prod}"
    return ToolResult("ok", CONNECTOR, rows=rows, demo_data=demo, truncated=truncated,
                      last_collected_at=max(days) if days else None, cite=cites, summary=summary[:SUMMARY_MAX])


_RUN = {"ml.calculate_prediction": _prediction, "ml.get_explanation": _explanation,
        "ml.calculate_recommendation": _recommendation, "ml.get_monitor_summary": _monitor_summary}
