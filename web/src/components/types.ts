// 표준 계약 타입 (contracts/predict-contract.md · api-contract.md · feature-contract.md). 팩 · 회사 이름을 모른다.
export type Status = 'ok' | 'watch' | 'review' | 'out_of_range' | 'rejected' | 'needs_approval';

/** features.yaml 한 항목 — GET /tenants/{t}/tasks/{task} 의 features 에서 온다. */
export type FeatureMeta = {
  name: string; label?: string; dtype: 'float' | 'int' | 'category' | 'bool';
  unit?: string | null; min?: number | null; max?: number | null; values?: string[] | null;
  default?: unknown; required?: boolean; controllable?: boolean; step?: number | null; integer?: boolean;
};

export type ParamMeta = {name: string; label?: string; unit?: string | null; default?: number; min?: number; max?: number};

export type TaskInfo = {
  task: string; type: string; title?: string;
  features?: FeatureMeta[] | Record<string, Omit<FeatureMeta, 'name'>>;
  controls?: string[]; fixed?: string[];
  params?: ParamMeta[] | Record<string, Omit<ParamMeta, 'name'>>;
  uses?: string[]; approver_role?: string;
  [k: string]: unknown;
};

export type Warning = {code: string; field: string | null; message: string};
export type Candidate = {
  conditions: Record<string, number | string>; predictions: Record<string, number>;
  intervals: Record<string, [number, number] | null>;
  constraints: {name: string; expr: string; lhs: number; rhs: number; satisfied: boolean; slack: number}[];
  violation: number; objective_value: number;
};
export type Recommendation = {
  rec_id: string; feasible: boolean; strategy: 'grid' | 'random'; n_candidates: number; n_feasible: number;
  in_train_range_rate: number;
  objective: {name: string; direction: 'minimize' | 'maximize'; tiebreak: {name: string; direction: string}[]};
  best: Candidate; candidates: Candidate[]; current: Candidate | null;
  improvement: Record<string, number> | null; on_infeasible: 'least_violation' | null;
};
export type PredictResponse = {
  task: string; type: string; tenant: string; entity_id: string | null;
  prediction: {value: number | null; unit: string; interval: [number, number] | null; grade: string | null; baseline: number | null} | null;
  probability: number | null;
  anomaly: {score: number | null; flag: boolean | null; threshold: number | null; contamination: number | null;
            contributors: {field: string; contribution: number}[]} | null;
  recommendation: Recommendation | null;
  status: Status; warnings: Warning[]; imputed_fields: string[]; out_of_range_fields: string[];
  explain: {method: string; top: {field: string; contribution: number}[]} | null;
  model: {name: string; version: string; trained_at: string; snapshot_id: string; synthetic: boolean} | null;
  uses: {task: string; version: string; synthetic: boolean}[] | null;
  prediction_id: string | null; synthetic: boolean; notice: string;
};
export type Metric = {value: number | null; baseline?: number | null; delta_vs_baseline?: number | null};
export type ListResponse<T> = {items: T[]; next_cursor: string | null; total?: number};

/** dict 또는 배열로 온 메타를 이름 붙은 배열로. */
export function named<T extends {name: string}>(x: T[] | Record<string, Omit<T, 'name'>> | undefined | null): T[] {
  if (!x) return [];
  if (Array.isArray(x)) return x;
  return Object.entries(x).map(([name, v]) => ({...(v as object), name} as T));
}
