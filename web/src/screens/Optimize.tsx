// 화면 3 — 조건 추천 (contracts/screen-map.md). 고정 변수 입력 → 후보 5 · 제약 충족표 · 학습 범위 배지.
// 추천은 설비 · MES 로 내려가지 않는다 — 승인 대기열에서 사람이 확인한다.
import {Fragment, useEffect, useMemo, useState} from 'react';
import {
  api, ConnectionBar, ErrorBox, FeatureForm, fmt, initialValues, named, Notice, RangeBadge, StatusBadge,
  SyntheticBadge, TaskPicker, toInputs, tpath, useApi, useConnection, Warnings,
} from '../components';
import type {Candidate, FeatureMeta, ParamMeta, PredictResponse, TaskInfo, Values} from '../components';

export default function Optimize() {
  const [c] = useConnection();
  const [task, setTask] = useState('');
  const info = useApi<TaskInfo>(c.tenant && c.key && task ? tpath(`/tasks/${encodeURIComponent(task)}`) : null, [c.tenant, c.key]);
  const all: FeatureMeta[] = useMemo(() => named<FeatureMeta>(info.data?.features), [info.data]);
  const fixedF = useMemo(() => info.data?.fixed ? all.filter(f => info.data!.fixed!.includes(f.name)) : all.filter(f => !f.controllable), [all, info.data]);
  const controlF = useMemo(() => info.data?.controls ? all.filter(f => info.data!.controls!.includes(f.name)) : all.filter(f => f.controllable), [all, info.data]);
  const params: ParamMeta[] = useMemo(() => named<ParamMeta>(info.data?.params as ParamMeta[] | undefined), [info.data]);

  const [fixed, setFixed] = useState<Values>({});
  const [current, setCurrent] = useState<Values>({});
  const [useCurrent, setUseCurrent] = useState(false);
  const [pv, setPv] = useState<Record<string, string>>({});
  const [res, setRes] = useState<PredictResponse | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFixed(initialValues(fixedF)); setCurrent(initialValues(controlF));
    setPv(Object.fromEntries(params.map(p => [p.name, p.default == null ? '' : String(p.default)])));
    setRes(null); setErr(null);
  }, [fixedF, controlF, params]);

  const submit = async () => {
    setBusy(true); setErr(null); setRes(null);
    const body: Record<string, unknown> = {fixed: toInputs(fixedF, fixed)};
    if (useCurrent && controlF.length) body.current = toInputs(controlF, current);
    const p: Record<string, number> = {};
    for (const [k, v] of Object.entries(pv)) if (v !== '' && Number.isFinite(Number(v))) p[k] = Number(v);
    body.params = p;
    try { setRes(await api<PredictResponse>('POST', tpath(`/tasks/${encodeURIComponent(task)}/optimize`), body)); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };

  return <section>
    <h1>3. 조건 추천</h1>
    <p className="notice" role="note">추천은 설비로 내려가지 않습니다 (승인 대기열에서 사람이 확인)</p>
    <ConnectionBar/>
    <div className="row"><TaskPicker value={task} onChange={setTask} types={['optimize']}/></div>
    <ErrorBox error={info.error}/>
    {info.data && <div className="card">
      <h2>{info.data.title ?? info.data.task}</h2>
      {info.data.uses?.length ? <p className="muted">의존 과제: {info.data.uses.join(', ')}</p> : null}
      <h3>고정 변수</h3>
      <FeatureForm features={fixedF} values={fixed} onChange={setFixed}
                   highlight={res ? {imputed: res.imputed_fields, outOfRange: res.out_of_range_fields} : undefined}/>
      {controlF.length > 0 && <>
        <label style={{display: 'block', marginTop: 12}}>
          <input type="checkbox" checked={useCurrent} onChange={e => setUseCurrent(e.target.checked)}/> 현재 조건 입력(개선량 계산)
        </label>
        {useCurrent && <FeatureForm features={controlF} values={current} onChange={setCurrent}/>}
      </>}
      {params.length > 0 && <>
        <h3>제약 값</h3>
        <div className="feature-form">{params.map(p => <div className="field" key={p.name}>
          <label htmlFor={`p-${p.name}`}>{p.label ?? p.name}{p.unit ? <span className="unit"> ({p.unit})</span> : null}</label>
          <input id={`p-${p.name}`} type="number" step="any" value={pv[p.name] ?? ''} min={p.min} max={p.max}
                 onChange={e => setPv({...pv, [p.name]: e.target.value})}/>
          <small className="muted">{p.min ?? ''}~{p.max ?? ''}</small>
        </div>)}</div>
      </>}
      <div className="row" style={{marginTop: 12}}>
        <button className="primary" disabled={busy || !task} onClick={submit}>{busy ? '탐색 중…' : '추천 조건 찾기'}</button>
      </div>
    </div>}
    <ErrorBox error={err}/>
    {res && <Result r={res}/>}
  </section>;
}

function Result({r}: {r: PredictResponse}) {
  const rec = r.recommendation;
  if (!rec) return <div className="card"><StatusBadge status={r.status}/><Warnings warnings={r.warnings}/></div>;
  return <div className="card" data-testid="optimize-result">
    <div className="row">
      <StatusBadge status={r.status}/><SyntheticBadge synthetic={r.synthetic}/>
      <RangeBadge rate={rec.in_train_range_rate}/>
      <span className="muted">추천 ID {rec.rec_id}</span>
    </div>
    {rec.on_infeasible === 'least_violation' &&
      <div className="error" role="alert"><strong>제약 충족 후보 없음 — 위반 최소 후보(least_violation) · 검토 필요</strong></div>}
    <dl className="kv" style={{marginTop: 8}}>
      <dt>충족 여부</dt><dd>{rec.feasible ? '제약 충족 후보 있음' : '제약 충족 후보 없음'}</dd>
      <dt>탐색</dt><dd>{rec.strategy} · 평가 {rec.n_candidates}점 · 충족 {rec.n_feasible}점</dd>
      <dt>목적</dt><dd>{rec.objective.name} {rec.objective.direction === 'minimize' ? '최소' : '최대'}
        {rec.objective.tiebreak.length ? ` (동률: ${rec.objective.tiebreak.map(t => `${t.name} ${t.direction === 'minimize' ? '최소' : '최대'}`).join(', ')})` : ''}</dd>
      <dt>의존 모델</dt><dd>{(r.uses ?? []).map(u => `${u.task}@${u.version}${u.synthetic ? ' (합성)' : ''}`).join(', ') || '—'}</dd>
      {rec.improvement && <><dt>개선량</dt><dd>{Object.entries(rec.improvement).map(([k, v]) => `${k} ${fmt(v)}`).join(', ')}</dd></>}
    </dl>
    <h3>후보 (상위 {rec.candidates.length})</h3>
    {rec.candidates.map((cand, i) => <CandidateCard key={i} rank={i + 1} c={cand}/>)}
    {rec.current && <><h3>현재 조건</h3><CandidateCard rank={0} c={rec.current}/></>}
    <h3>경고</h3>
    <Warnings warnings={r.warnings}/>
    <Notice text={r.notice}/>
  </div>;
}

function CandidateCard({rank, c}: {rank: number; c: Candidate}) {
  return <div className="card">
    <div className="row"><strong>{rank ? `${rank}위` : '현재'}</strong>
      <span>목적값 {fmt(c.objective_value)}</span><span>위반 {fmt(c.violation)}</span></div>
    <div className="cols">
      <dl className="kv">
        {Object.entries(c.conditions).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{fmt(v)}</dd></Fragment>)}
      </dl>
      <dl className="kv">
        {Object.entries(c.predictions).map(([k, v]) => <Fragment key={k}><dt>{k}</dt>
          <dd>{fmt(v)}{c.intervals[k] ? ` [${fmt(c.intervals[k]![0])} ~ ${fmt(c.intervals[k]![1])}]` : ''}</dd></Fragment>)}
      </dl>
    </div>
    <table className="grid"><thead><tr><th>제약</th><th>식</th><th>좌변</th><th>우변</th><th>충족</th><th>여유</th></tr></thead>
      <tbody>{c.constraints.map(k => <tr key={k.name}>
        <td>{k.name}</td><td><code>{k.expr}</code></td><td>{fmt(k.lhs)}</td><td>{fmt(k.rhs)}</td>
        <td>{k.satisfied ? <span className="badge badge-ok">충족</span> : <span className="badge badge-rejected">미충족</span>}</td>
        <td>{fmt(k.slack)}</td></tr>)}</tbody></table>
  </div>;
}
