// 화면 7 — 데이터 소스 · 스냅숏 (contracts/screen-map.md · goal2 §6). 소유 개발1.
// 소스별 doctor 결과(연결 · 미연결 · 대응률 · 목표 없음 · 기간) · 스냅숏 목록(행 · 기간 · sha256 · 합성 배지) · CSV 소스.
// API: B14 GET /tenants/{t}/doctor · B07 GET …/models · B08 GET /runs/{id}. 역할 admin · approver(조회) — 다른 역할은 API 가
// 거부한 그대로(403) 보인다. 지어내지 않는다 — 미연결 · `live 불가` · 목표 없음 · 미확인은 doctor 문구 그대로, 없는 값은 "—".
import {useEffect, useState} from 'react';
import {
  api, ConnectionBar, ErrorBox, fmt, SyntheticBadge, TaskPicker, tpath, useApi, useConnection,
} from '../components';
import type {ListResponse} from '../components';

type DoctorSource = {
  role: string; kind: string | null; status: string; rows: number | null; ts_from: string | null; ts_to: string | null;
  coverage: number | null; missing_rates: Record<string, number>; target: string | null; message: string;
  targets?: Record<string, string>; unmapped?: string[]; tables?: string[];
};
type Doctor = {tenant: string; mode: string | null; sources: DoctorSource[]; warnings?: string[]; disabled?: Record<string, string>};
type ModelItem = {version: string; run_id: string | null; stage: string; algo: string; synthetic: boolean; snapshot_id: string; created_at: string | null};
type RunSnap = {
  run_id: string; status: string; task: string;
  snapshot: {snapshot_id: string; rows: number; ts_from: string | null; ts_to: string | null; sha256: string; synthetic?: boolean};
};

const STAGE: Record<string, string> = {candidate: '후보', staging: '검토', production: '운영', archived: '보관'};
const LEARNED = ['regression', 'risk', 'anomaly', 'extract'];   // 스냅숏을 만드는 유형(학습 과제)

function int(n: number | null | undefined): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString('en-US') : '—';
}

function pct(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : '—';
}

function period(a: string | null | undefined, b: string | null | undefined): string {
  return a || b ? `${a ?? '—'} ~ ${b ?? '—'}` : '—';
}

function StatusCell({status}: {status: string}) {
  const ok = status === '연결';
  return <span className={`badge ${ok ? 'badge-ok' : 'badge-rejected'}`}>{status}</span>;
}

function TargetCell({target}: {target: string | null}) {
  if (!target) return <span className="muted">—</span>;
  return <span className={`badge ${target === '있음' ? 'badge-ok' : 'badge-watch'}`}>{target}</span>;
}

export default function Sources() {
  const [c] = useConnection();
  const ready = !!(c.tenant && c.key);
  const doctor = useApi<Doctor>(ready ? tpath('/doctor') : null, [c.tenant, c.key]);
  const d = doctor.data;
  const csv = (d?.sources ?? []).filter(s => s.kind === 'csv');
  return <section>
    <h1>7. 데이터 소스 · 스냅숏</h1>
    <ConnectionBar/>
    <ErrorBox error={doctor.error}/>
    {d && <div className="card">
      <h2>소스 점검 (doctor · fixture 모드)</h2>
      <p className="muted">회사 {d.tenant} · 모드 {d.mode ?? '—'} — 실연결 확인은 사람이 doctor-live 로 한다 (D-13)</p>
      {!d.sources.length ? <p className="muted">등록된 소스 없음</p> :
        <div className="table-wrap"><table className="grid" data-testid="doctor-sources">
          <thead><tr><th>역할</th><th>종류</th><th>상태</th><th className="num">행</th><th>기간</th><th>대응률</th>
            <th>최대 결측률</th><th>목표</th><th>메시지</th></tr></thead>
          <tbody>{d.sources.map(s => {
            const miss = Object.values(s.missing_rates ?? {});
            return <tr key={s.role} data-role={s.role} data-status={s.status}>
              <th scope="row">{s.role}</th><td><code>{s.kind ?? '—'}</code></td><td><StatusCell status={s.status}/></td>
              <td className="num">{int(s.rows)}</td><td>{period(s.ts_from, s.ts_to)}</td><td>{pct(s.coverage)}</td>
              <td>{miss.length ? pct(Math.max(...miss)) : '—'}</td><td><TargetCell target={s.target}/></td>
              <td className="wrap">{s.message || '—'}
                {s.unmapped && s.unmapped.length > 0 && <div className="muted">대응 안 된 변수: {s.unmapped.join(', ')}</div>}
                {s.targets && Object.keys(s.targets).length > 0 &&
                  <div className="muted">과제별 목표: {Object.entries(s.targets).map(([t, v]) => `${t} ${v}`).join(' · ')}</div>}
              </td>
            </tr>;
          })}</tbody>
        </table></div>}
      {(d.warnings ?? []).length > 0 && <ul className="warnings">{(d.warnings ?? []).map((w, i) => <li key={i}>{w}</li>)}</ul>}
      {d.disabled && Object.keys(d.disabled).length > 0 && <p className="muted">꺼진 과제: {Object.entries(d.disabled).map(([t, r]) => `${t} (${r})`).join(' · ')}</p>}
    </div>}
    {d && <div className="card">
      <h2>CSV 소스</h2>
      {!csv.length ? <p className="muted">CSV 소스 없음 — 회사 등록부 sources 에 kind: csv 로 둔다(파일은 UTF-8 · 열 대응은 feature_map)</p> :
        <ul>{csv.map(s => <li key={s.role} data-csv={s.role}><strong>{s.role}</strong> · <StatusCell status={s.status}/> · {int(s.rows)}행 · {s.message || '—'}</li>)}</ul>}
    </div>}
    {ready && <Snapshots/>}
  </section>;
}

function Snapshots() {
  const [c] = useConnection();
  const [task, setTask] = useState('');
  const models = useApi<ListResponse<ModelItem>>(task ? tpath(`/tasks/${encodeURIComponent(task)}/models`) : null, [c.tenant, c.key, task]);
  const items = models.data?.items ?? [];
  const [runs, setRuns] = useState<Record<string, RunSnap | Error>>({});
  useEffect(() => {
    let live = true;
    setRuns({});
    (async () => {
      for (const m of items) {
        if (!m.run_id) continue;
        try {
          const r = await api<RunSnap>('GET', `/runs/${encodeURIComponent(m.run_id)}`);
          if (live) setRuns(prev => ({...prev, [m.version]: r}));
        } catch (e) { if (live) setRuns(prev => ({...prev, [m.version]: e as Error})); }
      }
    })();
    return () => { live = false; };
  }, [items.map(m => `${m.version}:${m.run_id}`).join(',')]);   // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="card">
    <h2>스냅숏 (학습에 쓴 고정 데이터)</h2>
    <div className="row"><TaskPicker value={task} onChange={setTask} types={LEARNED}/></div>
    <ErrorBox error={models.error}/>
    {task && !models.error && (!items.length ? (!models.loading && <p className="muted">이 과제로 학습한 모델이 없어 스냅숏이 없습니다</p>) :
      <div className="table-wrap"><table className="grid" data-testid="snapshots">
        <thead><tr><th>스냅숏</th><th>버전</th><th>단계</th><th className="num">행</th><th>기간</th><th>sha256</th><th>데이터</th><th>실행</th></tr></thead>
        <tbody>{items.map(m => {
          const r = runs[m.version];
          const s = r && !(r instanceof Error) ? r.snapshot : null;
          return <tr key={m.version} data-snapshot={m.snapshot_id}>
            <td><code>{m.snapshot_id}</code></td><td>{m.version}</td><td>{STAGE[m.stage] ?? m.stage}</td>
            <td className="num">{s ? int(s.rows) : '—'}</td><td>{s ? period(s.ts_from, s.ts_to) : '—'}</td>
            <td>{s ? <code title={s.sha256}>{s.sha256.slice(0, 12)}…</code> : r instanceof Error ? <ErrorBox error={r}/> : '—'}</td>
            <td><SyntheticBadge synthetic={s ? !!s.synthetic : m.synthetic}/></td>
            <td>{m.run_id ? <code>{m.run_id}</code> : '—'}{r && !(r instanceof Error) && r.status !== 'succeeded' ? ` · ${r.status}` : ''}</td>
          </tr>;
        })}</tbody>
      </table></div>)}
    {items.length > 0 && <p className="muted">해시는 열 이름 정렬 · 행 정렬 뒤 정규 CSV 바이트의 SHA-256 (규칙 v2) — 같은 내용이면 같은 해시 · {fmt(items.length, 0)}개 버전</p>}
  </div>;
}
