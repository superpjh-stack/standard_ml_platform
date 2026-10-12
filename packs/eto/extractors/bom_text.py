"""규칙 추출기 — BOM 텍스트 전개 (task-contract §6.2 · source_inventory §11.5 KD-X2).

원천 `api/cad.py:105-116` 을 **읽어** 이관했다(실행하지 않는다). `bom_table` 영역(cad_regions 규칙 그대로)의 텍스트를
`|` 로 나눠 정확히 4칸 `품명 | 재질 | 수량 | 개당중량kg` 인 것만 행으로 만든다:
  재질 = 대문자 + 회사 별칭 통합(`material_aliases`) · 재질 ∈ 회사 재질 목록 · 수량 정수 1~1,000 · 개당중량 유한 0.01~10,000.
머리 행 · 다른 형식은 버린다(지어내지 않는다). 행 키는 predict-contract §8.2 `bom_rows[]`: name(80자) · material · quantity · mass_kg · source.

재질 목록 · 별칭은 회사 값이다(팩에 두지 않는다). 코어가 `context={"categories": …, "material_aliases": …}` 를 넘기면
그것으로 거르고, 넘기지 않으면 재질 검사를 하지 않고 경고로 알린다(개발2 에 요청 — progress-dev3.md).
재질 범주 이름은 과제 `drawing_regions` 가 아니라 팩 변수 `main_material` 의 회사 값 목록이다.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

NAME = "bom_text"
VERSION = "1.0.0"
KIND = "rule"

MATERIAL_CATEGORY = "main_material"      # features.yaml — 회사 categories 의 재질 목록 키
NAME_MAX = 80
QTY_RANGE = (1, 1000)
MASS_RANGE = (.01, 10000)
WARN_FORMAT = ("BOM 자동 전개는 '품명 | 재질 | 수량 | 개당중량kg' 텍스트 형식만 지원합니다. "
               "일반 표의 셀 연결·치수·중량 자동 추론은 지원하지 않습니다.")
WARN_NO_MATERIALS = "회사 재질 목록을 받지 못해 재질 검사를 하지 않았습니다 — 확정 전에 재질을 확인하세요."


def _regions_module():
    """같은 팩의 cad_regions.py (코어 로더가 파일 경로로 읽으므로 상대 import 대신 경로로)."""
    path = Path(__file__).with_name("cad_regions.py")
    name = f"mlp_eto_cad_regions_{abs(hash(str(path.resolve())))}"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def rows_from(regions: list[dict], *, materials: list[str] | None = None,
              aliases: dict[str, str] | None = None) -> list[dict]:
    """bom_table 영역 텍스트 → BOM 행 (원천 :105-116)."""
    table = {str(k).upper(): str(v) for k, v in (aliases or {}).items()}
    allowed = set(materials) if materials else None
    rows = []
    for reg in regions:
        if reg["label"] != "bom_table":
            continue
        for text in reg["texts"]:
            parts = [p.strip() for p in text.split("|")]
            if len(parts) != 4:
                continue
            name, mat, qty, mass = parts
            mat = table.get(mat.upper(), mat.upper())
            try:
                qty_f = float(qty)
                kg = float(mass)
            except ValueError:
                continue
            if (allowed is None or mat in allowed) and qty_f.is_integer() and QTY_RANGE[0] <= qty_f <= QTY_RANGE[1] \
                    and math.isfinite(kg) and MASS_RANGE[0] <= kg <= MASS_RANGE[1]:
                rows.append({"name": name[:NAME_MAX], "material": mat, "quantity": int(qty_f), "mass_kg": kg,
                             "source": reg["id"]})
    return rows


def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None, context: dict | None = None,
            **_ignored) -> dict:
    """→ 추출 결과. 영역은 cad_regions 가 내므로 여기서는 bom_rows 만(합칠 때 영역이 두 번 들어가지 않게)."""
    ctx = context or {}
    reg = _regions_module()
    a = reg.analyze(raw, unit=unit, limits=limits, max_region_texts=reg._cap(ctx.get("params")))   # 같은 도면이면 cad_regions 분석 재사용
    materials = list(((ctx.get("categories") or {}).get(MATERIAL_CATEGORY)) or []) or None
    rows = rows_from(a["regions"], materials=materials, aliases=ctx.get("material_aliases"))
    warnings = [WARN_FORMAT] + ([] if materials else [WARN_NO_MATERIALS])
    return {"regions": [], "objects": [], "bom_rows": rows, "confidence": None, "counts": {"bom_rows": len(rows)},
            "dimensions": None, "unit": "mm", "entity_count": a["entity_count"], "warnings": warnings}
