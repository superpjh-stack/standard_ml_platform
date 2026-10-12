// 화면 10 — 감사 · 예측 추적 (contracts/screen-map.md · B15, admin). 예측 → 모델 버전 → run → 스냅숏 → 원천 소스 · 실측.
// 끊긴 고리는 "원천 기록 없음" 으로 보인다(지어내지 않는다). 감사 근거는 예측 기록의 호출자 · 채널 · 시각.
import {useEffect, useState} from 'react';
import {api, ConnectionBar, ErrorBox, KeyValue, SyntheticBadge, StateBadge, useConnection} from '../components';

type Trace = {
  prediction: {prediction_id: string; task: string; version: string; entity_id: string | null; status: string; caller: string;
    channel: string; synthetic: boolean; ts: string | null; inputs: Record<string, unknown>; outputs: Record<string, unknown>} | null;
  model: {version: string; stage: string; algo: string; artifact_sha256: string} | null;
  run: {run_id: string; config_hash: string; seed: number | null; code_version: string; started_at?: string | null; finished_at?: string | null} | null;
  snapshot: {snapshot_id: string; sha256: string; rows: number; ts_from: string | null; ts_to: string | null; synthetic: boolean} | null;
  sources: {kind: string | null; ref: unknown}[] | null;
  actuals: {actual_id: number | string; entity_id: string; value: number; observed_at: string | null; source: string}[] | null;
};

const PID = /^prd_[0-9A-Z]{26}$/;
const MISSING = <span className="muted" data-missing="true">원천 기록 없음</span>;

function initialId(): string {
  try { return new URLSearchParams(window.location.search).get('prediction_id') ?? ''; } catch { return ''; }
}

export default function TraceScreen() {
  const [c] = useConnection();
  const [pid, setPid] = useState(initialId());
  const [data, setData] = useState<Trace | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = async (id: string) => {
    setBusy(true); setErr(null); setData(null);
    try { setData(await api<Trace>('GET', `/predictions/${encodeURIComponent(id)}/trace`)); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  useEffect(() => { if (PID.test(pid) && c.key) void load(pid); }, [c.key]);   // eslint-disable-line react-hooks/exhaustive-deps

  const p = data?.prediction ?? null;
  return <section>
    <h1>10. 감사 · 예측 추적</h1>
    <ConnectionBar/>
    <form className="row" onSubmit={e => { e.preventDefault(); if (PID.test(pid.trim())) void load(pid.trim()); }}>
      <label>예측 ID <input value={pid} size={34} maxLength={40} placeholder="prd_…" onChange={e => setPid(e.target.value)}/></label>
      <button className="primary" type="submit" disabled={busy || !PID.test(pid.trim())}>추적</button>
      {pid && !PID.test(pid.trim()) && <span className="muted">형식: prd_ + 26자</span>}
    </form>
    <ErrorBox error={err}/>
    {data && <div data-testid="trace-result">
      <div className="card"><h2>예측 · 감사 근거</h2>
        {p ? <KeyValue rows={[
          ['예측 ID', <code key="i">{p.prediction_id}</code>], ['과제', p.task], ['상태', p.status], ['개체', p.entity_id ?? '—'],
          ['호출자', p.caller], ['채널', p.channel], ['시각', p.ts ?? '—'], ['합성', <SyntheticBadge key="s" synthetic={p.synthetic}/>],
        ]}/> : MISSING}
      </div>
      <div className="cols">
        <div className="card"><h2>모델 버전</h2>
          {data.model ? <KeyValue rows={[['버전', data.model.version], ['단계', <StateBadge key="st" state={data.model.stage}/>],
            ['알고리즘', data.model.algo], ['산출물 sha256', <code key="a">{data.model.artifact_sha256}</code>]]}/> : MISSING}
        </div>
        <div className="card"><h2>학습 실행</h2>
          {data.run ? <KeyValue rows={[['run', data.run.run_id], ['설정 해시', <code key="c">{data.run.config_hash}</code>],
            ['시드', String(data.run.seed ?? '—')], ['코드 버전', data.run.code_version],
            ['끝난 시각', data.run.finished_at ?? '—']]}/> : MISSING}
        </div>
        <div className="card"><h2>스냅숏</h2>
          {data.snapshot ? <KeyValue rows={[['스냅숏', data.snapshot.snapshot_id], ['sha256', <code key="h">{data.snapshot.sha256}</code>],
            ['행', String(data.snapshot.rows)], ['기간', `${data.snapshot.ts_from ?? '—'} ~ ${data.snapshot.ts_to ?? '—'}`],
            ['합성', data.snapshot.synthetic ? '예' : '아니오']]}/> : MISSING}
        </div>
      </div>
      <div className="card"><h2>원천 소스</h2>
        {data.sources && data.sources.length ? <ul>{data.sources.map((s, i) =>
          <li key={i}><code>{s.kind ?? '종류 없음'}</code> — <code style={{overflowWrap: 'anywhere'}}>{typeof s.ref === 'string' ? s.ref : JSON.stringify(s.ref)}</code></li>)}</ul> : MISSING}
      </div>
      <div className="card"><h2>실측</h2>
        {data.actuals && data.actuals.length ? <table className="grid"><thead><tr><th>id</th><th>개체</th><th>값</th><th>관측 시각</th><th>출처</th></tr></thead>
          <tbody>{data.actuals.map(a => <tr key={String(a.actual_id)}><td>{String(a.actual_id)}</td><td>{a.entity_id}</td><td>{String(a.value)}</td>
            <td>{a.observed_at ?? '—'}</td><td>{a.source}</td></tr>)}</tbody></table>
          : <p className="muted">실측 없음</p>}
      </div>
    </div>}
  </section>;
}
