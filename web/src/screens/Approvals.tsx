// 화면 5 — 승인 대기열 (contracts/screen-map.md). 모델 · 추천 승인 카드(지표 비교 · 그림자 예측 차이 · 사유 입력) · 409 처리.
// production 은 POST /approvals/{id}/decide → approval.decide() 만 바꾼다.
import {Fragment, useCallback, useEffect, useState} from 'react';
import {
  api, ApiError, ConnectionBar, ErrorBox, fmt, MetricTable, StateBadge, tpath, useConnection,
} from '../components';
import type {Candidate, ListResponse, Metric} from '../components';

type Approval = {
  approval_id: string; task_id: string; kind: 'model' | 'recommendation' | string; ref_id: string;
  action: 'promote' | 'rollback' | 'apply' | string; approver_role: string; state: string;
  requested_by: string; requested_at: string | null; expires_at: string | null;
  decided_by: string | null; decided_at: string | null; reason: string | null; evidence: any;
};

const ACTION: Record<string, string> = {promote: '운영 승격', rollback: '되돌리기', apply: '추천 확인', confirm: '확정'};

export default function Approvals() {
  const [c] = useConnection();
  const [state, setState] = useState('pending');
  const [items, setItems] = useState<Approval[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (more?: string | null) => {
    if (!c.tenant || !c.key) { setItems([]); return; }
    setLoading(true); setErr(null);
    const qs = [state !== 'all' ? `state=${state}` : '', more ? `cursor=${encodeURIComponent(more)}` : ''].filter(Boolean).join('&');
    try {
      const r = await api<ListResponse<Approval>>('GET', tpath(`/approvals${qs ? `?${qs}` : ''}`));
      setItems(prev => more ? [...prev, ...r.items] : r.items);
      setCursor(r.next_cursor);
    } catch (e) { setErr(e); if (!more) setItems([]); } finally { setLoading(false); }
  }, [c.tenant, c.key, state]);

  useEffect(() => { void load(null); }, [load]);

  return <section>
    <h1>5. 승인 대기열</h1>
    <ConnectionBar/>
    <div className="row">
      <label>상태 <select value={state} onChange={e => setState(e.target.value)}>
        <option value="pending">대기</option><option value="approved">승인</option><option value="rejected">반려</option>
        <option value="expired">만료</option><option value="all">전체</option>
      </select></label>
      <button onClick={() => load(null)} disabled={loading}>새로 고침</button>
    </div>
    <ErrorBox error={err}/>
    {!items.length && !loading && !err && <p className="muted">승인 항목이 없습니다</p>}
    {items.map(a => <ApprovalCard key={a.approval_id} a={a} onDone={() => load(null)}/>)}
    {cursor && <button onClick={() => load(cursor)} disabled={loading}>더 보기</button>}
  </section>;
}

function ApprovalCard({a, onDone}: {a: Approval; onDone: () => void}) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const needReason = a.action === 'rollback';

  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(true); setErr(null);
    try {
      const r = await api<{approval_id: string; state: string; production_version: string | null}>(
        'POST', `/approvals/${encodeURIComponent(a.approval_id)}/decide`, {decision, reason: reason.trim() || null});
      setDone(`${r.state === 'approved' ? '승인' : '반려'}됨${r.production_version ? ` · 운영 버전 ${r.production_version}` : ''}`);
      onDone();
    } catch (e) {
      setErr(e);
      if (e instanceof ApiError && e.code === 'already_decided') onDone();
    } finally { setBusy(false); }
  };

  return <div className="card" data-approval={a.approval_id} data-kind={a.kind}>
    <div className="row">
      <StateBadge state={a.state}/>
      <strong>{a.kind === 'model' ? '모델' : a.kind === 'recommendation' ? '추천' : a.kind} · {ACTION[a.action] ?? a.action}</strong>
      <span>{a.task_id} · {a.ref_id}</span>
      <span className="muted">담당 {a.approver_role}</span>
    </div>
    <dl className="kv" style={{marginTop: 6}}>
      <dt>요청</dt><dd>{a.requested_by} · {a.requested_at ?? '—'}</dd>
      {a.expires_at && <><dt>만료</dt><dd>{a.expires_at}</dd></>}
      {a.reason && <><dt>요청 사유</dt><dd>{a.reason}</dd></>}
      {a.decided_by && <><dt>결정</dt><dd>{a.decided_by} · {a.decided_at}</dd></>}
    </dl>
    {a.kind === 'model' ? <ModelEvidence ev={a.evidence}/> : a.kind === 'recommendation' ? <RecEvidence ev={a.evidence}/> : null}
    {a.state === 'pending' && <div style={{marginTop: 8}}>
      <label style={{display: 'block'}}>결정 사유{needReason ? ' (필수)' : ''}
        <textarea rows={2} style={{width: '100%', boxSizing: 'border-box'}} maxLength={2000}
                  value={reason} onChange={e => setReason(e.target.value)}/></label>
      <div className="row" style={{marginTop: 6}}>
        <button className="primary" disabled={busy || (needReason && !reason.trim())} onClick={() => decide('approve')}>승인</button>
        <button className="danger" disabled={busy} onClick={() => decide('reject')}>반려</button>
      </div>
    </div>}
    {done && <p className="badge badge-ok">{done}</p>}
    <ErrorBox error={err}/>
  </div>;
}

function ModelEvidence({ev}: {ev: any}) {
  const target = ev?.target ?? {};
  const prod = ev?.production ?? null;
  const shadow = ev?.shadow ?? null;
  return <div>
    <p className="muted">대상 {target.version ?? '—'}{target.synthetic ? ' (합성)' : ''} · 현재 운영 {prod?.version ?? '없음'}</p>
    <MetricTable metrics={target.metrics as Record<string, Metric>} caption="시험 지표 (비교 대상 = 현재 운영)"
                 compare={prod ? prod.metrics as Record<string, Metric> : null}/>
    <h4>그림자 예측 차이</h4>
    {shadow ? <dl className="kv"><dt>건수</dt><dd>{fmt(shadow.n)}</dd><dt>평균 절대 차이</dt><dd>{fmt(shadow.mean_abs_diff)}</dd>
      <dt>최대 절대 차이</dt><dd>{fmt(shadow.max_abs_diff)}</dd></dl> : <p className="muted">그림자 비교 없음</p>}
  </div>;
}

function RecEvidence({ev}: {ev: any}) {
  const best: Candidate | undefined = ev?.best;
  return <div>
    <p className="muted">추천 {ev?.rec_id ?? '—'} · {ev?.feasible ? '제약 충족' : '제약 미충족(least_violation)'}
      {ev?.objective ? ` · 목적 ${typeof ev.objective === 'string' ? ev.objective : ev.objective.name}` : ''}
      {ev?.uses?.length ? ` · 의존 ${ev.uses.map((u: any) => `${u.task}@${u.version}`).join(', ')}` : ''}</p>
    {best && <div className="cols">
      <dl className="kv">{Object.entries(best.conditions).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{fmt(v)}</dd></Fragment>)}</dl>
      <dl className="kv">{Object.entries(best.predictions).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{fmt(v)}</dd></Fragment>)}</dl>
    </div>}
    {best && <table className="grid"><thead><tr><th>제약</th><th>좌변</th><th>우변</th><th>충족</th></tr></thead>
      <tbody>{best.constraints.map(k => <tr key={k.name}><td>{k.name}</td><td>{fmt(k.lhs)}</td><td>{fmt(k.rhs)}</td>
        <td>{k.satisfied ? '충족' : '미충족'}</td></tr>)}</tbody></table>}
  </div>;
}
