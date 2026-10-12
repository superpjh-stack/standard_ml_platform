"""QA-R2 — 해시 v2 · v1 스냅숏 호환: 저장소 var/snapshots(읽기만) 의 v1 파일을 임시 폴더로 복사해 load,
v2 파일 표지 제거(하향) · v1 파일 표지 추가(상향) · v1 파일 행 1개 변경 → 거부되는가."""
import shutil, sys, tempfile, random
from pathlib import Path
import pyarrow.parquet as pq
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.data import snapshot
src = sorted((ROOT / "var" / "snapshots").glob("*/*/*.parquet"))
v1 = [p for p in src if not (pq.read_schema(p).metadata or {}).get(snapshot.META_RULE)]
v2 = [p for p in src if (pq.read_schema(p).metadata or {}).get(snapshot.META_RULE)]
print(f"저장소 스냅숏 {len(src)} · v1 {len(v1)} · v2 {len(v2)}")
random.seed(0)
d = Path(tempfile.mkdtemp())
ok = bad = 0
for p in random.sample(v1, min(60, len(v1))) + random.sample(v2, min(20, len(v2))):
    q = d / p.relative_to(ROOT / "var" / "snapshots"); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy(p, q)
    try:
        snapshot.load(p.stem, base_dir=d); ok += 1
    except Exception as e:
        bad += 1; print("  load 실패", p.stem, type(e).__name__)
print(f"v1/v2 표본 load 성공 {ok} · 실패 {bad}")
def rewrite(p, md_fn, df_fn=None):
    t = pq.read_table(p); df = t.to_pandas()
    if df_fn: df = df_fn(df)
    import pyarrow as pa
    t2 = pa.Table.from_pandas(df, preserve_index=False).replace_schema_metadata(md_fn(dict(t.schema.metadata or {})))
    pq.write_table(t2, p)
def attempt(name, p, md_fn, df_fn=None):
    q = d / "atk" / p.relative_to(ROOT / "var" / "snapshots"); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy(p, q)
    rewrite(q, md_fn, df_fn)
    try:
        snapshot.load(p.stem, base_dir=d / "atk"); print(f"{name:40s} FAIL 적재됨")
    except snapshot.SnapshotCorrupt as e:
        print(f"{name:40s} PASS 거부 ({e})")
    shutil.rmtree(d / "atk")
def bump(df):
    c = [c for c in df.columns if df[c].dtype.kind == "f"][0]; df.loc[df.index[0], c] = df[c].iloc[0] + 1; return df
if v2:
    attempt("v2 표지 제거(v1 로 하향)", v2[0], lambda m: {k: v for k, v in m.items() if k != snapshot.META_RULE})
    attempt("v2 표지·기록해시 제거", v2[0], lambda m: {k: v for k, v in m.items() if k not in (snapshot.META_RULE, snapshot.META_KEY)})
    attempt("v2 값 1개 변경", v2[0], lambda m: m, bump)
if v1:
    attempt("v1 에 v2 표지 추가(상향)", v1[0], lambda m: {**m, snapshot.META_RULE: b"v2"})
    attempt("v1 값 1개 변경", v1[0], lambda m: m, bump)
    attempt("v1 값 변경 + 기록해시 제거", v1[0], lambda m: {k: v for k, v in m.items() if k != snapshot.META_KEY}, bump)
    attempt("v1 표지 값 'v0'(모르는 규칙)", v1[0], lambda m: {**m, snapshot.META_RULE: b"v0"})
shutil.rmtree(d)
