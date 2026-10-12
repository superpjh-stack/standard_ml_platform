"""QA2 벤치 재측정 (G-M14) — gates/bench.py 의 측정 함수(bench_tenant)를 그대로 쓰되 포트 8204 · DB ml_qar2_db · 결과 파일 분리.

실행: MLP_TEST_DB_DSN="dbname=ml_qar2_db host=/tmp" OMP_NUM_THREADS=1 uv run python outputs/qa-r2/qa2/bench_qa2.py
한계: 로컬 uvicorn 1 프로세스(compose 768MB · CPU 1 제한 아래가 아님). outputs/bench-*.json 은 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
assert "ml_qar2_db" in (os.environ.get("MLP_TEST_DB_DSN") or "")
sys.path.insert(0, str(ROOT / "gates"))
import bench  # noqa: E402

bench._free_port = lambda: 8204      # QA2 전용 포트
os.environ["OMP_NUM_THREADS"] = "1"
tmp = Path(tempfile.mkdtemp(prefix="qa2-bench-"))
res = {"limits": bench.LIMITS, "mode": "local-uvicorn port 8204", "compose_limited": False,
       "tenants": [bench.bench_tenant(s, tmp) for s in bench.TENANTS]}
worst = {"p95_ms": max(v["p95_ms"] for t in res["tenants"] for v in t["per_task"].values()),
         "batch500_s": max(v["batch500_s"] for t in res["tenants"] for v in t["per_task"].values()),
         "startup_s": max(t["startup_s"] for t in res["tenants"]), "rss_mb": max(t["rss_mb"] for t in res["tenants"])}
res["worst"] = worst
res["pass"] = all(worst[k] <= bench.LIMITS[k] for k in worst)
Path(__file__).with_name("bench-qa2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(worst), "PASS" if res["pass"] else "FAIL")
