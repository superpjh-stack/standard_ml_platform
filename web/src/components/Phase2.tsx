// 2차 공용 조각 — 금액 · 문서 뷰어 · 라벨 안내 · 키-값 · 예측 ID 링크 (개발2 소유, 화면 7~10 공용).
// 금액은 서버가 준 원 단위 문자열을 그대로 쓴다 — Number 로 바꾸지 않는다(브라우저 계산 0, G2-Q01).
import {Fragment} from 'react';
import type {ReactNode} from 'react';
import type {DocumentExtraction, Won} from './types';
import './components.css';

/** "8486493" → "8,486,493" (문자열 연산만). 숫자 문자열이 아니면 그대로 보인다. */
export function groupWon(value: Won | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const m = /^(-?)(\d+)$/.exec(String(value));
  if (!m) return String(value);
  const digits = m[2];
  const parts: string[] = [];
  for (let end = digits.length; end > 0; end -= 3) parts.unshift(digits.slice(Math.max(0, end - 3), end));
  return m[1] + parts.join(',');
}

export function Money({value, currency = 'KRW'}: {value: Won | null | undefined; currency?: string}) {
  return <span className="money" data-won={value ?? ''}>{groupWon(value)}{value ? <span className="unit"> {currency === 'KRW' ? '원' : currency}</span> : null}</span>;
}

const COST_LABEL: Record<string, string> = {
  material: '소재', processing: '가공', labor: '가공(공수)', outsource: '외주', setup: '준비', markup: '가산',
  subtotal: '공급가', vat: '부가세', total: '합계',
};

/** 구성 금액 표 — costs: {이름: 원 문자열}, total, lines(품목 행). */
export function MoneyTable({costs, total, lines, currency = 'KRW'}: {
  costs: Record<string, Won>; total: Won; lines?: {name: string; amount: Won}[] | null; currency?: string;
}) {
  return <div className="money-table">
    {lines && lines.length > 0 && <table className="grid" data-testid="quote-lines">
      <caption>품목</caption>
      <thead><tr><th>품목</th><th className="num">금액</th></tr></thead>
      <tbody>{lines.map((l, i) => <tr key={i}><td>{l.name}</td><td className="num"><Money value={l.amount} currency={currency}/></td></tr>)}</tbody>
    </table>}
    <table className="grid" data-testid="quote-costs">
      <caption>구성 금액</caption>
      <tbody>
        {Object.entries(costs).map(([k, v]) => <tr key={k}><th scope="row">{COST_LABEL[k] ?? k} <code className="muted">{k}</code></th>
          <td className="num"><Money value={v} currency={currency}/></td></tr>)}
        <tr className="total"><th scope="row">합계</th><td className="num"><strong><Money value={total} currency={currency}/></strong></td></tr>
      </tbody>
    </table>
  </div>;
}

/** 정답 라벨 없으면 지표를 만들지 않는다(labels: none) — 그대로 말한다. */
export function LabelsNotice({labels, metrics}: {labels: string; metrics?: Record<string, unknown> | null}) {
  if (labels === 'none') return <p className="notice" data-labels="none">정답 라벨 없음 — 지표 없음 (labels: none)</p>;
  if (labels === 'synthetic') return <p className="notice" data-labels="synthetic">합성 라벨 기준 지표{metrics ? '' : ' 없음'} — 실도면 정답이 아닙니다 (labels: synthetic)</p>;
  return <p className="notice" data-labels={labels}>라벨: {labels}</p>;
}

export function KeyValue({rows}: {rows: [string, ReactNode][]}) {
  return <dl className="kv">{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v ?? '—'}</dd></Fragment>)}</dl>;
}

/** 예측 ID → 화면 10 추적. */
export function IdLink({id}: {id: string | null | undefined}) {
  if (!id) return <span className="muted">—</span>;
  return <a href={`/app/trace?prediction_id=${encodeURIComponent(id)}`}><code>{id}</code></a>;
}

const REGION_COLOR: Record<string, string> = {title_block: '#1d4e89', bom_table: '#17633a', rev_table: '#8a3a00', other: '#9b1c1c'};
const OBJECT_COLOR: Record<string, string> = {outer: '#1d2421', hole: '#1d4e89', slot: '#4b2a85', other: '#9b1c1c'};

function num(x: unknown): number { return typeof x === 'number' && Number.isFinite(x) ? x : 0; }

/** 문서 추출 결과 — SVG 미리보기(영역 · 객체 bbox, 좌표 mm) + 영역 · 객체 · BOM 표. */
export function DocumentViewer({doc}: {doc: DocumentExtraction}) {
  const boxes = [
    ...doc.regions.map(r => ({id: r.id, label: r.label, bbox: r.bbox, color: REGION_COLOR[r.label] ?? '#555', kind: 'region'})),
    ...doc.objects.map(o => ({id: o.id, label: o.label, bbox: o.bbox, color: OBJECT_COLOR[o.label] ?? '#555', kind: 'object'})),
  ].filter(b => Array.isArray(b.bbox) && b.bbox.length === 4);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const b of boxes) {
    x0 = Math.min(x0, num(b.bbox[0])); y0 = Math.min(y0, num(b.bbox[1]));
    x1 = Math.max(x1, num(b.bbox[2])); y1 = Math.max(y1, num(b.bbox[3]));
  }
  const has = boxes.length > 0 && x1 > x0 && y1 > y0;
  const pad = has ? Math.max(x1 - x0, y1 - y0) * 0.03 : 0;
  const vb = has ? `${x0 - pad} ${-(y1 + pad)} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}` : '0 0 1 1';
  const strokeW = has ? Math.max(x1 - x0, y1 - y0) / 300 : 1;
  return <div className="doc-viewer" data-doc={doc.doc_id}>
    <KeyValue rows={[
      ['파일', doc.filename], ['sha256', <code key="s">{doc.raw_sha256.slice(0, 16)}…</code>], ['단위', doc.unit],
      ['엔티티', String(doc.entity_count)],
      ['추출기', doc.extractor.map(e => `${e.name}@${e.version} (${e.kind}${e.model_version ? ` · ${e.model_version}` : ''})`).join(', ')],
      ['평균 점수', doc.confidence === null ? '— (규칙만)' : String(Number(doc.confidence.toFixed(4)))],
      ['개수', Object.entries(doc.counts).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'],
    ]}/>
    <LabelsNotice labels={doc.labels} metrics={doc.metrics}/>
    {doc.warnings.length > 0 && <ul className="warnings">{doc.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
    {has ? <svg className="doc-preview" viewBox={vb} role="img" aria-label="도면 미리보기" preserveAspectRatio="xMidYMid meet">
      {boxes.map(b => <g key={`${b.kind}-${b.id}`} data-box={b.label}>
        <rect x={num(b.bbox[0])} y={-num(b.bbox[3])} width={num(b.bbox[2]) - num(b.bbox[0])} height={num(b.bbox[3]) - num(b.bbox[1])}
              fill="none" stroke={b.color} strokeWidth={strokeW} strokeDasharray={b.kind === 'region' ? `${strokeW * 4} ${strokeW * 2}` : undefined}/>
        <title>{`${b.kind === 'region' ? '영역' : '객체'} ${b.id} · ${b.label}`}</title>
      </g>)}
    </svg> : <p className="muted">미리보기할 영역 · 객체가 없습니다</p>}
    {doc.regions.length > 0 && <div className="table-wrap"><table className="grid" data-testid="doc-regions">
      <caption>영역 ({doc.regions.length})</caption>
      <thead><tr><th>id</th><th>종류</th><th>상태</th><th>텍스트</th></tr></thead>
      <tbody>{doc.regions.map(r => <tr key={r.id}><td>{r.id}</td><td>{r.label}</td><td>{r.status}</td><td>{(r.texts ?? []).slice(0, 6).join(' / ')}</td></tr>)}</tbody>
    </table></div>}
    {doc.objects.length > 0 && <div className="table-wrap"><table className="grid" data-testid="doc-objects">
      <caption>객체 ({doc.objects.length})</caption>
      <thead><tr><th>id</th><th>종류</th><th>모델 판정</th><th>점수</th><th>검토 사유</th></tr></thead>
      <tbody>{doc.objects.map(o => <tr key={o.id}><td>{o.id}</td><td>{o.label}</td><td>{o.model_label ?? '—'}</td>
        <td>{o.confidence === null ? '—' : String(Number(o.confidence.toFixed(3)))}</td><td>{o.review_reason ?? '—'}</td></tr>)}</tbody>
    </table></div>}
    {doc.bom_rows.length > 0 && <div className="table-wrap"><table className="grid" data-testid="doc-bom">
      <caption>BOM ({doc.bom_rows.length})</caption>
      <thead><tr><th>품명</th><th>재질</th><th>수량</th><th>개당 중량 kg</th><th>출처</th></tr></thead>
      <tbody>{doc.bom_rows.map((b, i) => <tr key={i}><td>{b.name}</td><td>{b.material}</td><td>{String(b.quantity)}</td>
        <td>{String(b.mass_kg)}</td><td>{b.source}</td></tr>)}</tbody>
    </table></div>}
  </div>;
}
