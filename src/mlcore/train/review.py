"""검토 대기열 — 학습 측 (task-contract §6.1 · predict-contract §8.1 · goal2 G2-R01 · D2-11).

대기열 항목의 재료는 둘뿐이다.
  - `test_split`: uses 과제 run 의 시험 구간 잔차. 학습기가 **final_eval 안에서** 계산해 보고서 `queue_residuals` 에
    남긴 것만 쓴다(여기서 시험 구간을 다시 보지 않는다 — 새 guard 접근 0).
  - `live_residual`: 실측(`mlp_actual`)이 붙은 운영 예측(`mlp_prediction`) — prediction_id 필수.
학습 · 검증 구간 잔차 · 전체 재적합 후 같은 데이터 채점(평창식, source_inventory P2)은 `QueueLeak` /
`InSampleEvaluation` 으로 거부하고 guard ledger 에 `queue_scoring` 으로 남긴다.
임계값: `abs_residual_ge: x` 는 그 값, `top_quantile: q` 는 **검증 구간 잔차**(학습 구간 모델의 표본 밖 잔차)의
1−q 분위(`quantile_from: valid` 고정). 시험 · 운영 · 표본 내 잔차로 분위를 재지 않는다.
이 모듈은 항목 초안(dict)만 만든다 — DB 쓰기(`mlp_review_item`) · item_id · 상태는 API(개발2) · 일정 작업(개발3) 몫이다.
과제 · 목표 이름은 인자로만 받는다(코어는 업종을 모른다).
"""

from __future__ import annotations

import hashlib
import math
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from .guard import AccessLedger, InSampleEvaluation, TestLeak

ORIGINS = ("test_split", "live_residual")
RULES = ("abs_residual_ge", "top_quantile")
QUANTILE_FROM = "valid"
DEFAULT_REASON = "|잔차| {abs_residual:.2f} ≥ {threshold}"
DEFAULT_MAX_ITEMS = 50
ITEM_KEYS = ("task", "entity_id", "prediction_id", "model_version", "predicted", "actual", "residual", "rule",
             "threshold", "reason", "origin")


class QueueLeak(TestLeak):
    """대기열을 학습 · 검증 구간 잔차나 허용되지 않은 출처로 만들려 했다 — 치명 결함(G2-R01)."""

    __test__ = False


def _record(ledger: AccessLedger | None, n: int, reason: str) -> None:
    if ledger is not None:
        ledger.record("queue_scoring", n, "mlcore/train/review.py", ok=False, reason=reason)


def parse_rule(rule: Mapping) -> tuple[str, float]:
    """`{abs_residual_ge: x}`(x ≥ 0) 또는 `{top_quantile: q}`(0 < q < 1) 정확히 하나."""
    keys = [k for k in (rule or {}) if k in RULES]
    extra = [k for k in (rule or {}) if k not in RULES]
    if len(keys) != 1 or extra:
        raise ValueError(f"대기열 규칙은 {RULES} 중 정확히 하나: {dict(rule or {})}")
    kind = keys[0]
    v = rule[kind]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ValueError(f"{kind} 값은 유한한 수: {v!r}")
    v = float(v)
    if kind == "abs_residual_ge" and v < 0:
        raise ValueError(f"abs_residual_ge 는 0 이상: {v}")
    if kind == "top_quantile" and not 0 < v < 1:
        raise ValueError(f"top_quantile 은 0 < q < 1: {v}")
    return kind, v


def _pred_sha(values: Sequence[float]) -> str:
    return hashlib.sha256(np.asarray(list(values), float).tobytes()).hexdigest()


def _verified_block(report: Mapping, ledger: AccessLedger | None) -> dict:
    """run 보고서의 `queue_residuals` 가 학습기 final_eval 1회에서 나온 시험 구간 잔차인지 증거로 확인한다.
    증거: ledger 에 ok 인 final_eval 정확히 1회 · 위반 0 / 블록 source=final_eval · origin=test_split /
    행 수 = 분할 시험 구간 크기 / 예측값 해시 = 보고서 `test_predictions_sha256`. 하나라도 어긋나면 표본 내(평창식)로 본다."""
    q = (report or {}).get("queue_residuals")
    if not q:
        _record(ledger, 0, "run 보고서에 queue_residuals 없음")
        raise InSampleEvaluation("run 보고서에 시험 구간 잔차(queue_residuals)가 없다 — 학습기 final_eval 결과만 쓴다")
    rows = list(q.get("test") or [])
    led = list(report.get("ledger") or [])
    finals = [e for e in led if e.get("purpose") == "final_eval" and e.get("ok")]
    bad = [e for e in led if not e.get("ok")]
    size = ((((report.get("split") or {}).get("boundaries") or {}).get("sizes")) or {}).get("test")
    problems = []
    if q.get("source") != "final_eval" or q.get("origin") != "test_split":
        problems.append(f"출처 {q.get('source')!r}/{q.get('origin')!r} — final_eval/test_split 아님")
    if len(finals) != 1 or bad:
        problems.append(f"ledger final_eval {len(finals)}회 · 위반 {len(bad)}")
    if size is None or len(rows) != int(size):
        problems.append(f"잔차 {len(rows)}행 ≠ 시험 구간 {size}행")
    if _pred_sha([r["predicted"] for r in rows]) != report.get("test_predictions_sha256"):
        problems.append("예측값 해시가 시험 1회 평가와 다르다")
    va = q.get("valid_abs")
    if va is None or q.get("valid_rows") != len(va) or q.get("valid_sha256") != _pred_sha(va):
        problems.append("검증 잔차 증거(valid_rows · valid_sha256)가 맞지 않다")
    if problems:
        _record(ledger, len(rows), "; ".join(problems))
        raise InSampleEvaluation("대기열 재료가 시험 구간 1회 평가 결과가 아니다(표본 내 채점 거부): " + "; ".join(problems))
    return q


def threshold(rule: Mapping, report: Mapping | None = None, *, quantile_from: str | None = QUANTILE_FROM,
              ledger: AccessLedger | None = None) -> dict:
    """규칙 → `{rule, value, from, n, q}`. top_quantile 은 run 보고서의 검증 구간 잔차 분위만."""
    kind, v = parse_rule(rule)
    if kind == "abs_residual_ge":
        return {"rule": kind, "value": v, "from": "rule", "n": None, "q": None}
    if quantile_from != QUANTILE_FROM:
        _record(ledger, 0, f"quantile_from={quantile_from!r}")
        raise QueueLeak(f"top_quantile 임계값은 검증 구간 잔차로만(quantile_from: valid) — {quantile_from!r} 거부")
    if report is None:
        raise ValueError("top_quantile 임계값에는 uses 과제 run 보고서(검증 구간 잔차)가 필요하다")
    q = _verified_block(report, ledger)
    va = np.asarray(q["valid_abs"], float)
    if not len(va):
        raise ValueError("검증 구간 잔차가 없다")
    return {"rule": kind, "value": float(np.quantile(va, 1 - v)), "from": QUANTILE_FROM, "n": int(len(va)), "q": v}


def build_items(rows: Iterable[Mapping], rule: Mapping, *, origin: str, task_id: str, model_version: str | None,
                origins: Sequence[str], thr: dict | None = None, max_items: int = DEFAULT_MAX_ITEMS,
                reason: str | None = None, ledger: AccessLedger | None = None) -> list[dict]:
    """잔차 행 → 항목 초안. 정렬 = |잔차| ↓(동률은 entity_id), 상한 max_items. origin 은 ORIGINS 중 과제가 켠 것만."""
    rows = list(rows)
    if origin not in ORIGINS:
        _record(ledger, len(rows), f"출처 {origin!r} — 학습 · 검증 · 표본 내 잔차 금지")
        raise QueueLeak(f"대기열 출처 {origin!r} 는 허용되지 않는다(test_split · live_residual 만)")
    if origin not in (origins or ()):
        _record(ledger, len(rows), f"출처 {origin!r} 가 과제 origins {list(origins or ())} 에 없다")
        raise QueueLeak(f"과제가 대기열 출처 {origin!r} 를 켜지 않았다")
    kind, _ = parse_rule(rule)
    thr = thr or threshold(rule, ledger=ledger)
    t = float(thr["value"])
    tpl = reason or DEFAULT_REASON
    out = []
    for r in rows:
        if r.get("actual") is None or r.get("predicted") is None:
            continue                                             # 실측 없는 예측은 대기열 대상이 아니다
        actual, pred = float(r["actual"]), float(r["predicted"])
        res = actual - pred
        if not math.isfinite(res) or abs(res) < t:
            continue
        pid = r.get("prediction_id")
        if origin == "live_residual" and not pid:
            raise ValueError("live_residual 항목에는 prediction_id 가 필요하다")
        out.append({"task": task_id, "entity_id": str(r["entity_id"]), "prediction_id": pid if origin == "live_residual" else None,
                    "model_version": r.get("model_version") or model_version, "predicted": pred, "actual": actual,
                    "residual": res, "rule": kind, "threshold": t,
                    "reason": tpl.format(abs_residual=abs(res), residual=res, threshold=round(t, 6), rule=kind),
                    "origin": origin})
    out.sort(key=lambda i: (-abs(i["residual"]), i["entity_id"]))
    return out[: max(0, int(max_items))]


def from_run(report: Mapping, rule: Mapping, *, task_id: str, model_version: str | None, origins: Sequence[str],
             quantile_from: str | None = QUANTILE_FROM, max_items: int = DEFAULT_MAX_ITEMS, reason: str | None = None,
             ledger: AccessLedger | None = None) -> list[dict]:
    """uses 과제 run 보고서 → test_split 항목. 보고서 증거가 맞지 않으면 InSampleEvaluation."""
    if "test_split" not in (origins or ()):
        _record(ledger, 0, "과제 origins 에 test_split 없음")
        raise QueueLeak("과제가 대기열 출처 test_split 을 켜지 않았다")
    q = _verified_block(report, ledger)
    thr = threshold(rule, report, quantile_from=quantile_from, ledger=ledger)
    return build_items(q["test"], rule, origin="test_split", task_id=task_id, model_version=model_version,
                       origins=origins, thr=thr, max_items=max_items, reason=reason, ledger=ledger)


def from_live(pairs: Iterable[Mapping], rule: Mapping, *, task_id: str, origins: Sequence[str],
              run_report: Mapping | None = None, quantile_from: str | None = QUANTILE_FROM,
              max_items: int = DEFAULT_MAX_ITEMS, reason: str | None = None,
              ledger: AccessLedger | None = None) -> list[dict]:
    """실측이 붙은 운영 예측 `[{prediction_id, entity_id, predicted, actual, model_version}]` → live_residual 항목.
    top_quantile 이면 임계값은 그 모델 run 보고서의 검증 잔차 분위(운영 묶음 자체로 분위를 재지 않는다)."""
    thr = threshold(rule, run_report, quantile_from=quantile_from, ledger=ledger)
    return build_items(pairs, rule, origin="live_residual", task_id=task_id, model_version=None, origins=origins,
                       thr=thr, max_items=max_items, reason=reason, ledger=ledger)


def residuals(predict: Callable, frame, *, fit_idx: Iterable[int], score_idx: Iterable[int],
              ledger: AccessLedger | None = None, target: str = "target") -> list[dict]:
    """모델로 frame 의 행을 채점해 잔차 행을 만든다 — **재적합 구간과 겹치는 행은 채점하지 않는다**(평창식 거부).
    시험 구간 인덱스는 이 함수로 얻을 수 없다(GuardedTest 만 가진다). 쓰임: 검증 잔차 · 이관 재현의 표본 밖 확인."""
    fit, score = {int(i) for i in fit_idx}, [int(i) for i in score_idx]
    both = fit.intersection(score)
    if both:
        _record(ledger, len(score), f"재적합 구간과 채점 구간이 {len(both)}행 겹친다(표본 내 채점)")
        raise InSampleEvaluation(f"재적합 구간과 채점 구간이 {len(both)}행 겹친다 — 전체 재적합 후 같은 데이터 채점 금지")
    sub = frame.iloc[score]
    pred = np.asarray(predict(sub), float)
    act = sub[target].to_numpy(dtype=float)
    return [{"entity_id": str(e), "actual": float(a), "predicted": float(p), "residual": float(a - p)}
            for e, a, p in zip(sub["entity_id"], act, pred)]


def live_pairs(conn, tenant_id: str, uses_task_id: str, *, version: str | None = None, since=None) -> list[dict]:
    """운영 예측 + 실측 짝 (DB 읽기만). 예측마다 같은 entity 의 가장 최근 실측 1건. entity_id 없는 예측은 짝이 없다."""
    sql = ("SELECT p.prediction_id, p.entity_id, p.version AS model_version, "
           "(p.outputs->'prediction'->>'value')::float AS predicted, a.value AS actual "
           "FROM mlp_prediction p JOIN LATERAL (SELECT value FROM mlp_actual a WHERE a.tenant_id=p.tenant_id "
           "AND a.task_id=p.task_id AND a.entity_id=p.entity_id ORDER BY observed_at DESC LIMIT 1) a ON true "
           "WHERE p.tenant_id=%s AND p.task_id=%s AND p.entity_id IS NOT NULL")
    args: list = [tenant_id, uses_task_id]
    if version is not None:
        sql += " AND p.version=%s"
        args.append(version)
    if since is not None:
        sql += " AND p.ts >= %s"
        args.append(since)
    return [dict(r) for r in conn.execute(sql + " ORDER BY p.ts, p.prediction_id", args).fetchall()]
