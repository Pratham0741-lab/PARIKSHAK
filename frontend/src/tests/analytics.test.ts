import { describe, it, expect } from 'vitest';
import { calculateMedian, calculateMAD, calculateRobustZ, computeBatchRobustZ } from '../lib/analytics/robustZ';
import { forecastDrift168h } from '../lib/analytics/driftForecast';
import { IsolationForest } from '../lib/analytics/isolationForest';
import { calculateMeanVector, computeCovarianceMatrix, invertMatrix, computeMahalanobisDistance } from '../lib/analytics/mahalanobis';
import { computePerformanceMetrics, generateRecallCurve } from '../lib/analytics/metrics';
import { parseAndValidateCsv } from '../lib/analytics/csvValidator';

describe('Robust Z-score Analytics', () => {
  it('calculates median correctly for odd and even length arrays', () => {
    expect(calculateMedian([1, 3, 2])).toBe(2);
    expect(calculateMedian([1, 2, 3, 4])).toBe(2.5);
    expect(calculateMedian([])).toBe(0);
  });

  it('calculates MAD correctly', () => {
    const vals = [1, 2, 3, 4, 5, 6, 7, 8, 9];
    const med = calculateMedian(vals);
    const mad = calculateMAD(vals, med);
    expect(med).toBe(5);
    expect(mad).toBe(2);
  });

  it('calculates robust z-score with divide-by-zero protection', () => {
    const z = calculateRobustZ(10, 10, 0);
    expect(z).toBe(0);
    const zExcursion = calculateRobustZ(20, 10, 2);
    expect(zExcursion).toBeGreaterThan(3.0);
  });

  it('computes batch robust z-score', () => {
    const batch = computeBatchRobustZ([10, 11, 10, 12, 11, 50]);
    expect(batch.median).toBe(11);
    expect(batch.zScores[batch.zScores.length - 1]).toBeGreaterThan(3.0);
  });
});

describe('Drift Forecast Analytics', () => {
  it('predicts 168h drift accurately based on 24h kinetic slope', () => {
    // 0h: 10, 24h: 12 -> slope = 2 / 24 = 0.0833
    // 168h predicted = 10 + 0.0833 * 168 = 24
    const res = forecastDrift168h(10, 12, 24, 0.15, 50.0);
    expect(res.predicted168h).toBeCloseTo(24.0, 1);
    expect(res.slopeUaPerHr).toBeCloseTo(0.0833, 3);
    expect(res.exceedsSafetySlope).toBe(false);
    expect(res.passesStaticLimit).toBe(true);
    expect(res.ciLowerUa).toBeLessThan(res.predicted168h);
    expect(res.ciUpperUa).toBeGreaterThan(res.predicted168h);
  });

  it('flags runaway thermal drift exceeding safety slope and static limit', () => {
    // 0h: 10, 24h: 20 -> slope = 10 / 24 = 0.4166
    // 168h predicted = 10 + 0.4166 * 168 = 80 (breaches 50 uA limit)
    const res = forecastDrift168h(10, 20, 85, 0.15, 50.0);
    expect(res.slopeUaPerHr).toBeGreaterThan(0.15);
    expect(res.exceedsSafetySlope).toBe(true);
    expect(res.passesStaticLimit).toBe(false);
    expect(res.residualUa).toBeCloseTo(5.0, 1);
  });
});

describe('Isolation Forest Analytics', () => {
  it('scores obvious multivariate outliers higher than nominal cluster points', () => {
    const iforest = new IsolationForest(30, 40);
    // Cluster around [10, 10]
    const nominalData: number[][] = [];
    for (let i = 0; i < 50; i++) {
      nominalData.push([10 + (i % 3) * 0.2, 10 + (i % 4) * 0.2]);
    }
    // Extreme outlier
    nominalData.push([150, 150]);

    iforest.fit(nominalData, 42);

    const nominalScore = iforest.score([10.1, 10.1]);
    const outlierScore = iforest.score([150, 150]);

    expect(outlierScore).toBeGreaterThan(nominalScore);
  });
});

describe('Mahalanobis Distance Analytics', () => {
  it('calculates mean vector and covariance correctly', () => {
    const data = [
      [1, 2],
      [3, 4],
      [5, 6],
    ];
    const mean = calculateMeanVector(data);
    expect(mean[0]).toBe(3);
    expect(mean[1]).toBe(4);

    const cov = computeCovarianceMatrix(data, mean);
    expect(cov.length).toBe(2);
    expect(cov[0].length).toBe(2);

    const inv = invertMatrix(cov);
    const dist = computeMahalanobisDistance([10, 10], mean, inv);
    expect(dist).toBeGreaterThan(0);
  });
});

describe('Performance Metrics & Confusion Matrix', () => {
  it('computes precision, recall, MAE, and RMSE accurately', () => {
    const items = [
      { actualFail: true, anomalyScore: 0.8, predicted168h: 40, actual168h: 42 },
      { actualFail: true, anomalyScore: 0.2, predicted168h: 15, actual168h: 30 }, // False negative (escape)
      { actualFail: false, anomalyScore: 0.1, predicted168h: 12, actual168h: 11 }, // True negative
      { actualFail: false, anomalyScore: 0.7, predicted168h: 22, actual168h: 20 }, // False positive
    ];

    const metrics = computePerformanceMetrics(items, 0.5);
    expect(metrics.confusionMatrix.tp).toBe(1);
    expect(metrics.confusionMatrix.fn).toBe(1);
    expect(metrics.confusionMatrix.fp).toBe(1);
    expect(metrics.confusionMatrix.tn).toBe(1);
    expect(metrics.recall).toBe(0.5);
    expect(metrics.precision).toBe(0.5);
    expect(metrics.mae).toBeGreaterThan(0);
  });

  it('generates recall curve across threshold spectrum', () => {
    const items = [
      { actualFail: true, anomalyScore: 0.9 },
      { actualFail: true, anomalyScore: 0.6 },
      { actualFail: false, anomalyScore: 0.2 },
    ];
    const curve = generateRecallCurve(items, 10);
    expect(curve.length).toBeGreaterThan(5);
    // At low threshold recall should be 1.0
    expect(curve[0].recall).toBe(1.0);
  });
});

describe('CSV Ingest & Validation Analytics', () => {
  it('validates good CSV data with correct intervals', () => {
    const csv = `part_id,val_0h,val_24h,val_96h,val_168h
U-0001,8.1,8.5,9.2,10.1
U-0002,7.9,8.2,8.9,9.8`;

    const res = parseAndValidateCsv(csv, 'lot-test');
    expect(res.requiredColumnsFound).toBe(true);
    expect(res.totalRowsParsed).toBe(2);
    expect(res.duplicatePartIds).toBe(0);
    expect(res.missingReadingsCount).toBe(0);
    expect(res.issues.length).toBe(0);
  });

  it('detects duplicate part IDs, missing intervals, and non-numeric values', () => {
    const csv = `part_id,val_0h,val_24h,val_96h,val_168h
U-0001,8.1,8.5,,10.1
U-0001,7.9,BAD,8.9,9.8`;

    const res = parseAndValidateCsv(csv, 'lot-test');
    expect(res.requiredColumnsFound).toBe(true);
    expect(res.duplicatePartIds).toBe(1);
    expect(res.missingReadingsCount).toBe(1);
    expect(res.invalidNumericCount).toBe(1);
    expect(res.issues.length).toBeGreaterThan(0);
  });
});
