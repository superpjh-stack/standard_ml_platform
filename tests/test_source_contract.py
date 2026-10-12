"""G-S05 — 읽기 전용 소스 (goal §2.1 · contracts/interfaces.md §2 · spec §4.1). 소유 개발1.

- 어댑터 5(synthetic · csv · gateway · dataplatform · mes)가 DataSource 모양(kind · probe · read)을 따른다.
- 어댑터 코드에 쓰기 SQL · 비 GET HTTP · 쓰기 모드 파일 0(gates/check_sources.py 와 같은 패턴).
- **fixture 원천 DB 사본**: tests/fixtures/<회사>/ 에 DB 사본이 아직 없어서(개발3 요청 기록) 이 시험이
  ml_test_db 안에 임시 스키마를 만들고 회사 fixture CSV(tests/fixtures/<회사>/snapshot.csv)를 회사 등록부
  `feature_map` · `target_map` 의 원천 테이블 · 열 모양으로 옮겨 사본을 만든다(테이블 · 열 이름은 등록부에서 읽는다).
  어댑터로 읽은 뒤 원천 행 수 diff = 0, 읽은 행 수 = 원천 행 수, 값 = fixture 값.
- DB 세션은 읽기 전용이다(쓰기 시도 → ReadOnlySqlTransaction). 허용목록 밖 테이블은 거부한다.
- dataplatform 은 **가짜 전송**으로만 시험한다(실제 호출 0): GET 만 · 커서 페이지 · 5 req/s · 5,000/일.
- 실패는 `source_disconnected` 봉투로 낸다(POST …/train → 503), 예외를 삼키지 않는다(probe 는 connected=False + 사유).
  사유 문구에 DSN · 주소 · 키 값이 없다.
"""

from __future__ import annotations

import re
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pytest
import yaml
from psycopg import sql

from mlcore.data.features import feature_defs
from mlcore.data.sources import (CsvSource, DataPlatformSource, GatewaySource, MesSource, ReadSpec, SourceDisconnected,
                                 SyntheticSource, make_source)
from mlcore.data.sources.dataplatform import RateLimiter
from mlcore.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.gate("G-S05")
TEST_DSN = get_settings().test_db_dsn


def _db_ok() -> bool:
    try:
        with psycopg.connect(TEST_DSN, connect_timeout=3) as c:
            c.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


needs_db = pytest.mark.skipif(not _db_ok(), reason="ml_test_db 없음 — make setup")


# ── 정적 · 모양 ────────────────────────────────────────────────────────────
def test_five_adapters_follow_datasource_shape(tmp_path):
    classes = {"synthetic": SyntheticSource, "csv": CsvSource, "gateway": GatewaySource,
               "dataplatform": DataPlatformSource, "mes": MesSource}
    for kind, cls in classes.items():
        assert cls.kind == kind
        assert callable(getattr(cls, "probe")) and callable(getattr(cls, "read"))
    cfgs = {"csv": {"kind": "csv", "path": "x.csv"}, "gateway": {"kind": "gateway", "table": "t", "dsn_env": "MLP_X_DSN"},
            "mes": {"kind": "mes", "tables": ["t"], "dsn_env": "MLP_X_DSN"},
            "dataplatform": {"kind": "dataplatform", "url_env": "MLP_X_URL", "key_env": "MLP_X_KEY", "view": "v"}}
    for kind, cfg in cfgs.items():
        assert type(make_source(cfg, pack_dir=tmp_path, pack_meta={})) is classes[kind]


def test_adapter_code_has_no_write_paths():
    sys.path.insert(0, str(ROOT / "gates"))
    try:
        import check_sources as cs
    finally:
        sys.path.pop(0)
    d = ROOT / "src" / "mlcore" / "data" / "sources"
    files = sorted(d.glob("*.py"))
    assert {p.stem for p in files} >= {"synthetic", "csv", "gateway", "dataplatform", "mes"}
    for p in files:
        txt = p.read_text(encoding="utf-8")
        for pat in (cs.WRITE_SQL, cs.NON_GET, cs.WRITE_OPEN):
            assert not pat.search(txt), f"{p.name}: {pat.pattern}"
    # DB 어댑터는 읽기 전용 세션을 건다 · HTTP 는 GET 하나
    assert "SET default_transaction_read_only = on" in (d / "readonly_db.py").read_text(encoding="utf-8")
    assert re.findall(r'method="([A-Z]+)"', (d / "dataplatform.py").read_text(encoding="utf-8")) == ["GET"]


# ── fixture 원천 DB 사본 (ml_test_db 임시 스키마) ───────────────────────────
def _tenant_cfg(code: str) -> dict:
    return yaml.safe_load((ROOT / "tenants" / f"{code}.yaml").read_text(encoding="utf-8"))


class SourceCopy:
    """임시 스키마 하나 = 원천 DB 사본. 쓰기는 이 도우미(시험)만 한다 — 어댑터는 읽기만."""

    def __init__(self):
        self.schema = "srcfx_" + secrets.token_hex(4)
        self.admin = psycopg.connect(TEST_DSN, autocommit=True)
        self.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))

    def table(self, name: str, df: pd.DataFrame) -> None:
        cols = []
        for c in df.columns:
            t = "double precision" if pd.api.types.is_float_dtype(df[c]) else \
                "bigint" if pd.api.types.is_integer_dtype(df[c]) else \
                "timestamptz" if pd.api.types.is_datetime64_any_dtype(df[c]) else "text"
            cols.append(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)))
        ident = sql.Identifier(self.schema, name)
        self.admin.execute(sql.SQL("CREATE TABLE {} ({})").format(ident, sql.SQL(", ").join(cols)))
        ins = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            ident, sql.SQL(", ").join(map(sql.Identifier, df.columns)), sql.SQL(", ").join(sql.Placeholder() * len(df.columns)))
        rows = [tuple(None if (isinstance(v, float) and np.isnan(v)) or v is pd.NaT else
                      (v.item() if hasattr(v, "item") else v) for v in r) for r in df.itertuples(index=False)]
        with self.admin.cursor() as cur:
            cur.executemany(ins, rows)

    def counts(self) -> dict[str, int]:
        names = [r[0] for r in self.admin.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY 1", (self.schema,))]
        return {n: self.admin.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(self.schema, n))).fetchone()[0]
                for n in names}

    def connect(self):
        return psycopg.connect(TEST_DSN, autocommit=True)

    def drop(self):
        self.admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()


@pytest.fixture
def copy():
    c = SourceCopy()
    yield c
    c.drop()


def _fixture_csv(code: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / "tests" / "fixtures" / code / "snapshot.csv", encoding="utf-8-sig")


def _mes_copy(copy: SourceCopy, code: str) -> tuple[dict, dict, pd.DataFrame, str]:
    """회사 fixture CSV → 등록부 대응표 모양의 MES 사본. 결합 키 · 시각 열은 사본 정의(원천 미확인 — D-32 · D-33)."""
    cfg = _tenant_cfg(code)
    cmap = {**(cfg.get("feature_map") or {}), **(cfg.get("target_map") or {})}
    allow = list(cfg["sources"]["actuals"]["tables"])
    csv = _fixture_csv(code)
    key, at = "FX_KEY", "FX_AT"
    used = []
    for t in allow:
        mine = {src.split(".", 1)[1]: dst for src, dst in cmap.items() if src.startswith(t + ".") and dst in csv.columns}
        if not mine:
            continue
        df = pd.DataFrame({key: csv["entity_id"].astype(str)})
        if not used:
            df[at] = pd.to_datetime(csv["ts"])
        for col, dst in mine.items():
            df[col] = csv[dst]
        copy.table(t, df)
        used.append(t)
    src_cfg = {"kind": "mes", "tables": allow, "dsn_env": "MLP_FX_RO_DSN", "schema": copy.schema,
               "join_on": key, "ts_column": at, "entity_column": key}
    return src_cfg, cmap, csv, used[0]


def _spec(code: str, short: str, cmap: dict) -> ReadSpec:
    from mlcore.registry.tenants import load_and_merge

    m = load_and_merge(code, tenants_base=ROOT / "tenants")
    t = m.tasks[f"{code}.{short}"]
    feats = feature_defs(m.pack.features, t.raw["features"], m.tenant.config.get("categories") or {}, m.pack.std_name)
    return ReadSpec(tenant_id=code, task=t, features=feats, columns_map=cmap)


MES_CASES = [("ks", "remaining_hours"), ("sw", "delta_e")]


@needs_db
@pytest.mark.parametrize("code,short", MES_CASES)
def test_mes_reads_fixture_copy_with_zero_row_diff(copy, monkeypatch, code, short):
    src_cfg, cmap, csv, _ = _mes_copy(copy, code)
    before = copy.counts()
    assert before and all(n == len(csv) for n in before.values())
    monkeypatch.setenv("MLP_FX_RO_DSN", TEST_DSN)          # 등록부에는 이름만 — 값은 프로세스 환경에서
    src = make_source(src_cfg, pack_dir=ROOT, pack_meta={})
    spec = _spec(code, short, cmap)
    frame = src.read(spec)
    health = src.probe(spec)
    after = copy.counts()
    assert after == before                                   # 원천 행 수 diff 0
    assert len(frame) == len(csv) and health.connected and health.rows == len(csv)
    assert set(frame["_source"]) == {"mes"} and frame["ts"].dt.tz is not None
    mapped = sorted({d for d in cmap.values() if d in spec.task.raw["features"]})
    exp = csv.set_index("entity_id")
    got = frame.set_index("entity_id")
    for name in mapped:
        a, b = got[name].loc[exp.index], exp[name]
        if pd.api.types.is_numeric_dtype(b):
            assert np.allclose(a.astype(float), b.astype(float), equal_nan=True), name
        else:
            assert (a.astype(str) == b.astype(str)).all(), name
    tgt = spec.task.raw["target"]["name"]
    if tgt in cmap.values():
        assert np.allclose(got["target"].loc[exp.index], exp[tgt])
    else:                                                    # 목표 원천이 미확인(D-33) — 지어내지 않는다
        assert "target" not in frame.columns and health.has_target is False and health.message == "목표 없음"


@needs_db
def test_db_session_is_read_only_and_allowlist_enforced(copy):
    src_cfg, cmap, csv, first = _mes_copy(copy, "sw")
    src = MesSource.from_config(src_cfg, connect=copy.connect)
    before = copy.counts()
    conn = src.db.connect()
    try:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(first)))
    finally:
        conn.close()
    assert copy.counts() == before
    copy.table("OUTSIDE_LIST", pd.DataFrame({"a": [1.0]}))
    with pytest.raises(SourceDisconnected, match="허용목록 밖"):
        src.db.select("OUTSIDE_LIST")
    bad = ReadSpec(tenant_id="sw", task=_spec("sw", "delta_e", cmap).task, features=_spec("sw", "delta_e", cmap).features,
                   columns_map={"OUTSIDE_LIST.a": "set_temp"})
    with pytest.raises(SourceDisconnected, match="허용목록 밖"):
        src.read(bad)
    no_key = MesSource.from_config({**src_cfg, "join_on": None}, connect=copy.connect)
    with pytest.raises(SourceDisconnected, match="결합 키"):
        no_key.read(_spec("sw", "delta_e", cmap))


@needs_db
def test_gateway_pivot_and_window_aggregation(copy):
    """원장(설비 · 태그 · 값 · 시각 세로 형식) → 태그별 열 → 1시간 창 평균. 사본 행 수 diff 0."""
    rng = np.random.default_rng(3)
    n = 240
    at = pd.Timestamp("2026-08-01T00:00:00+09:00") + pd.to_timedelta(np.arange(n) * 15, unit="min")
    raw = pd.DataFrame({"EQ": np.repeat(["E1", "E2"], n // 2), "TAG": np.tile(["T_A", "T_B"], n // 2),
                        "VAL": rng.normal(10, 2, n), "AT": np.concatenate([at[: n // 2], at[: n // 2]])})
    copy.table("LEDGER", raw)
    before = copy.counts()
    src = GatewaySource("LEDGER", connect=copy.connect, schema=copy.schema, ts_column="AT", entity_column="EQ",
                        pivot={"key": "TAG", "value": "VAL"}, window="1h", agg="mean")
    from tests._dev1 import FEATS, task
    t = task("anomaly", time_key=None)
    spec = ReadSpec(tenant_id="tt", task=t, features=FEATS, columns_map={"T_A": "x1", "T_B": "x2"})
    frame = src.read(spec)
    assert copy.counts() == before
    exp = raw.assign(AT=pd.to_datetime(raw["AT"])).pivot_table(index=["EQ", "AT"], columns="TAG", values="VAL").reset_index()
    exp["W"] = exp["AT"].dt.floor("1h")
    exp = exp.groupby(["EQ", "W"])[["T_A", "T_B"]].mean().reset_index()
    assert len(frame) == len(exp) and frame["entity_id"].str.contains("@").all()
    got = frame.sort_values(["entity_id"]).reset_index(drop=True)
    exp = exp.assign(entity_id=exp["EQ"] + "@" + exp["W"].map(lambda x: x.isoformat())).sort_values("entity_id").reset_index(drop=True)
    assert (got["entity_id"] == exp["entity_id"]).all()
    assert np.allclose(got["x1"], exp["T_A"]) and np.allclose(got["x2"], exp["T_B"])
    assert src.probe().rows == n and src.probe(spec).connected


@needs_db
def test_gateway_raw_rows_time_window_filter(copy):
    n = 50
    df = pd.DataFrame({"EQ": ["E1"] * n, "AT": pd.date_range("2026-08-01", periods=n, freq="h", tz="Asia/Seoul"),
                       "X1": np.arange(n, dtype=float)})
    copy.table("RAW", df)
    src = GatewaySource("RAW", connect=copy.connect, schema=copy.schema, ts_column="AT", entity_column="EQ")
    from tests._dev1 import FEATS, task
    t = task("anomaly", time_key=None)
    lo, hi = df["AT"].iloc[10], df["AT"].iloc[19]
    frame = src.read(ReadSpec(tenant_id="tt", task=t, features=FEATS, ts_from=lo.to_pydatetime(), ts_to=hi.to_pydatetime(),
                              columns_map={"X1": "x1"}))
    assert len(frame) == 10 and frame["x1"].tolist() == list(np.arange(10, 20, dtype=float))
    assert copy.counts() == {"RAW": n}


# ── 실패는 숨기지 않는다 · 사유에 비밀값 없음 ───────────────────────────────
def test_db_failures_are_source_disconnected_without_secrets(monkeypatch):
    from tests._dev1 import FEATS, task
    spec = ReadSpec(tenant_id="tt", task=task("anomaly"), features=FEATS)
    monkeypatch.delenv("MLP_FX_NONE_DSN", raising=False)
    src = GatewaySource("T", dsn_env="MLP_FX_NONE_DSN")
    with pytest.raises(SourceDisconnected) as e:
        src.read(spec)
    assert e.value.kind == "gateway" and "MLP_FX_NONE_DSN" in e.value.reason
    secret = "dbname=__no_such_db_fx__ host=/tmp user=__secret_user__"
    monkeypatch.setenv("MLP_FX_BAD_DSN", secret)
    for s in (GatewaySource("T", dsn_env="MLP_FX_BAD_DSN"), MesSource(["T"], dsn_env="MLP_FX_BAD_DSN")):
        with pytest.raises(SourceDisconnected) as e:
            s.read(spec)
        assert "연결 실패" in e.value.reason and "__no_such_db_fx__" not in str(e.value) and "__secret_user__" not in str(e.value)
        h = s.probe()
        assert h.connected is False and h.rows is None and "__secret" not in h.message


# ── dataplatform — 가짜 전송 (실제 호출 0) ───────────────────────────────────
class FakeTransport:
    def __init__(self, pages: list[dict] | None = None, status: int = 200):
        self.pages, self.status, self.calls = pages or [], status, []

    def __call__(self, url: str, headers: dict):                  # 본문 · 메서드 인자가 없다 — GET 만
        self.calls.append((url, dict(headers)))
        if self.status != 200:
            return self.status, {"error": "boom"}
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        i = int(q.get("cursor", "0"))
        return 200, self.pages[i]


def _dp_pages(n_pages: int = 3, per: int = 4) -> list[dict]:
    pages = []
    for p in range(n_pages):
        items = [{"eid": f"R{p * per + i:03d}", "at": f"2026-08-01T{p * per + i:02d}:00:00+09:00",
                  "x1": float(p * per + i), "c1": "A"} for i in range(per)]
        pages.append({"items": items, "next_cursor": str(p + 1) if p + 1 < n_pages else None})
    return pages


@pytest.fixture
def dp_env(monkeypatch):
    monkeypatch.setenv("MLP_FX_DP_URL", "http://localhost:1/base")
    monkeypatch.setenv("MLP_FX_DP_KEY", "fx-key-not-real")


def _dp(transport, **kw):
    clock = {"t": 0.0}
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s
    lim = kw.pop("limiter", None) or RateLimiter(clock=lambda: clock["t"], sleep=sleep)
    src = DataPlatformSource(url_env="MLP_FX_DP_URL", key_env="MLP_FX_DP_KEY", view=kw.pop("view", "fx_view"),
                             transport=transport, limiter=lim, ts_column="at", entity_column="eid", **kw)
    return src, slept


def test_dataplatform_pages_get_only_with_key_header(dp_env):
    from tests._dev1 import FEATS, task
    tr = FakeTransport(_dp_pages(3, 4))
    src, _ = _dp(tr, page_size=4)
    frame = src.read(ReadSpec(tenant_id="tt", task=task("anomaly"), features=FEATS))
    assert len(frame) == 12 and len(tr.calls) == 3
    assert frame["x1"].tolist() == [float(i) for i in range(12)] and frame["ts"].dt.tz is not None
    for url, headers in tr.calls:
        assert url.startswith("http://localhost:1/base/v1/readings?") and "view=fx_view" in url and "limit=4" in url
        assert headers["x-api-key"] == "fx-key-not-real" and "fx-key-not-real" not in url
    assert [("cursor=" in u) for u, _ in tr.calls] == [False, True, True]


def test_dataplatform_rate_limits(dp_env):
    from tests._dev1 import FEATS, task
    tr = FakeTransport(_dp_pages(12, 1))
    src, slept = _dp(tr)
    src.read(ReadSpec(tenant_id="tt", task=task("anomaly"), features=FEATS))
    assert len(tr.calls) == 12 and len(slept) == 2                       # 5 req/s — 6번째 · 11번째 앞에서 기다림
    day = {"d": date(2026, 10, 1)}
    lim = RateLimiter(per_day=5, clock=lambda: 0.0, sleep=lambda s: None, today=lambda: day["d"])
    src2, _ = _dp(FakeTransport(_dp_pages(8, 1)), limiter=lim)
    with pytest.raises(SourceDisconnected, match="일 요청 한도"):
        src2.read(ReadSpec(tenant_id="tt", task=task("anomaly"), features=FEATS))
    assert lim.used_today == 5
    day["d"] += timedelta(days=1)                                         # 다음 날 다시 센다
    lim.acquire()
    assert lim.used_today == 1


def test_dataplatform_failures_are_visible_and_secret_free(dp_env, monkeypatch):
    from tests._dev1 import FEATS, task
    spec = ReadSpec(tenant_id="tt", task=task("anomaly"), features=FEATS)
    src, _ = _dp(FakeTransport(status=500))
    with pytest.raises(SourceDisconnected) as e:
        src.read(spec)
    assert e.value.reason == "HTTP 500" and "localhost" not in str(e.value) and "fx-key" not in str(e.value)
    h = src.probe(spec)
    assert h.connected is False and h.message == "HTTP 500"

    def broken(url, headers):
        raise ConnectionError("down at http://localhost:1 with fx-key-not-real")
    src, _ = _dp(broken)
    with pytest.raises(SourceDisconnected) as e:
        src.read(spec)
    assert e.value.reason == "요청 실패: ConnectionError" and "fx-key" not in e.value.reason
    with pytest.raises(SourceDisconnected, match="뷰 이름 미확인"):
        _dp(FakeTransport(), view=None)[0].read(spec)
    monkeypatch.delenv("MLP_FX_DP_KEY")
    with pytest.raises(SourceDisconnected, match="MLP_FX_DP_KEY"):
        _dp(FakeTransport())[0].read(spec)


# ── 등록부의 실 원천 항목 → source_disconnected 봉투 (D-13: 키 없음) ────────────
@pytest.mark.parametrize("code,role", [("ks", "train"), ("ks", "gateway"), ("ks", "actuals"),
                                       ("sw", "train"), ("sw", "gateway"), ("sw", "actuals")])
def test_registry_live_sources_fail_as_source_disconnected(code, role, monkeypatch):
    from mlcore.data import jobs

    cfg = _tenant_cfg(code)["sources"][role]
    for k, v in cfg.items():
        if k.endswith("_env") and v:
            monkeypatch.delenv(v, raising=False)
    with pytest.raises(SourceDisconnected) as e:
        jobs.read_frame(code, f"{code}.{'remaining_hours' if code == 'ks' else 'delta_e'}", source_role=role)
    assert e.value.kind == cfg["kind"]


@needs_db
def test_train_api_returns_source_disconnected_envelope(tmp_path, monkeypatch):
    import _dev2 as h

    m = h.make_tenant("ks", tmp_path)
    monkeypatch.setenv("MLP_TENANTS_DIR", str(h.tenants_base(m)))     # 등록부 루트 주입(학습기 쪽 load_and_merge 를 감싸지 않는다)
    k = h.keys(m)
    tc = h.client(m)
    for role in ("train",):                       # 계약 본문 source_role = demo | eval | train (api-contract §4)
        r = tc.post(f"/api/v1/tenants/{m.tenant.code}/tasks/{m.tenant.code}.remaining_hours/train",
                    headers=h.hdr(k["admin"]), json={"source_role": role})
        assert r.status_code == 503, r.text
        body = r.json()
        assert set(body) == {"error"} and body["error"]["code"] == "source_disconnected"
        assert "MLP_" not in str(body["error"].get("detail"))
    assert h.count("SELECT count(*) AS n FROM mlp_train_run WHERE tenant_id = %s", (m.tenant.code,)) == 0
