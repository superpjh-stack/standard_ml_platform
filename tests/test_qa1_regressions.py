"""QA1 결함 회귀 시험 (outputs/qa1-데이터학습평가.md · 재현 스크립트 outputs/qa1/*.py 를 시험으로 옮김). 소유 개발1.

- DEF-QA1-001 (#8)  last_value 기준선은 학습(+검증) 구간 목표만 본다 — 시험 목표를 바꿔도 검증 기준선 · 선택 불변.
- DEF-QA1-002 (#9)  group_key 가 시간순과 함께 지켜지지 않으면 학습을 거부한다(오류 코드 split_time_group_conflict, D-85).
- DEF-QA1-006       guard 우회 경로(vars · copy · overlaps 반복 · 복사본 final_eval 2회)는 막히고, 정적 검사가 우회 패턴을 잡는다.
- DEF-QA1-007       스냅숏 해시 — 중복 (ts, entity_id) 행 순서 · entity_id 없는 원천 행 순서에 흔들리지 않고, 수치/문자열 dtype 을 구분한다.
- DEF-QA1-008       같은 시각 행 묶음은 분할 경계(시험 · 검증 · 폴드)에 갈리지 않는다.
- DEF-QA1-009       DB 어댑터 조회는 세션 설정과 별도로 트랜잭션 READ ONLY 로 돈다 · 읽기 역할(SET ROLE) · 쓰기 권한 계정 경고.
"""

from __future__ import annotations

import copy
import secrets
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pytest
from psycopg import sql

from mlcore.data import snapshot
from mlcore.data.frame import standardize
from mlcore.data.sources import ReadSpec, SourceDisconnected
from mlcore.data.sources.readonly_db import ReadOnlyDb
from mlcore.settings import get_settings
from mlcore.train import guard, split
from mlcore.train.trainer import StandardTrainer, TrainConfig
from tests._dev1 import FEATS, raw_rows, std_frame, task

ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = get_settings().test_db_dsn


def _te(frame, sp):
    return sorted(set(range(len(frame))) - set(sp.train_idx) - set(sp.valid_idx))


def _train(frame, t, out: Path):
    f = snapshot.canonical(frame)
    sid = "snp_" + snapshot.content_sha256(f)[:16]
    return StandardTrainer(features=FEATS, artifact_root=out, frame=f, synthetic=True).train(
        TrainConfig(t, sid, 7, "test", tuple(t.raw["candidates"]), {}))


# ── DEF-QA1-001 ────────────────────────────────────────────────────────────
def test_last_value_lag_uses_only_given_rows():
    """직전 값은 주어진 구간(학습+검증) 안에서만 잇는다 — 구간 밖(시험) 목표를 바꿔도 값이 같다."""
    from mlcore.train.trainer import last_value_lag

    t = task()
    f = snapshot.canonical(std_frame(t, raw_rows(400, 3)))
    rows = [i for i in range(len(f)) if i % 5 != 2]                 # 시험 행이 시간상 끼어 있는 최악의 경우
    lag = last_value_lag(f, rows)
    g = f.copy()
    others = [i for i in range(len(f)) if i % 5 == 2]
    g.loc[others, "target"] = g.loc[others, "target"] + 1000.0
    assert np.array_equal(lag, last_value_lag(g, rows), equal_nan=True)
    # 값 = 그 구간만 시각순으로 줄 세웠을 때 바로 앞 행의 목표
    sub = f.iloc[rows].sort_values(["ts", "entity_id"], kind="mergesort")
    exp = sub["target"].shift(1).reindex(f.index[rows]).to_numpy()
    assert np.array_equal(lag, exp, equal_nan=True) and np.isnan(lag).sum() == 1


def test_last_value_baseline_ignores_test_targets(tmp_path):
    """lv_flip.py 를 시간상 그룹이 이어진 배치로: 시험 목표만 크게 바꿔도 검증 기준선 · 선택된 기준선 종류가 같다."""
    t = task(group_key="lot", candidates=["ridge"])
    n = 1000
    raw = raw_rows(n, 11, groups=50)
    raw["y"] = np.cumsum(np.random.default_rng(1).normal(0, 1, n)) + raw["y"] * 0.05
    f = snapshot.canonical(std_frame(t, raw))
    sp, _ = split.plan(f, t, seed=7)
    te = _te(f, sp)
    g = f.copy()
    g.loc[te, "target"] = g.loc[te, "target"] + np.linspace(500, 5000, len(te))
    a = _train(f, t, tmp_path / "a")
    b = _train(g, t, tmp_path / "b")
    assert a.status == b.status == "succeeded"
    assert a.report["baselines_compared"]["valid"] == b.report["baselines_compared"]["valid"]
    assert a.report["baseline"] == b.report["baseline"] == "last_value"
    assert a.test_metrics != b.test_metrics                                 # 시험 지표만 바뀐다


def test_lv_flip_probe_no_longer_flips_baseline(tmp_path):
    """QA lv_flip.py 그대로(60그룹 무작위 배치): 시간순과 그룹을 함께 지킬 수 없어 두 실행 모두 거부 — 기준선이 뒤집힐 수 없다."""
    t = task(group_key="lot", candidates=["ridge"])
    n = 1000
    raw = raw_rows(n, 11)
    raw["y"] = np.cumsum(np.random.default_rng(1).normal(0, 1, n)) + raw["y"] * 0.05
    raw["lot"] = [f"G{x:02d}" for x in np.random.default_rng(0).integers(0, 60, n)]
    f = snapshot.canonical(std_frame(t, raw))
    g = f.copy()
    g["target"] = g["target"] + np.where(np.arange(n) > 800, 1000.0, 0.0)
    for r in (_train(f, t, tmp_path / "a"), _train(g, t, tmp_path / "b")):
        assert r.status == "failed"
        assert r.report["error"]["code"] == "split_time_group_conflict"
        assert r.warnings[0]["code"] == "split_time_group_conflict"


# ── DEF-QA1-002 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n", [600, 300])           # time_60_20_20 · time_cv5
def test_interleaved_groups_refuse_time_split(n):
    t = task(group_key="lot")
    raw = raw_rows(n, 4)
    raw["lot"] = [f"G{i % 25:02d}" for i in range(n)]                      # group_probe.py: 시간상 완전히 섞임
    f = std_frame(t, raw)
    with pytest.raises(split.SplitRefused) as e:
        split.plan(f, t, seed=1)
    assert e.value.code == "split_time_group_conflict"


@pytest.mark.parametrize("groups", [7, 40, 333])
@pytest.mark.parametrize("n", [1000, 400])
def test_grouped_time_split_is_strictly_chronological(groups, n):
    """그룹을 지키면서도 학습 < 검증 < 시험 시각이 엄격히 앞선다(시험 최초 시각보다 늦은 학습 · 검증 행 0)."""
    t = task(group_key="lot")
    f = std_frame(t, raw_rows(n, 3, groups=groups))
    sp, _ = split.plan(f, t, seed=1)
    ts = f["ts"]
    te = _te(f, sp)
    assert ts.iloc[list(sp.fit_idx)].max() < ts.iloc[te].min()
    assert ts.iloc[list(sp.train_idx)].max() < ts.iloc[list(sp.valid_idx)].min()
    for tr, va in sp.folds:
        assert ts.iloc[list(tr)].max() < ts.iloc[list(va)].min()
    assert "regrouped" not in sp.boundaries


# ── DEF-QA1-008 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n,per", [(1002, 3), (402, 3), (1000, 7)])
def test_same_timestamp_rows_never_straddle_a_boundary(n, per):
    t = task()
    raw = raw_rows(n, 12)
    raw["ts"] = pd.date_range("2026-01-01", periods=-(-n // per), freq="h", tz="Asia/Seoul").repeat(per)[:n]
    f = snapshot.canonical(std_frame(t, raw))
    sp, _ = split.plan(f, t, seed=7)
    ts = f["ts"]
    tr, va, te = set(ts.iloc[list(sp.train_idx)]), set(ts.iloc[list(sp.valid_idx)]), set(ts.iloc[_te(f, sp)])
    assert not tr & va and not va & te and not tr & te
    for ftr, fva in sp.folds:
        assert not set(ts.iloc[list(ftr)]) & set(ts.iloc[list(fva)])


# ── DEF-QA1-006 ────────────────────────────────────────────────────────────
def _guarded():
    led = guard.AccessLedger()
    return guard.GuardedTest(range(8, 10), led), led


def test_guard_hides_index_from_vars_and_copies():
    g, led = _guarded()
    with pytest.raises(TypeError):
        vars(g)                                                   # __dict__ 없음
    for fn in (copy.copy, copy.deepcopy):
        with pytest.raises(guard.TestLeak):
            fn(g)
    import pickle
    with pytest.raises(guard.TestLeak):
        pickle.dumps(g)
    assert len(led.violations()) == 3


def test_guard_final_eval_once_per_ledger_and_overlaps_once():
    frame = pd.DataFrame({"y": range(10)})
    led = guard.AccessLedger()
    a = guard.GuardedTest(range(8, 10), led)
    b = guard.GuardedTest(range(8, 10), led)                       # 같은 ledger 의 두 번째 래퍼(복사 우회 모사)
    a.take(frame, "final_eval")
    with pytest.raises(guard.TestLeak):
        b.take(frame, "final_eval")
    assert led.final_eval_count() == 1 and led.violations()[-1]["reason"] == "final_eval 2회째"
    c, led2 = _guarded()
    assert c.overlaps(range(0, 8)) is False
    with pytest.raises(guard.TestLeak):
        c.overlaps([8])                                            # 한 행씩 묻는 질의 → 복원 시도
    assert led2.violations()[-1]["purpose"] == "overlaps"


def test_leakage_static_check_flags_bypass_patterns():
    sys.path.insert(0, str(ROOT / "gates"))
    try:
        import check_leakage as cl
    finally:
        sys.path.pop(0)
    bad = {
        "vars": "idx = vars(test)['x']",
        "dict": "idx = test.__dict__",
        "mangle": "idx = test._GuardedTest__idx",
        "copy": "t2 = copy.copy(test)",
        "deepcopy": "t2 = copy.deepcopy(test)",
        "complement": "te = set(range(len(frame))) - set(sp.train_idx) - set(sp.valid_idx)",
        "test_ts": "lo = sp.boundaries['test_ts'][0]",
        "test_ts_get": "lo = sp.boundaries.get(\"test_ts\")",
        "overlaps": "rows = [i for i in range(n) if test.overlaps([i])]",
    }
    for name, line in bad.items():
        assert cl.scan_bypass("src/mlcore/train/x.py", line), name
    ok = "bounds[\"test_ts\"] = [str(ts[b]), str(ts[n - 1])] if n > b else None"
    assert not cl.scan_bypass("src/mlcore/train/split.py", ok)
    assert not cl.scan_bypass("src/mlcore/train/guard.py", "if test.overlaps(fit_idx):")
    assert not cl.scan_bypass("src/mlcore/registry/tenants.py", "merged = copy.deepcopy(base)")
    assert cl._static() == []                                     # 지금 src 에는 우회 0


# ── DEF-QA1-007 ────────────────────────────────────────────────────────────
@pytest.fixture
def f0():
    return std_frame(task(), raw_rows(300, 5))


def test_hash_stable_for_duplicate_key_rows_in_any_order(f0):
    dup = f0.iloc[[7]].copy()
    dup["x1"] = dup["x1"] + 1
    a = pd.concat([f0, dup], ignore_index=True)
    b = pd.concat([f0.iloc[:7], dup, f0.iloc[7:]], ignore_index=True)
    assert snapshot.content_sha256(a) == snapshot.content_sha256(b)
    assert snapshot.canonical(a).equals(snapshot.canonical(b))          # 학습기가 보는 행 순서도 같다


def test_hash_distinguishes_numeric_and_string_columns(f0):
    a = f0.copy()
    a["x1"] = a["x1"].round(0)
    b = a.copy()
    b["x1"] = b["x1"].map(lambda v: str(v) if pd.notna(v) else None).astype(object)
    assert snapshot.content_sha256(a) != snapshot.content_sha256(b)
    c = a.copy()
    c["x1"] = c["x1"].astype("Int64").astype(object)                    # 같은 수치 — 표기만 다름
    assert snapshot.content_sha256(a) == snapshot.content_sha256(c)


def test_hash_stable_when_source_has_no_entity_id():
    t = task()
    r = raw_rows(50, 1).drop(columns=["entity_id"])
    spec = ReadSpec(tenant_id="tt", task=t, features=FEATS)
    a = standardize(r, spec, kind="csv", source_ref="x")
    b = standardize(r.sample(frac=1, random_state=2), spec, kind="csv", source_ref="x")
    assert snapshot.content_sha256(a) == snapshot.content_sha256(b)


def test_legacy_snapshot_files_still_load(f0, tmp_path):
    """해시 규칙 v1 으로 고정된 기존 스냅숏(규칙 표지 없음)은 v1 으로 검증해 그대로 읽힌다 — 내용이 바뀌면 여전히 거부."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    df = snapshot.canonical(f0)
    old = snapshot.content_sha256_v1(df)
    sid = "snp_" + old[:16]
    p = tmp_path / "tt" / "tt.target_value" / f"{sid}.parquet"
    p.parent.mkdir(parents=True)
    tb = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(tb.replace_schema_metadata({**tb.schema.metadata, snapshot.META_KEY: old.encode()}), p)
    assert snapshot.load(sid, base_dir=tmp_path).equals(df)
    bad = df.copy()
    bad.loc[0, "x1"] = 0.123
    tb = pa.Table.from_pandas(bad, preserve_index=False)
    pq.write_table(tb.replace_schema_metadata({**tb.schema.metadata, snapshot.META_KEY: old.encode()}), p)
    with pytest.raises(snapshot.SnapshotCorrupt):
        snapshot.load(sid, base_dir=tmp_path)


# ── DEF-QA1-009 ────────────────────────────────────────────────────────────
def _db_ok() -> bool:
    try:
        with psycopg.connect(TEST_DSN, connect_timeout=3) as c:
            c.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


needs_db = pytest.mark.skipif(not _db_ok(), reason="ml_test_db 없음 — make setup")


@pytest.fixture
def side_effect_schema():
    """허용목록 '테이블' 이 실은 쓰기 함수를 부르는 뷰인 사본 — SELECT 로도 쓰기가 일어나는지 본다."""
    schema = "srcro_" + secrets.token_hex(4)
    admin = psycopg.connect(TEST_DSN, autocommit=True)
    s = sql.Identifier(schema)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(s))
    admin.execute(sql.SQL("CREATE TABLE {}.sink (x int)").format(s))
    admin.execute(sql.SQL("CREATE FUNCTION {}.touch() RETURNS SETOF int LANGUAGE sql VOLATILE AS "
                          "$$ INSERT INTO {}.sink VALUES (1) RETURNING x $$").format(s, s))
    admin.execute(sql.SQL("CREATE VIEW {}.v AS SELECT * FROM {}.touch() AS t(x)").format(s, s))
    yield schema, admin
    admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(s))
    admin.close()


def _sink(admin, schema) -> int:
    return admin.execute(sql.SQL("SELECT count(*) FROM {}.sink").format(sql.Identifier(schema))).fetchone()[0]


@needs_db
def test_reads_run_in_read_only_transaction_even_if_session_default_is_off(side_effect_schema):
    schema, admin = side_effect_schema
    db = ReadOnlyDb("gateway", connect=lambda: psycopg.connect(TEST_DSN, autocommit=True), allow=("v",), schema=schema)
    conn = db.connect()
    try:
        conn.execute("SET default_transaction_read_only = off")          # source_probe.py: 연결을 쥔 코드가 끈 경우
        with pytest.raises(SourceDisconnected, match="조회 실패"):
            db.select("v", conn=conn)
        with pytest.raises(SourceDisconnected):
            db.count("v", conn=conn)
    finally:
        conn.close()
    assert _sink(admin, schema) == 0                                      # 원천 쓰기 0


@needs_db
def test_read_role_and_write_privilege_warning(side_effect_schema, monkeypatch):
    from mlcore.data.sources import GatewaySource

    schema, admin = side_effect_schema
    connect = lambda: psycopg.connect(TEST_DSN, autocommit=True)            # noqa: E731
    db = ReadOnlyDb("gateway", connect=connect, allow=("sink",), schema=schema)
    assert db.write_privileges() == ["sink"]                              # 시험 계정은 소유자 — 쓰기 권한이 있다
    h = GatewaySource("sink", connect=connect, schema=schema).probe()
    assert h.connected and "쓰기 권한" in h.message and "읽기 전용 역할" in h.message
    with pytest.raises(SourceDisconnected, match="읽기 역할"):
        ReadOnlyDb("gateway", connect=connect, allow=("sink",), schema=schema,
                   role="mlp_no_such_role_" + secrets.token_hex(3)).connect()
