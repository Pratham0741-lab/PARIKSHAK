/**
 * Data access for PARIKSHAK.
 *
 * - HttpApi (default): calls the FastAPI backend (VITE_API_URL, default http://localhost:8000/api/v1).
 *   Every status, score, interval, contribution and metric shown in the UI comes from there.
 * - OfflineDemoApi (explicit "offline demo" mode, see ./offlineDemo.ts): synthetic data with
 *   client-side analytics on 0h/24h readings only. It never uses labels and offers no metrics.
 *
 * Mode: VITE_API_MODE=http|offline at build time, overridable at runtime from the Dev panel
 * (persisted in localStorage).
 */

import {
  ApiMode, AuditEvent, BenchmarkMetrics, CostCurve, Decision, Explanation, IngestOptions, IngestResult, IngestSummary, Lot,
  PARAMS, Param, Part, PartStatus, Prediction, Reading, SystemConfig, Verdict,
} from './types';
import { OfflineDemoApi } from './offlineDemo';

export interface ParikshakApi {
  readonly mode: ApiMode;
  readonly description: string;
  getConfig(): Promise<SystemConfig>;
  getLots(): Promise<Lot[]>;
  getParts(lotId: string, param?: Param): Promise<{ parts: Part[]; predictions: Record<string, Prediction> }>;
  getExplanation(partId: string): Promise<Explanation | null>;
  submitDecision(decision: Decision): Promise<void>;
  getAuditLog(lotId?: string): Promise<AuditEvent[]>;
  getMetrics(costs?: Costs): Promise<BenchmarkMetrics | null>;
  getCostCurve(module: 'A' | 'B', costs?: Costs): Promise<CostCurve | null>;
  validateCsv(csv: string): Promise<IngestSummary>;
  ingestCsv(csv: string, lotNumber?: string, actor?: string, opts?: IngestOptions): Promise<IngestResult>;
}

const STREAM_THRESHOLD = 2_000_000; // characters; above this the CSV is sent to /ingest/stream
/** Optional FN/FP cost weights passed to the metrics endpoints (defaults come from the backend settings). */
export interface Costs { fnCost?: number; fpCost?: number }
const costQuery = (c?: Costs) => (c?.fnCost != null ? `&fn_cost=${c.fnCost}` : '') + (c?.fpCost != null ? `&fp_cost=${c.fpCost}` : '');

export const DEFAULT_API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000/api/v1';
const BUILD_MODE: ApiMode = (import.meta.env.VITE_API_MODE as string | undefined) === 'offline' ? 'offline' : 'http';
const MODE_KEY = 'parikshak.apiMode';

export function initialMode(): ApiMode {
  try {
    const stored = globalThis.localStorage?.getItem(MODE_KEY);
    if (stored === 'http' || stored === 'offline') return stored;
  } catch {
    /* no storage (tests) */
  }
  return BUILD_MODE;
}

export function persistMode(mode: ApiMode): void {
  try {
    globalThis.localStorage?.setItem(MODE_KEY, mode);
  } catch {
    /* ignore */
  }
}

// ------------------------------------------------------------------ mapping helpers (exported for tests)
const DISPOSITION_TO_STATUS: Record<string, PartStatus> = { ACCEPTED: 'Accept', QUARANTINED: 'Reject', RE_TEST: 'Review' };
const STATUS_TO_DISPOSITION: Record<PartStatus, string> = { Accept: 'ACCEPTED', Reject: 'QUARANTINED', Review: 'RE_TEST' };
const VERDICT_TO_STATUS: Record<Verdict, PartStatus> = { PASS: 'Accept', REVIEW: 'Review', REJECT: 'Reject' };

const REASON_TEXT: Record<string, string> = {
  RULE_STATIC_LIMIT: 'Observed reading exceeds datasheet limit',
  RULE_PRED_LIMIT: '168h forecast reaches datasheet limit',
  RULE_BOTH_MODULES: 'Lot outlier and drift above safety slope',
  RULE_MODULE_A: 'Lot outlier (Module A)',
  RULE_MODULE_B: 'Drift above lot safety slope (Module B)',
  RULE_NOMINAL: 'Within lot envelope and safety slope',
  INSUFFICIENT_DATA: 'Insufficient data (missing 0h/24h reading)',
};

export function reasonFromVerdict(reason: string | null | undefined): string {
  if (!reason) return 'No prediction';
  const code = reason.split(':')[0].trim();
  return REASON_TEXT[code] ?? code;
}

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null);

export function mapPart(dto: Json, param: Param = 'leakage_current_ua'): { part: Part; prediction: Prediction | null } {
  const allReadings: Reading[] = (dto.readings as Json[])
    .map(r => ({
      intervalHours: r.interval_hours,
      values: { leakage_current_ua: r.leakage_current_ua, iddq_ma: r.iddq_ma, propagation_delay_ns: r.propagation_delay_ns },
      imputed: (r.imputed_fields ?? []) as Param[],
    }))
    .sort((a, b) => a.intervalHours - b.intervalHours);
  const readings: Record<number, number | null> = { 0: null, 24: null, 96: null, 168: null };
  for (const r of allReadings) readings[r.intervalHours] = r.values[param] ?? null;

  const p = dto.prediction as Json | null;
  const d = dto.latest_decision as Json | null;
  let status: PartStatus = 'Review';
  let statusSource: Part['statusSource'] = 'model';
  let reason = 'No prediction';
  let inspector: string | undefined;
  let updatedAt: string | undefined;
  if (d) {
    status = DISPOSITION_TO_STATUS[d.disposition] ?? 'Review';
    statusSource = 'inspector';
    reason = `Inspector: ${d.inspector_notes}`;
    inspector = d.inspector_id;
    updatedAt = d.reviewed_at;
  } else if (p) {
    status = VERDICT_TO_STATUS[p.verdict as Verdict] ?? 'Review';
    reason = reasonFromVerdict(p.verdict_reason);
    updatedAt = p.created_at;
  }

  const part: Part = {
    id: dto.id,
    partId: dto.serial_number,
    lotId: dto.lot_id,
    readings,
    allReadings,
    insufficientData: !!dto.insufficient_data,
    status,
    statusSource,
    reason,
    isFlagged: status !== 'Accept',
    inspector,
    updatedAt,
  };
  return { part, prediction: p ? mapPrediction(dto.serial_number, p) : null };
}

export function mapPrediction(partId: string, p: Json): Prediction {
  const details = (p.details ?? {}) as Json;
  const ma = details.module_a as Json | undefined;
  const ss = details.safety_slope as Json | undefined;
  const pi = (details.prediction_interval as Json | undefined)?.per_parameter ?? {};
  const forecast: Record<Param, number | null> = {
    leakage_current_ua: num(p.pred_leakage_168h),
    iddq_ma: num(p.pred_iddq_168h),
    propagation_delay_ns: num(p.pred_delay_168h),
  };
  const perParam: Partial<Record<Param, any>> = {}; // eslint-disable-line @typescript-eslint/no-explicit-any
  for (const k of PARAMS) {
    const s = ss?.per_parameter?.[k] ?? {};
    perParam[k] = {
      forecast168h: forecast[k],
      intervalLower: num(pi[k]?.lower),
      intervalUpper: num(pi[k]?.upper),
      predictedRate: num(s.predicted_rate),
      lotMedianRate: num(s.lot_median_rate),
      lotSpread: num(s.lot_spread),
      safetySlope: num(s.safety_slope),
      exceedsSafetySlope: !!s.exceeds_safety_slope,
      rateUnit: s.unit ?? '',
    };
  }
  const robustZ: Partial<Record<Param, number>> = {};
  for (const k of PARAMS) {
    const z = num(ma?.per_parameter?.[k]?.robust_z);
    if (z !== null) robustZ[k] = z;
  }
  return {
    partId,
    source: 'backend',
    verdict: (p.verdict as Verdict) ?? null,
    verdictReason: p.verdict_reason ?? '',
    moduleA: p.module_a_score === null || p.module_a_score === undefined ? null : {
      score: p.module_a_score,
      threshold: num(p.threshold_a),
      flag: !!p.module_a_flag,
      robustZ,
      mahalanobis: num(p.module_a_mahalanobis),
      isolation: num(ma?.diagnostics?.isolation_forest),
    },
    moduleB: PARAMS.every(k => forecast[k] === null) ? null : {
      score: num(p.module_b_score),
      thresholdK: num(p.threshold_b),
      flag: !!p.module_b_flag,
      driver: (ss?.driver_parameter as Param) ?? null,
      perParam,
    },
    cvFold: num(p.cv_fold),
    intervalCoverageTarget: num((details.prediction_interval as Json | undefined)?.coverage_target),
  };
}

export function mapExplanation(e: Json): Explanation {
  return {
    summary: e.summary,
    verdict: e.verdict,
    moduleA: {
      score: num(e.module_a.score),
      threshold: num(e.module_a.threshold),
      flag: !!e.module_a.flag,
      contributions: (e.module_a.contributions as Json[]).map(c => ({
        parameter: c.parameter, robustZ: num(c.robust_z), contribution: num(c.contribution),
        value: num(c.value_0_24h_mean), lotMedian: num(c.lot_median),
      })),
      topContributor: e.module_a.top_contributor ?? null,
    },
    moduleB: {
      score: num(e.module_b.score),
      thresholdK: num(e.module_b.threshold_k),
      flag: !!e.module_b.flag,
      driver: e.module_b.driver_parameter,
      contributions: (e.module_b.contributions as Json[]).map(c => ({
        feature: c.feature, label: c.label, value: c.value, targetSpace: c.target_space,
        effectPctOnForecast: num(c.effect_pct_on_forecast),
      })),
      topContributor: e.module_b.top_contributor ?? null,
      targetSpace: e.module_b.contribution_target_space ?? null,
    },
    staticLimit: {
      limits: e.static_limit.limits,
      maxObserved: e.static_limit.max_observed_0_24h,
      observedBreach: e.static_limit.observed_breach,
      forecastBreach: e.static_limit.forecast_breach,
    },
    cvFold: num(e.cv_fold),
  };
}

export function mapIngestSummary(v: Json): IngestSummary {
  return {
    ok: !!v.ok,
    rowsTotal: v.rows_total ?? 0,
    partsAccepted: v.parts_accepted ?? 0,
    rowsRejected: v.rows_rejected ?? 0,
    duplicatePartIds: v.duplicate_part_ids ?? 0,
    nonNumericCells: v.non_numeric_cells ?? 0,
    missingCells: v.missing_cells ?? 0,
    imputedCells: v.imputed_cells ?? 0,
    insufficientDataParts: v.insufficient_data_parts ?? 0,
    missingColumns: v.missing_columns ?? [],
    issues: (v.issues ?? []).map((i: Json) => ({ row: i.row, message: i.message, severity: i.severity, partId: i.part_id, column: i.column })),
    layout: v.layout ?? null,
    columnMap: v.column_map ?? [],
    units: v.units ?? {},
    needsUnitConfirmation: !!v.needs_unit_confirmation,
    nLotsInFile: v.n_lots_in_file ?? 0,
  };
}

// ------------------------------------------------------------------ HTTP implementation
export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

export class HttpApi implements ParikshakApi {
  readonly mode: ApiMode = 'http';
  readonly description: string;

  constructor(private baseUrl: string = DEFAULT_API_URL, private fetchImpl: typeof fetch = (...a) => fetch(...a)) {
    this.description = `Backend ${baseUrl}`;
  }

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail: unknown = undefined;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* no body */
      }
      throw new ApiError(res.status, `${init?.method ?? 'GET'} ${path} failed with HTTP ${res.status}`, detail);
    }
    return (await res.json()) as T;
  }

  async getConfig(): Promise<SystemConfig> {
    const c = await this.req<Json>('/config');
    return {
      datasheetLimits: c.datasheet_limits,
      fnCost: c.cost.fn_cost,
      fpCost: c.cost.fp_cost,
      thresholdStrategy: c.threshold_strategy,
      intervalCoverageTarget: num(c.interval_coverage_target),
      latestRun: c.latest_run ? { id: c.latest_run.id, createdAt: c.latest_run.created_at, protocol: c.latest_run.protocol } : null,
    };
  }

  async getLots(): Promise<Lot[]> {
    const lots = await this.req<Json[]>('/lots');
    return lots.map(l => ({
      id: l.id, lotNumber: l.lot_number, waferId: l.wafer_id ?? null, status: l.status, source: l.source,
      createdAt: l.created_at, totalParts: l.total_components, passCount: l.pass_count,
      reviewCount: l.review_count, rejectCount: l.reject_count,
      temperatureC: num(l.temperature_c), testParameter: l.test_parameter ?? null, unit: l.unit ?? null,
      staticLimit: num(l.static_limit), conditionsAssumed: l.conditions_assumed ?? [], sourceDetail: l.source_detail ?? null,
      moduleAFlagCount: num(l.module_a_flag_count), moduleBFlagCount: num(l.module_b_flag_count), supplier: l.supplier ?? null,
    }));
  }

  async getParts(lotId: string, param: Param = 'leakage_current_ua') {
    const dtos = await this.req<Json[]>(`/lots/${lotId}/parts`);
    const parts: Part[] = [];
    const predictions: Record<string, Prediction> = {};
    for (const dto of dtos) {
      const { part, prediction } = mapPart(dto, param);
      parts.push(part);
      if (prediction) predictions[part.partId] = prediction;
    }
    return { parts, predictions };
  }

  async getExplanation(partId: string): Promise<Explanation | null> {
    try {
      return mapExplanation(await this.req<Json>(`/components/${partId}/explain`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) return null; // no prediction (e.g. insufficient data)
      throw e;
    }
  }

  async submitDecision(d: Decision): Promise<void> {
    await this.req(`/reviews/${d.partId}/action`, {
      method: 'POST',
      body: JSON.stringify({ inspector_id: d.inspector, disposition: STATUS_TO_DISPOSITION[d.newStatus], inspector_notes: d.comment }),
    });
  }

  async getAuditLog(lotId?: string): Promise<AuditEvent[]> {
    const rows = await this.req<Json[]>(`/audit${lotId ? `?lot_id=${lotId}` : ''}`);
    return rows.map(r => ({
      id: r.id, timestamp: r.created_at, actor: r.actor, action: r.action, details: r.details,
      lotId: r.lot_id ?? undefined, partId: r.component_id ?? undefined, category: r.category,
    }));
  }

  async getMetrics(costs?: Costs): Promise<BenchmarkMetrics | null> {
    const m = await this.req<Json>(`/metrics/benchmark?x=1${costQuery(costs)}`);
    return {
      totalComponents: m.total_components, excludedWithoutGroundTruth: m.excluded_without_ground_truth,
      tp: m.true_positives, fp: m.false_positives, fn: m.false_negatives, tn: m.true_negatives,
      recall: m.recall, precision: m.precision, f1: m.f1_score, f2: m.f2_score,
      fnCost: m.fn_cost, fpCost: m.fp_cost, weightedCost: m.weighted_cost, costPer1000: m.cost_per_1000_parts,
      maeLeakage: m.module_b_mae_leakage, linearMaeLeakage: m.linear_baseline_mae_leakage,
      maeReductionPct: m.mae_reduction_pct, protocol: m.evaluation_protocol,
      outOfFold: m.out_of_fold_predictions, inSample: m.in_sample_predictions, thresholds: m.final_thresholds ?? null,
    };
  }

  async getCostCurve(module: 'A' | 'B', costs?: Costs): Promise<CostCurve | null> {
    const c = await this.req<Json>(`/metrics/cost-curve?module=${module}&points=40${costQuery(costs)}`);
    return {
      module,
      chosenThreshold: num(c.chosen_threshold),
      points: (c.points as Json[]).map(p => ({
        threshold: p.threshold, weightedCost: p.weighted_cost, fn: p.fn, fp: p.fp, recall: p.recall, precision: p.precision, f2: p.f2,
      })),
    };
  }

  async validateCsv(csv: string): Promise<IngestSummary> {
    if (csv.length > STREAM_THRESHOLD) {
      const r = await this.req<Json>(`/ingest/stream?validate_only=true`, { method: 'POST', body: csv, headers: { 'Content-Type': 'text/csv' } });
      return mapIngestSummary(r.validation);
    }
    return mapIngestSummary(await this.req<Json>('/ingest/validate', { method: 'POST', body: JSON.stringify({ csv }) }));
  }

  async ingestCsv(csv: string, lotNumber?: string, actor?: string, opts: IngestOptions = {}): Promise<IngestResult> {
    try {
      // Large files go to the streamed endpoint as a raw text/csv body (parsed row by row server-side).
      const big = csv.length > STREAM_THRESHOLD;
      const q = new URLSearchParams({ actor: actor ?? 'QA Inspector', units_confirmed: String(!!opts.unitsConfirmed) });
      if (lotNumber) q.set('lot_number', lotNumber);
      if (opts.filename) q.set('filename', opts.filename);
      const r = big
        ? await this.req<Json>(`/ingest/stream?${q}`, { method: 'POST', body: csv, headers: { 'Content-Type': 'text/csv' } })
        : await this.req<Json>('/ingest', {
          method: 'POST',
          body: JSON.stringify({ csv, lot_number: lotNumber || undefined, actor: actor ?? 'QA Inspector',
            filename: opts.filename, units_confirmed: !!opts.unitsConfirmed }),
        });
      return {
        lotId: r.lot_id, lotNumber: r.lot_number, validation: mapIngestSummary(r.validation),
        screening: r.screening ? { nScreened: r.screening.n_screened, nInsufficientData: r.screening.n_insufficient_data, verdicts: r.screening.verdicts, warning: r.screening.warning ?? null } : null,
      };
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.detail && typeof e.detail === 'object') {
        return { lotId: null, lotNumber: null, validation: mapIngestSummary(e.detail as Json), screening: null };
      }
      throw e;
    }
  }
}

export function createApi(mode: ApiMode): ParikshakApi {
  return mode === 'offline' ? new OfflineDemoApi() : new HttpApi();
}
