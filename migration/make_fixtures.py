"""시험 fixture 생성기 — tests/fixtures/<tenant>/ (tests/fixtures/README.md · D-45).

원천 저장소를 읽거나 실행하지 않는다. 팩 합성 생성기(packs/<pack>/synth/)만 쓴다(원천 demo_data() 이관본).
fixture 는 기대값에 맞춰 손질하지 않는다 — 바꾸려면 이 스크립트를 고치고 다시 만든 뒤 decisions.md 에 사유를 남긴다.

    uv run python migration/make_fixtures.py --tenant ks --kind snapshot     # tests/fixtures/ks/snapshot.parquet
    uv run python migration/make_fixtures.py --tenant ks --kind csv          # tests/fixtures/ks/snapshot.csv (UTF-8 BOM)
    uv run python migration/make_fixtures.py --tenant all --kind all         # ks · sw 둘 다
    uv run python migration/make_fixtures.py --kind template_csv --out <dir> # 새 회사용 CSV(_template 변수) → <dir>/snapshot.csv

웨이브 A 로 미룬 것: drift.parquet · psi_hand.json · source_db.sql · compat_expected.json (각 README TODO).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlcore.registry import packs, tenants  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S+09:00"       # 원천 recorded_at 문자열 모양과 같다


def frame_for(tenant: str, rows: int | None = None, seed: int | None = None) -> pd.DataFrame:
    """회사 demo(synthetic) 소스의 합성 프레임 — 첫 켜진 과제의 생성기(팩 안 과제가 공유)."""
    merged = tenants.load_and_merge(tenant)
    first = next(iter(merged.tasks))
    return tenants.synth_call(merged, first).generate(rows, seed)


def template_frame(rows: int | None = None, seed: int | None = None) -> pd.DataFrame:
    pack = packs.load_pack("_template")
    spec = packs.synth_spec(pack)
    return packs.load_synth(pack)(rows or spec.rows, spec.seed if seed is None else seed)


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    out = frame.copy()
    out["ts"] = out["ts"].dt.strftime(TS_FORMAT)
    return out.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def write_parquet(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = to_csv_bytes(frame)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", default="all", help="ks | sw | all")
    ap.add_argument("--kind", default="all", choices=["snapshot", "csv", "all", "template_csv"])
    ap.add_argument("--rows", type=int, default=None, help="기본 pack.yaml synth.rows")
    ap.add_argument("--seed", type=int, default=None, help="기본 회사 sources.demo.seed")
    ap.add_argument("--out", type=Path, default=None, help="template_csv 출력 폴더")
    a = ap.parse_args(argv)
    if a.kind == "template_csv":
        if a.out is None:
            ap.error("--kind template_csv 는 --out 이 필요하다")
        digest = write_csv(template_frame(a.rows, a.seed), a.out / "snapshot.csv")
        print(f"{a.out / 'snapshot.csv'}  sha256={digest}")
        return 0
    codes = tenants.all_codes() if a.tenant == "all" else [a.tenant]
    for code in codes:
        frame = frame_for(code, a.rows, a.seed)
        d = FIXTURES / code
        if a.kind in ("snapshot", "all"):
            print(f"{(d / 'snapshot.parquet').relative_to(ROOT)}  rows={len(frame)}  sha256={write_parquet(frame, d / 'snapshot.parquet')}")
        if a.kind in ("csv", "all"):
            print(f"{(d / 'snapshot.csv').relative_to(ROOT)}  rows={len(frame)}  sha256={write_csv(frame, d / 'snapshot.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
