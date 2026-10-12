// 콘솔 공용 API 클라이언트 (개발2 소유 — 화면 1~10 이 같이 쓴다).
// 연결 정보: 회사 코드는 localStorage, **API 키는 sessionStorage**(탭을 닫으면 사라진다 — F16-9, DEF 관찰 #16).
// 예전 형식(localStorage 에 키까지 저장)은 읽을 때 키를 sessionStorage 로 옮기고 localStorage 에서 지운다.
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
const STORE = 'mlp.console.connection';        // localStorage — {tenant} 만
const KEY_STORE = 'mlp.console.key';           // sessionStorage — API 키
const listeners = new Set<(c: Connection) => void>();

export function getConnection(): Connection {
  let tenant = '';
  let key = '';
  try {
    const raw = localStorage.getItem(STORE);
    if (raw) {
      const c = JSON.parse(raw);
      tenant = String(c.tenant ?? '');
      if (c.key) {                               // 예전 형식 — 키를 세션으로 옮기고 영구 저장소에서 지운다
        sessionStorage.setItem(KEY_STORE, String(c.key));
        localStorage.setItem(STORE, JSON.stringify({tenant}));
      }
    }
  } catch { /* 저장소 없음 */ }
  try { key = sessionStorage.getItem(KEY_STORE) ?? ''; } catch { /* 저장소 없음 */ }
  return {tenant, key};
}

export function setConnection(c: Connection) {
  try { localStorage.setItem(STORE, JSON.stringify({tenant: c.tenant})); } catch { /* 저장소 없음 */ }
  try { if (c.key) sessionStorage.setItem(KEY_STORE, c.key); else sessionStorage.removeItem(KEY_STORE); } catch { /* 저장소 없음 */ }
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

async function raise(res: Response): Promise<never> {
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  const err: ApiErrorBody = data?.error ?? {code: `http_${res.status}`, message: '요청을 처리할 수 없습니다'};
  throw new ApiError(res.status, err);
}

/** multipart POST (도면 업로드 · CSV 업로드). 오류 봉투는 ApiError 로 올린다. */
export async function apiUpload<T = unknown>(path: string, form: FormData): Promise<T> {
  const c = getConnection();
  const headers: Record<string, string> = {};
  if (c.key) headers['X-API-Key'] = c.key;
  const res = await fetch(`/api/v1${path}`, {method: 'POST', headers, body: form});
  if (!res.ok) return raise(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

/** 파일 내려받기(CSV) — 키 헤더가 필요해 링크 대신 fetch → Blob. 내용은 서버 그대로(브라우저 계산 0). */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const c = getConnection();
  const headers: Record<string, string> = {};
  if (c.key) headers['X-API-Key'] = c.key;
  const res = await fetch(`/api/v1${path}`, {headers});
  if (!res.ok) return raise(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 커서 목록 `{items, next_cursor, total}` — path 에 이미 ? 가 있어도 된다. path 가 null 이면 부르지 않는다. */
export function useList<T>(path: string | null, deps: unknown[] = []) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<Record<string, unknown>>({});   // 목록 응답의 items 밖 키(예 B09 can_decide)
  const fetchPage = useCallback(async (cursor: string | null) => {
    if (!path) { setItems([]); setNext(null); setTotal(null); setMeta({}); return; }
    setLoading(true); setError(null);
    const url = cursor ? `${path}${path.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(cursor)}` : path;
    try {
      const r = await api<{items: T[]; next_cursor: string | null; total?: number} & Record<string, unknown>>('GET', url);
      if (!cursor) { const {items: _i, next_cursor: _n, total: _t, ...rest} = r; void _i; void _n; void _t; setMeta(rest); }
      setItems(prev => cursor ? [...prev, ...r.items] : r.items);
      setNext(r.next_cursor ?? null);
      setTotal(typeof r.total === 'number' ? r.total : null);
    } catch (e) { if (!cursor) setItems([]); setError(e as Error); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { void fetchPage(null); }, [fetchPage]);
  return {items, total, next, error, loading, meta, reload: () => fetchPage(null), loadMore: () => next ? fetchPage(next) : Promise.resolve()};
}

/** JSON 본문을 **문자열 그대로** 보낸다 — 금액 · 수치 입력을 브라우저 Number(float)로 바꾸지 않기 위해(견적). */
export async function apiJsonText<T = unknown>(method: string, path: string, jsonText: string): Promise<T> {
  JSON.parse(jsonText);                         // 형식만 확인(값은 쓰지 않는다)
  const c = getConnection();
  const headers: Record<string, string> = {'Content-Type': 'application/json'};
  if (c.key) headers['X-API-Key'] = c.key;
  const res = await fetch(`/api/v1${path}`, {method, headers, body: jsonText});
  if (!res.ok) return raise(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}
