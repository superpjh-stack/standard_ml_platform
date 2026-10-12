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


if __name__ == "__main__":
    raise SystemExit(show(run()))
