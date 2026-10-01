/**
 * Judge mode client (backend only: training, prediction and scoring all run server-side in
 * ml_engine/judge.py and evaluation/score.py). Values are displayed as returned; nothing is computed here.
 */
import { DEFAULT_API_URL } from './api';

export interface Detection {
  n: number; tp: number; fp: number; fn: number; tn: number;
  recall: number; precision: number; f2: number; weighted_cost: number;
  cost_config: { fn_cost: number; fp_cost: number };
}
export interface JudgeMetrics {
  n_predictions: number; n_scored: number; n_excluded_no_truth: number; primary_parameter: string;
  detection: Detection;
  confusion_matrix: { tp: number; fn: number; fp: number; tn: number };
  trivial_policies: { flag_all_parts: { weighted_cost: number }; flag_no_parts: { weighted_cost: number } };
  regression: { n: number; mae: number | null; rmse: number | null };
  interval: { n: number; coverage: number | null; mean_width: number | null };
  per_label: Record<string, { n: number; flagged_rate: number }>;
  truth_source?: string; reproduce_with?: string; predictions_sha256?: string;
}
export interface JudgeModelInfo {
  file: string; data_sha256: string; n_parts: number; n_lots: number; n_parts_excluded_insufficient: number;
  parameters: string[]; primary_parameter: string; label_source: string; evaluation_split: string;
  single_lot: boolean; oof_metrics: JudgeMetrics; trained_at: string;
  path: string; banner: string[]; max_flag_rate: number;
  paths_tried: { path: string; flag_rate: number; rejected_because: string[] }[];
  thresholds: { threshold_a: number | null; threshold_b: number | null; source: string };
}
export interface JudgeJob { id: string; state: 'running' | 'done' | 'failed'; message: string; file: string; model?: JudgeModelInfo }
export interface Explanation {
  module_a: { score: number | null; threshold: number | null; flag: boolean; top_parameter: string; robust_z: number | null; value_0_24h_mean: number | null; lot_median: number | null };
  module_b: { score: number | null; k: number | null; flag: boolean; top_parameter: string; predicted_rate: number | null; safety_slope: number | null };
  static_limit: { observed_breach: boolean; forecast_breach: boolean };
}
export interface JudgeRow {
  Part_ID: string; Predicted_168h: number | null; PI_low: number | null; PI_high: number | null;
  Anomaly_score: number | null; Flag: number; Reason: string; explanation: Explanation | null;
}
export interface JudgePrediction {
  input: { file: string; sha256: string; n_parts: number; n_lots: number; parameters: string[]; ignored_intervals: number[] };
  rows: JudgeRow[]; flagged: number; export_sha256: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${DEFAULT_API_URL}/judge${path}`, { ...init, headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = JSON.stringify((await res.json()).detail); } catch { /* no body */ }
    throw new Error(`${init?.method ?? 'GET'} /judge${path}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const judgeApi = {
  model: () => call<{ model: JudgeModelInfo | null; rule: { id: string; text: string }; export_columns: string[] }>('/model'),
  train: (csv: string, filename: string) => call<JudgeJob>('/train', { method: 'POST', body: JSON.stringify({ csv, filename }) }),
  job: (id: string) => call<JudgeJob>(`/jobs/${id}`),
  predict: (csv: string, filename: string) => call<JudgePrediction>('/predict', { method: 'POST', body: JSON.stringify({ csv, filename }) }),
  score: (truth_csv: string, truth_filename: string) =>
    call<JudgeMetrics>('/score', { method: 'POST', body: JSON.stringify({ truth_csv, truth_filename }) }),
  exportUrl: `${DEFAULT_API_URL}/judge/predictions.csv`,
};
