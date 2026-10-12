"""G-M04 — 예측 계약. contracts/predict-contract.md §5 JSON Schema 로
  A. 스키마 자체 시험: 예시 4(유형 4)가 통과하고, 키 누락 · 유형별 null 규칙 위반 · 상태 범위 밖 변형이 실패하는가.
  B. 켜진 과제 8 전부의 predict · predict:batch 실제 응답(fixture 학습 → 승인 → 예측)이 스키마와 일치하는가.
  C. 호환 라우터 옛 키 — tests/test_compat.py.
B 는 predict 구현 · production 모델이 있어야 한다 — 없으면 FAIL(대상 없음)."""
import copy
import json
import re

from gatelib import ROOT, Line, pytest_gate, read, show


def schema_and_examples():
    text = read(ROOT / "contracts" / "predict-contract.md")
    schema = json.loads(re.search(r"```json predict-response-schema\n(.*?)```", text, re.S).group(1))
    sec = text[text.index("## 6."): text.index("## 7.")]
    examples = [json.loads(x) for x in re.findall(r"```json\n(.*?)```", sec, re.S)]
    return schema, examples


def self_test() -> tuple[int, int, list[str]]:
    import jsonschema
    schema, examples = schema_and_examples()
    jsonschema.Draft202012Validator.check_schema(schema)
    v = jsonschema.Draft202012Validator(schema)
    cases, fails = 0, []
    types = sorted({e["type"] for e in examples})
    if types != ["anomaly", "optimize", "regression", "risk"]:
        fails.append(f"예시 유형 {types}")
    for e in examples:
        cases += 1
        errs = list(v.iter_errors(e))
        if errs:
            fails.append(f"예시 {e['task']} 불통과: {errs[0].message[:60]}")
        for key in schema["required"]:          # 키 누락 → 실패해야
            cases += 1
            bad = copy.deepcopy(e)
            bad.pop(key)
            if v.is_valid(bad):
                fails.append(f"{e['type']}: {key} 누락이 통과")
        for key, val in (("prediction", {"value": 1, "unit": "x", "interval": None, "grade": None, "baseline": None}),
                         ("anomaly", {"score": 0, "flag": False, "threshold": 0, "contamination": 0.1, "contributors": []}),
                         ("probability", 0.5), ("uses", []), ("status", "nonsense")):
            if e.get(key) is None or key == "status":
                cases += 1
                bad = copy.deepcopy(e)
                bad[key] = val
                if v.is_valid(bad) and not (e["type"] == "risk" and key == "probability"):
                    fails.append(f"{e['type']}: {key} null 규칙 위반이 통과")
    return cases - len(fails), cases, fails


def run() -> list[Line]:
    try:
        passed, total, fails = self_test()
    except Exception as e:  # noqa: BLE001
        return [Line("G-M04", "예측 계약", "FAIL", f"스키마 자체 시험 오류 {type(e).__name__}: {e}")]
    head = f"A 스키마 자체 시험 {passed}/{total}" + (f" ({'; '.join(fails[:2])})" if fails else "")
    try:
        from mlcore.serve import predict as _p  # noqa: F401
        has_predict = True
    except ImportError:
        has_predict = False
    if fails:
        return [Line("G-M04", "예측 계약", "FAIL", head)]
    if not has_predict:
        return [Line("G-M04", "예측 계약", "FAIL", head + " · B predict 미구현 — 켜진 과제 0/8 검사 · C " + pytest_gate("G-M04", "", "tests/test_compat.py").measured)]
    t = pytest_gate("G-M04", "예측 계약", "tests/test_predict_contract.py")
    c = pytest_gate("G-M04", "예측 계약", "tests/test_compat.py")
    ok = t.status == c.status == "PASS"
    return [Line("G-M04", "예측 계약", "PASS" if ok else "FAIL", head + f" · B {t.measured} · C {c.measured}")]


# ── 2차 — G2-T01 유형 3 계약 (goal2 §2) ──────────────────────────────────────────────────────────
PHASE2_TYPES = ("review_queue", "extract", "quote")
PHASE2_SCHEMAS = ("review-item-schema", "document-schema", "quote-schema")


def run_phase2() -> list[Line]:
    """유형 3 이 std · 계약에 있고(phase 1 로 켜짐), 응답 스키마 3 이 유효하고, 2차 유형 경로의 501 이 0 이며
    tests/test_types_phase2.py(입력 · 출력 · 상태 전이 · 오류 계약 시험)가 통과."""
    import jsonschema
    import yaml
    probs = []
    types = (yaml.safe_load(read(ROOT / "std" / "task_types.yaml")) or {}).get("types", {})
    off = [t for t in PHASE2_TYPES if (types.get(t) or {}).get("phase") != 1]
    if off:
        probs.append(f"std 유형 phase≠1 {off}")
    tc = read(ROOT / "contracts" / "task-contract.md")
    by_type = (yaml.safe_load(re.search(r"```yaml task-schema\n(.*?)```", tc, re.S).group(1)) or {}).get("by_type", {})
    if [t for t in PHASE2_TYPES if t not in by_type]:
        probs.append("task-schema by_type 에 2차 유형 없음")
    pc = read(ROOT / "contracts" / "predict-contract.md")
    for name in PHASE2_SCHEMAS:
        m = re.search(rf"```json {name}\n(.*?)```", pc, re.S)
        if not m:
            probs.append(f"{name} 없음")
            continue
        jsonschema.Draft202012Validator.check_schema(json.loads(m.group(1)))
    still_501 = [ln for ln in read(ROOT / "contracts" / "api-contract.md").splitlines()
                 if re.match(r"^\| B(09|10|11) [a-z]+ \| 2 \|", ln)]
    if still_501:
        probs.append(f"api-contract §1 의 B09~B11 이 아직 단계 2(501) {len(still_501)}행")
    t = pytest_gate("G2-T01", "유형 3 계약", "tests/test_types_phase2.py")
    if t.status != "PASS":
        probs.append(t.measured)
    if probs:
        return [Line("G2-T01", "유형 3 계약", "FAIL", "; ".join(probs[:4]))]
    return [Line("G2-T01", "유형 3 계약", "PASS", f"유형 3 phase 1 · 스키마 3 유효 · 501 0 · {t.measured}")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
