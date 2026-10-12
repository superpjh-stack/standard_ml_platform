"""데이터 소스 어댑터 — synthetic · csv · 표준 프레임 (contracts/interfaces.md §2 · spec §4.1-4.2 · G-S05 일부)."""

from __future__ import annotations

import textwrap

import pandas as pd
import pytest

from mlcore.data import jobs
from mlcore.data.sources import CsvSource, ReadSpec, SourceDisconnected, SyntheticSource, make_source
from tests._dev1 import FEATS, raw_rows, task

STD = {"tenant_id", "task_id", "entity_id", "ts", "target", "_source", "_source_ref"}


def _gen_file(tmp_path, body: str | None = None):
    d = tmp_path / "pk" / "synth"
    d.mkdir(parents=True)
    (d / "rows.py").write_text(body or textwrap.dedent("""
        import sys
        sys.path.insert(0, %r)
        from tests._dev1 import raw_rows
        def generate(rows=600, seed=0, *, categories=None):
            return raw_rows(rows, seed)
    """ % str(__import__("pathlib").Path(__file__).resolve().parents[1])), encoding="utf-8")
    return tmp_path / "pk"


def spec(t=None):
    return ReadSpec(tenant_id="tt", task=t or task(), features=FEATS)


def test_synthetic_file_standard_frame(tmp_path):
    src = SyntheticSource(_gen_file(tmp_path), "synth/rows.py", seed=3, rows=200)
    df = src.read(spec())
    assert STD <= set(df.columns) and {"x1", "x2", "c1"} <= set(df.columns)
    assert len(df) == 200 and (df["tenant_id"] == "tt").all() and (df["task_id"] == "tt.target_value").all()
    assert str(df["ts"].dt.tz) == "Asia/Seoul"
    assert df["ts"].is_monotonic_increasing
    assert df["target"].notna().all() and (df["_source"] == "synthetic").all()
    # 같은 시드 → 같은 프레임, 다른 시드 → 다른 프레임
    pd.testing.assert_frame_equal(df, src.read(spec()))
    other = SyntheticSource(_gen_file(tmp_path / "b"), "synth/rows.py", seed=4, rows=200).read(spec())
    assert not df["x1"].equals(other["x1"])


def test_synthetic_missing_generator_is_disconnected(tmp_path):
    src = SyntheticSource(tmp_path, "synth/none.py", seed=1, rows=10)
    with pytest.raises(SourceDisconnected) as e:
        src.read(spec())
    assert e.value.kind == "synthetic"
    h = src.probe(spec())
    assert h.connected is False and h.rows is None and "없음" in h.message


def test_probe_reports_coverage_and_target(tmp_path):
    src = SyntheticSource(_gen_file(tmp_path), "synth/rows.py", seed=1, rows=100)
    h = src.probe(spec())
    assert h.connected and h.rows == 100 and h.feature_coverage == 1.0 and h.has_target is True
    assert 0 < h.missing_rates["x2"] < 0.2 and h.ts_from < h.ts_to


def test_csv_bom_columns_map_units(tmp_path):
    raw = raw_rows(50, 1).rename(columns={"x1": "SRC_X1", "c1": "SRC_C1", "y": "SRC_Y"})
    raw["ts"] = raw["ts"].dt.strftime("%Y-%m-%d %H:%M:%S%z")
    p = tmp_path / "f.csv"
    raw.to_csv(p, index=False, encoding="utf-8-sig")
    t = task()
    sp = ReadSpec(tenant_id="tt", task=t, features=FEATS,
                  columns_map={"TBL.SRC_X1": "x1", "SRC_C1": "c1", "TBL.SRC_Y": "y"})
    df = CsvSource(p, units={"x1": 2.0}).read(sp)
    assert len(df) == 50 and (df["_source"] == "csv").all()
    base = raw_rows(50, 1)
    assert df["x1"].round(9).tolist() == (base["x1"] * 2).round(9).tolist()
    assert df["target"].round(9).tolist() == base["y"].round(9).tolist()
    assert df["c1"].tolist() == base["c1"].tolist()
    assert str(df["ts"].dt.tz) == "Asia/Seoul"


def test_csv_missing_file_is_disconnected(tmp_path):
    src = CsvSource(tmp_path / "no.csv")
    with pytest.raises(SourceDisconnected):
        src.read(spec())
    assert src.probe(spec()).connected is False


def test_csv_without_target_says_no_target(tmp_path):
    raw = raw_rows(30, 1).drop(columns=["y"])
    p = tmp_path / "f.csv"
    raw.to_csv(p, index=False)
    h = CsvSource(p).probe(spec())
    assert h.connected and h.has_target is False and h.message == "목표 없음"


def test_missing_feature_column_is_nan_not_invented(tmp_path):
    raw = raw_rows(30, 1).drop(columns=["x2"])
    p = tmp_path / "f.csv"
    raw.to_csv(p, index=False)
    df = CsvSource(p).read(spec())
    assert df["x2"].isna().all()


@pytest.mark.parametrize("kind", ["gateway", "dataplatform", "mes", "nope"])
def test_unimplemented_kinds_fail_visibly(kind, tmp_path):
    with pytest.raises(SourceDisconnected):
        make_source({"kind": kind}, pack_dir=tmp_path, pack_meta={})


def test_read_window_and_limit(tmp_path):
    src = SyntheticSource(_gen_file(tmp_path), "synth/rows.py", seed=1, rows=100)
    t = task()
    full = src.read(spec(t))
    lo, hi = full["ts"].iloc[10], full["ts"].iloc[30]
    w = src.read(ReadSpec(tenant_id="tt", task=t, features=FEATS, ts_from=lo.to_pydatetime(), ts_to=hi.to_pydatetime(), limit=5))
    assert len(w) == 5 and w["ts"].min() >= lo


@pytest.mark.parametrize("tenant,task_id", [("ks", "ks.remaining_hours"), ("sw", "sw.delta_e"),
                                            ("ks", "ks.sensor_ood"), ("sw", "sw.defect_risk")])
def test_pack_generator_through_registry(tenant, task_id):
    """팩 합성 생성기(개발3) → 회사 등록부 해석(synth_call) → 표준 프레임. 원천 행 720 · 결측 24."""
    m, t, frame, ref, synthetic = jobs.read_frame(tenant, task_id)
    assert synthetic is True and ref["kind"] == "synthetic" and ref["seed"] == 42
    assert len(frame) == 720
    names = t.raw["features"]
    assert set(names) <= set(frame.columns)
    assert int(frame[names].isna().sum().sum()) == 24
    if t.type == "anomaly":
        assert "target" not in frame.columns
    else:
        assert frame["target"].notna().all()
    assert frame["entity_id"].is_unique


def test_csv_source_from_registry_eval_role():
    """sources.eval (csv fixture, 개발3) 를 읽으면 합성 생성기와 같은 내용이다."""
    _, _, a, _, _ = jobs.read_frame("sw", "sw.delta_e")
    _, _, b, ref, synthetic = jobs.read_frame("sw", "sw.delta_e", source_role="eval")
    assert synthetic is False and ref["kind"] == "csv"
    cols = [c for c in a.columns if c not in ("_source", "_source_ref")]
    pd.testing.assert_frame_equal(a[cols].reset_index(drop=True), b[cols].reset_index(drop=True),
                                  check_exact=False, rtol=1e-12, check_dtype=False)
