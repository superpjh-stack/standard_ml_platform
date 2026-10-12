// 화면 지도 — contracts/screen-map.md 와 같다. 회사 화면 코드는 0 (G-S03).
import Overview from './Overview';
import Predict from './Predict';
import Optimize from './Optimize';
import Models from './Models';
import Approvals from './Approvals';
import Monitor from './Monitor';
import Sources from './Sources';
import Review from './Review';
import Quotes from './Quotes';
import Trace from './Trace';

export const SCREENS = [
  {no: 1, path: 'overview', label: '회사 · 과제 개요', Component: Overview},
  {no: 2, path: 'predict', label: '예측 시험', Component: Predict},
  {no: 3, path: 'optimize', label: '조건 추천', Component: Optimize},
  {no: 4, path: 'models', label: '모델 비교 · 검증', Component: Models},
  {no: 5, path: 'approvals', label: '승인 대기열', Component: Approvals},
  {no: 6, path: 'monitor', label: '감시', Component: Monitor},
  {no: 7, path: 'sources', label: '데이터 소스 · 스냅숏', Component: Sources},
  {no: 8, path: 'review', label: '검토 대기열', Component: Review},
  {no: 9, path: 'quotes', label: '도면 추출 · 견적', Component: Quotes},
  {no: 10, path: 'trace', label: '감사 · 예측 추적', Component: Trace},
] as const;
