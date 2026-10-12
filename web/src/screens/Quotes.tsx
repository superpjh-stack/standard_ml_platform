// 화면 9 — 도면 추출 · 견적 (contracts/screen-map.md · B10 · B11 · B13). 회사 화면 코드 0.
// 금액은 서버 문자열 그대로(브라우저 계산 0). 입력 수치는 문자열로 받아 JSON 본문에 그대로 넣는다(Number 변환 0).
// 확정은 요청만(202 → 화면 5 승인 대기열에서 approver 이상이 결정, D2-04 · D2-19). 확정 견적 수정은 409 quote_locked.
import {useEffect, useMemo, useState} from 'react';
import {
  api, apiDownload, apiJsonText, apiUpload, ConnectionBar, DocumentViewer, ErrorBox, IdLink, KeyValue, Money, MoneyTable,
  named, Notice, StateBadge, SyntheticBadge, TaskPicker, tpath, useApi, useConnection, useList,
} from '../components';
import type {DocumentExtraction, FeatureMeta, Quote, TaskInfo} from '../components';

const MAX_BYTES = 5 * 1024 * 1024;
const NUMERIC = /^-?\d+(\.\d+)?$/;

/** 문서 결과에서 'counts.hole' 같은 경로 값. */
function at(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), obj);
}

function show(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

/** 입력 칸(문자열) → JSON 조각. 수치 문자열은 따옴표 없이, 그 밖은 문자열로. */
function jsonValue(s: string): string {
  const t = s.trim();
  if (t === '') return 'null';
  return NUMERIC.test(t) ? t : JSON.stringify(t);
}

export default function Quotes() {
  const [c] = useConnection();
  const ready = !!(c.tenant && c.key);
  const [extractTask, setExtractTask] = useState('');
  const [quoteTask, setQuoteTask] = useState('');
  const [doc, setDoc] = useState<DocumentExtraction | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);

  return <section>
    <h1>9. 도면 추출 · 견적</h1>
    <ConnectionBar/>
    <div className="cols">
      <div className="card"><h2>도면 추출</h2>
        <TaskPicker value={extractTask} onChange={t => { setExtractTask(t); setDoc(null); }} types={['extract']}/>
        {ready && extractTask ? <Extract task={extractTask} doc={doc} onDoc={setDoc}/> : <p className="muted">추출 과제가 없습니다</p>}
      </div>
      <div className="card"><h2>견적</h2>
        <TaskPicker value={quoteTask} onChange={t => { setQuoteTask(t); setQuote(null); }} types={['quote']}/>
        {!quoteTask && <p className="muted">견적 과제가 없습니다</p>}
      </div>
    </div>
    {doc && <div className="card"><h2>추출 결과</h2><DocumentViewer doc={doc}/></div>}
    {ready && quoteTask && <QuoteEditor task={quoteTask} doc={doc} quote={quote} onQuote={setQuote}/>}
    {quote && <QuoteDetail quote={quote} onQuote={setQuote}/>}
    {ready && quoteTask && <History task={quoteTask} onPick={setQuote}/>}
  </section>;
}

function Extract({task, doc, onDoc}: {task: string; doc: DocumentExtraction | null; onDoc: (d: DocumentExtraction | null) => void}) {
  const [file, setFile] = useState<File | null>(null);
  const [unit, setUnit] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const docs = useList<DocumentExtraction>(tpath(`/tasks/${encodeURIComponent(task)}/documents`), [task]);
  const upload = async () => {
    if (!file) return;
    setBusy(true); setErr(null);
    const form = new FormData();
    form.append('file', file, file.name);
    if (unit) form.append('unit_override', unit);
    try { onDoc(await apiUpload<DocumentExtraction>(tpath(`/tasks/${encodeURIComponent(task)}/documents`), form)); void docs.reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const pick = async (id: string) => {
    setErr(null);
    try { onDoc(await api<DocumentExtraction>('GET', tpath(`/tasks/${encodeURIComponent(task)}/documents/${encodeURIComponent(id)}`))); }
    catch (e) { setErr(e); }
  };
  return <div>
    <p className="muted">DXF(ASCII) · 최대 5 MiB · 모델 공간 엔티티 20,000 개 (과제 상한이 더 낮을 수 있음)</p>
    <div className="row">
      <input type="file" accept=".dxf" aria-label="DXF 파일" onChange={e => setFile(e.target.files?.[0] ?? null)}/>
      <label>단위 <select value={unit} onChange={e => setUnit(e.target.value)}>
        <option value="">도면 헤더</option><option value="mm">mm</option><option value="inch">inch</option></select></label>
      <button className="primary" disabled={busy || !file || (file?.size ?? 0) > MAX_BYTES} onClick={upload}>업로드 · 추출</button>
    </div>
    {file && file.size > MAX_BYTES && <p className="error">5 MiB 를 넘습니다 — 서버도 413 document_too_large 로 거부합니다</p>}
    <ErrorBox error={err}/>
    <ErrorBox error={docs.error}/>
    {docs.items.length > 0 && <div className="table-wrap"><table className="grid"><caption>최근 도면</caption>
      <thead><tr><th>파일</th><th>엔티티</th><th>라벨</th><th>시각</th><th/></tr></thead>
      <tbody>{docs.items.map(d => <tr key={d.doc_id} aria-selected={doc?.doc_id === d.doc_id}>
        <td>{d.filename}</td><td>{String(d.entity_count)}</td><td>{d.labels}</td><td>{d.created_at}</td>
        <td><button onClick={() => void pick(d.doc_id)}>보기</button></td></tr>)}</tbody></table></div>}
    {docs.next && <button onClick={() => void docs.loadMore()}>더 보기</button>}
  </div>;
}

function QuoteEditor({task, doc, quote, onQuote}: {task: string; doc: DocumentExtraction | null; quote: Quote | null; onQuote: (q: Quote) => void}) {
  const info = useApi<TaskInfo>(tpath(`/tasks/${encodeURIComponent(task)}`), [task]);
  const features: FeatureMeta[] = useMemo(() => named<FeatureMeta>(info.data?.features), [info.data]);
  const recognized = (info.data?.recognized ?? null) as Record<string, string> | null;
  const names: string[] = useMemo(() => {
    const declared = Array.isArray(info.data?.inputs) ? (info.data!.inputs as string[]) : [];
    return Array.from(new Set([...declared, ...features.map(f => f.name)]));
  }, [info.data, features]);
  const recog = (name: string): unknown => (doc && recognized && recognized[name] ? at(doc, recognized[name]) : undefined);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState('');
  const [lines, setLines] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  useEffect(() => {      // 인식값 → 초기값 (사람이 고치면 서버가 overrides 로 남긴다)
    const v: Record<string, string> = {};
    for (const n of names) {
      const r = recog(n);
      const f = features.find(x => x.name === n);
      v[n] = r !== undefined && typeof r !== 'object' ? String(r) : f?.default !== undefined && f?.default !== null ? String(f.default) : '';
    }
    setVals(v);
    const listPath = recognized ? Object.entries(recognized).find(([, p]) => Array.isArray(doc ? at(doc, p) : undefined)) : undefined;
    setLines(listPath && doc ? JSON.stringify(at(doc, listPath[1]), null, 1) : '');
  }, [names.join(','), doc?.doc_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const body = (): string => {
    const parts = names.map(n => `${JSON.stringify(n)}: ${jsonValue(vals[n] ?? '')}`);
    let inputs = `{${parts.join(', ')}}`;
    if (extra.trim()) {                          // 추가 입력(JSON 객체 조각) — 문자열 그대로 합친다
      const inner = extra.trim().replace(/^\{/, '').replace(/\}$/, '').trim();
      if (inner) inputs = `{${[...parts, inner].join(', ')}}`;
    }
    const linesText = lines.trim() || '[]';
    return `{"doc_id": ${doc ? JSON.stringify(doc.doc_id) : 'null'}, "inputs": ${inputs}, "lines": ${linesText}, "reviewed": false, "review_note": null}`;
  };
  const send = async (revise: boolean) => {
    setBusy(true); setErr(null);
    try {
      const path = revise && quote
        ? tpath(`/tasks/${encodeURIComponent(task)}/quotes/${encodeURIComponent(quote.quote_id)}/revisions`)
        : tpath(`/tasks/${encodeURIComponent(task)}/quotes`);
      onQuote(await apiJsonText<Quote>('POST', path, body()));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const overridden = new Set((quote?.overrides ?? []).map(o => o.field));
  const locked = quote?.status === 'confirmed' || quote?.status === 'pending_confirm';

  return <div className="card" data-testid="quote-editor"><h2>견적 입력 검토 · 수정</h2>
    <ErrorBox error={info.error}/>
    <Notice text={info.data?.notice as string | undefined}/>
    {doc ? <p className="muted">인식 출처: {doc.filename} ({doc.doc_id})</p> : <p className="muted">도면 없이 직접 입력합니다</p>}
    <div className="feature-form">
      {names.map(n => {
        const f = features.find(x => x.name === n);
        const r = recog(n);
        const changed = r !== undefined && typeof r !== 'object' && String(r) !== (vals[n] ?? '').trim();
        return <div key={n} className={`field${changed || overridden.has(n) ? ' field-imputed' : ''}`} data-field={n}>
          <label>{f?.label ?? n}{f?.unit ? <span className="unit"> ({f.unit})</span> : null}</label>
          {f?.dtype === 'category' && f.values ? <select value={vals[n] ?? ''} onChange={e => setVals({...vals, [n]: e.target.value})}>
            <option value="">(비움)</option>{f.values.map(v => <option key={v} value={v}>{v}</option>)}</select>
            : <input inputMode="decimal" value={vals[n] ?? ''} onChange={e => setVals({...vals, [n]: e.target.value})}/>}
          {r !== undefined && typeof r !== 'object' && <small className="muted">인식값 {String(r)}{changed ? ' → 수정됨' : ''}</small>}
        </div>;
      })}
    </div>
    <label style={{display: 'block', marginTop: 8}}>추가 입력 (JSON 객체, 예: 수량 · 단가 입력)
      <textarea rows={2} style={{width: '100%'}} value={extra} onChange={e => setExtra(e.target.value)} placeholder='{"quantity": 1}'/></label>
    <label style={{display: 'block'}}>품목 행 lines (JSON 배열)
      <textarea rows={4} style={{width: '100%', fontFamily: 'monospace'}} value={lines} onChange={e => setLines(e.target.value)} placeholder="[]"/></label>
    <div className="row" style={{marginTop: 8}}>
      <button className="primary" disabled={busy} onClick={() => void send(false)}>견적 초안 만들기</button>
      {quote && <button disabled={busy || locked} onClick={() => void send(true)} title={locked ? '확정(대기) 견적은 고칠 수 없습니다' : ''}>
        이 견적 수정본(revision) 만들기</button>}
    </div>
    <ErrorBox error={err}/>
  </div>;
}

function QuoteDetail({quote, onQuote}: {quote: Quote; onQuote: (q: Quote) => void}) {
  const [reviewed, setReviewed] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [requested, setRequested] = useState<string | null>(null);
  const base = tpath(`/tasks/${encodeURIComponent(quote.task)}/quotes/${encodeURIComponent(quote.quote_id)}`);
  const confirm = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api<{approval_id: string; state: string}>('POST', `${base}/confirm`, {reviewed, review_note: note});
      setRequested(r.approval_id);
      onQuote(await api<Quote>('GET', base));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const csv = async () => {
    setErr(null);
    try { await apiDownload(`${base}.csv`, `${quote.quote_id}.csv`); } catch (e) { setErr(e); }
  };
  return <div className="card" data-testid="quote-detail" data-status={quote.status}>
    <div className="row"><h2 style={{margin: 0}}>견적 {quote.quote_id}</h2><StateBadge state={quote.status}/>
      <span className="muted">revision {quote.revision}</span><SyntheticBadge synthetic={quote.synthetic}/></div>
    <Notice text={quote.notice}/>
    <div className="cols">
      <MoneyTable costs={quote.costs} total={quote.total} lines={quote.lines} currency={quote.currency}/>
      <div>
        <KeyValue rows={[
          ['도면', quote.doc_id ?? '—'], ['이전 revision', quote.supersedes ?? '—'],
          ['검토', quote.reviewed ? `${quote.reviewed_by ?? '—'} · ${quote.review_note ?? ''}` : '검토 전'],
          ['확정', quote.confirmed_by ? `${quote.confirmed_by} · ${quote.confirmed_at ?? '—'}` : '—'],
          ['승인 요청', quote.approval_id ?? '—'],
          ['단가 · 계수', Object.entries(quote.rates).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'],
        ]}/>
        <table className="grid"><caption>작업시간 예측 (근거)</caption>
          <thead><tr><th>과제</th><th>값</th><th>예측 ID</th></tr></thead>
          <tbody>{quote.predictions.map(p => <tr key={p.prediction_id}><td>{p.task}</td><td>{p.value} {p.unit}</td><td><IdLink id={p.prediction_id}/></td></tr>)}</tbody></table>
        <p className="muted">모델 {quote.model_versions.map(m => `${m.task}@${m.version}${m.synthetic ? ' (합성)' : ''}`).join(', ') || '—'}</p>
      </div>
    </div>
    <h3>사람 수정 이력 (overrides)</h3>
    {quote.overrides.length ? <table className="grid" data-testid="quote-overrides"><thead><tr><th>칸</th><th>인식값</th><th>확정값</th></tr></thead>
      <tbody>{quote.overrides.map((o, i) => <tr key={i}><td>{o.field}</td><td>{show(o.recognized)}</td><td>{show(o.confirmed)}</td></tr>)}</tbody></table>
      : <p className="muted">수정한 칸 없음</p>}
    {quote.status === 'confirmed' && <p className="notice">확정 · 잠금 — 금액은 확정 스냅숏 그대로이며 수정하면 409 quote_locked</p>}
    {quote.status === 'pending_confirm' && <p className="notice">확정 대기 — 화면 5 승인 대기열에서 approver 이상이 결정합니다{requested ? ` (승인 ${requested})` : ''}</p>}
    {quote.status === 'draft' && <div style={{marginTop: 8}}>
      <label><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/> 입력 · 금액을 검토했습니다</label>
      <label style={{display: 'block'}}>검토 메모 (5자 이상)
        <textarea rows={2} style={{width: '100%'}} maxLength={500} value={note} onChange={e => setNote(e.target.value)}/></label>
      <button className="primary" disabled={busy} onClick={() => void confirm()}>확정 요청</button>
    </div>}
    <div className="row" style={{marginTop: 8}}><button onClick={() => void csv()}>CSV 내려받기</button></div>
    <ErrorBox error={err}/>
  </div>;
}

function History({task, onPick}: {task: string; onPick: (q: Quote) => void}) {
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const list = useList<Quote>(tpath(`/tasks/${encodeURIComponent(task)}/quotes${q ? `?search=${encodeURIComponent(q)}` : ''}`), [task, q]);
  return <div className="card"><h2>견적 이력</h2>
    <form className="row" onSubmit={e => { e.preventDefault(); setQ(search.trim()); }}>
      <label>검색 <input value={search} maxLength={80} onChange={e => setSearch(e.target.value)}/></label>
      <button type="submit">찾기</button>{list.total !== null && <span className="muted">총 {list.total}건</span>}
    </form>
    <ErrorBox error={list.error}/>
    {!list.loading && !list.error && list.items.length === 0 && <p className="muted">견적 없음</p>}
    {list.items.length > 0 && <div className="table-wrap"><table className="grid">
      <thead><tr><th>견적</th><th>상태</th><th>rev</th><th className="num">합계</th><th>시각</th><th/></tr></thead>
      <tbody>{list.items.map(it => <tr key={it.quote_id}><td><code>{it.quote_id}</code></td><td><StateBadge state={it.status}/></td>
        <td>{it.revision}</td><td className="num"><Money value={it.total}/></td><td>{it.created_at}</td>
        <td><button onClick={() => onPick(it)}>보기</button></td></tr>)}</tbody></table></div>}
    {list.next && <button onClick={() => void list.loadMore()}>더 보기</button>}
  </div>;
}
