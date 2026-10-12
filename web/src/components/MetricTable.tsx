// 지표 표 — 모든 지표는 기준선과 함께 (spec §2.4). 기준선을 못 이기면 표시한다.
import type {Metric} from './types';
import './components.css';

// 낮을수록 좋은 지표 (std/metrics.yaml direction). 모르는 지표는 우열을 표시하지 않는다.
const LOWER = new Set(['mae', 'rmse', 'mape', 'brier', 'log_loss']);
const HIGHER = new Set(['r2', 'roc_auc', 'pr_auc', 'ap', 'auc', 'coverage', 'f1', 'precision', 'recall']);

export function fmt(v: unknown, nd = 4): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isFinite(v) ? String(Number(v.toFixed(nd))) : '—';
  return String(v);
}

export function beats(name: string, m: Metric): boolean | null {
  if (m.value == null || m.baseline == null) return null;
  const n = name.toLowerCase();
  if (LOWER.has(n)) return m.value < m.baseline;
  if (HIGHER.has(n)) return m.value > m.baseline;
  return null;
}

/** metrics: {지표 이름: {value, baseline, delta_vs_baseline}} 또는 {지표 이름: 숫자}. */
export function MetricTable({metrics, caption, compare}: {
  metrics: Record<string, Metric | number | null> | null | undefined; caption?: string;
  compare?: Record<string, Metric | number | null> | null;   // 예: 현재 production 지표
}) {
  const rows = Object.entries(metrics ?? {}).map(([k, v]) => [k, typeof v === 'number' || v === null ? {value: v} : v] as [string, Metric]);
  if (!rows.length) return <p className="muted">지표 없음</p>;
  return <table className="grid metric-table">
    {caption && <caption>{caption}</caption>}
    <thead><tr><th>지표</th><th>값</th><th>기준선</th><th>Δ</th><th>판정</th>{compare && <th>비교 대상</th>}</tr></thead>
    <tbody>{rows.map(([k, m]) => {
      const b = beats(k, m);
      const c = compare?.[k];
      const cv = typeof c === 'number' || c == null ? c : c.value;
      return <tr key={k}>
        <th scope="row">{k}</th><td>{fmt(m.value)}</td><td>{fmt(m.baseline)}</td><td>{fmt(m.delta_vs_baseline)}</td>
        <td>{b === null ? '—' : b ? <span className="badge badge-ok">기준선 이김</span> : <span className="badge badge-rejected">기준선 못 이김</span>}</td>
        {compare && <td>{fmt(cv)}</td>}
      </tr>;
    })}</tbody>
  </table>;
}
