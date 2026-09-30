/**
 * Core data types for PARIKSHAK.
 *
 * There is deliberately NO ground-truth / defect-label field anywhere in the frontend model.
 * A part's status comes only from the backend model verdict or an inspector decision
 * (or, in the explicitly labelled offline demo, from client analytics on 0h/24h readings).
 */

export type PartStatus = 'Accept' | 'Review' | 'Reject';
export type Verdict = 'PASS' | 'REVIEW' | 'REJECT';
export type ApiMode = 'http' | 'offline';

export const PARAMS = ['leakage_current_ua', 'iddq_ma', 'propagation_delay_ns'] as const;
export type Param = (typeof PARAMS)[number];
export const PARAM_LABEL: Record<Param, string> = {
  leakage_current_ua: 'Leakage',
  iddq_ma: 'IDDQ',
  propagation_delay_ns: 'Prop. delay',
};
export const PARAM_UNIT: Record<Param, string> = {
  leakage_current_ua: 'µA',
  iddq_ma: 'mA',
  propagation_delay_ns: 'ns',
};
export const INTERVALS = [0, 24, 96, 168] as const;

export interface SystemConfig {
  datasheetLimits: Record<Param, number>;
  fnCost: number;
  fpCost: number;
  thresholdStrategy: string;
  intervalCoverageTarget: number | null;
  latestRun: { id: string; createdAt: string; protocol: string } | null;
}

export interface Lot {
  id: string;
  lotNumber: string;
  waferId: string | null;
  status: string;
  source: 'SYNTHETIC' | 'CSV_INGEST' | 'OFFLINE_DEMO' | string;
  createdAt: string;
  totalParts: number;
  passCount: number;
  reviewCount: number;
  rejectCount: number;
  /** Burn-in test conditions (data). Fields listed in conditionsAssumed were defaulted, not supplied. */
  temperatureC: number | null;
  testParameter: string | null;
  unit: string | null;
  staticLimit: number | null;
  conditionsAssumed: string[];
  sourceDetail: Record<string, unknown> | null;
}

export interface Reading {
  intervalHours: number;
  values: Record<Param, number>;
  imputed: Param[];
}

export interface Part {
  id: string; // component UUID (backend) or synthetic id (offline)
  partId: string; // serial number shown to the inspector
  lotId: string;
  /** Leakage current (µA) per interval; null when that interval has no reading. */
  readings: Record<number, number | null>;
  allReadings: Reading[];
  insufficientData: boolean;
  status: PartStatus;
  statusSource: 'model' | 'inspector' | 'offline-demo';
  reason: string;
  isFlagged: boolean;
  inspector?: string;
  updatedAt?: string;
}

export interface ModuleAResult {
  score: number;
  threshold: number | null; // null = module disabled
  flag: boolean;
  robustZ: Partial<Record<Param, number>>;
  mahalanobis: number | null;
  isolation: number | null;
}

export interface ParamDrift {
  forecast168h: number | null;
  intervalLower: number | null;
  intervalUpper: number | null;
  predictedRate: number | null;
  lotMedianRate: number | null;
  lotSpread: number | null;
  safetySlope: number | null;
  exceedsSafetySlope: boolean;
  rateUnit: string;
}

export interface ModuleBResult {
  score: number | null;
  thresholdK: number | null;
  flag: boolean;
  driver: Param | null;
  perParam: Partial<Record<Param, ParamDrift>>;
}

export interface Prediction {
  partId: string;
  source: 'backend' | 'offline-demo';
  verdict: Verdict | null;
  verdictReason: string;
  moduleA: ModuleAResult | null;
  moduleB: ModuleBResult | null;
  cvFold: number | null;
  intervalCoverageTarget: number | null;
}

export interface FeatureContribution {
  feature: string;
  label: string;
  value: number;
  targetSpace: string;
  effectPctOnForecast: number | null;
}

export interface Explanation {
  summary: string;
  verdict: string | null;
  moduleA: {
    score: number | null;
    threshold: number | null;
    flag: boolean;
    contributions: { parameter: Param; robustZ: number | null; contribution: number | null; value: number | null; lotMedian: number | null }[];
    topContributor: string | null;
  };
  moduleB: {
    score: number | null;
    thresholdK: number | null;
    flag: boolean;
    driver: Param;
    contributions: FeatureContribution[];
    topContributor: string | null;
    targetSpace: string | null;
  };
  staticLimit: { limits: Record<Param, number>; maxObserved: Record<Param, number | null>; observedBreach: Record<Param, boolean>; forecastBreach: Record<Param, boolean> };
  cvFold: number | null;
}

export interface BenchmarkMetrics {
  totalComponents: number;
  excludedWithoutGroundTruth: number;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  recall: number;
  precision: number;
  f1: number;
  f2: number;
  fnCost: number;
  fpCost: number;
  weightedCost: number;
  costPer1000: number;
  maeLeakage: number;
  linearMaeLeakage: number;
  maeReductionPct: number;
  protocol: string;
  outOfFold: number;
  inSample: number;
  thresholds: { threshold_a: number | null; threshold_b: number | null; strategy?: string } | null;
}

export interface CostCurvePoint {
  threshold: number;
  weightedCost: number;
  fn: number;
  fp: number;
  recall: number;
  precision: number;
  f2: number;
}

export interface CostCurve {
  module: 'A' | 'B';
  chosenThreshold: number | null;
  points: CostCurvePoint[];
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  details: string;
  partId?: string;
  lotId?: string;
  category: string;
}

export interface Decision {
  partId: string; // component id
  lotId: string;
  newStatus: PartStatus;
  comment: string;
  inspector: string;
}

export interface IngestIssue {
  row: number;
  message: string;
  severity: 'error' | 'warning';
  partId?: string;
  column?: string;
}

export interface IngestSummary {
  ok: boolean;
  rowsTotal: number;
  partsAccepted: number;
  rowsRejected: number;
  duplicatePartIds: number;
  nonNumericCells: number;
  missingCells: number;
  imputedCells: number;
  insufficientDataParts: number;
  missingColumns: string[];
  issues: IngestIssue[];
}

export interface IngestResult {
  lotId: string | null;
  lotNumber: string | null;
  validation: IngestSummary;
  screening: { nScreened: number; nInsufficientData: number; verdicts: Record<string, number> } | null;
}
