// 화면 1 — 회사 · 과제 개요 (contracts/screen-map.md · 개발3). B01 health · B02 tasks · B06 overview · B12 records.
// 회사 · 과제 이름은 API 에서만 온다(회사 화면 코드 0). production 이 없으면 "운영 모델 없음 (model_not_ready)" 그대로 보인다.
import {useEffect, useState} from 'react';
import {
  api, ConnectionBar, ErrorBox, fmt, SyntheticBadge, tpath, useApi, useConnection,
} from '../components';
import type {ListResponse} from '../components';

type TaskRow = {
  task: string; type: string; title?: string | null; uses?: string[] | null;
  production: {version: string; algo: string; trained_at: string; synthetic: boolean} | null;
};
type TaskList = ListResponse<TaskRow> & {tenant?: {code: string; name?: string; pack?: string; mode?: string};
  disabled?: {task: string; reason: string}[]};
type Alert = {metric: string; feature: string | null; value: number | null; level: string};
type OverviewBody = {
  task: string; type: string; model_ready: boolean;
  production: TaskRow['production']; test_metrics: Record<string, number | null> | null;
  baseline: Record<string, number | null> | null; uses: {task: string; version: string | null; synthetic: boolean | null}[] | null;
  predictions_yesterday: number; pending_approvals: number;
  monitor: {level: string | null; day: string | null; alerts: Alert[]; note?: string};
};
type Health = {status: string; db: boolean; version: string; tenant: string | null;
  tasks: {task: string; model_ready: boolean; version: string | null}[]};

const LEVEL: Record<string, [string, string]> = {ok: ['정상', 'ok'], warn: ['경고', 'watch'], retrain: ['재학습 후보', 'review']};
const PRIMARY: Record<string, string> = {regression: 'mae', risk: 'brier', anomaly: 'flag_rate'};

export function LevelBadge({level}: {level: string | null | undefined}) {
  if (!level) return <span className="badge badge-out_of_range">감시 기록 없음</span>;
  const [label, cls] = LEVEL[level] ?? [level, 'watch'];
  return <span className={`badge badge-${cls}`} data-level={level}>{label}</span>;
}

export default function Overview() {
  const [c] = useConnection();
  const ready = !!(c.tenant && c.key);
  const health = useApi<Health>('/health', []);
  const tasks = useApi<TaskList>(ready ? tpath('/tasks') : null, [c.tenant, c.key]);
  const [ov, setOv] = useState<Record<string, OverviewBody | Error>>({});

  useEffect(() => {
    setOv({});
    (tasks.data?.items ?? []).forEach(t => {
      api<OverviewBody>('GET', tpath(`/tasks/${encodeURIComponent(t.task)}/overview`))
        .then(b => setOv(o => ({...o, [t.task]: b})))
        .catch(e => setOv(o => ({...o, [t.task]: e as Error})));
    });
  }, [tasks.data]);

  const ten = tasks.data?.tenant;
  return <section>
    <h1>1. 회사 · 과제 개요</h1>
    <ConnectionBar/>
    <div className="card">
      <div className="row">
        <strong>서버</strong>
        {health.data ? <>
          <span className={`badge badge-${health.data.status === 'ok' ? 'ok' : 'review'}`}>{health.data.status}</span>
          <span className="muted">DB {health.data.db ? '연결' : '미연결'} · 버전 {health.data.version}</span>
        </> : <ErrorBox error={health.error}/>}
        {ten && <span className="muted">회사 {ten.name ?? ten.code} ({ten.code}) · 팩 {ten.pack} · 모드 {ten.mode}</span>}
      </div>
    </div>
    <ErrorBox error={tasks.error}/>
    {tasks.data && <div className="card">
      <h2>과제 {tasks.data.items.length}</h2>
      <div className="table-wrap"><table className="grid" data-testid="overview-tasks">
        <thead><tr><th>과제</th><th>유형</th><th>운영 버전</th><th>시험 지표 / 기준선</th><th>어제 예측</th><th>승인 대기</th><th>감시</th></tr></thead>
        <tbody>{tasks.data.items.map(t => <TaskLine key={t.task} t={t} o={ov[t.task]}/>)}</tbody>
      </table></div>
      {(tasks.data.disabled ?? []).length > 0 && <p className="error">꺼진 과제: {tasks.data.disabled!.map(d => `${d.task} (${d.reason})`).join(', ')}</p>}
    </div>}
    {ready && tasks.data && <Records tasks={tasks.data.items}/>}
  </section>;
}

function TaskLine({t, o}: {t: TaskRow; o: OverviewBody | Error | undefined}) {
  const body = o && !(o instanceof Error) ? o : null;
  const key = PRIMARY[t.type];
  const prod = t.production;
  return <tr data-task={t.task}>
    <td><strong>{t.title ?? t.task}</strong><div className="muted">{t.task}</div></td>
    <td>{t.type}</td>
    <td>{t.type === 'optimize'
      ? (body?.uses ?? []).map(u => <div key={u.task}>{u.task}: {u.version ?? <span className="badge badge-rejected">운영 모델 없음 (model_not_ready)</span>} <SyntheticBadge synthetic={u.synthetic}/></div>)
      : prod ? <>{prod.version} · {prod.algo} <SyntheticBadge synthetic={prod.synthetic}/></>
        : <span className="badge badge-rejected">운영 모델 없음 (model_not_ready)</span>}</td>
    <td>{body?.test_metrics && key ? `${key} ${fmt(body.test_metrics[key])} / ${fmt(body.baseline?.[key])}` : '—'}</td>
    <td>{body ? body.predictions_yesterday : '…'}</td>
    <td>{body ? body.pending_approvals : '…'}</td>
    <td>{o instanceof Error ? <ErrorBox error={o}/> : body ? <>
      <LevelBadge level={body.monitor.level}/>
      {body.monitor.alerts.slice(0, 3).map((a, i) => <div key={i} className="muted">{a.metric}{a.feature ? `:${a.feature}` : ''} {fmt(a.value, 3)}</div>)}
    </> : '…'}</td>
  </tr>;
}

// ── 대상(LOT) 데이터 — B12 records. CSV 는 BOM · 수식 주입 방지 ─────────────────────────────
type RecordsBody = ListResponse<Record<string, unknown>>;

export function csvCell(v: unknown): string {
  let s = v === null || v === undefined ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;                    // 수식 주입 방지
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function Records({tasks}: {tasks: TaskRow[]}) {
  const learned = tasks.filter(t => t.type !== 'optimize');
  const [task, setTask] = useState(learned[0]?.task ?? '');
  const [search, setSearch] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [stack, setStack] = useState<(string | null)[]>([]);
  const q = new URLSearchParams({limit: '20', ...(search ? {search} : {}), ...(cursor ? {cursor} : {})});
  const rec = useApi<RecordsBody>(task ? tpath(`/tasks/${encodeURIComponent(task)}/records?${q}`) : null, [task, search, cursor]);
  const cols = rec.data?.items.length ? Object.keys(rec.data.items[0]).filter(k => !['tenant_id', 'task_id', '_source_ref'].includes(k)) : [];
  const download = () => {
    if (!rec.data) return;
    const lines = [cols.map(csvCell).join(','), ...rec.data.items.map(r => cols.map(k => csvCell(r[k])).join(','))];
    const blob = new Blob(['﻿' + lines.join('\n')], {type: 'text/csv;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `${task}-records.csv`; a.click(); URL.revokeObjectURL(a.href);
  };
  return <div className="card">
    <h2>대상 데이터</h2>
    <div className="row">
      <label className="picker">과제 <select value={task} onChange={e => { setTask(e.target.value); setCursor(null); setStack([]); }}>
        {learned.map(t => <option key={t.task} value={t.task}>{t.title ?? t.task}</option>)}
      </select></label>
      <label>대상 ID 검색 <input value={search} maxLength={60} onChange={e => { setSearch(e.target.value); setCursor(null); setStack([]); }}/></label>
      <span className="muted">{rec.data ? `${rec.data.total ?? rec.data.items.length}건` : ''}</span>
      <button disabled={!stack.length} onClick={() => { const s = [...stack]; setCursor(s.pop() ?? null); setStack(s); }}>이전</button>
      <button disabled={!rec.data?.next_cursor} onClick={() => { setStack([...stack, cursor]); setCursor(rec.data!.next_cursor); }}>다음</button>
      <button disabled={!rec.data?.items.length} onClick={download}>CSV</button>
    </div>
    <ErrorBox error={rec.error}/>
    {rec.data && (rec.data.items.length ? <div className="table-wrap"><table className="grid" data-testid="records">
      <thead><tr>{cols.map(k => <th key={k}>{k}</th>)}</tr></thead>
      <tbody>{rec.data.items.map((r, i) => <tr key={i}>{cols.map(k => <td key={k}>{r[k] === null ? '—' : typeof r[k] === 'number' ? fmt(r[k], 3) : String(r[k])}</td>)}</tr>)}</tbody>
    </table></div> : <p className="muted">결과 없음</p>)}
  </div>;
}
