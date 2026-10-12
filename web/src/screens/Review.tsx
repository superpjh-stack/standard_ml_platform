// 화면 8 — 검토 대기열 (contracts/screen-map.md · B09). 대기열은 시험 구간 잔차 · 실측이 붙은 운영 잔차로만 만든다.
// 검토 결과(확인 · 오탐 + 메모)는 approver(자기 과제) · admin. 닫힌 항목 재검토는 409 already_decided 를 그대로 보인다.
import {useState} from 'react';
import {
  api, ApiError, ConnectionBar, ErrorBox, fmt, IdLink, KeyValue, StateBadge, TaskPicker, tpath, useConnection, useList,
} from '../components';
import type {ReviewItem} from '../components';

const RULE: Record<string, string> = {abs_residual_ge: '|잔차| ≥ 임계값', top_quantile: '잔차 상위 분위(검증 구간 임계값)'};
const ORIGIN: Record<string, string> = {test_split: '시험 구간 잔차', live_residual: '운영 잔차(실측)'};

export default function Review() {
  const [c] = useConnection();
  const [task, setTask] = useState('');
  const [state, setState] = useState('open');
  const [outcome, setOutcome] = useState<{id: string; text?: string; error?: unknown} | null>(null);
  const path = c.tenant && c.key && task
    ? tpath(`/tasks/${encodeURIComponent(task)}/review${state !== 'all' ? `?state=${state}` : ''}`) : null;
  const list = useList<ReviewItem>(path, [c.tenant, c.key]);

  return <section>
    <h1>8. 검토 대기열</h1>
    <ConnectionBar/>
    <div className="row">
      <TaskPicker value={task} onChange={t => { setTask(t); setOutcome(null); }} types={['review_queue']}/>
      <label>상태 <select value={state} onChange={e => setState(e.target.value)}>
        <option value="open">검토 대기</option><option value="confirmed_issue">문제 확인</option>
        <option value="false_alarm">오탐</option><option value="all">전체</option>
      </select></label>
      {list.total !== null && <span className="muted">총 {list.total}건</span>}
    </div>
    {!task && <p className="muted">검토 대기열 과제가 없습니다</p>}
    {outcome && <div className="card" data-testid="review-outcome">
      {outcome.text && <p>{outcome.text}</p>}
      <ErrorBox error={outcome.error}/>
    </div>}
    <ErrorBox error={list.error}/>
    {task && !list.loading && !list.error && list.items.length === 0 && <p className="muted" data-testid="review-empty">검토할 항목 없음</p>}
    {list.items.map(it => <ReviewCard key={it.item_id} item={it}
      onDone={o => { setOutcome({id: it.item_id, ...o}); void list.reload(); }}/>)}
    {list.next && <button onClick={() => void list.loadMore()} disabled={list.loading}>더 보기</button>}
  </section>;
}

function ReviewCard({item, onDone}: {item: ReviewItem; onDone: (o: {text?: string; error?: unknown}) => void}) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const decide = async (state: 'confirmed_issue' | 'false_alarm') => {
    setBusy(true); setErr(null);
    try {
      await api('PATCH', tpath(`/tasks/${encodeURIComponent(item.task)}/review/${encodeURIComponent(item.item_id)}`), {state, note});
      onDone({text: `${item.item_id} → ${state === 'confirmed_issue' ? '문제 확인' : '오탐'}`});
    } catch (e) {
      if (e instanceof ApiError && e.code === 'already_decided') onDone({text: `${item.item_id} 은(는) 이미 검토되었습니다`, error: e});
      else setErr(e);
    } finally { setBusy(false); }
  };
  return <div className="card" data-item={item.item_id} data-origin={item.origin}>
    <div className="row">
      <StateBadge state={item.state}/>
      <strong>{item.entity_id}</strong>
      <span>|잔차| {fmt(Math.abs(item.residual))}</span>
      <span className="muted">{RULE[item.rule] ?? item.rule} · 임계값 {fmt(item.threshold)}</span>
      <span className="badge badge-needs_approval">{ORIGIN[item.origin] ?? item.origin}</span>
    </div>
    <KeyValue rows={[
      ['예측', fmt(item.predicted)], ['실측', fmt(item.actual)], ['잔차 (실측 − 예측)', fmt(item.residual)],
      ['사유', item.reason], ['모델 버전', item.model_version], ['예측 ID', <IdLink key="p" id={item.prediction_id}/>],
      ['생성', item.created_at],
      ...(item.decided_by ? [['검토', `${item.decided_by} · ${item.decided_at ?? '—'}`] as [string, string]] : []),
      ...(item.note ? [['메모', item.note] as [string, string]] : []),
    ]}/>
    {item.state === 'open' && <div style={{marginTop: 8}}>
      <label style={{display: 'block'}}>검토 메모 (필수)
        <textarea rows={2} style={{width: '100%'}} maxLength={2000} value={note} onChange={e => setNote(e.target.value)}/></label>
      <div className="row" style={{marginTop: 6}}>
        <button className="primary" disabled={busy || !note.trim()} onClick={() => decide('confirmed_issue')}>문제 확인</button>
        <button className="danger" disabled={busy || !note.trim()} onClick={() => decide('false_alarm')}>오탐</button>
      </div>
    </div>}
    <ErrorBox error={err}/>
  </div>;
}
