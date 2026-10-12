"""견적 서비스 — B11 `/quotes*` (api-contract §6 · predict-contract §8.3 · task-contract §6.3 · D2-19). 소유 개발2.

**돈은 Decimal 만**(G2-Q01 · gates/check_decimal.py 가 이 파일도 본다): float 리터럴 · float() · round() · math 0,
반올림은 `quantize(..., rounding=ROUND_HALF_UP)` 만. 요청 숫자는 `jsonout.loads`(parse_float=Decimal)로 읽어 float 를 거치지 않고,
응답 금액은 원 단위 정수 **문자열**이다. 회귀 예측(작업시간)은 `uses` 과제의 표준 predict(18키 · mlp_prediction 1행)로 하고
그 `prediction_id` 를 근거로 남긴다 — 모델 입력 경계의 수치 변환은 `validate.ml_inputs`(이 파일 밖)에서만.

흐름: 초안(draft, revision 1) → 사람 수정(revisions — overrides 누적) → 확정 요청(confirm → pending_confirm + 승인 kind=quote)
→ B13 decide(approver 이상, D2-04) → confirmed(새 행 — mlp_quote 는 추가만). 확정 · 대기 중 수정은 409 quote_locked.
확정 금액은 그 행의 스냅숏(입력 · 단가 · 예측 ID · 모델 버전 · 구성 금액)이라 모델 · 단가가 바뀌어도 그대로다.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import sys
from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .. import approval as approval_mod
from .. import audit
from ..db.conn import connect
from . import documents
from .errors import InvalidInput, MissingRequired, NotFound, ServeError
from .ids import new_id
from .jsonout import dumps
from .validate import as_defs, check_missing, check_rules, ml_inputs, validate_bounds, validate_format

KST = timezone(timedelta(hours=9))
ONE = Decimal(1)
QUOTE_ID = re.compile(r"^qte_[0-9A-Z]{26}$")
BODY_KEYS = {"doc_id", "inputs", "lines", "reviewed", "review_note"}
CONFIRM_KEYS = {"reviewed", "review_note"}
NOTE_MAX = 500
LINES_MAX = 200
CSV_DANGER = ("=", "+", "-", "@", "\t", "\r")


class QuoteLocked(ServeError):
    status, code, default_message = 409, "quote_locked", "확정되었거나 확정 대기 중인 견적은 고칠 수 없습니다"


# ── 금액 ─────────────────────────────────────────────────────────────────────────────────
def won(x: Decimal) -> str:
    """원 단위 정수 Decimal → 10진 문자열. 정수가 아니면 견적식 결함(500 — 지어내지 않는다)."""
    if not isinstance(x, Decimal) or not x.is_finite():
        raise TypeError(f"금액이 Decimal 이 아닙니다 ({type(x).__name__})")
    if x != x.to_integral_value():
        raise ValueError("금액이 원 단위 정수가 아닙니다 — 견적식이 quantize(Decimal(1), ROUND_HALF_UP) 해야 합니다")
    return format(x.quantize(ONE, rounding=ROUND_HALF_UP), "f")


def dec_text(x: Any) -> str:
    """예측값 · 단가 등 10진 문자열(지수 표기 없음)."""
    return format(x if isinstance(x, Decimal) else Decimal(str(x)), "f")


def safe_cell(v: Any) -> str:
    """CSV 수식 주입 방지 — `= + - @ \\t \\r` 로 시작하면 앞에 `'` (source_inventory §10.1 E11)."""
    s = "" if v is None else v if isinstance(v, str) else dumps(v) if isinstance(v, (dict, list)) else str(v)
    return "'" + s if s.startswith(CSV_DANGER) else s


# ── 플러그인 ──────────────────────────────────────────────────────────────────────────────
_FORMULAS: dict[tuple[str, str], Any] = {}


def load_formula(pack_path: Path, module: str) -> Any:
    path = (Path(pack_path) / module).resolve()
    if not path.is_file() or Path(pack_path).resolve() not in path.parents:
        raise FileNotFoundError(f"견적식 모듈 없음: {module}")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    key = (str(path), sha)
    if key not in _FORMULAS:
        name = f"mlp_formula_{sha[:16]}_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "quote", None)):
            raise TypeError(f"견적식 {path.stem} 에 quote() 가 없습니다")
        _FORMULAS[key] = mod
    return _FORMULAS[key]


# ── 요청 검증 ─────────────────────────────────────────────────────────────────────────────
def _is_num(v: Any) -> bool:
    return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, Decimal) and v.is_finite())


def _check_value(v: Any, depth: int = 0) -> None:
    if depth > 4:
        raise InvalidInput("입력 값이 너무 깊습니다", {"field": None, "rule": "depth"})
    if isinstance(v, dict):
        for x in v.values():
            _check_value(x, depth + 1)
    elif isinstance(v, list):
        for x in v:
            _check_value(x, depth + 1)
    elif isinstance(v, Decimal) and not v.is_finite():
        raise InvalidInput("유한하지 않은 숫자입니다", {"field": None, "rule": "finite"})
    elif not (v is None or isinstance(v, (str, int, bool, Decimal))):
        raise InvalidInput("입력 값이 올바르지 않습니다", {"field": None, "rule": "type"})


def parse_body(body: Any, *, keys: set[str] = BODY_KEYS) -> dict:
    if not isinstance(body, dict):
        raise InvalidInput("요청 본문은 객체여야 합니다", {"field": None, "rule": "type"})
    unknown = [k for k in body if k not in keys]
    if unknown:
        shown = unknown[0] if isinstance(unknown[0], str) and re.match(r"^[a-z_]{1,32}$", unknown[0]) else None
        raise InvalidInput("모르는 키가 있습니다", {"field": shown, "rule": "extra_forbidden"})
    _check_value(body)
    if "reviewed" in body and not isinstance(body["reviewed"], bool):
        raise InvalidInput("reviewed 는 true/false 입니다", {"field": "reviewed", "rule": "bool"})
    note = body.get("review_note")
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
        raise InvalidInput(f"review_note 는 {NOTE_MAX}자 이하 문자열입니다", {"field": "review_note", "rule": "string"})
    if "doc_id" in body and body["doc_id"] is not None and not (isinstance(body["doc_id"], str)
                                                               and documents.DOC_ID.match(body["doc_id"])):
        raise InvalidInput("doc_id 형식이 아닙니다", {"field": "doc_id", "rule": "pattern"})
    if "inputs" in body and not isinstance(body["inputs"], dict):
        raise InvalidInput("inputs 는 객체입니다", {"field": "inputs", "rule": "type"})
    lines = body.get("lines")
    if lines is not None and (not isinstance(lines, list) or len(lines) > LINES_MAX
                              or not all(isinstance(x, dict) for x in lines)):
        raise InvalidInput(f"lines 는 객체 {LINES_MAX}개 이하 목록입니다", {"field": "lines", "rule": "type"})
    return body


class QuoteContext:
    """견적 과제 하나 — 과제 정의 · 의존 과제 · 견적식 · 단가."""

    def __init__(self, spec: Any, catalog: Any):
        documents.check_type(spec, "quote")
        self.spec, self.catalog = spec, catalog
        self.tenant_id = spec.tenant_id
        self.task = spec.task
        raw = self.task.raw
        self.formula = load_formula(catalog.merged.pack.path, str(raw["formula"]))
        # 단가: 이름 → Decimal, 단가표(rate_tables)는 이름 → {범주 값: Decimal} (D2-45 — 범주별 kg 단가 · 밀도 등)
        self.rates = {str(k): ({str(c): Decimal(str(x)) for c, x in v.items()} if isinstance(v, dict) else Decimal(str(v)))
                      for k, v in (raw.get("rates") or {}).items()}
        self.input_names = list(raw.get("inputs") or [])
        pack_feats = catalog.merged.pack.features
        cats = catalog.merged.tenant.config.get("categories") or {}
        from ..data.features import feature_defs
        names = [n for n in self.input_names if n in pack_feats]
        self.defs = tuple(feature_defs(pack_feats, names, cats))
        self.extra = [n for n in self.input_names if n not in pack_feats]      # 단가 · 수량 입력(features.yaml 밖)
        by_pack = {s.task.pack_id: s for s in (catalog.get(self.tenant_id, t) for t in catalog.ids())}
        self.uses = []
        for pack_id in raw.get("uses") or []:
            dep = by_pack.get(pack_id)
            if dep is None:
                catalog.require_servable(self.tenant_id, f"{self.tenant_id}.{pack_id.split('.', 1)[-1]}")
                raise NotFound("의존 과제가 켜져 있지 않습니다", {"rule": "uses", "field": None})
            self.uses.append(dep)
        conf = raw.get("confirm") or {}
        self.note_min = int(conf.get("review_note_min") or 5)
        self.approver_role = conf.get("approver_role") or raw["approver_role"]
        fx = raw.get("from_extract")
        self.from_extract = f"{self.tenant_id}.{fx.split('.', 1)[-1]}" if fx else None
        self.recognized = dict(raw.get("recognized") or {})

    # 입력 3단 검증(predict 와 같은 함수) + 견적 고유 입력
    def check_inputs(self, inputs: dict) -> dict:
        unknown = [k for k in inputs if k not in self.input_names]
        if unknown:
            shown = unknown[0] if re.match(r"^[a-z][a-z0-9_]{0,40}$", str(unknown[0])) else None
            raise InvalidInput("모르는 입력입니다", {"field": shown, "rule": "extra_forbidden"})
        feats = {k: v for k, v in inputs.items() if k not in self.extra}
        ml = ml_inputs(feats)
        validate_format(ml, self.defs)
        validate_bounds(ml, self.defs)
        check_rules(ml_inputs(inputs), self.task.raw.get("input_rules"))
        check_missing(ml, self.defs, 0)
        for n in self.extra:
            v = inputs.get(n)
            if v is None:
                raise MissingRequired("필수 입력이 없습니다", {"field": n, "rule": "required"})
            if not _is_num(v) or v < 0:
                raise InvalidInput("0 이상 숫자여야 합니다", {"field": n, "rule": "number"})
        return inputs

    def _recognized_values(self, doc_id: str | None) -> dict:
        if not doc_id:
            return {}
        res = documents.result_of(self.tenant_id, doc_id)
        if res is None or (self.from_extract and res["task_id"] != self.from_extract):
            raise NotFound("문서를 찾을 수 없습니다", {"field": "doc_id", "rule": "not_found"})
        out = {}
        for field, path in self.recognized.items():
            if field == "tolerance":
                continue
            cur: Any = res
            for part in str(path).split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            out[field] = cur
        return out

    def overrides(self, doc_id: str | None, inputs: dict, lines: list) -> list[dict]:
        """인식값과 확정 입력이 다른 칸마다 1항목 (허용차 recognized.tolerance — 10진 문자열, 기본 0)."""
        rec = self._recognized_values(doc_id)
        tol = Decimal(str(self.recognized.get("tolerance", "0")))
        out = []
        for field, rv in rec.items():
            confirmed = inputs.get(field) if field in inputs else (lines if isinstance(rv, list) else None)
            if isinstance(rv, list) or isinstance(confirmed, list):
                same = _norm(_strip(rv)) == _norm(_project(rv, confirmed))
            elif _is_numlike(rv) and _is_numlike(confirmed):
                same = abs(_d(rv) - _d(confirmed)) <= tol
            else:
                same = rv == confirmed
            if not same:
                out.append({"field": field, "recognized": _plain(rv), "confirmed": _plain(confirmed)})
        return out

    def compute(self, inputs: dict, lines: list, *, actor: str) -> dict:
        """예측(uses) → 견적식. → {lines, costs, total, predictions, model_versions, synthetic, notice}."""
        from .predict import PredictRequest, Predictor
        prepared = dict(inputs)
        if callable(getattr(self.formula, "prepare", None)):
            prepared.update(self.formula.prepare(dict(inputs), [dict(x) for x in lines]) or {})
        predicted: dict[str, Decimal] = {}
        preds, versions, synthetic = [], [], False
        predictor = Predictor(self.catalog)
        for dep in self.uses:
            feats = {n: prepared[n] for n in dep.features if n in prepared}
            out = predictor.predict(self.tenant_id, dep.task.id, PredictRequest(inputs=ml_inputs(feats)),
                                    caller=actor, channel="quote")   # 견적이 부른 예측 — mlp_prediction.channel 'quote' (D2-45)
            value = (out.get("prediction") or {}).get("value")
            if value is None:
                raise InvalidInput("작업시간 예측을 할 수 없는 입력입니다(학습 범위 밖 거부)",
                                   {"field": None, "rule": "prediction_rejected"})
            short = dep.task.id.split(".", 1)[-1]
            predicted[short] = Decimal(str(value))
            preds.append({"task": dep.task.id, "prediction_id": out["prediction_id"], "short": short,
                          "unit": (out.get("prediction") or {}).get("unit") or "", "status": out["status"]})
            versions.append({"task": dep.task.id, "version": out["model"]["version"], "synthetic": out["model"]["synthetic"]})
            synthetic = synthetic or bool(out["synthetic"])
        res = self.formula.quote(dict(prepared), [dict(x) for x in lines], dict(predicted), dict(self.rates))
        if not isinstance(res, dict) or "total" not in res:
            raise TypeError("견적식 결과에 total 이 없습니다")
        used = {**predicted, **(res.get("predicted") or {})}
        out_lines = []
        for ln in res.get("lines") or []:
            item = {k: v for k, v in dict(ln).items()}
            item["amount"] = won(item["amount"])
            out_lines.append(item)
        costs = {str(k): won(v) for k, v in (res.get("costs") or {}).items()}
        return {
            "lines": out_lines, "costs": costs, "total": won(res["total"]),
            "predictions": [{"task": p["task"], "prediction_id": p["prediction_id"], "value": dec_text(used[p["short"]]),
                             "unit": p["unit"]} for p in preds],
            "model_versions": versions, "synthetic": synthetic, "inputs": prepared,
        }


def _is_numlike(v: Any) -> bool:
    return _is_num(v) or (isinstance(v, (int,)) and not isinstance(v, bool)) or type(v).__name__ == "float"


def _d(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _plain(v: Any) -> Any:
    """overrides 에 남길 값 — 수치는 정확한 10진(Decimal), 목록 · 객체는 그대로."""
    if type(v).__name__ == "float":
        return Decimal(str(v))
    return v


PROJECT_SKIP = ("source", "evidence", "id")


def _project(recognized: Any, confirmed: Any) -> Any:
    """목록 칸(예 BOM) 비교 — 확정 행을 인식 행이 가진 키로만 줄인다(확정에만 있는 단가 · 인식에만 있는 출처 근거는 비교 밖).
    행 수 · 순서 · 공통 키 값이 같으면 수정 없음. 모양이 다르면 그대로 비교한다(다르다고 본다)."""
    if not (isinstance(recognized, list) and isinstance(confirmed, list) and len(recognized) == len(confirmed)
            and all(isinstance(x, dict) for x in recognized + confirmed)):
        return confirmed
    out = []
    for r, c in zip(recognized, confirmed):
        keys = [k for k in r if k not in PROJECT_SKIP]
        out.append({k: c.get(k) for k in keys})
    return out


def _strip(recognized: Any) -> Any:
    if isinstance(recognized, list) and all(isinstance(x, dict) for x in recognized):
        return [{k: v for k, v in r.items() if k not in PROJECT_SKIP} for r in recognized]
    return recognized


def _norm(v: Any) -> str:
    def conv(x):
        if isinstance(x, dict):
            return {k: conv(x[k]) for k in sorted(x)}
        if isinstance(x, list):
            return [conv(i) for i in x]
        if _is_numlike(x):
            return format(_d(x).normalize(), "f")
        return x
    return json.dumps(conv(v), ensure_ascii=False, sort_keys=True)


# ── 저장 · 조회 ───────────────────────────────────────────────────────────────────────────
COLS = ("quote_id, tenant_id, task_id, doc_id, lines::text AS lines_t, total, overrides::text AS overrides_t, "
        "model_versions::text AS model_versions_t, reviewed, reviewed_by, review_note, created_at, status, revision, "
        "supersedes, inputs::text AS inputs_t, costs::text AS costs_t, rates::text AS rates_t, "
        "prediction_ids::text AS prediction_ids_t, approval_id, confirmed_by, confirmed_at, created_by")


def _iso(ts) -> str | None:
    return ts.astimezone(KST).isoformat(timespec="seconds") if ts is not None else None


def _load(text: str | None, default: Any) -> Any:
    from .jsonout import loads
    return default if text is None else loads(text)


def view(row: dict, notice: str) -> dict:
    preds = _load(row["prediction_ids_t"], [])
    return {
        "quote_id": row["quote_id"], "task": row["task_id"], "status": row["status"], "revision": row["revision"],
        "supersedes": row["supersedes"], "doc_id": row["doc_id"], "inputs": _load(row["inputs_t"], {}),
        "lines": _load(row["lines_t"], []), "costs": _load(row["costs_t"], {}), "total": won(row["total"]),
        "currency": "KRW", "rates": _load(row["rates_t"], {}), "predictions": preds,
        "model_versions": _load(row["model_versions_t"], []), "overrides": _load(row["overrides_t"], []),
        "reviewed": row["reviewed"], "review_note": row["review_note"], "reviewed_by": row["reviewed_by"],
        "approval_id": row["approval_id"], "confirmed_by": row["confirmed_by"], "confirmed_at": _iso(row["confirmed_at"]),
        "synthetic": any(bool(v.get("synthetic")) for v in _load(row["model_versions_t"], [])),
        "notice": notice, "created_at": _iso(row["created_at"]),
    }


def _insert(c, row: dict) -> dict:
    c.execute(
        "INSERT INTO mlp_quote (quote_id, tenant_id, task_id, doc_id, lines, total, overrides, model_versions, reviewed, "
        "reviewed_by, review_note, status, revision, supersedes, inputs, costs, rates, prediction_ids, approval_id, "
        "confirmed_by, confirmed_at, created_by) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,"
        "%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s)",
        (row["quote_id"], row["tenant_id"], row["task_id"], row["doc_id"], dumps(row["lines"]), Decimal(row["total"]),
         dumps(row["overrides"]), dumps(row["model_versions"]), row["reviewed"], row["reviewed_by"], row["review_note"],
         row["status"], row["revision"], row["supersedes"], dumps(row["inputs"]), dumps(row["costs"]),
         dumps(row["rates"]), dumps(row["predictions"]), row["approval_id"], row["confirmed_by"],
         row.get("confirmed_at"), row["created_by"]))
    return latest_row(c, row["tenant_id"], row["task_id"], row["quote_id"])


def latest_row(c, tenant_id: str, task_id: str | None, quote_id: str) -> dict | None:
    """같은 계열(supersedes 사슬)의 최신 revision. 다른 회사 · 다른 과제 · 없음 → None."""
    if not QUOTE_ID.match(quote_id or ""):
        return None
    cond, params = ("AND task_id = %s", [task_id]) if task_id else ("", [])
    return c.execute(
        f"WITH RECURSIVE s AS (SELECT * FROM mlp_quote WHERE quote_id = %s AND tenant_id = %s {cond} "
        "UNION ALL SELECT q.* FROM mlp_quote q JOIN s ON q.supersedes = s.quote_id AND q.tenant_id = s.tenant_id) "
        f"SELECT {COLS} FROM s ORDER BY revision DESC LIMIT 1", [quote_id, tenant_id, *params]).fetchone()


def _lock(c, tenant_id: str, task_id: str) -> None:
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mlp_quote:{tenant_id}:{task_id}",))


def _as_row(qc: QuoteContext, *, quote_id, doc_id, computed, overrides, reviewed, reviewed_by, review_note, status,
            revision, supersedes, approval_id, confirmed_by, created_by, confirmed_at=None) -> dict:
    return {"quote_id": quote_id, "tenant_id": qc.tenant_id, "task_id": qc.task.id, "doc_id": doc_id,
            "lines": computed["lines"], "total": computed["total"], "overrides": overrides,
            "model_versions": computed["model_versions"], "reviewed": reviewed, "reviewed_by": reviewed_by,
            "review_note": review_note, "status": status, "revision": revision, "supersedes": supersedes,
            "inputs": computed["inputs"], "costs": computed["costs"], "rates": {k: ({c: dec_text(x) for c, x in v.items()} if isinstance(v, dict) else dec_text(v))
                                                  for k, v in qc.rates.items()},
            "predictions": computed["predictions"], "approval_id": approval_id, "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at, "created_by": created_by}


def _review_fields(body: dict, actor: str, note_min: int) -> tuple[bool, str | None, str | None]:
    reviewed = bool(body.get("reviewed", False))
    note = body.get("review_note")
    if reviewed and (not isinstance(note, str) or len(note.strip()) < note_min):
        raise MissingRequired(f"검토 메모(review_note)는 {note_min}자 이상입니다", {"field": "review_note", "rule": "min_length"})
    return reviewed, note, actor if reviewed else None


def create(qc: QuoteContext, body: dict, *, actor: str) -> dict:
    body = parse_body(body)
    inputs = qc.check_inputs(dict(body.get("inputs") or {}))
    lines = list(body.get("lines") or [])
    doc_id = body.get("doc_id")
    ov = qc.overrides(doc_id, inputs, lines)
    reviewed, note, by = _review_fields(body, actor, qc.note_min)
    computed = qc.compute(inputs, lines, actor=actor)
    row = _as_row(qc, quote_id=new_id("qte"), doc_id=doc_id, computed=computed, overrides=ov, reviewed=reviewed,
                  reviewed_by=by, review_note=note, status="draft", revision=1, supersedes=None, approval_id=None,
                  confirmed_by=None, created_by=actor)
    with connect() as c:
        saved = _insert(c, row)
    return view(saved, qc.spec.notice)


def revise(qc: QuoteContext, quote_id: str, body: dict, *, actor: str) -> dict:
    body = parse_body(body)
    inputs = qc.check_inputs(dict(body.get("inputs") or {}))
    lines = list(body.get("lines") or [])
    with connect() as c:
        prev = latest_row(c, qc.tenant_id, qc.task.id, quote_id)
    if prev is None:
        raise NotFound("견적을 찾을 수 없습니다")
    if prev["status"] != "draft":
        raise QuoteLocked(detail={"rule": prev["status"], "field": None})
    doc_id = body["doc_id"] if "doc_id" in body else prev["doc_id"]
    new_ov = qc.overrides(doc_id, inputs, lines)
    reviewed, note, by = _review_fields(body, actor, qc.note_min)
    computed = qc.compute(inputs, lines, actor=actor)
    with connect() as c:
        _lock(c, qc.tenant_id, qc.task.id)
        cur = latest_row(c, qc.tenant_id, qc.task.id, quote_id)
        if cur["quote_id"] != prev["quote_id"] or cur["status"] != "draft":     # 그 사이 다른 수정 · 확정 요청
            raise QuoteLocked("견적이 그 사이 바뀌었습니다 — 다시 불러오세요", {"rule": "concurrent", "field": None})
        history = _load(cur["overrides_t"], [])
        seen = {_norm(x) for x in history}
        merged = history + [x for x in new_ov if _norm(x) not in seen]          # 지우지 않고 누적
        row = _as_row(qc, quote_id=new_id("qte"), doc_id=doc_id, computed=computed, overrides=merged, reviewed=reviewed,
                      reviewed_by=by, review_note=note, status="draft", revision=cur["revision"] + 1,
                      supersedes=cur["quote_id"], approval_id=None, confirmed_by=None, created_by=actor)
        saved = _insert(c, row)
    return view(saved, qc.spec.notice)


def _copy(cur: dict, **change) -> dict:
    row = {"quote_id": new_id("qte"), "tenant_id": cur["tenant_id"], "task_id": cur["task_id"], "doc_id": cur["doc_id"],
           "lines": _load(cur["lines_t"], []), "total": won(cur["total"]), "overrides": _load(cur["overrides_t"], []),
           "model_versions": _load(cur["model_versions_t"], []), "reviewed": cur["reviewed"],
           "reviewed_by": cur["reviewed_by"], "review_note": cur["review_note"], "status": cur["status"],
           "revision": cur["revision"] + 1, "supersedes": cur["quote_id"], "inputs": _load(cur["inputs_t"], {}),
           "costs": _load(cur["costs_t"], {}), "rates": _load(cur["rates_t"], {}),
           "predictions": _load(cur["prediction_ids_t"], []), "approval_id": cur["approval_id"],
           "confirmed_by": cur["confirmed_by"], "confirmed_at": cur["confirmed_at"], "created_by": cur["created_by"]}
    row.update(change)
    return row


def request_confirm(qc: QuoteContext, quote_id: str, body: Any, *, actor: str, role: str | None,
                    request_id: str | None = None) -> dict:
    """확정 요청 — 검토 체크 · 메모 ≥ 5자 → pending_confirm 새 행 + 승인 요청(kind=quote, action=confirm) 한 트랜잭션."""
    body = parse_body(body if body is not None else {}, keys=CONFIRM_KEYS)
    if body.get("reviewed") is not True:
        raise MissingRequired("검토 확인(reviewed: true)이 필요합니다", {"field": "reviewed", "rule": "required"})
    note = body.get("review_note")
    if not isinstance(note, str) or len(note.strip()) < qc.note_min:
        raise MissingRequired(f"검토 메모(review_note)는 {qc.note_min}자 이상입니다", {"field": "review_note", "rule": "min_length"})
    with connect() as c:
        _lock(c, qc.tenant_id, qc.task.id)
        cur = latest_row(c, qc.tenant_id, qc.task.id, quote_id)
        if cur is None:
            raise NotFound("견적을 찾을 수 없습니다")
        if cur["status"] != "draft":
            raise QuoteLocked(detail={"rule": cur["status"], "field": None})
        approval_id = new_id("apr")
        row = _copy(cur, status="pending_confirm", reviewed=True, review_note=note, reviewed_by=actor,
                    approval_id=approval_id, created_by=actor)
        c.execute("INSERT INTO mlp_approval (approval_id, tenant_id, task_id, kind, ref_id, action, approver_role, state, "
                  "requested_by, evidence, expires_at) VALUES (%s,%s,%s,'quote',%s,'confirm',%s,'pending',%s,%s::jsonb, "
                  "now() + make_interval(secs => %s))",
                  (approval_id, qc.tenant_id, qc.task.id, row["quote_id"], qc.approver_role, actor,
                   dumps({"quote_id": row["quote_id"], "revision": row["revision"], "total": row["total"],
                          "costs": row["costs"], "model_versions": row["model_versions"],
                          "overrides": len(row["overrides"])}),
                   int(approval_mod.ttl_hours("quote") * 3600)))
        _insert(c, row)
        audit.write(tenant_id=qc.tenant_id, actor=actor, role=role, action="quote.confirm_requested",
                    target=f"{qc.task.id}@{row['quote_id']}", detail={"approval_id": approval_id, "total": row["total"]},
                    request_id=request_id, conn=c)
    return {"approval_id": approval_id, "state": "pending"}


def decide_in_tx(c, appr: dict, *, approve: bool, actor: str) -> None:
    """approval.decide() 가 같은 트랜잭션에서 부른다 — 승인: confirmed 새 행, 반려 · 만료: draft 새 행(다시 고칠 수 있다)."""
    _lock(c, appr["tenant_id"], appr["task_id"])
    cur = latest_row(c, appr["tenant_id"], appr["task_id"], appr["ref_id"])
    if cur is None or cur["quote_id"] != appr["ref_id"] or cur["status"] != "pending_confirm":
        raise approval_mod.AlreadyDecided("견적의 상태가 바뀌어 결정할 수 없습니다",
                                          {"approval_id": appr["approval_id"], "rule": "quote_not_pending"})
    if approve:
        row = _copy(cur, status="confirmed", confirmed_by=actor, created_by=actor)
        row["confirmed_at"] = c.execute("SELECT now() AS t").fetchone()["t"]
    else:
        row = _copy(cur, status="draft", reviewed=False, reviewed_by=None, approval_id=None, created_by=actor)
    _insert(c, row)


def get(tenant_id: str, task_id: str, quote_id: str, notice: str) -> dict:
    with connect() as c:
        row = latest_row(c, tenant_id, task_id, quote_id)
    if row is None:
        raise NotFound("견적을 찾을 수 없습니다")
    return view(row, notice)


def list_quotes(tenant_id: str, task_id: str, notice: str, *, search: str | None, limit: int, cursor: str | None,
                status: str | None = None) -> dict:
    where = ("FROM mlp_quote q WHERE q.tenant_id = %s AND q.task_id = %s AND NOT EXISTS "
             "(SELECT 1 FROM mlp_quote s WHERE s.tenant_id = q.tenant_id AND s.supersedes = q.quote_id)")
    params: list = [tenant_id, task_id]
    if status:
        where += " AND q.status = %s"
        params.append(status)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where += " AND (q.quote_id ILIKE %s OR coalesce(q.review_note, '') ILIKE %s OR coalesce(q.doc_id, '') ILIKE %s)"
        params += [like, like, like]
    count_params = list(params)
    page = where
    if cursor:
        page += " AND q.quote_id < %s"
        params.append(cursor)
    with connect() as c:
        rows = c.execute(f"SELECT {COLS.replace('quote_id,', 'q.quote_id,', 1)} {page} ORDER BY q.quote_id DESC LIMIT %s",
                         [*params, limit + 1]).fetchall()
        total = c.execute(f"SELECT count(*) AS n {where}", count_params).fetchone()["n"]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [view(r, notice) for r in rows], "next_cursor": rows[-1]["quote_id"] if more and rows else None,
            "total": total}


def to_csv(q: dict, columns: list[str] | None = None) -> bytes:
    """UTF-8 BOM CSV — 요약(항목 · 값) + 품목 행. 금액은 응답 문자열 그대로. 모든 칸에 수식 주입 방지."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    summary = [("quote_id", q["quote_id"]), ("task", q["task"]), ("status", q["status"]), ("revision", q["revision"]),
               ("doc_id", q["doc_id"]), *[(f"costs.{k}", v) for k, v in q["costs"].items()], ("total", q["total"]),
               ("currency", q["currency"]), *[(f"inputs.{k}", v) for k, v in q["inputs"].items()],
               *[(f"rates.{k}.{c}", x) if isinstance(v, dict) else (f"rates.{k}", v)
                 for k, v in q["rates"].items() for c, x in (v.items() if isinstance(v, dict) else [(None, v)])],
               *[(f"predictions.{p['task']}", p["value"]) for p in q["predictions"]],
               ("reviewed", q["reviewed"]), ("review_note", q["review_note"]), ("confirmed_by", q["confirmed_by"]),
               ("confirmed_at", q["confirmed_at"]), ("overrides", len(q["overrides"])), ("notice", q["notice"])]
    if columns:
        by = dict(summary)
        summary = [(k, by.get(k)) for k in columns]
    w.writerow(["항목", "값"])
    for k, v in summary:
        w.writerow([safe_cell(k), safe_cell(dumps(v) if isinstance(v, bool) else v)])
    if q["lines"]:
        keys = list(dict.fromkeys(k for ln in q["lines"] for k in ln))
        w.writerow([])
        w.writerow([safe_cell(k) for k in keys])
        for ln in q["lines"]:
            w.writerow([safe_cell(ln.get(k)) for k in keys])
    return ("﻿" + buf.getvalue()).encode("utf-8")
