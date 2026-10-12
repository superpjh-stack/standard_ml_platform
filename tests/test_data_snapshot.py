"""스냅숏 — 정규 CSV 해시 · Parquet 고정 · 학습 범위 · mlp_snapshot (contracts/interfaces.md §2.2 · spec §4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from mlcore.data import snapshot
from tests._dev1 import raw_rows, std_frame, task


@pytest.fixture
def frame():
    return std_frame(task(), raw_rows(300, 5))


def test_hash_ignores_column_order(frame):
    cols = list(frame.columns)
    shuffled = frame[cols[::-1]]
    assert snapshot.content_sha256(frame) == snapshot.content_sha256(shuffled)
    rng = np.random.default_rng(0)
    assert snapshot.content_sha256(frame) == snapshot.content_sha256(frame[list(rng.permutation(cols))])


def test_hash_ignores_row_order_and_int_float_spelling(frame):
    assert snapshot.content_sha256(frame) == snapshot.content_sha256(frame.sample(frac=1, random_state=1))
    f2 = frame.copy()
    f2["x1"] = f2["x1"].round()
    f3 = f2.copy()
    f3["x1"] = f3["x1"].astype("Int64").astype(object)
    assert snapshot.content_sha256(f2) == snapshot.content_sha256(f3)


def test_hash_changes_with_content(frame):
    f2 = frame.copy()
    f2.loc[3, "x1"] += 1e-9
    assert snapshot.content_sha256(frame) != snapshot.content_sha256(f2)
    f3 = frame.copy()
    f3.loc[3, "c1"] = None
    assert snapshot.content_sha256(frame) != snapshot.content_sha256(f3)


def test_hash_same_instant_any_timezone(frame):
    f2 = frame.copy()
    f2["ts"] = f2["ts"].dt.tz_convert("UTC")
    assert snapshot.content_sha256(frame) == snapshot.content_sha256(f2)


def test_freeze_path_id_and_load_roundtrip(frame, tmp_path):
    t = task()
    s = snapshot.freeze(frame, tenant_id="tt", task=t, source_ref={"kind": "synthetic"}, synthetic=True, base_dir=tmp_path)
    assert s.snapshot_id == "snp_" + s.sha256[:16]
    assert s.path == str(tmp_path / "tt" / t.id / f"{s.snapshot_id}.parquet")
    assert s.rows == 300 and s.columns == tuple(sorted(frame.columns))
    back = snapshot.load(s.snapshot_id, base_dir=tmp_path)
    assert snapshot.content_sha256(back) == s.sha256
    assert str(back["ts"].dt.tz) == "Asia/Seoul"
    info = snapshot.load_info(s.snapshot_id, base_dir=tmp_path)
    assert info["synthetic"] is True and info["sha256"] == s.sha256
    # 열 순서만 다른 프레임은 같은 스냅숏
    s2 = snapshot.freeze(frame[list(frame.columns)[::-1]], tenant_id="tt", task=t, source_ref={}, synthetic=True,
                         base_dir=tmp_path)
    assert s2.snapshot_id == s.snapshot_id


def test_ranges_missing_rates(frame, tmp_path):
    s = snapshot.freeze(frame, tenant_id="tt", task=task(), source_ref={}, synthetic=True, base_dir=tmp_path)
    x1 = frame["x1"].dropna().to_numpy()
    assert s.ranges["x1"] == pytest.approx({"p1": np.percentile(x1, 1), "p99": np.percentile(x1, 99)})
    assert s.ranges["c1"] == {"values": ["A", "B", "C"]}
    assert "tenant_id" not in s.ranges and "target" not in s.ranges
    assert s.missing_rates["x2"] == pytest.approx(frame["x2"].isna().mean())
    assert s.ts_from == frame["ts"].min().to_pydatetime()


def test_corrupt_snapshot_is_rejected(frame, tmp_path):
    s = snapshot.freeze(frame, tenant_id="tt", task=task(), source_ref={}, synthetic=True, base_dir=tmp_path)
    table = pq.read_table(s.path)
    df = table.to_pandas()
    df.loc[0, "x1"] = -1.0
    import pyarrow as pa
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False).replace_schema_metadata(table.schema.metadata), s.path)
    with pytest.raises(snapshot.SnapshotCorrupt):
        snapshot.load(s.snapshot_id, base_dir=tmp_path)


def test_record_mlp_snapshot_row(tmp_path):
    """시험 DB(ml_test_db)에 mlp_snapshot 1행 — 멱등."""
    from mlcore.data import jobs
    from mlcore.db.conn import DbUnavailable, connect

    m, t, frame, ref, synthetic = jobs.read_frame("ks", "ks.remaining_hours")
    s = snapshot.freeze(frame, tenant_id="ks", task=t, source_ref=ref, synthetic=synthetic, base_dir=tmp_path)
    try:
        snapshot.record(s, test=True)
        snapshot.record(s, test=True)
    except DbUnavailable:
        pytest.fail("ml_test_db 연결 불가 — make setup")
    with connect(test=True) as c:
        rows = c.execute("SELECT * FROM mlp_snapshot WHERE snapshot_id=%s", (s.snapshot_id,)).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["sha256"] == s.sha256 and r["rows"] == 720 and r["synthetic"] is True
    assert set(r["ranges"]) == set(t.raw["features"])
    assert r["source_ref"]["seed"] == 42
