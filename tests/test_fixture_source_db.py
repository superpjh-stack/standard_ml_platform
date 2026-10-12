"""원천 DB 사본 fixture (tests/fixtures/<t>/source_db.sql — D-W1-10 · G-S05 재료). 소유 개발3.

사본을 시험 DB 임시 스키마에 적재하면 테이블마다 720행이고, 등록부 대응 열 값이 합성 snapshot 과 같다.
fixture 는 손질하지 않는다 — 생성기 출력과 바이트 단위로 같아야 한다.
"""

from __future__ import annotations

import os
import secrets

import numpy as np
import pandas as pd
import pytest
import yaml

from migration import make_fixtures

ROOT = make_fixtures.ROOT
DSN = os.environ.get("MLP_TEST_DB_DSN") or "dbname=ml_test_db host=/tmp"


@pytest.mark.parametrize("t", ["ks", "sw"])
def test_source_db_is_regenerated_not_edited(t):
    assert (ROOT / "tests" / "fixtures" / t / "source_db.sql").read_text(encoding="utf-8") == make_fixtures.source_db_sql(t)


@pytest.mark.parametrize("t", ["ks", "sw"])
def test_source_db_loads_and_matches_snapshot(t):
    psycopg = pytest.importorskip("psycopg")
    try:
        conn = psycopg.connect(DSN, autocommit=True)
    except Exception:  # noqa: BLE001
        pytest.skip("ml_test_db 없음")
    schema = "srcfx_" + secrets.token_hex(4)
    cfg = yaml.safe_load((ROOT / "tenants" / f"{t}.yaml").read_text(encoding="utf-8"))
    cmap = {**cfg["feature_map"], **(cfg.get("target_map") or {})}
    snap = pd.read_parquet(ROOT / "tests" / "fixtures" / t / "snapshot.parquet").set_index("entity_id")
    try:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        conn.execute((ROOT / "tests" / "fixtures" / t / "source_db.sql").read_text(encoding="utf-8"))
        tables = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
                                             "ORDER BY 1", (schema,))]
        assert set(tables) == {x.split(".", 1)[0] for x in cmap} & set(cfg["sources"]["actuals"]["tables"])
        for table in tables:
            cur = conn.execute(f'SELECT * FROM "{table}" ORDER BY "FX_KEY"')
            df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description]).set_index("FX_KEY")
            assert len(df) == 720
            for col in df.columns:
                if col == "FX_AT":
                    assert (pd.to_datetime(df[col]).dt.tz_convert("Asia/Seoul") == snap.loc[df.index, "ts"]).all()
                    continue
                dst = cmap[f"{table}.{col}"]
                a, b = df[col], snap.loc[df.index, dst]
                if pd.api.types.is_numeric_dtype(b):
                    assert np.allclose(a.astype(float), b.astype(float), equal_nan=True, rtol=0, atol=0), col
                else:
                    assert (a.astype(str) == b.astype(str)).all(), col
        unmapped = set(cfg.get("unmapped") or {})
        all_cols = {c for tb in tables for c in pd.DataFrame(conn.execute(f'SELECT * FROM "{tb}" LIMIT 0').description).iloc[:, 0]} \
            if tables else set()
        assert not ({str(c).lower() for c in all_cols} & unmapped)          # 대응 없는 변수는 사본에도 없다
    finally:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.close()
