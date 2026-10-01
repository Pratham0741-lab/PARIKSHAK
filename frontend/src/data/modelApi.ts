/** Model report (/metrics/model) and API health. Values are displayed as returned. */
import { DEFAULT_API_URL } from './api';

export interface Detection { n: number; tp: number; fp: number; fn: number; tn: number; recall: number; precision: number; f2: number; weighted_cost: number; false_negative_rate?: number }
export interface ScoreBlock {
  detection: Detection;
  regression?: Record<string, { model: { mae: number; rmse: number }; linear_baseline?: { mae: number; rmse: number }; interval?: { empirical_coverage: number } }>;
  trivial_policies?: { flag_all_parts: { weighted_cost: number }; flag_no_parts: { weighted_cost: number } };
  n_scored?: number;
}
export interface ModelReport {
  registry: { id: string; created_at: string; current: boolean; artifact: string | null; held_out_recall: number | null; held_out_precision: number | null; held_out_weighted_cost: number | null }[];
  held_out: ScoreBlock;
  train_optimistic: ScoreBlock | null;
  split: { method: string; n_lots: number; n_parts: number } | null;
  protocol: string | null;
  feature_importance: { method: string; per_parameter: Record<string, { feature: string; label: string; share: number }[]> } | Record<string, never>;
  predicted_vs_actual: { parameter: string; unit: string; points: { pred: number; actual: number; lo: number | null; hi: number | null; linear: number }[] };
}

export async function getModelReport(): Promise<ModelReport> {
  const res = await fetch(`${DEFAULT_API_URL}/metrics/model`);
  if (!res.ok) throw new Error(`GET /metrics/model failed with HTTP ${res.status}`);
  return res.json();
}

/** Real API health: GET /health on the backend root. */
export async function getHealth(): Promise<boolean> {
  try {
    const res = await fetch(DEFAULT_API_URL.replace(/\/api\/v1\/?$/, '') + '/health');
    return res.ok;
  } catch {
    return false;
  }
}
