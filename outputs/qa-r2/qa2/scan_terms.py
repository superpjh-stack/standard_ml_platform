"""QA2 독립 금지어 검사 (G-M01) — gates/check_core_terms.py 를 쓰지 않고 팩 · 등록부에서 직접 단어를 모은다.

실행: uv run python outputs/qa-r2/qa2/scan_terms.py
코어(src/mlcore · web/src)에서 팩 변수 · 과제 · 목표 · 비용식 · 결정 변수 · 파라미터 · 회사 코드 · 이름 · 별칭 · 원천 테이블 · 열 ·
범주값 · 설비 코드를 단어 경계로 찾는다. 팩(packs/)에서는 회사 쪽 단어를 찾는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
pack_terms, tenant_terms = set(), set()
for pack in ("press", "textile"):
    pd_ = ROOT / "packs" / pack
    feats = yaml.safe_load((pd_ / "features.yaml").read_text())
    pack_terms |= {k for k in feats if k != "std_name"}
    pack_terms.add(pack)
    for t in (pd_ / "tasks").glob("*.yaml"):
        d = yaml.safe_load(t.read_text())
        pack_terms.add(d["id"].split(".", 1)[1])
        pack_terms |= set((d.get("decision_vars") or {})) | set((d.get("params") or {})) | set((d.get("formulas") or {}))
        tgt = (d.get("target") or {}).get("name")
        if tgt:
            pack_terms.add(tgt)
        pack_terms |= {c["name"] for c in d.get("constraints") or []}
for code in ("ks", "sw"):
    d = yaml.safe_load((ROOT / "tenants" / f"{code}.yaml").read_text())
    tenant_terms |= {d["code"], d["name"], *(d.get("aliases") or [])}
    for vals in (d.get("categories") or {}).values():
        tenant_terms |= set(map(str, vals))
    for k in (d.get("feature_map") or {}):
        tenant_terms |= set(k.split("."))
    for s in (d.get("sources") or {}).values():
        for key in ("table", "view"):
            if s.get(key):
                tenant_terms.add(s[key])
        tenant_terms |= set(s.get("tables") or [])
    for v in ((d.get("compat") or {}).get("equipment_by_print_type") or {}).values():
        tenant_terms |= set(map(str, v))
    for v in ((d.get("compat") or {}).get("mes_prediction_views") or {}).values():
        tenant_terms |= set(v.split("."))
GENERIC = {"reserve", "max_cost"}   # 제약 이름 중 일반어 — 결과에 따로 표시
hits = {"core_pack": [], "core_tenant": [], "pack_tenant": []}


def scan(paths, terms, bucket):
    for p in paths:
        if p.suffix not in (".py", ".ts", ".tsx", ".js", ".css", ".html", ".yaml", ".json", ".sql") or "node_modules" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for t in terms:
            if len(t) < 2:
                continue
            pat = r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])"
            for mm in re.finditer(pat, text):
                line = text.count("\n", 0, mm.start()) + 1
                hits[bucket].append(f"{p.relative_to(ROOT)}:{line}:{t}")


core = [p for d in ("src/mlcore", "web/src") for p in (ROOT / d).rglob("*") if p.is_file()]
packs = [p for p in (ROOT / "packs").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
scan(core, pack_terms, "core_pack")
scan(core, tenant_terms, "core_tenant")
scan(packs, tenant_terms, "pack_tenant")
print(json.dumps({"n_pack_terms": len(pack_terms), "n_tenant_terms": len(tenant_terms), "n_core_files": len(core),
                  "n_pack_files": len(packs), "hits": {k: v[:40] for k, v in hits.items()},
                  "counts": {k: len(v) for k, v in hits.items()}}, ensure_ascii=False, indent=1))
