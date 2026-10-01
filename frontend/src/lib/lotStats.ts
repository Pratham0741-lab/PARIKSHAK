/**
 * Lot analytics computed in the browser from the API's readings and predictions (no new data sources).
 * Every threshold here is a documented constant shown next to the panel that uses it.
 */
import { Lot, Param, Part, Prediction } from '../data/types';
import { calculateMAD, calculateMedian } from './analytics/robustZ';

export const MAD_TO_SD = 1.4826;
/** Robust band used by the measurement-risk heatmap: |x - median| > ROBUST_Z_CUT * 1.4826 * MAD. */
export const ROBUST_Z_CUT = 3.5;

export function valuesAt(parts: Part[], param: Param, t: number): number[] {
  const out: number[] = [];
  for (const p of parts) {
    const r = p.allReadings.find(x => x.intervalHours === t);
    const v = r?.values[param];
    if (v != null && Number.isFinite(v)) out.push(v);
  }
  return out;
}

export function robust(values: number[]): { median: number; mad: number; n: number } | null {
  if (values.length === 0) return null;
  const median = calculateMedian(values);
  return { median, mad: calculateMAD(values, median), n: values.length };
}

/** Fraction of parts outside the robust band at a time point (null if no readings). */
export function outsideFraction(values: number[], z = ROBUST_Z_CUT): number | null {
  const r = robust(values);
  if (!r) return null;
  const s = Math.max(MAD_TO_SD * r.mad, 1e-12);
  return values.filter(v => Math.abs(v - r.median) / s > z).length / values.length;
}

export function verdictCounts(parts: Part[], predictions: Record<string, Prediction>) {
  const c = { PASS: 0, REVIEW: 0, REJECT: 0, none: 0, moduleA: 0, moduleB: 0 };
  for (const p of parts) {
    const pr = predictions[p.partId];
    const v = pr?.verdict;
    if (v === 'PASS' || v === 'REVIEW' || v === 'REJECT') c[v] += 1;
    else c.none += 1;
    if (pr?.moduleA?.flag) c.moduleA += 1;
    if (pr?.moduleB?.flag) c.moduleB += 1;
  }
  return c;
}

/** Per-lot rates from the lots list (model verdicts; never ground truth). */
export function lotRates(l: Lot) {
  const n = l.totalParts || 0;
  return {
    n,
    flagRate: n ? (l.reviewCount + l.rejectCount) / n : null,
    anomalyRate: n && l.moduleAFlagCount != null ? l.moduleAFlagCount / n : null,
    driftRate: n && l.moduleBFlagCount != null ? l.moduleBFlagCount / n : null,
  };
}

/** Documented lot-status rule: a lot is "Monitoring" when its Module A or Module B flag rate is above the median
 * across all lots by more than STATUS_Z robust SDs (1.4826 x MAD across lots); otherwise "Stable". */
export const STATUS_Z = 2;
export function lotStatusRule(lots: Lot[]) {
  const rates = lots.map(lotRates);
  const ref = (k: 'anomalyRate' | 'driftRate') => robust(rates.map(r => r[k]).filter((x): x is number => x != null));
  const ra = ref('anomalyRate');
  const rd = ref('driftRate');
  const above = (x: number | null, r: { median: number; mad: number } | null) =>
    x != null && r != null && x > r.median + STATUS_Z * Math.max(MAD_TO_SD * r.mad, 1e-9);
  return (l: Lot): { status: 'Monitoring' | 'Stable' | 'n/a'; why: string } => {
    const x = lotRates(l);
    if (x.anomalyRate == null || x.driftRate == null) return { status: 'n/a', why: 'no Module A/B flag counts for this lot' };
    const a = above(x.anomalyRate, ra), d = above(x.driftRate, rd);
    return a || d
      ? { status: 'Monitoring', why: `${a ? 'anomaly' : 'drift'} rate above the cross-lot median + ${STATUS_Z} robust SD` }
      : { status: 'Stable', why: `anomaly and drift rates within the cross-lot median + ${STATUS_Z} robust SD` };
  };
}

/** Threshold for highlighting a lot's flag rate in Trends: cross-lot median + 3 robust SDs. */
export const HIGHLIGHT_Z = 3;
export function highlightThreshold(values: number[]): number | null {
  const r = robust(values);
  return r ? r.median + HIGHLIGHT_Z * MAD_TO_SD * r.mad : null;
}
