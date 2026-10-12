// 화면 6 — 감시 (contracts/screen-map.md · 개발3). B14 monitor · doctor.
// 변수별 PSI · 범위 밖 · 결측 추이, 실측 성능 추이(없으면 "실측 없음"), 재학습 후보 → 승인 대기열 링크.
// 감시는 후보까지만 만든다 — 이 화면에는 승격 버튼이 없다(승인은 화면 5).
import {useState} from 'react';
import {ConnectionBar, ErrorBox, fmt, StateBadge, TaskPicker, tpath, useApi, useConnection} from '../components';
import {LevelBadge} from './Overview';

type Item = {day: string; metric: string; feature: string | null; value: number | null; level: string;
  detail: Record<string, unknown>};
type Cand = {version: string; stage: string; beats_baseline: boolean; run_id: string; approval_id: string | null;
  approval_state: string | null; created_at: string};
type MonitorBody = {items: Item[]; next_cursor: string | null; last_day: string | null; retrain_candidates: Cand[]};
type Source = {role: string; kind: string; status: string; rows: number | null; ts_from: string | null; ts_to: string | null;
  coverage: number | null; missing_rates: Record<string, number>; target: string | null; message: string};

const METRIC_LABEL: Record<string, string> = {psi: 'PSI', oor_rate: '학습 범위 밖 비율', missing_rate: '결측률'};
const RANK: Record<string, number> = {ok: 0, warn: 1, retrain: 2};

function Spark({values}: {values: (number | null)[]}) {
  const v = values.map(x => (x === null || !Number.isFinite(x) ? null : x));
  const nums = v.filter((x): x is number => x !== null);
  if (nums.length < 2) return <span className="muted">—</span>;
  const lo = Math.min(...nums), hi = Math.max(...nums), w = 90, h = 22;
  const pts = v.map((x, i) => x === null ? null : `${(i / (v.length - 1)) * w},${h - ((x - lo) / (hi - lo || 1)) * h}`)
    .filter(Boolean).join(' ');
  return <svg width={w} height={h} role="img" aria-label="추이"><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5"/></svg>;
}

export default function Monitor() {
  const [c] = useConnection();
  const ready = !!(c.tenant && c.key);
  const [task, setTask] = useState('');
  const [days, setDays] = useState(30);
  const mon = useApi<MonitorBody>(ready && task ? tpath(`/tasks/${encodeURIComponent(task)}/monitor?days=${days}`) : null, [task, days, c.tenant, c.key]);
  const doc = useApi<{tenant: string; sources: Source[]}>(ready ? tpath('/doctor') : null, [c.tenant, c.key]);
  const items = mon.data?.items ?? [];
  const daysList = [...new Set(items.map(i => i.day))].sort();
  const series = (metric: string, feature: string | null) =>
    daysList.map(d => items.find(i => i.day === d && i.metric === metric && (i.feature ?? null) === feature) ?? null);
  const features = [...new Set(items.filter(i => i.metric === 'psi').map(i => i.feature ?? ''))];
  const latest = (metric: string, feature: string | null) => series(metric, feature).filter(Boolean).slice(-1)[0] ?? null;
  const live = series('live_perf', null);
  const lastLive = live.filter(Boolean).slice(-1)[0];

  return <section>
    <h1>6. 감시</h1>
    <ConnectionBar/>
    <div className="row">
      <TaskPicker value={task} onChange={setTask} exclude={['optimize']}/>
      <label className="picker">기간 <select value={days} onChange={e => setDays(Number(e.target.value))}>
        {[7, 30, 90].map(d => <option key={d} value={d}>{d}일</option>)}
      </select></label>
      {mon.data && <span className="muted">마지막 감시일 {mon.data.last_day ?? '없음'}</span>}
    </div>
    <ErrorBox error={mon.error}/>
    {mon.data && !items.length && <p className="muted">감시 기록 없음 — 스케줄러(매일 KST 02:00)가 아직 돌지 않았거나 운영 모델이 없습니다.</p>}
    {items.length > 0 && <div className="card">
      <h2>변수별 분포</h2>
      <div className="table-wrap"><table className="grid" data-testid="monitor-features">
        <thead><tr><th>변수</th>{(['psi', 'oor_rate', 'missing_rate'] as const).map(m => <th key={m} colSpan={2}>{METRIC_LABEL[m]}</th>)}</tr></thead>
        <tbody>{features.map(f => <tr key={f}>
          <td>{f}</td>
          {(['psi', 'oor_rate', 'missing_rate'] as const).map(m => {
            const l = latest(m, f);
            return [<td key={`${m}v`}>{l ? <>{fmt(l.value, 3)} <LevelBadge level={l.level}/></> : '—'}</td>,
                    <td key={`${m}s`}><Spark values={series(m, f).map(x => x?.value ?? null)}/></td>];
          })}
        </tr>)}</tbody>
      </table></div>
    </div>}
    {items.length > 0 && <div className="card">
      <h2>과제 지표</h2>
      <dl className="kv">
        <dt>실측 성능</dt><dd>{lastLive && lastLive.value !== null
          ? <>{String(lastLive.detail.metric ?? '')} {fmt(lastLive.value, 4)} (시험 {fmt(lastLive.detail.test as number, 4)}, 악화 {fmt(lastLive.detail.drop as number, 3)}) <LevelBadge level={lastLive.level}/> <Spark values={live.map(x => x?.value ?? null)}/></>
          : <span className="muted">실측 없음</span>}</dd>
        <dt>예측 수</dt><dd>{fmt(latest('volume', null)?.value, 0)} <Spark values={series('volume', null).map(x => x?.value ?? null)}/></dd>
        <dt>오류율</dt><dd>{latest('error_rate', null)?.value == null ? <span className="muted">호출 없음</span> : fmt(latest('error_rate', null)!.value, 3)}</dd>
        <dt>범위 밖 행 비율</dt><dd>{fmt(latest('oor_rate', null)?.value, 3)} <LevelBadge level={latest('oor_rate', null)?.level}/></dd>
        <dt>최고 수준</dt><dd><LevelBadge level={items.reduce((a, i) => (RANK[i.level] > RANK[a] ? i.level : a), 'ok')}/></dd>
      </dl>
    </div>}
    {mon.data && <div className="card">
      <h2>재학습 후보</h2>
      {mon.data.retrain_candidates.length ? <div className="table-wrap"><table className="grid" data-testid="retrain-candidates">
        <thead><tr><th>버전</th><th>단계</th><th>기준선</th><th>승인</th><th>만든 때</th></tr></thead>
        <tbody>{mon.data.retrain_candidates.map(r => <tr key={r.version}>
          <td>{r.version}</td><td><StateBadge state={r.stage}/></td><td>{r.beats_baseline ? '이김' : '못 이김 — 후보로 둠'}</td>
          <td>{r.approval_id ? <><StateBadge state={r.approval_state ?? 'pending'}/> <a href="/app/approvals">승인 대기열에서 보기</a></> : '—'}</td>
          <td>{r.created_at}</td>
        </tr>)}</tbody>
      </table></div> : <p className="muted">감시가 만든 재학습 후보 없음</p>}
    </div>}
    <div className="card">
      <h2>데이터 소스 점검 (doctor · fixture 모드)</h2>
      <ErrorBox error={doc.error}/>
      {doc.data && <div className="table-wrap"><table className="grid" data-testid="doctor">
        <thead><tr><th>역할</th><th>종류</th><th>상태</th><th>행</th><th>기간</th><th>변수 대응률</th><th>최대 결측률</th><th>목표</th><th>사유</th></tr></thead>
        <tbody>{doc.data.sources.map(s => {
          const miss = Object.values(s.missing_rates ?? {});
          return <tr key={s.role}>
            <td>{s.role}</td><td>{s.kind}</td>
            <td><span className={`badge badge-${s.status === '연결' ? 'ok' : 'rejected'}`}>{s.status}</span></td>
            <td>{s.rows ?? '—'}</td><td>{s.ts_from ? `${s.ts_from} ~ ${s.ts_to}` : '—'}</td>
            <td>{s.coverage === null ? '—' : `${(s.coverage * 100).toFixed(1)}%`}</td>
            <td>{miss.length ? `${(Math.max(...miss) * 100).toFixed(1)}%` : '—'}</td>
            <td>{s.target === '목표 없음' ? <span className="badge badge-review">목표 없음</span> : s.target ?? '—'}</td>
            <td className="muted">{s.message}</td>
          </tr>;
        })}</tbody>
      </table></div>}
    </div>
  </section>;
}
