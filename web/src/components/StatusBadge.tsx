// 상태 배지 — 상태 코드 6(std/statuses.yaml). 판단은 코드로, 문구는 labels 로 바꿀 수 있다.
import type {Status} from './types';
import './components.css';

export const STATUS_LABEL: Record<Status, string> = {
  ok: '정상', watch: '주의', review: '검토 필요', out_of_range: '범위 밖', rejected: '예측 불가', needs_approval: '승인 필요',
};

export function StatusBadge({status, labels}: {status: Status | string; labels?: Partial<Record<string, string>>}) {
  const label = labels?.[status] ?? STATUS_LABEL[status as Status] ?? status;
  return <span className={`badge badge-${status}`} data-status={status}>{label}</span>;
}

/** 합성 모델 배지 — 합성 스냅숏으로 학습한 모델의 답이면 반드시 보인다. */
export function SyntheticBadge({synthetic}: {synthetic: boolean | null | undefined}) {
  if (!synthetic) return null;
  return <span className="badge badge-synthetic" title="합성 데이터로 학습한 모델입니다">합성</span>;
}

/** 학습 범위 배지 — 탐색점 · 입력이 학습 범위(p1~p99) 안인가. */
export function RangeBadge({inRange, rate}: {inRange?: boolean; rate?: number}) {
  const ok = rate !== undefined ? rate >= 1 : !!inRange;
  const text = rate !== undefined ? `학습 범위 안 ${(rate * 100).toFixed(0)}%` : ok ? '학습 범위 안' : '학습 범위 밖';
  return <span className={`badge ${ok ? 'badge-ok' : 'badge-out_of_range'}`}>{text}</span>;
}

/** 승인 상태 배지 (mlp_approval.state). */
export function StateBadge({state}: {state: string}) {
  const map: Record<string, [string, string]> = {
    pending: ['대기', 'watch'], approved: ['승인', 'ok'], rejected: ['반려', 'rejected'], expired: ['만료', 'out_of_range'],
    candidate: ['후보', 'watch'], staging: ['검증', 'review'], production: ['운영', 'ok'], archived: ['보관', 'out_of_range'],
    // 2차 — 검토 대기열 (mlp_review_item.state) · 견적 (mlp_quote.status)
    open: ['검토 대기', 'watch'], confirmed_issue: ['문제 확인', 'rejected'], false_alarm: ['오탐', 'ok'],
    draft: ['초안', 'watch'], pending_confirm: ['확정 대기', 'needs_approval'], confirmed: ['확정 · 잠금', 'locked'],
  };
  const [label, cls] = map[state] ?? [state, 'watch'];
  return <span className={`badge badge-${cls}`} data-state={state}>{label}</span>;
}
