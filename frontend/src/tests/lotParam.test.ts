import { describe, expect, it } from 'vitest';
import { lotLimit, lotParam } from '../data/types';
import { mapPart, mapPrediction } from '../data/api';

const lot = (testParameter: string | null, used: string[] | undefined, staticLimit: number | null = null) =>
  ({ testParameter, staticLimit, sourceDetail: used ? { parameters_used: used } : null });
const DATASHEET = { leakage_current_ua: 50, iddq_ma: 5, propagation_delay_ns: 10 };

const dto = (values: Record<string, number | null>) => ({
  id: 'c1', serial_number: 'P1', lot_id: 'L', insufficient_data: false, prediction: null, latest_decision: null,
  readings: [0, 24].map(h => ({ interval_hours: h, leakage_current_ua: null, iddq_ma: null, propagation_delay_ns: null,
    ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v == null ? null : v + h / 100])) })),
});

describe('charts follow the lot parameter', () => {
  it('iddq-only lot: parameter, limit and readings are IDDQ', () => {
    const l = lot('iddq_ma', ['iddq_ma'], 5);
    expect(lotParam(l)).toBe('iddq_ma');
    expect(lotLimit(l, 'iddq_ma', DATASHEET)).toBe(5);
    expect(mapPart(dto({ iddq_ma: 1.5 }), lotParam(l)).part.readings[24]).toBeCloseTo(1.74);
  });

  it('delay-only lot whose test parameter defaulted to leakage still charts delay with the delay limit', () => {
    const l = lot('leakage_current_ua', ['propagation_delay_ns'], 50);
    expect(lotParam(l)).toBe('propagation_delay_ns');
    expect(lotLimit(l, 'propagation_delay_ns', DATASHEET)).toBe(10); // the 50 belongs to leakage, not delay
    expect(mapPart(dto({ propagation_delay_ns: 4.2 }), 'propagation_delay_ns').part.readings[0]).toBeCloseTo(4.2);
  });

  it('a forecast for IDDQ alone still yields Module B results (no leakage forecast needed)', () => {
    const pr = mapPrediction('P1', { pred_leakage_168h: null, pred_iddq_168h: 1.6, pred_delay_168h: null, verdict: 'PASS' });
    expect(pr.moduleB?.perParam.iddq_ma?.forecast168h).toBe(1.6);
    expect(pr.moduleB?.perParam.leakage_current_ua?.forecast168h).toBeNull();
  });

  it('three-parameter lots keep leakage', () => {
    expect(lotParam(lot(null, undefined))).toBe('leakage_current_ua');
    expect(lotParam(lot('leakage_current_ua', ['leakage_current_ua', 'iddq_ma', 'propagation_delay_ns']))).toBe('leakage_current_ua');
  });
});
