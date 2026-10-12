"""새 회사 등록부 — `make tenant NEW=<code> PACK=<pack> [CSV=<path>] [CATEGORIES=<yaml>]` (G-M10 · D-51 · D2-100). 개발3.

    uv run python migration/make_tenant.py --new yn --pack _template --csv /tmp/yn/snapshot.csv
    uv run python migration/make_tenant.py --new qz --pack press --categories /tmp/qz/fill.yaml

회사 범주(`values_from: tenant`)가 있는 팩은 채움 파일(`--categories`, 형식은 `tenants.load_fill`)로 값을 준다.
값이 모자라 병합 규칙에 걸리면 `<code>.yaml.draft` 초안을 남기고 채울 칸을 알린다(지어내지 않는다).

`tenants/<code>.yaml` 하나만 만든다(등록부 루트는 `MLP_TENANTS_DIR`, 없으면 저장소 tenants/). 코드는 고치지 않는다.
CSV 는 복사 · 커밋하지 않는다 — 등록부의 `sources.eval.path` 가 가리키기만 한다(tenant-contract T4).
이어서: `make db-seed` → `make doctor TENANT=<code>` → `POST …/train {source_role: eval}` → 승인 → predict.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlcore.registry import tenants  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="새 회사 등록부 만들기")
    ap.add_argument("--new", required=True, help="회사 코드 (^[a-z][a-z0-9]{1,7}$)")
    ap.add_argument("--pack", default="_template")
    ap.add_argument("--csv", default=None, help="eval 소스 CSV 경로(복사하지 않는다)")
    ap.add_argument("--name", default=None, help="회사명(없으면 코드 + # 미확인)")
    ap.add_argument("--categories", default=None,
                    help="채움 파일(YAML): categories: {<변수>: [값, ...]} · 선택 material_aliases · tasks: {<과제>: {rates: ...}}")
    a = ap.parse_args(argv)
    try:
        fill = tenants.load_fill(a.categories) if a.categories else None
        path = tenants.scaffold(a.new, a.pack, csv=a.csv or None, name=a.name, fill=fill)
    except (tenants.RegistryRejected, tenants.TenantExists, OSError) as e:
        print(f"거부: {e}", file=sys.stderr)
        return 2
    m = tenants.load_and_merge(a.new)
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = path
    print(f"{shown}  pack={m.pack.code}  mode={m.tenant.config['mode']}  과제={list(m.tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
