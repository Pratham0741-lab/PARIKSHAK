/**
 * Global store. All data comes from the active ParikshakApi (backend by default).
 * Every disposition change goes through the decision dialog and requires a comment.
 */

import { create } from 'zustand';
import { createApi, initialMode, ParikshakApi, persistMode } from '../data/api';
import { DEFAULT_OFFLINE_SETTINGS, OfflineDemoApi, OfflineDemoSettings } from '../data/offlineDemo';
import {
  ApiMode, AuditEvent, BenchmarkMetrics, CostCurve, Explanation, IngestOptions, IngestResult, Lot, Part, PartStatus, Prediction,
  SystemConfig, lotParam,
} from '../data/types';

export const MIN_COMMENT_LENGTH = 5; // same rule as the backend (ReviewActionRequest.inspector_notes)
const INSPECTOR_KEY = 'parikshak.inspector';

function initialInspector(): string {
  try {
    return globalThis.localStorage?.getItem(INSPECTOR_KEY) || '';
  } catch {
    return '';
  }
}

interface DecisionDialogState {
  open: boolean;
  status: PartStatus;
  partIds: string[]; // component ids
}

interface ParikshakStore {
  mode: ApiMode;
  api: ParikshakApi;
  config: SystemConfig | null;
  lots: Lot[];
  activeLot: Lot | null;
  parts: Part[];
  predictions: Record<string, Prediction>;
  explanations: Record<string, Explanation | null>;
  selectedPartId: string | null;
  selectedPartIds: Set<string>;
  auditEvents: AuditEvent[];
  metrics: BenchmarkMetrics | null;
  costCurves: { A: CostCurve | null; B: CostCurve | null };
  inspector: string;
  offlineSettings: OfflineDemoSettings;
  isLoading: boolean;
  error: string | null;
  decisionDialog: DecisionDialogState;
  isShortcutModalOpen: boolean;
  isDevModalOpen: boolean;
  /** Data-source tag for the Judge screen (its files are not lots). */
  judgeSource: string | null;
  setJudgeSource: (tag: string | null) => void;

  fetchInitialData: () => Promise<void>;
  setActiveLot: (lotId: string) => Promise<void>;
  selectPart: (partId: string) => void;
  navigatePart: (direction: 'next' | 'prev') => void;
  togglePartSelection: (partId: string) => void;
  selectAllParts: (filteredIds?: string[]) => void;
  clearPartSelection: () => void;
  openDecisionDialog: (status: PartStatus, partIds?: string[]) => void;
  closeDecisionDialog: () => void;
  submitDecision: (status: PartStatus, comment: string, partIds: string[]) => Promise<void>;
  loadExplanation: (partId: string) => Promise<void>;
  loadMetrics: () => Promise<void>;
  setMode: (mode: ApiMode) => Promise<void>;
  updateOfflineSettings: (s: Partial<OfflineDemoSettings>) => Promise<void>;
  setInspector: (name: string) => void;
  ingestCsv: (csv: string, lotNumber?: string, opts?: IngestOptions) => Promise<IngestResult>;
  setShortcutModalOpen: (open: boolean) => void;
  setDevModalOpen: (open: boolean) => void;
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const useStore = create<ParikshakStore>((set, get) => {
  const mode = initialMode();
  return {
    mode,
    api: createApi(mode),
    config: null,
    lots: [],
    activeLot: null,
    parts: [],
    predictions: {},
    explanations: {},
    selectedPartId: null,
    selectedPartIds: new Set(),
    auditEvents: [],
    metrics: null,
    costCurves: { A: null, B: null },
    inspector: initialInspector(),
    offlineSettings: DEFAULT_OFFLINE_SETTINGS,
    isLoading: true,
    error: null,
    decisionDialog: { open: false, status: 'Review', partIds: [] },
    isShortcutModalOpen: false,
    isDevModalOpen: false,

    fetchInitialData: async () => {
      set({ isLoading: true, error: null });
      const { api } = get();
      try {
        const [config, lots] = await Promise.all([api.getConfig(), api.getLots()]);
        set({ config, lots });
        const keep = get().activeLot && lots.find(l => l.id === get().activeLot!.id);
        const active = keep || lots[0];
        if (active) await get().setActiveLot(active.id);
        set({ isLoading: false });
      } catch (e) {
        set({ isLoading: false, error: `Could not load data from ${api.description}: ${errorText(e)}` });
      }
    },

    setActiveLot: async (lotId: string) => {
      const { api, lots } = get();
      const lot = lots.find(l => l.id === lotId) ?? null;
      if (!lot) return;
      try {
        const [{ parts, predictions }, auditEvents] = await Promise.all([api.getParts(lotId, lotParam(lot)), api.getAuditLog(lotId)]);
        const current = get().selectedPartId;
        const selected = parts.find(p => p.partId === current) ?? parts.find(p => p.isFlagged) ?? parts[0];
        set({
          activeLot: lot, parts, predictions, auditEvents, explanations: {},
          selectedPartId: selected ? selected.partId : null, selectedPartIds: new Set(), error: null,
        });
      } catch (e) {
        set({ error: `Could not load lot ${lot.lotNumber}: ${errorText(e)}` });
      }
    },

    selectPart: (partId: string) => set({ selectedPartId: partId }),

    navigatePart: (direction) => {
      const { parts, selectedPartId } = get();
      if (parts.length === 0) return;
      const i = parts.findIndex(p => p.partId === selectedPartId);
      const next = direction === 'next' ? (i + 1) % parts.length : (i - 1 + parts.length) % parts.length;
      set({ selectedPartId: parts[next].partId });
    },

    togglePartSelection: (partId: string) => {
      const s = new Set(get().selectedPartIds);
      if (s.has(partId)) s.delete(partId);
      else s.add(partId);
      set({ selectedPartIds: s });
    },
    selectAllParts: (filteredIds) => set({ selectedPartIds: new Set(filteredIds ?? get().parts.map(p => p.partId)) }),
    clearPartSelection: () => set({ selectedPartIds: new Set() }),

    openDecisionDialog: (status, partIds) => {
      const { selectedPartIds, selectedPartId, parts } = get();
      const serials = partIds ?? (selectedPartIds.size > 0 ? [...selectedPartIds] : selectedPartId ? [selectedPartId] : []);
      const ids = serials.map(sn => parts.find(p => p.partId === sn)?.id).filter((x): x is string => !!x);
      if (ids.length === 0) return;
      set({ decisionDialog: { open: true, status, partIds: ids } });
    },
    closeDecisionDialog: () => set({ decisionDialog: { ...get().decisionDialog, open: false } }),

    submitDecision: async (status, comment, partIds) => {
      const { api, activeLot, inspector } = get();
      if (!activeLot) return;
      if (comment.trim().length < MIN_COMMENT_LENGTH) throw new Error(`A comment of at least ${MIN_COMMENT_LENGTH} characters is required.`);
      if (inspector.trim().length < 2) throw new Error('Set your inspector ID (top bar) before recording a decision.');
      for (const id of partIds) {
        await api.submitDecision({ partId: id, lotId: activeLot.id, newStatus: status, comment: comment.trim(), inspector: inspector.trim() });
      }
      set({ decisionDialog: { ...get().decisionDialog, open: false }, selectedPartIds: new Set() });
      await get().setActiveLot(activeLot.id); // re-read statuses and the audit log from the source of truth
    },

    loadExplanation: async (partId: string) => {
      const part = get().parts.find(p => p.partId === partId);
      if (!part || partId in get().explanations) return;
      try {
        const exp = await get().api.getExplanation(part.id);
        set({ explanations: { ...get().explanations, [partId]: exp } });
      } catch (e) {
        set({ error: `Could not load explanation for ${partId}: ${errorText(e)}` });
      }
    },

    loadMetrics: async () => {
      const { api } = get();
      try {
        const [metrics, A, B] = await Promise.all([api.getMetrics(), api.getCostCurve('A'), api.getCostCurve('B')]);
        set({ metrics, costCurves: { A, B } });
      } catch (e) {
        set({ error: `Could not load metrics: ${errorText(e)}` });
      }
    },

    setMode: async (mode: ApiMode) => {
      persistMode(mode);
      const api = mode === 'offline' ? new OfflineDemoApi(get().offlineSettings) : createApi('http');
      set({ mode, api, activeLot: null, lots: [], parts: [], predictions: {}, explanations: {}, metrics: null, costCurves: { A: null, B: null } });
      await get().fetchInitialData();
    },

    updateOfflineSettings: async (s) => {
      const merged = { ...get().offlineSettings, ...s };
      set({ offlineSettings: merged });
      const { api } = get();
      if (api instanceof OfflineDemoApi) {
        api.regenerate(merged); // every setting (seed, size, defect rate, static limit) is applied
        set({ activeLot: null });
        await get().fetchInitialData();
      }
    },

    setInspector: (name: string) => {
      try {
        globalThis.localStorage?.setItem(INSPECTOR_KEY, name);
      } catch {
        /* ignore */
      }
      set({ inspector: name });
    },

    ingestCsv: async (csv: string, lotNumber?: string, opts?: IngestOptions) => {
      const res = await get().api.ingestCsv(csv, lotNumber, get().inspector || 'QA Inspector', opts);
      if (res.lotId) {
        const lots = await get().api.getLots();
        set({ lots });
        await get().setActiveLot(res.lotId);
      }
      return res;
    },

    judgeSource: null,
    setJudgeSource: (tag) => set({ judgeSource: tag }),
    setShortcutModalOpen: (open) => set({ isShortcutModalOpen: open }),
    setDevModalOpen: (open) => set({ isDevModalOpen: open }),
  };
});
