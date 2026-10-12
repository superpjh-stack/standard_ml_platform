// 화면 4 — 모델 비교 · 검증 (contracts/screen-map.md · spec §5.4). 소유 개발1.
// 후보별 검증 지표 · 선정 사유 · 시험 지표 대 기준선 · 중요도 · 잔차 · (risk) 보정 곡선 · 현재 production 과의 비교.
// API: B07 GET …/models · B08 POST …/train · GET /runs/{id}. 지어내지 않는다 — 없는 값은 "—", 기준선 미달은 그대로 보인다.
import {useEffect, useMemo, useState} from 'react';
import {
  api, ConnectionBar, ErrorBox, fmt, MetricTable, SyntheticBadge, TaskPicker, tpath, useApi, useConnection, Warnings,
} from '../components';
import type {ListResponse, Metric} from '../components';

type ModelItem = {
  version: string; stage: string; algo: string; metrics: Record<string, Metric> | null; beats_baseline: boolean;
  synthetic: boolean; snapshot_id: string; created_at: string | null; promoted_at: string | null;
  promoted_by: string | null; run_id?: string | null;
};

type Imp = {feature: string; mean: number; std: number};
type CalBin = {bin: number; n: number; mean_pred: number; observed: number};
type RunView = {
  run_id: string; status: string; task: string; champion: string | null; beats_baseline: boolean | null;
  version: string | null; stage?: string | null;
  snapshot: {snapshot_id: string; rows: number; ts_from: string | null; ts_to: string | null; sha256: string; synthetic?: boolean};
  valid_metrics: Record<string, Record<string, number | null>>;
  test_metrics: Record<string, Metric>;
  warnings: {code: string; message: string; detail?: Record<string, unknown>; field?: string | null}[];
  error?: {type?: string; message?: string} | null;
  report?: {
    selection_metric?: string | null; selection_reason?: string; valid_baseline?: Record<string, number | null>;
    baseline?: string; baseline_value?: number | null; beats_baseline_rule?: string;
    baselines_compared?: {valid: Record<string, Record<string, number>>; test: Record<string, Record<string, number>>} | null;
    interval?: {method: string; alpha: number; q: number; n: number} | null;
    threshold?: number | null; threshold_rule?: string | null;
    calibration?: {method: string; fit_on: string; n: number} | null;
    search?: Record<string, {trials: number; best_trial: number; best_params: Record<string, unknown>}> | null;
    outliers?: {method: string; k: number} | null; outliers_removed?: number;
    split?: {policy: string; boundaries?: {sizes?: Record<string, number>}};
    task_type?: string;
    permutation_importance?: Imp[] | null;
    residuals?: {mean: number; std: number; quantiles: Record<string, number>} | null;
    error_by_category?: Record<string, Record<string, {n: number; mae: number}>> | null;
    calibration_curve?: CalBin[] | null;
    labels?: string | null;
    extract_metrics?: {
      labels?: string; class_f1?: Record<string, number>;
      confusion_matrix?: {labels: string[]; matrix: number[][]};
      baseline?: {class_f1?: Record<string, number>};
    } | null;
  };
};

const STAGE: Record<string, string> = {candidate: '후보', staging: '검토', production: '운영', archived: '보관'};
const BASELINE: Record<string, string> = {
  train_mean: '학습 구간 평균', last_value: '직전 값(시계열)', train_positive_rate: '학습 구간 양성률', contamination: '기대 오염률',
  majority_class: '학습 구간 최빈 클래스',
};

function BeatsBadge({beats}: {beats: boolean | null | undefined}) {
  if (beats === null || beats === undefined) return <span className="muted">—</span>;
  return beats ? <span className="badge badge-ok">기준선 이김</span>
    : <span className="badge badge-rejected" title="candidate 까지만 — staging 거부">기준선 못 이김</span>;
}

export default function Models() {
  const [c] = useConnection();
  const [task, setTask] = useState('');
  const ready = !!(c.tenant && c.key && task);
  const models = useApi<ListResponse<ModelItem>>(ready ? tpath(`/tasks/${encodeURIComponent(task)}/models`) : null,
    [c.tenant, c.key, task]);
  const items = models.data?.items ?? [];
  const production = items.find(m => m.stage === 'production') ?? null;
  const [version, setVersion] = useState('');
  useEffect(() => {
    if (items.length && !items.some(m => m.version === version)) {
      setVersion((items.find(m => m.stage === 'candidate') ?? items[0]).version);
    }
  }, [items.map(m => m.version).join(','), version]);   // eslint-disable-line react-hooks/exhaustive-deps
  const selected = items.find(m => m.version === version) ?? null;

  return <section>
    <h1>4. 모델 비교 · 검증</h1>
    <ConnectionBar/>
    <div className="row"><TaskPicker value={task} onChange={setTask} exclude={['optimize']}/></div>
    <ErrorBox error={models.error}/>
    {ready && <TrainRequest task={task}/>}
    {ready && !models.error && <div className="card">
      <h2>모델 버전</h2>
      {!items.length && !models.loading ? <p className="muted">등록된 모델 없음 — 학습 요청 후 작업자가 candidate 를 만든다</p> :
        <div className="table-wrap"><table className="grid">
          <thead><tr><th></th><th>버전</th><th>단계</th><th>알고리즘</th><th>기준선</th><th>데이터</th><th>스냅숏</th><th>등록</th></tr></thead>
          <tbody>{items.map(m => <tr key={m.version} aria-selected={m.version === version}>
            <td><input type="radio" name="ver" checked={m.version === version} onChange={() => setVersion(m.version)}
                       aria-label={`${m.version} 선택`}/></td>
            <td>{m.version}</td><td>{STAGE[m.stage] ?? m.stage}</td><td>{m.algo}</td>
            <td><BeatsBadge beats={m.beats_baseline}/></td><td><SyntheticBadge synthetic={m.synthetic}/></td>
            <td><code>{m.snapshot_id}</code></td><td>{m.created_at ?? '—'}</td>
          </tr>)}</tbody>
        </table></div>}
      {items.length > 0 && !production && <p className="muted">운영 모델 없음 (model_not_ready) — 비교 대상 없음</p>}
      {selected && <MetricTable metrics={selected.metrics} compare={production && production.version !== selected.version ? production.metrics : null}
        caption={`시험 지표 대 기준선 — ${selected.version}${production && production.version !== selected.version ? ` · 비교: 운영 ${production.version}` : ''}`}/>}
    </div>}
    {ready && <RunDetail initial={selected?.run_id ?? ''}/>}
  </section>;
}

function TrainRequest({task}: {task: string}) {
  const [role, setRole] = useState('demo');
  const [out, setOut] = useState<{run_id: string; status: string; reused?: boolean} | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr(null); setOut(null);
    try { setOut(await api('POST', tpath(`/tasks/${encodeURIComponent(task)}/train`), {source_role: role})); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return <div className="card">
    <h2>학습 요청 (admin)</h2>
    <div className="row">
      <label>소스 <select value={role} onChange={e => setRole(e.target.value)}>
        <option value="demo">demo (합성)</option><option value="eval">eval (fixture)</option><option value="train">train (실 원천)</option>
      </select></label>
      <button onClick={submit} disabled={busy}>학습 접수</button>
      <span className="muted">API 는 접수만 한다 — 작업자가 학습 · candidate 등록(D-57)</span>
    </div>
    <ErrorBox error={err}/>
    {out && <p>실행 <code>{out.run_id}</code> · {out.status}{out.reused ? ' (같은 스냅숏 · 설정 — 기존 실행)' : ''}</p>}
  </div>;
}

function RunDetail({initial}: {initial: string}) {
  const [input, setInput] = useState(initial);
  const [runId, setRunId] = useState(initial);
  useEffect(() => { setInput(initial); setRunId(initial); }, [initial]);
  const run = useApi<RunView>(runId ? `/runs/${encodeURIComponent(runId)}` : null, [runId]);
  const r = run.data;
  return <div className="card">
    <h2>학습 실행 검증</h2>
    <form className="row" onSubmit={e => { e.preventDefault(); setRunId(input.trim()); }}>
      <label>실행 ID <input value={input} onChange={e => setInput(e.target.value)} size={24} placeholder="run_…"/></label>
      <button type="submit">조회</button>
    </form>
    <ErrorBox error={run.error}/>
    {r && <RunBody r={r}/>}
  </div>;
}

function RunBody({r}: {r: RunView}) {
  const rep = r.report ?? {};
  const sel = rep.selection_metric ?? null;
  return <>
    <p>
      <code>{r.run_id}</code> · 상태 <strong>{r.status}</strong> · 과제 {r.task}
      {r.version && <> · 버전 {r.version}</>} · <BeatsBadge beats={r.beats_baseline}/> <SyntheticBadge synthetic={r.snapshot?.synthetic}/>
    </p>
    {r.status === 'failed' && <div className="error" role="alert">학습 실패: {r.error?.type} {r.error?.message}</div>}
    <p className="muted">
      스냅숏 <code>{r.snapshot.snapshot_id}</code> · {r.snapshot.rows}행 · {r.snapshot.ts_from ?? '—'} ~ {r.snapshot.ts_to ?? '—'}
      · 분할 {rep.split?.policy ?? '—'} {rep.split?.boundaries?.sizes ? `(${Object.entries(rep.split.boundaries.sizes).map(([k, v]) => `${k} ${v}`).join(' · ')})` : ''}
    </p>
    <div className="cols">
      <div>
        <h3>후보별 검증 지표</h3>
        <ValidTable valid={r.valid_metrics} champion={r.champion} sel={sel} baseline={rep.valid_baseline}/>
        <p><strong>선정 사유</strong> — {rep.selection_reason ?? '—'}</p>
        {rep.search && <p className="muted">무작위 탐색: {Object.entries(rep.search).map(([k, s]) => `${k} ${s.trials}회`).join(' · ')}</p>}
      </div>
      <div>
        <MetricTable metrics={r.test_metrics} caption="시험 구간 1회 — 지표 대 기준선"/>
        <p className="muted">기준선: {BASELINE[rep.baseline ?? ''] ?? rep.baseline ?? '—'} {rep.baseline_value != null ? `(${fmt(rep.baseline_value)})` : ''}
          {' · '}판정 규칙: {rep.beats_baseline_rule ?? '—'}</p>
        {rep.baselines_compared && <BaselineCompare b={rep.baselines_compared}/>}
        <Extras rep={rep}/>
      </div>
    </div>
    <div className="cols">
      <Importance items={rep.permutation_importance}/>
      <Residuals res={rep.residuals} byCat={rep.error_by_category}/>
      {rep.task_type === 'risk' && <CalibrationCurve bins={rep.calibration_curve}/>}
    </div>
    {rep.task_type === 'extract' && <ExtractDetail rep={rep}/>}
    <h3>경고</h3>
    <Warnings warnings={(r.warnings ?? []).map(w => ({code: w.code, field: w.field ?? null, message: w.message}))}/>
  </>;
}

function ValidTable({valid, champion, sel, baseline}: {
  valid: RunView['valid_metrics']; champion: string | null; sel: string | null; baseline?: Record<string, number | null>;
}) {
  const names = Object.keys(valid ?? {});
  const cols = useMemo(() => Array.from(new Set(names.flatMap(n => Object.keys(valid[n] ?? {})))), [valid]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!names.length) return <p className="muted">검증 지표 없음</p>;
  return <div className="table-wrap"><table className="grid">
    <thead><tr><th>후보</th>{cols.map(c => <th key={c}>{c}{c === sel ? ' ★' : ''}</th>)}</tr></thead>
    <tbody>
      {names.map(n => <tr key={n}><th scope="row">{n}{n === champion ? ' (챔피언)' : ''}</th>
        {cols.map(c => <td key={c}>{fmt(valid[n]?.[c])}</td>)}</tr>)}
      {baseline && <tr><th scope="row" className="muted">검증 기준선</th>{cols.map(c => <td key={c} className="muted">{fmt(baseline[c])}</td>)}</tr>}
    </tbody>
  </table></div>;
}

function BaselineCompare({b}: {b: NonNullable<NonNullable<RunView['report']>['baselines_compared']>}) {
  const kinds = Object.keys(b.valid ?? {});
  return <div className="table-wrap"><table className="grid">
    <caption>기준선 후보 비교 (검증 구간에서 고름)</caption>
    <thead><tr><th>기준선</th><th>검증 mae</th><th>시험 mae</th></tr></thead>
    <tbody>{kinds.map(k => <tr key={k}><th scope="row">{BASELINE[k] ?? k}</th><td>{fmt(b.valid[k]?.mae)}</td><td>{fmt(b.test?.[k]?.mae)}</td></tr>)}</tbody>
  </table></div>;
}

function Extras({rep}: {rep: NonNullable<RunView['report']>}) {
  const rows: [string, string][] = [];
  if (rep.interval) rows.push(['예측 구간', `${rep.interval.method} · α ${rep.interval.alpha} · q ${fmt(rep.interval.q)} (검증 ${rep.interval.n}행)`]);
  if (rep.threshold != null) rows.push(['임계값', `${fmt(rep.threshold)}${rep.threshold_rule ? ` — ${rep.threshold_rule}` : ''}`]);
  rows.push(['확률 보정', rep.calibration ? `${rep.calibration.method} (${rep.calibration.fit_on} ${rep.calibration.n}행)` : rep.task_type === 'risk' ? '없음' : '—']);
  rows.push(['이상치 제거', rep.outliers ? `${rep.outliers.method} k=${rep.outliers.k} · ${rep.outliers_removed ?? 0}행` : '꺼짐']);
  return <table className="grid"><tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody></table>;
}

function Importance({items}: {items?: Imp[] | null}) {
  if (!items?.length) return <div><h3>순열 중요도 (시험 구간)</h3><p className="muted">없음</p></div>;
  const max = Math.max(...items.map(i => Math.abs(i.mean)), 1e-12);
  return <div>
    <h3>순열 중요도 (시험 구간)</h3>
    <table className="grid"><tbody>{items.map(i => <tr key={i.feature}>
      <th scope="row">{i.feature}</th>
      <td style={{width: '55%'}}><div aria-hidden="true" style={{height: 10, borderRadius: 3, background: i.mean >= 0 ? '#5b8f73' : '#c97a7a',
        width: `${Math.max(2, (Math.abs(i.mean) / max) * 100)}%`}}/></td>
      <td>{fmt(i.mean)} ± {fmt(i.std, 3)}</td>
    </tr>)}</tbody></table>
  </div>;
}

function Residuals({res, byCat}: {res?: NonNullable<RunView['report']>['residuals']; byCat?: NonNullable<RunView['report']>['error_by_category']}) {
  return <div>
    <h3>잔차 (시험 구간)</h3>
    {!res ? <p className="muted">없음</p> : <table className="grid"><tbody>
      <tr><th scope="row">평균 · 표준편차</th><td>{fmt(res.mean)} · {fmt(res.std)}</td></tr>
      {Object.entries(res.quantiles ?? {}).map(([q, v]) => <tr key={q}><th scope="row">분위 {q}</th><td>{fmt(v)}</td></tr>)}
    </tbody></table>}
    {byCat && Object.entries(byCat).map(([f, groups]) => <table className="grid" key={f}>
      <caption>범주별 오차 — {f}</caption>
      <thead><tr><th>값</th><th>n</th><th>평균 절대 오차</th></tr></thead>
      <tbody>{Object.entries(groups).map(([k, g]) => <tr key={k}><td>{k}</td><td>{g.n}</td><td>{fmt(g.mae)}</td></tr>)}</tbody>
    </table>)}
  </div>;
}

function CalibrationCurve({bins}: {bins?: CalBin[] | null}) {
  if (!bins?.length) return <div><h3>보정 곡선</h3><p className="muted">없음</p></div>;
  const S = 180, P = 24;
  const x = (v: number) => P + v * (S - 2 * P);
  const y = (v: number) => S - P - v * (S - 2 * P);
  const pts = bins.map(b => `${x(b.mean_pred)},${y(b.observed)}`).join(' ');
  return <div>
    <h3>보정 곡선 (시험 구간)</h3>
    <svg viewBox={`0 0 ${S} ${S}`} width="100%" style={{maxWidth: 260}} role="img" aria-label="예측 확률 대 관측 빈도">
      <rect x={P} y={P} width={S - 2 * P} height={S - 2 * P} fill="none" stroke="#cfd8d3"/>
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="#9aa7a0" strokeDasharray="4 3"/>
      <polyline points={pts} fill="none" stroke="#1d4e89" strokeWidth={2}/>
      {bins.map(b => <circle key={b.bin} cx={x(b.mean_pred)} cy={y(b.observed)} r={2 + Math.min(4, Math.sqrt(b.n) / 3)} fill="#1d4e89">
        <title>{`예측 ${fmt(b.mean_pred, 3)} · 관측 ${fmt(b.observed, 3)} · n ${b.n}`}</title></circle>)}
      <text x={S / 2} y={S - 4} fontSize={10} textAnchor="middle">예측 확률</text>
      <text x={8} y={S / 2} fontSize={10} textAnchor="middle" transform={`rotate(-90 8 ${S / 2})`}>관측 빈도</text>
    </svg>
  </div>;
}

function ExtractDetail({rep}: {rep: NonNullable<RunView['report']>}) {
  const d = rep.extract_metrics;
  if (rep.labels === 'none' || !d) return <p className="notice" data-labels="none">정답 라벨 없음 — 지표 없음 (labels: none)</p>;
  const cm = d.confusion_matrix;
  return <div className="cols">
    <div>
      <h3>클래스별 F1 (시험 구간{d.labels === 'synthetic' ? ' · 합성 라벨' : ''})</h3>
      <table className="grid"><thead><tr><th>클래스</th><th>F1</th><th>기준선 F1</th></tr></thead>
        <tbody>{Object.entries(d.class_f1 ?? {}).map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{fmt(v)}</td>
          <td className="muted">{fmt(d.baseline?.class_f1?.[k])}</td></tr>)}</tbody></table>
    </div>
    {cm && <div className="table-wrap">
      <h3>혼동행렬 (행 = 실제 · 열 = 예측)</h3>
      <table className="grid" data-testid="confusion"><thead><tr><th></th>{cm.labels.map(l => <th key={l}>{l}</th>)}</tr></thead>
        <tbody>{cm.matrix.map((row, i) => <tr key={i}><th scope="row">{cm.labels[i]}</th>
          {row.map((v, j) => <td key={j} className="num">{i === j ? <strong>{v}</strong> : v}</td>)}</tr>)}</tbody></table>
    </div>}
  </div>;
}
