// 화면 2 — 예측 시험 (contracts/screen-map.md). 폼은 features.yaml 메타(GET .../tasks/{task})에서 만든다. 회사 화면 코드 0.
import {useEffect, useMemo, useState} from 'react';
import {
  api, ConnectionBar, ErrorBox, FeatureForm, fmt, initialValues, named, Notice, StatusBadge, SyntheticBadge,
  TaskPicker, toInputs, tpath, useApi, useConnection, Warnings,
} from '../components';
import type {FeatureMeta, PredictResponse, TaskInfo, Values} from '../components';

export default function Predict() {
  const [c] = useConnection();
  const [task, setTask] = useState('');
  const info = useApi<TaskInfo>(c.tenant && c.key && task ? tpath(`/tasks/${encodeURIComponent(task)}`) : null, [c.tenant, c.key]);
  const features: FeatureMeta[] = useMemo(() => named<FeatureMeta>(info.data?.features), [info.data]);
  const [values, setValues] = useState<Values>({});
  const [entity, setEntity] = useState('');
  const [explain, setExplain] = useState(false);
  const [res, setRes] = useState<PredictResponse | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setValues(initialValues(features)); setRes(null); setErr(null); }, [features]);

  const submit = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await api<PredictResponse>('POST', tpath(`/tasks/${encodeURIComponent(task)}/predict`),
        {inputs: toInputs(features, values), entity_id: entity.trim() || null, explain}));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  return <section>
    <h1>2. 예측 시험</h1>
    <ConnectionBar/>
    <div className="row"><TaskPicker value={task} onChange={setTask} exclude={['optimize']}/></div>
    <ErrorBox error={info.error}/>
    {info.data && <div className="card">
      <h2>{info.data.title ?? info.data.task} <small className="muted">[{info.data.type}]</small></h2>
      <FeatureForm features={features} values={values} onChange={setValues}
                   highlight={res ? {imputed: res.imputed_fields, outOfRange: res.out_of_range_fields} : undefined}/>
      <div className="row" style={{marginTop: 12}}>
        <label>대상 ID(선택) <input value={entity} maxLength={128} onChange={e => setEntity(e.target.value)}/></label>
        <label><input type="checkbox" checked={explain} onChange={e => setExplain(e.target.checked)}/> 기여 변수(explain)</label>
        <button className="primary" disabled={busy || !task} onClick={submit}>{busy ? '예측 중…' : '예측'}</button>
      </div>
    </div>}
    <ErrorBox error={err}/>
    {res && <Result r={res}/>}
  </section>;
}

function Result({r}: {r: PredictResponse}) {
  return <div className="card" data-testid="predict-result">
    <div className="row"><StatusBadge status={r.status}/><SyntheticBadge synthetic={r.synthetic}/>
      <span className="muted">{r.task} · {r.type}</span></div>
    <div className="cols" style={{marginTop: 8}}>
      <dl className="kv">
        {r.prediction && <>
          <dt>예측값</dt><dd>{r.prediction.value === null ? '— (예측하지 않음)' : `${fmt(r.prediction.value)} ${r.prediction.unit}`}</dd>
          <dt>구간</dt><dd>{r.prediction.interval ? `${fmt(r.prediction.interval[0])} ~ ${fmt(r.prediction.interval[1])}` : '—'}</dd>
          <dt>등급</dt><dd>{r.prediction.grade ?? '—'}</dd>
          <dt>기준선</dt><dd>{fmt(r.prediction.baseline)}</dd>
        </>}
        {r.probability !== null && <><dt>확률</dt><dd>{fmt(r.probability)}</dd></>}
        {r.anomaly && <>
          <dt>이상 점수</dt><dd>{fmt(r.anomaly.score)}</dd>
          <dt>이상 여부</dt><dd>{r.anomaly.flag === null ? '—' : r.anomaly.flag ? '이상' : '정상 범위'}</dd>
          <dt>임계값</dt><dd>{fmt(r.anomaly.threshold)}</dd>
          <dt>오염률</dt><dd>{fmt(r.anomaly.contamination)}</dd>
          <dt>기여 변수</dt><dd>{r.anomaly.contributors.length ? r.anomaly.contributors.map(x => `${x.field} ${fmt(x.contribution, 3)}`).join(', ') : '—'}</dd>
        </>}
      </dl>
      <dl className="kv">
        <dt>모델</dt><dd>{r.model ? `${r.model.name} ${r.model.version}` : '—'}</dd>
        <dt>학습 시각</dt><dd>{r.model?.trained_at ?? '—'}</dd>
        <dt>스냅숏</dt><dd>{r.model?.snapshot_id ?? '—'}</dd>
        <dt>예측 ID</dt><dd>{r.prediction_id ?? '—'}</dd>
        <dt>대상 ID</dt><dd>{r.entity_id ?? '—'}</dd>
        <dt>보정 변수</dt><dd>{r.imputed_fields.join(', ') || '없음'}</dd>
        <dt>범위 밖 변수</dt><dd>{r.out_of_range_fields.join(', ') || '없음'}</dd>
      </dl>
    </div>
    <h3>경고</h3>
    <Warnings warnings={r.warnings}/>
    {r.explain && <>
      <h3>기여 상위 ({r.explain.method})</h3>
      <table className="grid"><thead><tr><th>변수</th><th>기여</th></tr></thead>
        <tbody>{r.explain.top.map(t => <tr key={t.field}><td>{t.field}</td><td>{fmt(t.contribution)}</td></tr>)}</tbody></table>
    </>}
    <Notice text={r.notice}/>
  </div>;
}
