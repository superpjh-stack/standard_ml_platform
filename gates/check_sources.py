"""G-S05 — 읽기 전용 소스. 어댑터 5(synthetic · csv · gateway · dataplatform · mes)가 DataSource 를 따르고,
쓰기 SQL · 비 GET HTTP · 쓰기 모드 파일 열기 0. fixture 원천 DB 행 수 diff 0 · source_disconnected 봉투는
tests/test_source_contract.py 가 본다."""
import re

from gatelib import ROOT, Line, pytest_gate, read, rel, show

KINDS = ("synthetic", "csv", "gateway", "dataplatform", "mes")
WRITE_SQL = re.compile(r"(?i)[\"']\s*(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE|DROP\s|ALTER\s|CREATE\s|GRANT\s|COPY\s+\w+\s+FROM)")
NON_GET = re.compile(r"\.(post|put|patch|delete)\s*\(|method\s*=\s*[\"'](POST|PUT|PATCH|DELETE)")
WRITE_OPEN = re.compile(r"open\([^)]*[\"'][wax]\+?b?[\"']|\.to_(csv|parquet|sql)\(|\.write_(text|bytes)\(")


def run() -> list[Line]:
    d = ROOT / "src" / "mlcore" / "data" / "sources"
    present = [k for k in KINDS if (d / f"{k}.py").is_file()]
    problems = []
    for p in d.glob("*.py") if d.is_dir() else []:
        txt = read(p)
        for label, pat in (("쓰기 SQL", WRITE_SQL), ("비 GET HTTP", NON_GET), ("쓰기 파일", WRITE_OPEN)):
            if pat.search(txt):
                problems.append(f"{rel(p)}: {label}")
        if p.stem in KINDS and not re.search(r"def probe\(", txt) or (p.stem in KINDS and not re.search(r"def read\(", txt)):
            problems.append(f"{rel(p)}: probe/read 없음")
    t = pytest_gate("G-S05", "읽기 전용 소스", "tests/test_source_contract.py")
    msg = f"어댑터 {len(present)}/5" + (f" (없음 {[k for k in KINDS if k not in present]})" if len(present) < 5 else "")
    msg += f" · 정적 위반 {len(problems)}" + (f" ({'; '.join(problems[:3])})" if problems else "") + f" · {t.measured}"
    ok = len(present) == 5 and not problems and t.status == "PASS"
    return [Line("G-S05", "읽기 전용 소스", "PASS" if ok else "FAIL", msg)]


if __name__ == "__main__":
    raise SystemExit(show(run()))
