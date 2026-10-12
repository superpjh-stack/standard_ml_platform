"""QA3 t07 — 드리프트 fixture → 감시 → 재학습 후보 → 승인 요청, production 불변. 기준선 미달 후보는 stage 하지 않는다.
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
drift = pd.read_parquet(ROOT / "tests/fixtures/ks/drift.parquet")
rows = daily.run_daily("ks", date(2026, 9, 3), frames={T: drift}, retrain_source="eval")
summ = [r for r in rows if r["metric"] == "_summary" and r["task_id"] == T][0]
psi = {r["feature"]: (round(r["value"], 4), r["level"]) for r in rows if r["metric"] == "psi" and r["task_id"] == T}
check("G-M09", "드리프트 fixture → 재학습 접수 · production 불변", summ["retrain"] and summ["run_id"] and prod() == p0,
      f"사유={summ.get('reasons')} psi.vibration={psi.get('vibration')} production {p0}→{prod()}")
res, ref = training.run_and_register(summ["run_id"])
check("G-M09", "작업자 등록 → candidate · production 불변", ref is not None and ref.stage == "candidate" and prod() == p0, f"{ref.version if ref else None} {stages()}")
got = retrain.request_approvals("ks", T)
apr = q("SELECT state, requested_by FROM mlp_approval WHERE approval_id=%s", (got[0]["approval_id"],)) if got and got[0]["approval_id"] else None
check("G-M09", "감시 → staging + 승인 요청(pending, monitor) · production 불변", apr == [("pending", "monitor")] and stages()[ref.version] == "staging" and prod() == p0,
      f"{got} {apr} {stages()}")
check("G-M09", "감시 두 번째 실행 → 새 요청 없음", retrain.request_approvals("ks", T) == [], "")
# 기준선 미달 후보
rows2 = daily.run_daily("ks", date(2026, 9, 4), frames={T: drift}, retrain_source="eval")
s2 = [r for r in rows2 if r["metric"] == "_summary" and r["task_id"] == T][0]
check("G-M09", "다음 날 같은 드리프트 → 재접수(같은 스냅숏이면 재사용)", bool(s2["run_id"]), f"run_id={s2['run_id']} 첫날={summ['run_id']}", warn=True)
if s2["run_id"] and s2["run_id"] != summ["run_id"]:
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
