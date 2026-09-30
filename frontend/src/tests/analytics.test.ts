import { describe, it, expect } from 'vitest';
import { calculateMedian, calculateMAD, calculateRobustZ, computeBatchRobustZ } from '../lib/analytics/robustZ';
import { findSimilarParts } from '../lib/analytics/explainability';
import { generateOfflineReadings, screenOffline, OfflineDemoApi, DEFAULT_OFFLINE_SETTINGS } from '../data/offlineDemo';
import { HttpApi, mapPart, reasonFromVerdict } from '../data/api';

describe('Robust z-score', () => {
  it('median / MAD / z', () => {
    expect(calculateMedian([1, 3, 2])).toBe(2);
    expect(calculateMedian([1, 2, 3, 4])).toBe(2.5);
    expect(calculateMAD([1, 2, 3, 4, 5, 6, 7, 8, 9])).toBe(2);
    expect(calculateRobustZ(10, 10, 0)).toBe(0);
    expect(computeBatchRobustZ([10, 11, 10, 12, 11, 50]).zScores[5]).toBeGreaterThan(3);
  });
});

describe('Offline demo never uses labels or future readings', () => {
  it('parts carry no label field', async () => {
    const api = new OfflineDemoApi({ ...DEFAULT_OFFLINE_SETTINGS, lotSize: 200 });
    const lot = (await api.getLots())[0];
    const { parts } = await api.getParts(lot.id);
    for (const p of parts) {
      const keys = Object.keys(p).join(',').toLowerCase();
      expect(keys).not.toMatch(/truth|label|anomaly|defect/);
    }
  });

  it('statuses depend only on 0h/24h readings', () => {
    const raw = generateOfflineReadings({ ...DEFAULT_OFFLINE_SETTINGS, lotSize: 300 });
    const a = screenOffline(raw, 50).map(s => s.status);
    const tampered = raw.map(p => ({
      ...p,
      readings: p.readings.map(r => (r.intervalHours >= 96 ? { ...r, values: { ...r.values, leakage_current_ua: r.values.leakage_current_ua + 1000 } } : r)),
    }));
    expect(screenOffline(tampered, 50).map(s => s.status)).toEqual(a);
  });

  it('offline mode offers no metrics, intervals or contributions', async () => {
    const api = new OfflineDemoApi({ ...DEFAULT_OFFLINE_SETTINGS, lotSize: 50 });
    expect(await api.getMetrics()).toBeNull();
    expect(await api.getExplanation('x')).toBeNull();
    const { predictions } = await api.getParts('any');
    for (const p of Object.values(predictions)) {
      expect(p.moduleB?.perParam.leakage_current_ua?.intervalLower).toBeNull();
    }
  });

  it('applies every generator setting (defect rate and static limit change the lot)', async () => {
    const a = new OfflineDemoApi({ seed: 1, lotSize: 400, defectRate: 0.0, staticLimitUa: 50 });
    const b = new OfflineDemoApi({ seed: 1, lotSize: 400, defectRate: 0.25, staticLimitUa: 50 });
    const c = new OfflineDemoApi({ seed: 1, lotSize: 400, defectRate: 0.25, staticLimitUa: 12 });
    const flagged = async (api: OfflineDemoApi) => (await api.getParts('x')).parts.filter(p => p.isFlagged).length;
    expect(await flagged(b)).toBeGreaterThan(await flagged(a));
    expect(await flagged(c)).toBeGreaterThan(await flagged(b));
    expect((await c.getConfig()).datasheetLimits.leakage_current_ua).toBe(12);
  });
});

const dto = (serial: string, verdict: string, decision: unknown = null, contribA = 1.5) => ({
  id: `id-${serial}`, lot_id: 'lot-1', serial_number: serial, insufficient_data: false,
  readings: [0, 24, 96, 168].map(t => ({ interval_hours: t, leakage_current_ua: 10 + t / 100, iddq_ma: 1.5, propagation_delay_ns: 4.2, imputed_fields: null })),
  latest_decision: decision,
  prediction: {
    id: 'p', module_a_score: contribA, module_a_mahalanobis: 1.1, module_a_flag: contribA > 2, pred_leakage_168h: 12.3,
    pred_iddq_168h: 1.5, pred_delay_168h: 4.2, drift_slope_ua_per_hr: 0.01, module_b_flag: false, module_b_score: 0.4,
    threshold_a: 2.0, threshold_b: 3.1, safety_slope_ua_per_hr: 0.02, cv_fold: 3, verdict, verdict_reason: 'RULE_MODULE_A: x',
    created_at: '2026-09-30T00:00:00Z',
    details: { prediction_interval: { coverage_target: 0.9, per_parameter: { leakage_current_ua: { lower: 11 + contribA, upper: 14 + 2 * contribA } } },
      safety_slope: { driver_parameter: 'leakage_current_ua', per_parameter: { leakage_current_ua: { predicted_rate: 0.01, safety_slope: 0.02, lot_median_rate: 0.0, lot_spread: 0.005, exceeds_safety_slope: false, unit: 'uA/h' } } },
      module_a: { per_parameter: { leakage_current_ua: { robust_z: contribA } }, diagnostics: { isolation_forest: 0.2 } } },
  },
});

describe('HttpApi mapping (backend is the source of truth)', () => {
  it('status comes from the model verdict, or from the latest inspector decision', () => {
    expect(mapPart(dto('A', 'REJECT')).part.status).toBe('Reject');
    expect(mapPart(dto('B', 'PASS')).part.status).toBe('Accept');
    const decided = mapPart(dto('C', 'REJECT', { disposition: 'ACCEPTED', original_verdict: 'REJECT', inspector_id: 'QA-7', inspector_notes: 'retested ok', reviewed_at: '2026-09-30T01:00:00Z' }));
    expect(decided.part.status).toBe('Accept');
    expect(decided.part.statusSource).toBe('inspector');
    expect(reasonFromVerdict('RULE_MODULE_A: long text')).toBe('Lot outlier (Module A)');
  });

  it('changing the backend output changes what the UI model contains', () => {
    const a = mapPart(dto('A', 'PASS', null, 1.0)).prediction!;
    const b = mapPart(dto('A', 'REVIEW', null, 3.0)).prediction!;
    expect(a.moduleA!.score).not.toBe(b.moduleA!.score);
    const ia = a.moduleB!.perParam.leakage_current_ua!;
    const ib = b.moduleB!.perParam.leakage_current_ua!;
    expect([ia.intervalLower, ia.intervalUpper]).not.toEqual([ib.intervalLower, ib.intervalUpper]);
    expect(a.cvFold).toBe(3);
  });

  it('calls the backend endpoints and maps a lot of parts', async () => {
    const calls: string[] = [];
    const fake = (async (url: string) => {
      calls.push(url);
      return { ok: true, status: 200, json: async () => [dto('A', 'REJECT'), dto('B', 'PASS')] } as Response;
    }) as unknown as typeof fetch;
    const api = new HttpApi('http://backend/api/v1', fake);
    const { parts, predictions } = await api.getParts('lot-1');
    expect(calls).toEqual(['http://backend/api/v1/lots/lot-1/parts']);
    expect(parts.map(p => p.status)).toEqual(['Reject', 'Accept']);
    expect(Object.keys(predictions)).toEqual(['A', 'B']);
  });

  it('decisions are POSTed with the inspector comment', async () => {
    let body: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any
    const fake = (async (_url: string, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return { ok: true, status: 201, json: async () => ({}) } as Response;
    }) as unknown as typeof fetch;
    await new HttpApi('http://b', fake).submitDecision({ partId: 'c1', lotId: 'l', newStatus: 'Reject', comment: 'oxide leakage trend', inspector: 'QA-1' });
    expect(body).toEqual({ inspector_id: 'QA-1', disposition: 'QUARANTINED', inspector_notes: 'oxide leakage trend' });
  });
});

describe('Similar parts use only 0h/24h', () => {
  it('ignores 96h/168h', () => {
    const mk = (id: string, v0: number, v24: number, v168: number) => ({
      id, partId: id, lotId: 'l', readings: { 0: v0, 24: v24, 96: null, 168: v168 }, allReadings: [], insufficientData: false,
      status: 'Accept' as const, statusSource: 'model' as const, reason: '', isFlagged: false,
    });
    const t = mk('T', 10, 11, 999);
    const res = findSimilarParts(t, [t, mk('near', 10.1, 11.1, 0), mk('far', 20, 25, 999)], 2);
    expect(res[0].partId).toBe('near');
  });
});
