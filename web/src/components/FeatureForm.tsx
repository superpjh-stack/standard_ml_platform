// 변수 폼 생성기 — features.yaml 메타(GET .../tasks/{task} 의 features)로 입력 폼을 만든다. 회사 화면 코드 0.
// 빈 칸은 null(보정 대상)로 보낸다. 범위 판정 · 보정은 서버가 한다 — 여기서는 min/max 힌트만 준다.
import type {FeatureMeta} from './types';
import './components.css';

export type Values = Record<string, number | string | boolean | null>;

export function initialValues(features: FeatureMeta[]): Values {
  const out: Values = {};
  for (const f of features) {
    const d = f.default as Values[string] | undefined;
    if (d !== undefined && d !== null) out[f.name] = d;
    else if (f.dtype === 'category' && f.values?.length) out[f.name] = f.values[0];
    else out[f.name] = null;
  }
  return out;
}

/** 서버로 보낼 값 — 숫자 문자열은 숫자로, 빈 값은 null. */
export function toInputs(features: FeatureMeta[], values: Values): Values {
  const out: Values = {};
  for (const f of features) {
    const v = values[f.name];
    if (v === '' || v === undefined) { out[f.name] = null; continue; }
    if ((f.dtype === 'float' || f.dtype === 'int') && typeof v === 'string') {
      const n = Number(v);
      out[f.name] = Number.isFinite(n) ? n : v;
    } else out[f.name] = v;
  }
  return out;
}

function hint(f: FeatureMeta): string {
  const parts: string[] = [];
  if (f.min != null || f.max != null) parts.push(`${f.min ?? ''}~${f.max ?? ''}`);
  if (f.step != null) parts.push(`간격 ${f.step}`);
  if (f.required === false) parts.push('비우면 보정');
  return parts.join(' · ');
}

export function FeatureForm({features, values, onChange, highlight, disabled}: {
  features: FeatureMeta[]; values: Values; onChange: (v: Values) => void;
  highlight?: {imputed?: string[]; outOfRange?: string[]};   // 응답의 imputed_fields · out_of_range_fields 표시
  disabled?: boolean;
}) {
  const set = (name: string, v: Values[string]) => onChange({...values, [name]: v});
  if (!features.length) return <p className="muted">입력 변수가 없습니다</p>;
  return <div className="feature-form">
    {features.map(f => {
      const id = `f-${f.name}`;
      const v = values[f.name];
      const cls = highlight?.outOfRange?.includes(f.name) ? 'field field-oor' : highlight?.imputed?.includes(f.name) ? 'field field-imputed' : 'field';
      let input;
      if (f.dtype === 'category') {
        input = <select id={id} value={v == null ? '' : String(v)} disabled={disabled}
                        onChange={e => set(f.name, e.target.value === '' ? null : e.target.value)}>
          {f.required === false && <option value="">(비움 — 보정)</option>}
          {(f.values ?? []).map(x => <option key={x} value={x}>{x}</option>)}
        </select>;
      } else if (f.dtype === 'bool') {
        input = <input id={id} type="checkbox" checked={v === true} disabled={disabled} onChange={e => set(f.name, e.target.checked)}/>;
      } else {
        input = <input id={id} type="number" inputMode="decimal" value={v == null ? '' : String(v)} disabled={disabled}
                       min={f.min ?? undefined} max={f.max ?? undefined}
                       step={f.dtype === 'int' || f.integer ? 1 : f.step ?? 'any'}
                       onChange={e => set(f.name, e.target.value === '' ? null : e.target.value)}/>;
      }
      return <div className={cls} key={f.name} data-field={f.name}>
        <label htmlFor={id}>{f.label ?? f.name}{f.unit && f.unit !== '-' ? <span className="unit"> ({f.unit})</span> : null}
          {f.required !== false && <span className="req" aria-label="필수">*</span>}</label>
        {input}
        <small className="muted">{hint(f)}</small>
      </div>;
    })}
  </div>;
}
