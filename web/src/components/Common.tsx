// 공용 조각 — 연결 막대 · 오류 상자 · 과제 선택 · 경고 목록 (개발2 소유, 화면 1~6 공용).
import {useEffect} from 'react';
import {ApiError, useApi, useConnection, tpath} from './api';
import type {ListResponse, TaskInfo, Warning} from './types';
import './components.css';

/** 회사 코드 · API 키 입력 — 이 브라우저에만 저장한다. */
export function ConnectionBar() {
  const [c, setC] = useConnection();
  return <form className="conn" onSubmit={e => e.preventDefault()} aria-label="연결">
    <label>회사 코드 <input value={c.tenant} size={8} onChange={e => setC({...c, tenant: e.target.value.trim()})}/></label>
    <label>API 키 <input type="password" value={c.key} size={24} autoComplete="off"
                         onChange={e => setC({...c, key: e.target.value.trim()})}/></label>
    {!c.tenant || !c.key ? <span className="muted">회사 코드와 API 키를 넣으세요</span> : null}
  </form>;
}

const CODE_TEXT: Record<string, string> = {
  model_not_ready: '운영 모델 없음 (model_not_ready)',
  model_artifact_mismatch: '모델 산출물 불일치 (model_artifact_mismatch)',
  source_disconnected: '미연결 (source_disconnected)',
  auth_required: 'API 키가 없거나 틀립니다 (auth_required)',
  forbidden: '권한이 없습니다 (forbidden)',
  not_found: '찾을 수 없습니다 (not_found)',
  already_decided: '이미 결정된 승인입니다 (already_decided)',
  invalid_transition: '등록부 전이 규칙 위반 (invalid_transition)',
  not_implemented: '2차 범위입니다 (not_implemented)',
  invalid_input: '입력 값이 올바르지 않습니다 (invalid_input)',
  missing_required: '필수 입력이 없습니다 (missing_required)',
  out_of_bounds: '허용 범위 밖입니다 (out_of_bounds)',
  invalid_document: '도면 파일이 올바르지 않습니다 (invalid_document)',
  document_too_large: '도면이 상한을 넘습니다 (document_too_large)',
  quote_locked: '확정된 견적은 고칠 수 없습니다 (quote_locked)',
};

/** 오류를 그대로 보인다 — 숨기거나 대체 값으로 바꾸지 않는다. */
export function ErrorBox({error}: {error: unknown}) {
  if (!error) return null;
  if (error instanceof ApiError) {
    const d = error.detail ?? {};
    const where = [d.field ? `변수 ${String(d.field)}` : '', d.rule ? `규칙 ${String(d.rule)}` : ''].filter(Boolean).join(' · ');
    return <div className="error" role="alert" data-code={error.code}>
      <strong>{error.status} · {CODE_TEXT[error.code] ?? error.code}</strong>
      <div>{error.message}{where ? ` (${where})` : ''}</div>
    </div>;
  }
  return <div className="error" role="alert"><strong>오류</strong><div>{String((error as Error)?.message ?? error)}</div></div>;
}

/** 과제 선택 — types 로 거른다(예: optimize 만). 과제 목록은 B02 GET /tenants/{t}/tasks. */
export function TaskPicker({value, onChange, types, exclude}: {
  value: string; onChange: (task: string) => void; types?: string[]; exclude?: string[];
}) {
  const [c] = useConnection();
  const {data, error} = useApi<ListResponse<TaskInfo>>(c.tenant && c.key ? tpath('/tasks') : null, [c.tenant, c.key]);
  const items = (data?.items ?? []).filter(t => (!types || types.includes(t.type)) && !(exclude ?? []).includes(t.type));
  useEffect(() => {
    if (items.length && !items.some(t => t.task === value)) onChange(items[0].task);
  }, [items.map(t => t.task).join(','), value]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <ErrorBox error={error}/>;
  return <label className="picker">과제 <select value={value} onChange={e => onChange(e.target.value)}>
    {!items.length && <option value="">(과제 없음)</option>}
    {items.map(t => <option key={t.task} value={t.task}>{t.title ? `${t.title} — ` : ''}{t.task} [{t.type}]</option>)}
  </select></label>;
}

export function Warnings({warnings}: {warnings: Warning[]}) {
  if (!warnings.length) return <p className="muted">경고 없음</p>;
  return <ul className="warnings">{warnings.map((w, i) =>
    <li key={i} data-code={w.code}><code>{w.code}</code>{w.field ? <> · <code>{w.field}</code></> : null} — {w.message}</li>)}</ul>;
}

export function Notice({text}: {text: string | null | undefined}) {
  return text ? <p className="notice">{text}</p> : null;
}
