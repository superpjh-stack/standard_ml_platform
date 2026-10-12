"""시험 fixture 생성기 — tests/fixtures/<tenant>/ (tests/fixtures/README.md · D-45).

원천 저장소를 읽거나 실행하지 않는다. 팩 합성 생성기(packs/<pack>/synth/)만 쓴다(원천 demo_data() 이관본).
fixture 는 기대값에 맞춰 손질하지 않는다 — 바꾸려면 이 스크립트를 고치고 다시 만든 뒤 decisions.md 에 사유를 남긴다.

    uv run python migration/make_fixtures.py --tenant ks --kind snapshot     # tests/fixtures/ks/snapshot.parquet
    uv run python migration/make_fixtures.py --tenant ks --kind csv          # tests/fixtures/ks/snapshot.csv (UTF-8 BOM)
    uv run python migration/make_fixtures.py --tenant all --kind all         # ks · sw 둘 다
    uv run python migration/make_fixtures.py --kind template_csv --out <dir> # 새 회사용 CSV(_template 변수) → <dir>/snapshot.csv
    uv run python migration/make_fixtures.py --tenant all --kind drift       # tests/fixtures/<t>/drift.parquet (운영 입력 7일 · 분포 이동)
    uv run python migration/make_fixtures.py --tenant all --kind psi_hand    # tests/fixtures/<t>/psi_hand.json (손 계산 기대값)

drift: 팩 생성기를 **다른 시드**(DRIFT_SEED)로 168행(7일 × 24h) 만든 뒤, 지정 변수에 학습 스냅숏 표준편차 × 배수를 더하고
features.yaml [min, max] 로 자른다. 목표 열은 뺀다(운영 입력). psi_hand: 감시 규칙(monitor/stats.py 머리말)을
**mlcore 를 쓰지 않는 순수 파이썬**으로 다시 계산한 값과, 손으로 셀 수 있는 작은 사례의 산식 · 값.
    uv run python migration/make_fixtures.py --tenant all --kind source_db   # tests/fixtures/<t>/source_db.sql (원천 DB 사본, 합성)

source_db: gateway · mes 어댑터 시험용 **원천 DB 사본**(값은 합성 snapshot 과 같은 행 — 실데이터 0). 테이블 = 등록부
`sources.actuals.tables` 중 `feature_map` · `target_map` 에 열이 있는 것, 열 = 원천 열 이름. 결합 키 `FX_KEY`(= entity_id) ·
시각 `FX_AT`(첫 테이블)은 사본 정의다(원천 결합 키 미확인 — D-32 · D-33). 스키마 이름은 넣지 않는다 — 읽는 쪽이
`SET search_path` 로 임시 스키마를 고른다. 대응이 없는 변수(등록부 `unmapped`)는 사본에도 없다.
웨이브 A 로 미룬 것: compat_expected.json (README TODO).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    merged = tenants.load_and_merge(tenant, tenants_base=tenants.TENANTS_DIR)
    first = next(iter(merged.tasks))
    return tenants.synth_call(merged, first).generate(rows, seed)


def template_frame(rows: int | None = None, seed: int | None = None) -> pd.DataFrame:
    pack = packs.load_pack("_template")
    spec = packs.synth_spec(pack)
    return packs.load_synth(pack)(rows or spec.rows, spec.seed if seed is None else seed)


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    """표기 규칙(D2-102): 실수는 반올림하지 않고 pandas 기본(최단 왕복 repr). CSV 어댑터의 `read_csv` 기본 파서가 1 ulp 급
    오차(상대 ≤ 1e-12)로 읽으므로 eval 스냅숏 해시는 demo 와 다르다 — `tests/test_fixture_csv_rule.py`."""
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


# ── 드리프트 · 손 계산 (G-M09) ──────────────────────────────────────────────
DRIFT_SEED = 20260901                     # 학습 스냅숏(시드 42)과 다른 시드 — 같은 분포의 새 운영 입력
DRIFT_ROWS = 168                          # 7일 × 24시간
DRIFT_START = "2026-09-01 00:00"          # 스냅숏(8월) 다음 — KST
DRIFT_SHIFT = {"ks": {"vibration": 1.5}, "sw": {"absorb_rate": 1.5}}   # 변수 = 학습 표준편차 배수


def drift_frame(tenant: str, shift: dict[str, float] | None = None, seed: int = DRIFT_SEED,
                rows: int = DRIFT_ROWS) -> pd.DataFrame:
    merged = tenants.load_and_merge(tenant, tenants_base=tenants.TENANTS_DIR)
    first = next(iter(merged.tasks))
    call = tenants.synth_call(merged, first)
    base = call.generate()                       # 학습 스냅숏과 같은 행(σ 기준)
    frame = call.generate(rows, seed)
    targets = {(t.raw.get("target") or {}).get("name") for t in merged.tasks.values()} - {None}
    frame = frame.drop(columns=[c for c in targets if c in frame.columns])
    for name, k in (DRIFT_SHIFT.get(tenant, {}) if shift is None else shift).items():
        f = merged.pack.features[name]
        sd = float(base[name].std(ddof=0))
        frame[name] = (frame[name] + float(k) * sd).clip(f["min"], f["max"])
    frame["ts"] = pd.date_range(DRIFT_START, periods=rows, freq="h", tz="Asia/Seoul")
    frame["entity_id"] = [f"DRIFT-{i + 1:04d}" for i in range(rows)]
    return frame


def _q(sorted_vals: list[float], p: float) -> float:
    """선형 보간 분위(numpy 기본과 같은 정의) — 순수 파이썬."""
    h = (len(sorted_vals) - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo])


def hand_psi(expected: list, actual: list, categorical: bool = False, bins: int = 10, eps: float = 1e-6) -> dict:
    e = [x for x in expected if x is not None and not (isinstance(x, float) and math.isnan(x))]
    a = [x for x in actual if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if categorical:
        cats = sorted({str(x) for x in e} | {str(x) for x in a})
        es = [sum(str(x) == c for x in e) / len(e) for c in cats]
        as_ = [sum(str(x) == c for x in a) / len(a) for c in cats]
        edges = cats
    else:
        se = sorted(float(x) for x in e)
        edges = sorted({_q(se, k / bins) for k in range(1, bins)})

        def shares(vals):
            counts = [0] * (len(edges) + 1)
            for v in vals:
                i = 0
                while i < len(edges) and float(v) > edges[i]:   # 값 == 경계면 아래 구간
                    i += 1
                counts[i] += 1
            return [c / len(vals) for c in counts]
        es, as_ = shares(e), shares(a)
    total = 0.0
    for x, y in zip(es, as_):
        x, y = max(x, eps), max(y, eps)
        total += (y - x) * math.log(y / x)
    return {"edges": edges, "e_shares": es, "a_shares": as_, "psi": total}


def psi_hand(tenant: str) -> dict:
    """손 계산 기대값. cases = 손으로 셀 수 있는 사례(산식 포함) · drift = drift.parquet 대 snapshot 의 PSI · 결측률."""
    cases = [
        {"name": "numeric_deciles", "categorical": False, "expected": list(range(1, 11)),
         "actual": [1, 1, 1, 1, 1, 6, 7, 8, 9, 10],
         "arithmetic": "경계 1.9, 2.8, …, 9.1 → e = 0.1 × 10 · a = [0.5, 0, 0, 0, 0, 0.1 × 5] → "
                       "0.4·ln(5) + 4·(1e-6 − 0.1)·ln(1e-6 / 0.1)"},
        {"name": "categorical", "categorical": True, "expected": ["A"] * 5 + ["B"] * 3 + ["C"] * 2,
         "actual": ["A"] * 2 + ["B"] * 3 + ["C"] * 5, "arithmetic": "(0.2 − 0.5)·ln(0.4) + (0.5 − 0.2)·ln(2.5) = 0.6·ln(2.5)"},
        {"name": "identical", "categorical": False, "expected": list(range(1, 21)), "actual": list(range(1, 21)),
         "arithmetic": "같은 분포 → 0"},
    ]
    for c in cases:
        c.update(hand_psi(c["expected"], c["actual"], c["categorical"]))
    checks = {
        "oor_rate": {"values": [1, 2, 5, 8, 9, None, 10, 3, 7, 2.5], "range": {"p1": 2, "p99": 8},
                     "rate": 3 / 9, "arithmetic": "결측 1 제외 9개 중 1 · 9 · 10 이 [2, 8] 밖 → 3/9"},
        "oor_rate_category": {"values": ["A", "B", "Z", None], "range": {"values": ["A", "B"]}, "rate": 1 / 3},
        "missing_rate": {"values": [1, None, 3, None, 5], "rate": 0.4},
    }
    merged = tenants.load_and_merge(tenant, tenants_base=tenants.TENANTS_DIR)
    snap = frame_for(tenant)
    drift = drift_frame(tenant)
    first = next(t for t in merged.tasks.values() if t.raw.get("features"))
    feats = list(first.raw["features"])
    dpsi = {f: hand_psi(snap[f].tolist(), drift[f].tolist(),
                        merged.pack.features[f].get("dtype") == "category")["psi"] for f in feats}
    miss = {f: {"expected": float(snap[f].isna().mean()), "actual": float(drift[f].isna().mean())} for f in feats}
    return {"rule": "monitor/stats.py 머리말 — 기대 10분위(선형 보간) 경계 · 구간 (a, b] · 0 비율 1e-6 바닥 · Σ (a − e)·ln(a/e)",
            "cases": cases, "checks": checks,
            "drift": {"seed": DRIFT_SEED, "rows": DRIFT_ROWS, "shift": DRIFT_SHIFT.get(tenant, {}),
                      "psi": dpsi, "missing": miss, "features": feats}}


# ── 원천 DB 사본 (G-S05 · D-W1-10) ─────────────────────────────────────────
FX_KEY, FX_AT = "FX_KEY", "FX_AT"


def _sql_lit(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return "NULL"
    if isinstance(v, pd.Timestamp):
        return "'" + v.isoformat() + "'"
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return "NULL" if isinstance(v, float) and math.isnan(v) else repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def source_db_tables(tenant: str) -> dict[str, pd.DataFrame]:
    merged = tenants.load_and_merge(tenant, tenants_base=tenants.TENANTS_DIR)
    cfg = merged.tenant.config
    cmap = {**(cfg.get("feature_map") or {}), **(cfg.get("target_map") or {})}
    frame = frame_for(tenant)
    out: dict[str, pd.DataFrame] = {}
    for table in (cfg.get("sources") or {}).get("actuals", {}).get("tables") or []:
        mine = {src.split(".", 1)[1]: dst for src, dst in cmap.items() if src.startswith(table + ".") and dst in frame.columns}
        if not mine:
            continue
        df = pd.DataFrame({FX_KEY: frame["entity_id"].astype(str)})
        if not out:
            df[FX_AT] = frame["ts"]
        for col, dst in mine.items():
            df[col] = frame[dst]
        out[table] = df
    return out


def source_db_sql(tenant: str) -> str:
    lines = [f"-- 원천 DB 사본 (합성 · 익명) — migration/make_fixtures.py --tenant {tenant} --kind source_db. 손질 금지.",
             "-- 스키마 이름 없음: 읽는 쪽이 SET search_path 로 임시 스키마를 고른다. 값은 tests/fixtures/<t>/snapshot.* 와 같은 행."]
    for table, df in source_db_tables(tenant).items():
        cols = []
        for c in df.columns:
            t = ("timestamptz" if pd.api.types.is_datetime64_any_dtype(df[c]) else
                 "double precision" if pd.api.types.is_float_dtype(df[c]) else
                 "bigint" if pd.api.types.is_integer_dtype(df[c]) else "text")
            cols.append(f'"{c}" {t}')
        lines.append(f'CREATE TABLE "{table}" ({", ".join(cols)});')
        head = f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in df.columns)}) VALUES'
        rows = [f"({', '.join(_sql_lit(v) for v in r)})" for r in df.itertuples(index=False)]
        for i in range(0, len(rows), 200):
            lines.append(head + "\n" + ",\n".join(rows[i:i + 200]) + ";")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", default="all", help="ks | sw | all")
    ap.add_argument("--kind", default="all", choices=["snapshot", "csv", "all", "template_csv", "drift", "psi_hand", "source_db"])
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
    codes = tenants.all_codes(tenants.TENANTS_DIR) if a.tenant == "all" else [a.tenant]
    for code in codes:
        d = FIXTURES / code
        if a.kind in ("drift", "all"):
            print(f"{(d / 'drift.parquet').relative_to(ROOT)}  rows={DRIFT_ROWS}  sha256={write_parquet(drift_frame(code), d / 'drift.parquet')}")
        if a.kind in ("psi_hand", "all"):
            data = json.dumps(psi_hand(code), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8") + b"\n"
            (d / "psi_hand.json").write_bytes(data)
            print(f"{(d / 'psi_hand.json').relative_to(ROOT)}  sha256={hashlib.sha256(data).hexdigest()}")
        if a.kind in ("source_db", "all"):
            data = source_db_sql(code).encode("utf-8")
            (d / "source_db.sql").write_bytes(data)
            print(f"{(d / 'source_db.sql').relative_to(ROOT)}  tables={list(source_db_tables(code))}  sha256={hashlib.sha256(data).hexdigest()}")
        if a.kind in ("drift", "psi_hand", "source_db"):
            continue
        frame = frame_for(code, a.rows, a.seed)
        d = FIXTURES / code
        if a.kind in ("snapshot", "all"):
            print(f"{(d / 'snapshot.parquet').relative_to(ROOT)}  rows={len(frame)}  sha256={write_parquet(frame, d / 'snapshot.parquet')}")
        if a.kind in ("csv", "all"):
            print(f"{(d / 'snapshot.csv').relative_to(ROOT)}  rows={len(frame)}  sha256={write_csv(frame, d / 'snapshot.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
