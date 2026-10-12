"""표준 예측 계약의 pydantic 모델 (contracts/predict-contract.md §1 · §2 · §5). 소유 개발2.

응답 18키는 **전부 필수**다(기본값 없음 — 키가 빠지면 검증 실패). 유형에 없는 필드는 null.
요청은 extra="forbid" · allow_inf_nan=False — 모르는 키 · NaN · Infinity 는 422 invalid_input.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

TaskTypeP1 = Literal["regression", "risk", "anomaly", "optimize"]
Status = Literal["ok", "watch", "review", "out_of_range", "rejected", "needs_approval"]
WarningCode = Literal["imputed", "out_of_range", "near_range", "threshold_exceeded", "watch_band", "anomaly_input",
                      "synthetic_model", "infeasible", "constraint_unmet", "extrapolation"]
InputValue = Union[StrictInt, StrictFloat, StrictStr, None]

_STRICT = ConfigDict(extra="forbid", allow_inf_nan=False, protected_namespaces=())


# ── 요청 ────────────────────────────────────────────────────────────────────
class _Req(BaseModel):
    """요청 본문 공통 — 문자열 · 키의 NUL(U+0000)은 형식 검사 전에 422 rule `nul`(DB 가 받지 않는다 — DEF-QA2R2-002 · D2-111).
    위치는 `validate.find_nul` 이 되풀이해도 되는 모양(이름 꼴 키 · 색인)으로 정해 ctx 로 넘긴다(safe_errors 가 쓴다)."""

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        from pydantic_core import PydanticCustomError

        from .validate import find_nul
        hit = find_nul(data)
        if hit is not None:
            raise PydanticCustomError("nul", "문자열에 NUL 문자(U+0000)가 있습니다", {"nul_field": hit[1] or ""})
        return data


class PredictBody(_Req):
    model_config = _STRICT
    inputs: dict[str, InputValue]
    entity_id: Optional[StrictStr] = Field(default=None, max_length=128)
    explain: StrictBool = False                                       # "yes" · 1 → 422 (DEF-QA2-007)
    model_version: Optional[StrictStr] = Field(default=None, pattern=r"^v[1-9][0-9]*$")


class BatchBody(BaseModel):
    """건은 여기서 검증하지 않는다 — 한 건의 형식 오류(NaN · 모르는 키 · 형)가 배치 전체를 422 로 만들지 않게
    라우터가 건마다 `PredictBody` 로 검증해 그 자리에 `{index, error}` 를 둔다(predict-contract §5 · DEF-QA2-003).
    배치 크기(0 · 501건 이상)만 전체 422."""
    model_config = _STRICT
    items: list[Any] = Field(min_length=1, max_length=500)


Number = Union[StrictInt, StrictFloat]


class OptimizeBody(_Req):
    model_config = _STRICT
    fixed: dict[str, InputValue]
    current: Optional[dict[str, InputValue]] = None
    params: Optional[dict[str, Number]] = None
    entity_id: Optional[StrictStr] = Field(default=None, max_length=128)
    request_approval: StrictBool = True        # false = 추천 기록만, 승인 요청 0 (D2-08 · D2-15 ⑥ — Agent 도구)


class ActualBody(_Req):
    model_config = _STRICT
    entity_id: StrictStr = Field(min_length=1, max_length=128)
    value: Union[StrictInt, StrictFloat]
    observed_at: datetime

    @model_validator(mode="after")
    def _tz(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at 은 시간대가 있어야 합니다")
        return self


class TrainBody(_Req):
    model_config = _STRICT
    source_role: Literal["demo", "eval", "train"] = "demo"
    seed: Optional[StrictInt] = None


class ReasonBody(_Req):
    model_config = _STRICT
    reason: Optional[StrictStr] = Field(default=None, max_length=2000)


class DecideBody(_Req):
    model_config = _STRICT
    decision: Literal["approve", "reject"]
    reason: Optional[StrictStr] = Field(default=None, max_length=2000)


# ── 응답 ────────────────────────────────────────────────────────────────────
class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Prediction(_Out):
    value: Optional[float]
    unit: str
    interval: Optional[list[float]] = Field(min_length=2, max_length=2)
    grade: Optional[Literal["low", "watch", "high"]]
    baseline: Optional[float]


class Contributor(_Out):
    field: str
    contribution: float


class Anomaly(_Out):
    score: Optional[float]
    flag: Optional[bool]
    threshold: Optional[float]
    contamination: Optional[float]
    contributors: list[Contributor] = Field(max_length=5)


class Constraint(_Out):
    name: str
    expr: str
    lhs: float
    rhs: float
    satisfied: bool
    slack: float


class Candidate(_Out):
    conditions: dict[str, Union[float, str]]
    predictions: dict[str, float]
    intervals: dict[str, Optional[list[float]]]
    constraints: list[Constraint]
    violation: float = Field(ge=0)
    objective_value: float


class Direction(_Out):
    name: str
    direction: Literal["minimize", "maximize"]


class Objective(_Out):
    name: str
    direction: Literal["minimize", "maximize"]
    tiebreak: list[Direction]


class Recommendation(_Out):
    rec_id: str = Field(pattern=r"^rec_")
    feasible: bool
    strategy: Literal["grid", "random"]
    n_candidates: int = Field(ge=1)
    n_feasible: int = Field(ge=0)
    in_train_range_rate: float = Field(ge=0, le=1)
    objective: Objective
    best: Candidate
    candidates: list[Candidate] = Field(min_length=1, max_length=5)
    current: Optional[Candidate]
    improvement: Optional[dict[str, float]]
    on_infeasible: Optional[Literal["least_violation"]]


class Warning(_Out):  # noqa: A001 — 계약 이름 그대로
    code: WarningCode
    field: Optional[str]
    message: str


class Explain(_Out):
    method: Literal["permutation_local", "linear_coef", "tree_path"]
    top: list[Contributor] = Field(max_length=5)


class ModelInfo(_Out):
    name: str
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    trained_at: str
    snapshot_id: str = Field(pattern=r"^snp_")
    synthetic: bool


class Use(_Out):
    task: str
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    synthetic: bool


_ALLOWED_STATUS = {
    "regression": {"ok", "watch", "review", "out_of_range", "rejected"},
    "risk": {"ok", "watch", "review", "out_of_range", "rejected"},
    "anomaly": {"ok", "review", "out_of_range", "rejected"},
    "optimize": {"needs_approval", "review"},
}


class PredictResponse(_Out):
    """18키. 필드 순서 = 계약 §2 표 순서."""
    task: str = Field(pattern=r"^[a-z][a-z0-9]{1,7}\.[a-z][a-z0-9_]*$")
    type: TaskTypeP1
    tenant: str = Field(pattern=r"^[a-z][a-z0-9]{1,7}$")
    entity_id: Optional[str]
    prediction: Optional[Prediction]
    probability: Optional[float] = Field(ge=0, le=1)
    anomaly: Optional[Anomaly]
    recommendation: Optional[Recommendation]
    status: Status
    warnings: list[Warning]
    imputed_fields: list[str]
    out_of_range_fields: list[str]
    explain: Optional[Explain]
    model: Optional[ModelInfo]
    uses: Optional[list[Use]]
    prediction_id: Optional[str] = Field(pattern=r"^prd_")
    synthetic: bool
    notice: str = Field(min_length=1)

    @model_validator(mode="after")
    def _by_type(self):
        """유형별 null 규칙 (predict-contract §4 — JSON Schema allOf 와 같다)."""
        t = self.type
        present = {k: getattr(self, k) is not None for k in
                   ("prediction", "probability", "anomaly", "recommendation", "model", "uses", "prediction_id")}
        need = {
            "regression": {"prediction": True, "probability": False, "anomaly": False, "recommendation": False,
                           "model": True, "uses": False, "prediction_id": True},
            "risk": {"prediction": True, "anomaly": False, "recommendation": False, "model": True, "uses": False,
                     "prediction_id": True},
            "anomaly": {"prediction": False, "probability": False, "anomaly": True, "recommendation": False,
                        "model": True, "uses": False, "prediction_id": True},
            "optimize": {"prediction": False, "probability": False, "anomaly": False, "recommendation": True,
                         "model": False, "uses": True, "prediction_id": False},
        }[t]
        for k, want in need.items():
            if present[k] != want:
                raise ValueError(f"{t}: {k} 는 {'있어야' if want else 'null 이어야'} 한다")
        if t == "risk" and self.prediction.unit != "probability":
            raise ValueError("risk: prediction.unit 은 probability")
        if t == "optimize" and (self.explain is not None or not self.uses):
            raise ValueError("optimize: explain null · uses ≥ 1")
        if self.status not in _ALLOWED_STATUS[t]:
            raise ValueError(f"{t}: 허용되지 않는 status")
        if len(set(self.imputed_fields)) != len(self.imputed_fields) or \
                len(set(self.out_of_range_fields)) != len(self.out_of_range_fields):
            raise ValueError("imputed_fields · out_of_range_fields 는 중복 없음")
        return self


RESPONSE_KEYS = tuple(PredictResponse.model_fields)


def to_contract(d: dict) -> dict:
    """dict → 검증 → 18키 dict(키 순서 고정). 계약 위반이면 ValidationError(500 — 숨기지 않는다)."""
    return PredictResponse.model_validate(d).model_dump(mode="json")


# ── 오류 위치 (입력값 · 요청 키 되풀이 0 — goal §2.3 · D-75 · DEF-QA3-002) ───────────────────────────
def _known_fields() -> frozenset[str]:
    names: set[str] = set()
    for obj in list(globals().values()):
        fields = getattr(obj, "model_fields", None)
        if isinstance(fields, dict) and getattr(obj, "__module__", None) == __name__:
            names |= set(fields)
    return frozenset(names)


KNOWN_FIELDS = _known_fields()


def safe_field(loc: Iterable[Any], *, skip: int = 0) -> str | None:
    """pydantic 오류 위치 → 되풀이해도 되는 위치. 요청 본문의 **키 이름도 요청자가 보낸 문자열**이다.
    계약 스키마에 선언된 필드 이름과 배열 색인만 남기고, 그 밖의 첫 조각(모르는 키 · dict 안 임의 키)은 `*` 로 바꾼 뒤
    끊는다(뒤따르는 형 이름 조각 int · str … 도 버린다). skip = 앞에서 버릴 조각 수(FastAPI 의 body · query)."""
    out: list[str] = []
    for p in list(loc)[skip:]:
        if isinstance(p, int):
            out.append(str(p))
        elif isinstance(p, str) and p in KNOWN_FIELDS:
            out.append(p)
        else:
            out.append("*")
            break
    return ".".join(out) or None


def safe_errors(errors: Iterable[dict], *, skip: int = 0, prefix: str | None = None, limit: int = 20) -> list[dict]:
    """[{field, rule}] — 중복 제거 · 최대 limit 개. rule 은 pydantic 오류 종류(코드가 정한 짧은 이름)."""
    seen, out = set(), []
    for e in errors:
        f = safe_field(e.get("loc", ()), skip=skip)
        if e.get("type") == "nul":                       # _Req 가 정한 안전한 위치(입력값 · 임의 키 되풀이 없음)
            f = ((e.get("ctx") or {}).get("nul_field") or None) if f is None else f
        if prefix:
            f = prefix if f is None else f"{prefix}.{f}"
        item = (f, str(e.get("type"))[:40])
        if item not in seen:
            seen.add(item)
            out.append({"field": item[0], "rule": item[1]})
        if len(out) >= limit:
            break
    return out
