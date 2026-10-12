"""DEF-QA2R2-001 (#34 중대) — 추출 결과 상한은 **판정용 결과**만 잰다, 미리보기는 따로 줄인다 (D2-110).

#30 수정(D2-91)의 결과 상한 4 MiB 가 미리보기(원 · 호 1개당 49점 등 표시용 점)까지 재서, 원천 경동(`api/cad.py:54,87`
— 엔티티 20,000 상한만)이 분석하는 정상 도면(원 5,000개 · 181 KB)이 413 `result_bytes` 였다. 이제
  ① `max_result_bytes` 는 결과에서 `preview` 를 뺀 판정용 결과(regions · objects · bom_rows · counts …)만 잰다,
  ② 미리보기는 별도 상한 — 팩은 점 예산(params `preview_max_points`)으로 원 · 호 분할 수를 줄이고 넘는 경로를 생략 표시,
     코어는 `max_preview_bytes` 를 넘는 미리보기를 생략 표시로 바꾼다(413 아님),
  ③ 원천이 처리하는 범위의 최악 도면(원 · 호만 20,000)이 두 추출기 + 코어 상한 판정까지 ≤ 5 s · RSS ≤ 300 MB.
DoS 방어(#30)는 그대로 — `tests/test_extract_eto_scale.py` · `test_c2_dev2.py` 의 413 region_texts · items · time · result_bytes.
QA 재현: `outputs/qa2-r2/q3/server_extract_r2.py`(circles_5000 · circles_19000).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import _dev2 as h
from mlcore.registry import tenants
from mlcore.tasks.extract import SPEC_LIMITS, ExtractError, check_result, fit_preview, limits_for, load_extractor

pytestmark = [pytest.mark.gate("G2-E01")]
ROOT = Path(__file__).resolve().parents[1]
TIME_LIMIT_S = 5.0
RSS_LIMIT_MB = 300


def _dxf(ents) -> bytes:
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "4"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"),
             *ents, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode()


def _circle(cx, cy, r):
    return [(0, "CIRCLE"), (8, "C"), (10, str(cx)), (20, str(cy)), (30, "0"), (40, str(r))]


def _arc(cx, cy, r, a0, a1):
    return [(0, "ARC"), (8, "C"), (10, str(cx)), (20, str(cy)), (30, "0"), (40, str(r)), (50, str(a0)), (51, str(a1))]


def _rect(x0, y0, x1, y1, layer="TITLE"):
    out = [(0, "LWPOLYLINE"), (8, layer), (90, "4"), (70, "1")]
    for px, py in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        out += [(10, str(px)), (20, str(py))]
    return out


def _text(v, x, y):
    return [(0, "TEXT"), (8, "T"), (10, str(x)), (20, str(y)), (30, "0"), (40, "3"), (1, v)]


def qa_circles(nc: int) -> bytes:
    """QA r2 `server_extract_r2.py` 의 circles_<n> 그대로 — 원(구멍) nc 개 + 외곽 사각형 + 텍스트."""
    ents = [e for i in range(nc) for e in _circle((i % 150) * 10, (i // 150) * 10, 3)]
    return _dxf(ents + _rect(-50, -50, 3000, 3000) + _text("TITLE BLOCK", 0, 0))


@pytest.fixture(scope="module")
def kd_task():
    m = tenants.load_and_merge("kd")
    return m, m.tasks["kd.drawing_regions"].raw


# ── 코어: 판정용 결과만 · 미리보기 별도 상한 ───────────────────────────────────────────────────────
def test_result_cap_measures_judged_result_only():
    """미리보기가 4 MiB 를 넘어도 판정용 결과가 작으면 413 이 아니다. 판정용 결과가 넘으면 그대로 413 result_bytes."""
    lim = {**SPEC_LIMITS}
    big_preview = {"paths": [{"points": [[1.2345, 6.789]] * 49, "layer": "C"}] * 6000}
    assert len(json.dumps(big_preview)) > lim["max_result_bytes"]
    check_result({"regions": [], "objects": [], "bom_rows": [], "counts": {}, "preview": big_preview}, lim, "t")
    judged = {"regions": [{"id": f"R{i}", "label": "other", "bbox": [0, 0, 1, 1], "texts": ["x" * 2000] * 5}
                          for i in range(800)], "preview": {}}
    with pytest.raises(ExtractError) as e:
        check_result(judged, lim, "t")
    assert (e.value.code, e.value.rule) == ("document_too_large", "result_bytes")


def test_preview_over_its_own_cap_is_omitted_not_rejected():
    """미리보기 상한(`max_preview_bytes`, task-contract §4) 초과 → 미리보기만 생략 표시로 바뀐다(판정용 결과는 그대로)."""
    lim = {**SPEC_LIMITS}
    res = {"regions": [{"id": "R1"}], "objects": [], "bom_rows": [], "counts": {"other": 1},
           "preview": {"bbox": [0, 0, 1, 1], "paths": [{"points": [[1.2345, 6.789]] * 49}] * 8000, "texts": []}}
    out = fit_preview(res, lim)
    assert out["regions"] == res["regions"] and out["counts"] == res["counts"]
    p = out["preview"]
    assert p["omitted"] is True and p["reason"] == "preview_bytes" and p["max_bytes"] == lim["max_preview_bytes"]
    assert p["bbox"] == [0, 0, 1, 1] and "paths" not in p
    small = {"regions": [], "preview": {"paths": [{"points": [[0, 0], [1, 1]]}]}}
    assert fit_preview(small, lim) == small                                   # 상한 안은 그대로
    assert fit_preview({"regions": []}, lim) == {"regions": []}               # 미리보기 없는 추출기
    assert limits_for({"document": {"max_preview_bytes": 10 ** 12}})["max_preview_bytes"] == SPEC_LIMITS["max_preview_bytes"]


# ── 팩 eto: 점 예산 ──────────────────────────────────────────────────────────────────────────────
def test_cad_regions_preview_point_budget(kd_task):
    """원 · 호가 많으면 분할 수를 줄이고(최소 8분할), 그래도 넘으면 뒤 경로를 생략하고 표시한다. bbox 는 원천(48분할)과 같다."""
    m, task = kd_task
    spec = next(s for s in task["extractors"] if s["name"] == "cad_regions")
    mod = load_extractor(m.pack.path, spec)
    budget = int(spec["params"]["preview_max_points"])
    small = mod.extract(qa_circles(10), "x.dxf", unit="mm", limits=limits_for(task), context={"params": spec["params"]})
    assert all(len(p["points"]) == 49 for p in small["preview"]["paths"][:10]) and small["preview"]["reduced"] is None
    big = mod.extract(qa_circles(19_000), "x.dxf", unit="mm", limits=limits_for(task), context={"params": spec["params"]})
    pv = big["preview"]
    assert sum(len(p["points"]) for p in pv["paths"]) <= budget
    assert pv["reduced"]["arc_segments"] < 48 and pv["reduced"]["max_points"] == budget
    assert len(pv["paths"]) + pv["reduced"]["omitted_paths"] == 19_001
    assert pv["bbox"] == [-50.0, -50.0, 3000.0, 3000.0]


# ── API: QA 재현 — 상한 안 정상 도면은 201 ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def kd_api(tmp_path_factory):
    if not h.db_ok():
        pytest.skip("ml_test_db 없음 — make setup")
    m = h.make_tenant("kd", tmp_path_factory.mktemp("c2r2kd"))
    return m, h.keys(m), h.client(m)


@pytest.mark.parametrize("nc", [3_000, 5_000, 19_000])
def test_many_circles_drawing_201(kd_api, nc):
    """QA circles_5000(181 KB) · circles_19000(694 KB) 이 413 result_bytes 였다 — 원천처럼 201 (문서 행 1)."""
    m, k, tc = kd_api
    code = m.tenant.code
    before = h.count("SELECT count(*) AS n FROM mlp_document WHERE tenant_id = %s", (code,))
    r = tc.post(f"/api/v1/tenants/{code}/tasks/{code}.drawing_regions/documents", headers=h.hdr(k["operator"]),
                files={"file": (f"circles_{nc}.dxf", qa_circles(nc), "application/dxf")})
    assert r.status_code == 201, r.text[:500]
    body = r.json()
    assert body["entity_count"] == nc + 2 and body["labels"] == "none" and body["metrics"] is None
    assert h.count("SELECT count(*) AS n FROM mlp_document WHERE tenant_id = %s", (code,)) == before + 1


# ── 최악 도면(원 · 호만 20,000) 시간 · RSS ──────────────────────────────────────────────────────────
SCRIPT = textwrap.dedent("""
    import json, resource, sys, time
    sys.path.insert(0, {tests!r})
    from test_c2r2_extract_preview import _dxf, _circle, _arc
    from mlcore.registry import tenants
    from mlcore.tasks.extract import ExtractError, check_result, fit_preview, limits_for, load_extractor, merge_results
    n = int(sys.argv[1])
    ents = []
    for i in range(n):                    # 원 · 호만(반씩) — 원천 경동 엔티티 상한 20,000 안의 최악 미리보기 꼴
        x, y = (i % 150) * 10, (i // 150) * 10
        ents += _circle(x, y, 3) if i % 2 else _arc(x, y, 3, 10, 300)
    raw = _dxf(ents)
    m = tenants.load_and_merge("kd")
    task = m.tasks["kd.drawing_regions"].raw
    limits = limits_for(task)
    t0 = time.perf_counter()
    out = {{"entities": n}}
    try:
        parts = []                        # 코어 자식 프로세스(_child)와 같은 순서: 추출 → 미리보기 상한 → 결과 상한
        for spec in task["extractors"]:
            mod = load_extractor(m.pack.path, spec)
            ctx = {{"categories": m.tenant.config.get("categories") or {{}}, "params": dict(spec.get("params") or {{}})}}
            res = fit_preview(mod.extract(raw, "x.dxf", unit="mm", limits=limits, context=ctx), limits)
            check_result(res, limits, mod.NAME)
            parts.append((mod, res))
        merged = merge_results(parts)
        check_result(merged, limits, "merged")
        pv = parts[0][1]["preview"]
        out.update(ok=True, preview_points=sum(len(p["points"]) for p in pv.get("paths", [])),
                   preview_kb=len(json.dumps(pv)) / 1024, reduced=pv.get("reduced"))
    except ExtractError as e:
        out.update(ok=False, code=e.code, rule=e.rule)
    out["sec"] = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out["rss_mb"] = rss / 2**20 if sys.platform == "darwin" else rss / 2**10
    print(json.dumps(out))
""")


def test_worst_circles_arcs_at_entity_limit_fast_and_small():
    """원 · 호만 20,000 엔티티 — 201 경로(추출 2 + 미리보기 · 결과 상한) ≤ 5 s · RSS ≤ 300 MB, 미리보기 ≤ 미리보기 상한."""
    r = subprocess.run([sys.executable, "-c", SCRIPT.format(tests=str(ROOT / "tests")), "20000"],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"], out
    assert out["preview_kb"] * 1024 <= SPEC_LIMITS["max_preview_bytes"] and out["reduced"], out
    assert out["sec"] <= TIME_LIMIT_S and out["rss_mb"] <= RSS_LIMIT_MB, out
