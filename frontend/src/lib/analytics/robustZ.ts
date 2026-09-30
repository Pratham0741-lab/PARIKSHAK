/**
 * Robust Z-Score calculations using Median and Median Absolute Deviation (MAD).
 * Space-grade screening standard resistant to heavy-tailed anomaly distortions.
 */

export function calculateMedian(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 !== 0) {
    return sorted[mid];
  }
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

export function calculateMAD(values: number[], precomputedMedian?: number): number {
  if (values.length === 0) return 0;
  const med = precomputedMedian !== undefined ? precomputedMedian : calculateMedian(values);
  const absoluteDeviations = values.map(v => Math.abs(v - med));
  return calculateMedian(absoluteDeviations);
}

const NORMAL_CONSISTENCY_CONSTANT = 1.4826;
const EPSILON = 1e-6;

export function calculateRobustZ(value: number, median: number, mad: number): number {
  const scaledMad = Math.max(mad * NORMAL_CONSISTENCY_CONSTANT, EPSILON);
  return (value - median) / scaledMad;
}

export function computeBatchRobustZ(values: number[]): {
  median: number;
  mad: number;
  scaledMad: number;
  zScores: number[];
} {
  const median = calculateMedian(values);
  const mad = calculateMAD(values, median);
  const scaledMad = Math.max(mad * NORMAL_CONSISTENCY_CONSTANT, EPSILON);
  const zScores = values.map(v => (v - median) / scaledMad);

  return {
    median,
    mad,
    scaledMad,
    zScores,
  };
}
