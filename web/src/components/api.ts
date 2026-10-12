// 콘솔 공용 API 클라이언트 (개발2 소유 — 화면 1~6 이 같이 쓴다).
// 연결 정보(회사 코드 · API 키)는 이 브라우저의 localStorage 에만 둔다. 서버 · 코드에 키를 적지 않는다.
import {useCallback, useEffect, useState} from 'react';

export type ApiErrorBody = {code: string; message: string; detail?: Record<string, unknown>};

export class ApiError extends Error {
  status: number; code: string; detail: Record<string, unknown>;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status; this.code = body.code; this.detail = body.detail ?? {};
  }
}

export type Connection = {tenant: string; key: string};
const STORE = 'mlp.console.connection';
const listeners = new Set<(c: Connection) => void>();

export function getConnection(): Connection {
  try {
    const raw = localStorage.getItem(STORE);
    if (raw) { const c = JSON.parse(raw); return {tenant: String(c.tenant ?? ''), key: String(c.key ?? '')}; }
  } catch { /* 저장소 없음 */ }
  return {tenant: '', key: ''};
}

export function setConnection(c: Connection) {
  try { localStorage.setItem(STORE, JSON.stringify(c)); } catch { /* 저장소 없음 */ }
  listeners.forEach(fn => fn(c));
}

export function useConnection(): [Connection, (c: Connection) => void] {
  const [c, setC] = useState<Connection>(getConnection());
  useEffect(() => { listeners.add(setC); return () => { listeners.delete(setC); }; }, []);
  return [c, setConnection];
}

/** /api/v1 호출. 오류 봉투 {error:{code,message,detail}} 는 ApiError 로 올린다(숨기지 않는다). */
export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const c = getConnection();
  const headers: Record<string, string> = {};
  if (c.key) headers['X-API-Key'] = c.key;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(`/api/v1${path}`, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const err: ApiErrorBody = data?.error ?? {code: `http_${res.status}`, message: '요청을 처리할 수 없습니다'};
    throw new ApiError(res.status, err);
  }
  return data as T;
}

/** 회사 범위 경로 — /tenants/{t}{rest} */
export function tpath(rest: string): string {
  return `/tenants/${encodeURIComponent(getConnection().tenant)}${rest}`;
}

/** GET 을 부르고 {data, error, loading, reload} 를 돌려준다. path 가 null 이면 부르지 않는다. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!path) { setData(null); return; }
    setLoading(true); setError(null);
    try { setData(await api<T>('GET', path)); } catch (e) { setData(null); setError(e as Error); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { void load(); }, [load]);
  return {data, error, loading, reload: load};
}
