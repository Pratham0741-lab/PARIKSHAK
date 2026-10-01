import { Lot, PARAM_UNIT, Part, Prediction, lotParam } from '../data/types';

/** Anomaly score shown in the UI: max(Module A score / threshold A, Module B z / k), the same definition as the
 * judge-mode export (ml_engine/judge.py). null when the part has no model score. */
export function anomalyScore(pr: Prediction | null | undefined): number | null {
  if (!pr) return null;
  const a = pr.moduleA && pr.moduleA.threshold ? pr.moduleA.score / pr.moduleA.threshold : null;
  const b = pr.moduleB && pr.moduleB.score != null && pr.moduleB.thresholdK && pr.moduleB.thresholdK > 0 ? pr.moduleB.score / pr.moduleB.thresholdK : null;
  const xs = [a, b].filter((v): v is number => v != null && Number.isFinite(v));
  return xs.length ? Math.max(...xs) : null;
}

export function lotCsv(lot: Lot | null, parts: Part[], predictions: Record<string, Prediction>): string {
  const param = lotParam(lot);
  const header = ['part_id', 'lot', ...[0, 24, 96, 168].map(h => `${param}_${h}h`), `forecast_${param}_168h`, 'interval_lower', 'interval_upper',
    'anomaly_score', 'module_a_score', 'threshold_a', 'module_b_z', 'threshold_b', 'model_verdict', 'status', 'status_source', 'inspector', 'reason'];
  const q = (v: unknown) => (v == null ? '' : typeof v === 'string' ? `"${v.replace(/"/g, '""')}"` : String(v));
  return [header.join(','), ...parts.map(p => {
    const pr = predictions[p.partId];
    const l = pr?.moduleB?.perParam[param];
    return [p.partId, lot?.lotNumber, p.readings[0], p.readings[24], p.readings[96], p.readings[168], l?.forecast168h, l?.intervalLower, l?.intervalUpper,
      anomalyScore(pr), pr?.moduleA?.score, pr?.moduleA?.threshold, pr?.moduleB?.score, pr?.moduleB?.thresholdK, pr?.verdict, p.status, p.statusSource,
      p.inspector, p.reason].map(q).join(',');
  })].join('\n');
}

export function download(name: string, text: string, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export const unitOf = (lot: Lot | null) => PARAM_UNIT[lotParam(lot)];
