"""QA1 스냅숏 해시 — 같은 내용이면 같은 해시(안정성), 내용이 다르면 다른 해시(민감도).
실행: source outputs/qa-r2/qa1/env.sh && uv run python outputs/qa-r2/qa1/snapshot_hash_probe.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from mlcore.data import jobs, snapshot
from mlcore.data.frame import standardize
from mlcore.data.sources import ReadSpec
from tests._dev1 import FEATS, raw_rows, std_frame, task

_, t, f0, _, _ = jobs.read_frame("ks", "ks.remaining_hours")
H = snapshot.content_sha256
h0 = H(f0)
num = [c for c in f0.columns if pd.api.types.is_float_dtype(f0[c]) and c != "target"][0]
cat = [c for c in f0.columns if f0[c].dtype == object and c not in ("tenant_id", "task_id", "entity_id", "_source", "_source_ref", "group")]
same, diff = [], []
same.append(("열 순서 역순", f0[list(reversed(f0.columns))]))
same.append(("행 섞기", f0.sample(frac=1, random_state=1)))
same.append(("ts 를 UTC 로 표현(같은 순간)", f0.assign(ts=f0["ts"].dt.tz_convert("UTC"))))
f_int = f0.copy(); f_int[num] = f_int[num].round(0); f_int2 = f_int.copy(); f_int2[num] = f_int2[num].astype("Int64")
same.append(("정수 dtype vs 실수 dtype(같은 값)", (f_int, f_int2)))
same.append(("parquet 왕복", None))
d = f0.copy(); d.loc[5, num] = d.loc[5, num] + 1e-12; diff.append(("값 1e-12 변경", d))
d = f0.copy(); d.loc[5, num] = np.nan; diff.append(("값 → 결측", d))
d = f0.copy(); d["extra"] = 0.0; diff.append(("열 추가", d))
d = f0.copy(); d = d.drop(index=3); diff.append(("행 삭제", d))
d = f0.copy(); d.loc[5, "target"] = d.loc[5, "target"] + 0.5; diff.append(("목표 변경", d))
if cat:
    d = f0.copy(); d.loc[5, cat[0]] = str(d.loc[5, cat[0]]) + "x"; diff.append(("범주 문자열 변경", d))
d = f0.copy(); d.loc[5, "_source_ref"] = "other"; diff.append(("_source_ref 변경", d))
d = f0.copy(); d = d.rename(columns={num: num + "_r"}); diff.append(("열 이름 변경", d))
d = f0.copy(); d.loc[5, num] = 0.0; e = d.copy(); e.loc[5, num] = -0.0
diff.append(("0.0 vs -0.0 (다르게 나와도 무방, 기록용)", (d, e)))
# 의미 차이인데 같은 해시가 나는가: 범주 열 값 '1' (문자) vs 수치 1.0
a = f0.copy(); a[num] = a[num].round(0); b = a.copy(); b[num] = b[num].map(lambda v: str(v) if pd.notna(v) else None).astype(object)
diff.append(("수치 열 → 같은 값의 문자열 열(dtype 변경)", (a, b)))
# 중복 (ts, entity_id) 행 — 순서만 바꿈
d = f0.copy(); dup = d.iloc[[7]].copy(); dup[num] = dup[num] + 1; d2 = pd.concat([d, dup], ignore_index=True)
d3 = pd.concat([d.iloc[:7], dup, d.iloc[7:]], ignore_index=True)
same.append(("같은 (ts,entity_id) 중복행 순서만 다름", (d2, d3)))

import tempfile
for name, x in same:
    if x is None:
        with tempfile.TemporaryDirectory() as dd:
            s = snapshot.freeze(f0, tenant_id="ks", task=t, source_ref={}, synthetic=True, base_dir=Path(dd))
            ok = H(snapshot.load(s.snapshot_id, base_dir=Path(dd))) == h0 and s.sha256 == h0
    elif isinstance(x, tuple):
        ok = H(x[0]) == H(x[1])
    else:
        ok = H(x) == h0
    print(f"G-M06  스냅숏 안정 {name:38s} {'PASS' if ok else 'FAIL'}  같은 해시={ok}")
for name, x in diff:
    if isinstance(x, tuple):
        ok = H(x[0]) != H(x[1])
    else:
        ok = H(x) != h0
    st = "PASS" if ok else ("WARN" if "기록용" in name or "dtype" in name else "FAIL")
    print(f"G-M06  스냅숏 민감 {name:38s} {st}  다른 해시={ok}")

# entity_id 가 없는 원천: 같은 원천 행을 다른 순서로 받으면?
t2 = task()
r = raw_rows(50, 1).drop(columns=["entity_id"])
a = standardize(r, ReadSpec(tenant_id="tt", task=t2, features=FEATS), kind="csv", source_ref="x")
b = standardize(r.sample(frac=1, random_state=2), ReadSpec(tenant_id="tt", task=t2, features=FEATS), kind="csv", source_ref="x")
print(f"G-M06  스냅숏 안정 entity_id 없는 원천 · 행 순서만 다름          {'PASS' if H(a) == H(b) else 'WARN'}  같은 해시={H(a) == H(b)} (ROW-n 이 원천 행 순서로 붙는다)")
