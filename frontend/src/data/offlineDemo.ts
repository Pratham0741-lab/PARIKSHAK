/**
 * OFFLINE DEMO mode (explicitly labelled in the UI).
 *
 * Generates a seeded synthetic lot so the UI can be explored without the backend. It is NOT the
 * ML system:
 *  - the defect type used to shape each synthetic trajectory is discarded immediately and never
 *    reaches a Part, a status or a metric;
 *  - statuses come from simple, documented client-side rules on the 0h/24h readings only
 *    (robust z vs the lot; linear-extrapolation drift vs a lot-relative slope);
 *  - there are no prediction intervals, no feature contributions and no performance metrics
 *    (those require labelled held-out evaluation in the backend).
 */

import { computeBatchRobustZ } from '../lib/analytics/robustZ';
import {
  ApiMode, AuditEvent, BenchmarkMetrics, CostCurve, Decision, Explanation, IngestResult, IngestSummary, Lot,
  Part, PartStatus, Prediction, Reading, SystemConfig,
} from './types';

export interface OfflineDemoSettings {
  seed: number;
  lotSize: number;
  defectRate: number; // fraction of parts generated with a defect trajectory (hidden from the UI)
  staticLimitUa: number;
}

export const DEFAULT_OFFLINE_SETTINGS: OfflineDemoSettings = { seed: 42, lotSize: 400, defectRate: 0.07, staticLimitUa: 50 };

/** Documented demo rule constants (the backend learns its thresholds; the offline demo cannot). */
export const OFFLINE_RULES = { outlierZ: 3.5, slopeK: 3.0 } as const;

export function createRng(seed: number) {
  let s = Math.floor(seed) >>> 0;
  return function next(): number {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(rng: () => number, mean = 0, sd = 1): number {
  const u1 = Math.max(1e-9, rng());
  const u2 = rng();
  return mean + sd * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

/** Synthetic readings only. The internal trajectory type is local to this function. */
export function generateOfflineReadings(cfg: OfflineDemoSettings): { partId: string; readings: Reading[] }[] {
  const rng = createRng(cfg.seed);
  const out: { partId: string; readings: Reading[] }[] = [];
  for (let i = 0; i < cfg.lotSize; i++) {
    const roll = rng();
    const kind = roll < cfg.defectRate ? Math.floor(rng() * 3) : -1; // -1 nominal, 0 steep, 1 late, 2 level
    let v0 = Math.max(0.5, Math.exp(normal(rng, Math.log(10), 0.12)));
    let slope = Math.max(0, normal(rng, 0.004, 0.003));
    let late = 0;
    if (kind === 2) v0 *= 2.5 + rng();
    if (kind === 0) slope = 0.12 + rng() * 0.1;
    if (kind === 1) late = 15 + rng() * 15;
    const iddq0 = normal(rng, 1.5, 0.06);
    const delay0 = normal(rng, 4.2, 0.12);
    const readings: Reading[] = [0, 24, 96, 168].map(t => {
      const leak = v0 + slope * t + (t === 168 ? late : 0) + normal(rng, 0, 0.25);
      return {
        intervalHours: t,
        values: {
          leakage_current_ua: Math.max(0.1, Number(leak.toFixed(3))),
          iddq_ma: Number((iddq0 * (1 + 0.02 * (t / 168)) + normal(rng, 0, 0.02)).toFixed(4)),
          propagation_delay_ns: Number((delay0 + normal(rng, 0, 0.03)).toFixed(4)),
        },
        imputed: [],
      };
    });
    out.push({ partId: `DEMO-${String(i + 1).padStart(4, '0')}`, readings });
  }
  return out;
}

/** Client analytics on 0h/24h leakage only (no labels, no 96h/168h). */
export function screenOffline(parts: { partId: string; readings: Reading[] }[], staticLimitUa: number) {
  const v = (p: { readings: Reading[] }, t: number) => p.readings.find(r => r.intervalHours === t)!.values.leakage_current_ua;
  const level = parts.map(p => (v(p, 0) + v(p, 24)) / 2);
  const forecast = parts.map(p => v(p, 0) + 7 * (v(p, 24) - v(p, 0)));
  const rate = parts.map((p, i) => (forecast[i] - v(p, 0)) / 168);
  const lz = computeBatchRobustZ(level);
  const rz = computeBatchRobustZ(rate);
  return parts.map((p, i) => {
    const aScore = Math.max(0, lz.zScores[i]);
    const aFlag = aScore >= OFFLINE_RULES.outlierZ;
    const safety = rz.median + OFFLINE_RULES.slopeK * rz.scaledMad;
    const bFlag = rate[i] >= safety;
    const breach = forecast[i] >= staticLimitUa;
    const status: PartStatus = breach || (aFlag && bFlag) ? 'Reject' : aFlag || bFlag ? 'Review' : 'Accept';
    const reason = breach ? 'Linear forecast reaches static limit' : aFlag && bFlag ? 'Lot outlier and drift above slope'
      : aFlag ? 'Lot outlier (demo rule)' : bFlag ? 'Drift above lot slope (demo rule)' : 'Within demo rules';
    const prediction: Prediction = {
      partId: p.partId,
      source: 'offline-demo',
      verdict: status === 'Accept' ? 'PASS' : status === 'Review' ? 'REVIEW' : 'REJECT',
      verdictReason: `OFFLINE DEMO RULE: ${reason}`,
      moduleA: { score: aScore, threshold: OFFLINE_RULES.outlierZ, flag: aFlag, robustZ: { leakage_current_ua: lz.zScores[i] }, mahalanobis: null, isolation: null },
      moduleB: {
        score: (rate[i] - rz.median) / rz.scaledMad,
        thresholdK: OFFLINE_RULES.slopeK,
        flag: bFlag,
        driver: 'leakage_current_ua',
        perParam: {
          leakage_current_ua: {
            forecast168h: forecast[i], intervalLower: null, intervalUpper: null, predictedRate: rate[i],
            lotMedianRate: rz.median, lotSpread: rz.scaledMad, safetySlope: safety, exceedsSafetySlope: bFlag, rateUnit: 'uA/h',
          },
        },
      },
      cvFold: null,
      intervalCoverageTarget: null,
    };
    return { status, reason, prediction };
  });
}

const NEEDS_BACKEND = 'Not available in offline demo mode: this requires the backend (labelled held-out evaluation / ML models).';

export class OfflineDemoApi {
  readonly mode: ApiMode = 'offline';
  readonly description = 'OFFLINE DEMO: synthetic data, simple client rules, not the ML model';
  private lot!: Lot;
  private parts: Part[] = [];
  private predictions: Record<string, Prediction> = {};
  private audit: AuditEvent[] = [];

  constructor(private settings: OfflineDemoSettings = DEFAULT_OFFLINE_SETTINGS) {
    this.regenerate(settings);
  }

  regenerate(settings: OfflineDemoSettings): void {
    this.settings = settings;
    const raw = generateOfflineReadings(settings);
    const screened = screenOffline(raw, settings.staticLimitUa);
    const lotId = `offline-${settings.seed}`;
    this.parts = raw.map((r, i) => {
      const readings: Record<number, number | null> = {};
      for (const x of r.readings) readings[x.intervalHours] = x.values.leakage_current_ua;
      return {
        id: `${lotId}-${r.partId}`, partId: r.partId, lotId, readings, allReadings: r.readings, insufficientData: false,
        status: screened[i].status, statusSource: 'offline-demo', reason: screened[i].reason,
        isFlagged: screened[i].status !== 'Accept',
      };
    });
    this.predictions = Object.fromEntries(screened.map((s, i) => [raw[i].partId, s.prediction]));
    const count = (s: PartStatus) => this.parts.filter(p => p.status === s).length;
    this.lot = {
      id: lotId, lotNumber: `DEMO-SEED-${settings.seed}`, waferId: null, status: 'OFFLINE_DEMO', source: 'OFFLINE_DEMO',
      createdAt: new Date().toISOString(), totalParts: this.parts.length,
      passCount: count('Accept'), reviewCount: count('Review'), rejectCount: count('Reject'),
      temperatureC: null, testParameter: 'leakage_current_ua', unit: 'uA', staticLimit: settings.staticLimitUa,
      conditionsAssumed: ['temperature_c'], moduleAFlagCount: null, moduleBFlagCount: null, supplier: null, sourceDetail: { kind: 'OFFLINE_DEMO', generator: 'offline-demo', seed: settings.seed },
    };
    this.audit = [{
      id: `offline-${Date.now()}`, timestamp: new Date().toISOString(), actor: 'offline-demo', category: 'SYSTEM',
      action: 'Offline demo lot generated',
      details: `${this.parts.length} synthetic parts (seed ${settings.seed}); ${this.lot.reviewCount} review, ${this.lot.rejectCount} reject by demo rules`,
      lotId,
    }];
  }

  async getConfig(): Promise<SystemConfig> {
    return {
      datasheetLimits: { leakage_current_ua: this.settings.staticLimitUa, iddq_ma: 5, propagation_delay_ns: 8 },
      fnCost: NaN, fpCost: NaN, thresholdStrategy: 'offline demo rules', intervalCoverageTarget: null, latestRun: null,
    };
  }
  async getLots(): Promise<Lot[]> { return [this.lot]; }
  async getParts(_lotId: string) { return { parts: this.parts.map(p => ({ ...p })), predictions: { ...this.predictions } }; }
  async getExplanation(_partId: string): Promise<Explanation | null> { return null; }
  async submitDecision(d: Decision): Promise<void> {
    const p = this.parts.find(x => x.id === d.partId);
    if (!p) return;
    p.status = d.newStatus;
    p.statusSource = 'inspector';
    p.reason = `Inspector: ${d.comment}`;
    p.isFlagged = d.newStatus !== 'Accept';
    p.inspector = d.inspector;
    p.updatedAt = new Date().toISOString();
    this.audit.unshift({
      id: `offline-dec-${Date.now()}`, timestamp: p.updatedAt, actor: d.inspector, category: 'DECISION',
      action: 'Decision recorded (offline, not persisted)', details: `${p.partId} -> ${d.newStatus}: ${d.comment}`,
      partId: p.id, lotId: p.lotId,
    });
  }
  async getAuditLog(_lotId?: string): Promise<AuditEvent[]> { return [...this.audit]; }
  async getMetrics(): Promise<BenchmarkMetrics | null> { return null; }
  async getCostCurve(_m: 'A' | 'B'): Promise<CostCurve | null> { return null; }
  async validateCsv(_csv: string): Promise<IngestSummary> { throw new Error(NEEDS_BACKEND); }
  async ingestCsv(_csv: string): Promise<IngestResult> { throw new Error(NEEDS_BACKEND); }
}
