"""팩 eto 도면 영역 추출 — 상한 안 도면의 시간 · 메모리 (DEF-QA22-001 · #30 팩 부분 · D2-101).

1차 `regions_from` 은 키워드 텍스트마다 사각형 전부 · 영역마다 텍스트 전부를 다시 훑었고(영역 × 텍스트), `bom_text` 가 같은
분석을 한 번 더 했다 — 20,000 엔티티 도면 1건이 174 s · RSS 2.26 GB. 이제
  ① 결과는 1차 알고리즘(아래 `_naive_regions`, 원천 api/cad.py:50-123 그대로)과 같다 — 무작위 도면으로 대조,
  ② 엔티티 상한(20,000) 도면 최악 꼴 두 가지가 두 추출기 합쳐 ≤ 5 s · 자식 프로세스 최대 RSS ≤ 300 MB,
  ③ 영역 안 텍스트를 다 담으면 결과가 제곱으로 커지는 꼴(겹친 사각형)은 과제 params 상한에서 413 `document_too_large`.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mlcore.registry import tenants
from mlcore.tasks.extract import ExtractError, limits_for, load_extractor

pytestmark = [pytest.mark.gate("G2-E01")]
ROOT = Path(__file__).resolve().parents[1]
TIME_LIMIT_S = 5.0
RSS_LIMIT_MB = 300


def _dxf(entities: list[tuple[int, str]]) -> bytes:
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "4"), (0, "ENDSEC"),
             (0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF")]
    return "".join(f"{c}\n{v}\n" for c, v in pairs).encode("utf-8")


def _rect(x, y, w, hh):
    out = [(0, "LWPOLYLINE"), (8, "L"), (90, "4"), (70, "1")]
    for px, py in [(x, y), (x + w, y), (x + w, y + hh), (x, y + hh)]:
        out += [(10, repr(float(px))), (20, repr(float(py)))]
    return out


def _text(v, x, y):
    return [(0, "TEXT"), (8, "T"), (10, repr(float(x))), (20, repr(float(y))), (30, "0.0"), (40, "3.0"), (1, v)]


def _naive_regions(mod, texts, rects):
    """1차(원천 그대로) 알고리즘 — 대조 기준."""
    regions, seen = [], set()
    for text in texts:
        value = text["text"].upper()
        if not any(any(w in value for w in words) for words in mod.KEYWORDS.values()):
            continue
        x, y = text["point"]
        enclosing = [r for r in rects if r[0] <= x <= r[2] and r[1] <= y <= r[3] and r[2] > r[0] and r[3] > r[1]]
        if not enclosing:
            continue
        box = min(enclosing, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        if tuple(box) in seen:
            continue
        seen.add(tuple(box))
        inside = [t["text"] for t in texts if box[0] <= t["point"][0] <= box[2] and box[1] <= t["point"][1] <= box[3]]
        kinds = {k for k, words in mod.KEYWORDS.items() if any(any(w in t.upper() for w in words) for t in inside)}
        label = next(iter(kinds)) if len(kinds) == 1 else "other"
        regions.append({"id": f"REG-{len(regions) + 1:03}", "label": label, "bbox": box, "texts": inside,
                        "evidence": text["text"], "status": mod.REVIEW})
    return regions


@pytest.fixture(scope="module")
def kd():
    return tenants.load_and_merge("kd")


def _mods(kd):
    task = kd.tasks["kd.drawing_regions"].raw
    return task, [(spec, load_extractor(kd.pack.path, spec)) for spec in task["extractors"]]


@pytest.mark.parametrize("seed", range(6))
def test_regions_match_first_algorithm(kd, seed):
    """무작위 도면(겹친 · 같은 크기 · 경계 위 텍스트 · 퇴화 사각형 포함) — 영역 · 순서 · 텍스트가 1차와 같다."""
    _, mods = _mods(kd)
    mod = dict((s["name"], m) for s, m in mods)["cad_regions"]
    rnd = random.Random(seed)
    words = ["BOM", "DWG NO 1", "REVISION A", "부품표", "PIPE | SUS304 | 2 | 1.5", "note", "REV. B", "도면명"]
    ents = []
    for _ in range(120):
        x, y = rnd.choice([0, 5, 10, 20]) + rnd.randint(0, 30), rnd.randint(0, 40)
        ents += _rect(x, y, rnd.choice([0, 5, 10, 25, 60]), rnd.choice([0, 5, 10, 25, 60]))
    for _ in range(200):
        ents += _text(rnd.choice(words), rnd.choice([0, 5, 10, 15, 25, 30, 40, 70]) + rnd.random() * (seed % 2),
                      rnd.choice([0, 5, 10, 20, 40, 65]))
    g = mod.parse(_dxf(ents), unit="mm")
    assert mod.regions_from(g["texts"], g["rects"]) == _naive_regions(mod, g["texts"], g["rects"])


def test_bom_text_reuses_one_analysis(kd, monkeypatch):
    """같은 도면을 두 추출기가 받으면 분석(parse)은 한 번 — 결과는 따로 분석할 때와 같다."""
    task, mods = _mods(kd)
    reg = dict((s["name"], m) for s, m in mods)
    raw = _dxf(_rect(0, 0, 100, 50) + _text("BOM", 10, 10) + _text("PIPE | SUS304 | 2 | 1.5", 20, 20))
    limits = limits_for(task)
    base = reg["bom_text"].extract(raw, "x.dxf", unit="mm", limits=limits, context={})
    calls = []
    for m in {id(x): x for x in (reg["cad_regions"], reg["bom_text"]._regions_module())}.values():
        real = m.parse
        monkeypatch.setattr(m, "parse", lambda *a, _r=real, **k: calls.append(1) or _r(*a, **k))
    raw2 = raw + b"\n"                                                     # 새 도면(캐시 밖)
    reg["cad_regions"].extract(raw2, "x.dxf", unit="mm", limits=limits, context={})
    again = reg["bom_text"].extract(raw2, "x.dxf", unit="mm", limits=limits, context={})
    assert len(calls) == 1 and again["bom_rows"] == base["bom_rows"]


SCRIPT = textwrap.dedent("""
    import json, resource, sys, time
    sys.path.insert(0, {tests!r})
    from test_extract_eto_scale import _dxf, _rect, _text
    from mlcore.registry import tenants
    from mlcore.tasks.extract import ExtractError, limits_for, load_extractor, merge_results
    kind, n = sys.argv[1], int(sys.argv[2])
    ents = []
    if kind == "nested":      # 사각형 n 개가 겹겹이, 텍스트 n 개가 각 고리 안 — 영역 i 안 텍스트 i+1 개(1차: 제곱)
        for i in range(n): ents += _rect(-i - 1, -i - 1, 2 * i + 2, 2 * i + 2)
        for i in range(n): ents += _text("BOM", i + 0.5, 0)
    else:                     # 격자: 칸마다 사각형 · 키워드 텍스트 · BOM 행 텍스트 하나씩 — 영역 n 개 · BOM 행 n 개
        for i in range(n): ents += _rect((i % 100) * 10, (i // 100) * 10, 8, 8)
        for i in range(n): ents += _text("BOM", (i % 100) * 10 + 2, (i // 100) * 10 + 2)
        for i in range(n): ents += _text("PIPE | STS304 | 2 | 1.5", (i % 100) * 10 + 5, (i // 100) * 10 + 5)
    raw = _dxf(ents)
    m = tenants.load_and_merge("kd")
    task = m.tasks["kd.drawing_regions"].raw
    limits = limits_for(task)
    t0 = time.perf_counter()
    out = {{"entities": len([1 for c, _ in ents if c == 0])}}
    try:
        parts = []
        for spec in task["extractors"]:
            mod = load_extractor(m.pack.path, spec)
            ctx = {{"categories": m.tenant.config.get("categories") or {{}}, "params": dict(spec.get("params") or {{}})}}
            parts.append((mod, mod.extract(raw, "x.dxf", unit="mm", limits=limits, context=ctx)))
        merged = merge_results(parts)
        out.update(ok=True, regions=len(merged["regions"]), bom_rows=len(merged["bom_rows"]),
                   result_mb=len(json.dumps(merged, ensure_ascii=False, default=str)) / 2**20)
    except ExtractError as e:
        out.update(ok=False, code=e.code, rule=e.rule)
    out["sec"] = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out["rss_mb"] = rss / 2**20 if sys.platform == "darwin" else rss / 2**10
    print(json.dumps(out))
""")


def _run(kind: str, n: int) -> dict:
    r = subprocess.run([sys.executable, "-c", SCRIPT.format(tests=str(ROOT / "tests")), kind, str(n)],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_grid_drawing_at_entity_limit_fast_and_small():
    """≈20,000 엔티티(칸 6,666 × 사각형 · 키워드 · BOM 행) — 영역 6,666 · BOM 행 6,666 을 다 내면서 ≤ 5 s · RSS ≤ 300 MB."""
    out = _run("grid", 6_666)
    assert out["entities"] == 19_998 and out["ok"] and out["regions"] == 6_666 and out["bom_rows"] == 6_666, out
    assert out["sec"] <= TIME_LIMIT_S and out["rss_mb"] <= RSS_LIMIT_MB, out


def test_nested_drawing_at_entity_limit_rejected_fast():
    """겹친 사각형 20,000 엔티티 — 1차는 174 s · 2.26 GB · 500. 이제 영역 안 텍스트 상한(params)에서 413, ≤ 5 s · ≤ 300 MB."""
    out = _run("nested", 10_000)
    assert out["ok"] is False and out["code"] == "document_too_large" and out["rule"] == "region_texts", out
    assert out["sec"] <= TIME_LIMIT_S and out["rss_mb"] <= RSS_LIMIT_MB, out


def test_region_text_cap_comes_from_task_params(kd):
    """상한은 팩 YAML(params) 값이다(코드 상수 아님). params 를 주지 않으면 1차처럼 상한 없이 모두 낸다."""
    task, mods = _mods(kd)
    params = {s["name"]: s.get("params") or {} for s, _ in mods}
    assert all(isinstance(p.get("max_region_texts"), int) and p["max_region_texts"] > 0 for p in params.values())
    mod = dict((s["name"], m) for s, m in mods)["cad_regions"]
    ents = []
    for i in range(30):
        ents += _rect(-i - 1, -i - 1, 2 * i + 2, 2 * i + 2)
    for i in range(30):
        ents += _text("BOM", i + 0.5, 0)
    raw = _dxf(ents)
    full = mod.extract(raw, "x.dxf", unit="mm", limits=limits_for(task), context={})
    assert sum(len(r["texts"]) for r in full["regions"]) == 30 * 31 // 2
    with pytest.raises(ExtractError) as e:
        mod.extract(raw, "x.dxf", unit="mm", limits=limits_for(task), context={"params": {"max_region_texts": 100}})
    assert e.value.code == "document_too_large" and e.value.rule == "region_texts"
