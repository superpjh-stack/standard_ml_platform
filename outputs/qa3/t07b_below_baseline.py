"""QA3 t07b (t07 뒤 이어서 — 기준선 미달만) — 드리프트 fixture → 감시 → 재학습 후보 → 승인 요청, production 불변. 기준선 미달 후보는 stage 하지 않는다.
ml_qa3_db · 실제 등록부 ks (MLP_DB_DSN 은 env.sh). 기준선 미달은 QA DB 에서 그 후보 행의 beats_baseline 을 false 로 바꿔 만든다."""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg

from qa_lib import check, dump
from mlcore.monitor import daily, retrain
from mlcore.serve import training

ROOT = Path(__file__).resolve().parents[2]
DSN = "dbname=ml_qa3_db host=/tmp"
T = "ks.remaining_hours"


def q(sql, p=()):
    with psycopg.connect(DSN) as c:
        cur = c.execute(sql, p)
        return cur.fetchall() if cur.description else None


def stages():
    return dict(q("SELECT version, stage FROM mlp_model_version WHERE tenant_id='ks' AND task_id=%s", (T,)))


def prod():
    return [v for v, s in stages().items() if s == "production"]


p0 = prod()
from datetime import date
drift = pd.read_parquet(ROOT / "tests/fixtures/ks/drift.parquet")
summ = {"run_id": None}
# 기준선 미달 후보
rows2 = daily.run_daily("ks", date(2026, 9, 4), frames={T: drift}, retrain_source="eval")
s2 = [r for r in rows2 if r["metric"] == "_summary" and r["task_id"] == T][0]
check("G-M09", "다음 날 같은 드리프트 → 재접수(같은 스냅숏이면 재사용)", bool(s2["run_id"]), f"run_id={s2['run_id']} 첫날={summ['run_id']}", warn=True)
if False:
    _, ref2 = training.run_and_register(s2["run_id"])
    vbad = ref2.version
else:   # 같은 스냅숏이라 재사용 — 감시 접수 run 을 하나 더 만든다(seed 다르게)
    from mlcore.data import jobs
    out = jobs.submit("ks", T, actor="monitor", source_role="eval", seed=777)
    _, ref2 = training.run_and_register(out)
    vbad = ref2.version
q("UPDATE mlp_model_version SET beats_baseline=false WHERE tenant_id='ks' AND task_id=%s AND version=%s", (T, vbad))
got2 = retrain.request_approvals("ks", T)
item = [g for g in got2 if g["version"] == vbad]
check("G-M09", "기준선 미달 후보 → stage 0 · 승인 요청 0", stages()[vbad] == "candidate" and item and item[0]["approval_id"] is None and prod() == p0,
      f"{vbad}={stages()[vbad]} {item} production={prod()}")
n = q("SELECT count(*) FROM mlp_approval WHERE ref_id=%s AND task_id=%s", (vbad, T))[0][0]
check("G-M09", "기준선 미달 후보의 mlp_approval 0", n == 0, f"{n}")
dump(sys.argv[1])
