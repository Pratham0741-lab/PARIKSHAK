/**
 * Global Zustand Store for PARIKSHAK Space Hardware Burn-In Screening.
 */

import { create } from 'zustand';
import { api } from '../data/api';
import { AuditEvent, Decision, Lot, Part, PartStatus, Prediction } from '../data/types';

interface DevSettings {
  seed: number;
  lotSize: number;
  defectRate: number;
  staticLimitUa: number;
  safetySlopeLimit: number;
}

interface ParikshakStore {
  lots: Lot[];
  activeLot: Lot | null;
  parts: Part[];
  predictions: Record<string, Prediction>;
  selectedPartId: string | null;
  selectedPartIds: Set<string>;
  auditEvents: AuditEvent[];
  inspector: string;
  devSettings: DevSettings;
  isLoading: boolean;
  isShortcutModalOpen: boolean;
  isDevModalOpen: boolean;

  // Actions
  fetchInitialData: () => Promise<void>;
  setActiveLot: (lotId: string) => Promise<void>;
  selectPart: (partId: string) => void;
  navigatePart: (direction: 'next' | 'prev') => void;
  togglePartSelection: (partId: string) => void;
  selectAllParts: (filteredIds?: string[]) => void;
  clearPartSelection: () => void;
  applyDecision: (partId: string, newStatus: PartStatus, reason: string) => Promise<void>;
  applyBulkDecisions: (newStatus: PartStatus, reason?: string) => Promise<void>;
  updateDevSettings: (settings: Partial<DevSettings>) => void;
  setShortcutModalOpen: (open: boolean) => void;
  setDevModalOpen: (open: boolean) => void;
  ingestCsvLot: (csvContent: string) => Promise<boolean>;
}

export const useStore = create<ParikshakStore>((set, get) => ({
  lots: [],
  activeLot: null,
  parts: [],
  predictions: {},
  selectedPartId: null,
  selectedPartIds: new Set(),
  auditEvents: [],
  inspector: 'A. Nair',
  devSettings: {
    seed: 42,
    lotSize: 1248,
    defectRate: 0.07,
    staticLimitUa: 50.0,
    safetySlopeLimit: 0.15,
  },
  isLoading: true,
  isShortcutModalOpen: false,
  isDevModalOpen: false,

  fetchInitialData: async () => {
    set({ isLoading: true });
    try {
      const lots = await api.getLots();
      if (lots.length > 0) {
        const active = lots[0];
        const parts = await api.getParts(active.id);
        const predictions = await api.getPredictions(active.id);
        const auditEvents = await api.getAuditLog(active.id);

        // Auto-select first flagged or first part
        const flagged = parts.find(p => p.status === 'Reject' || p.status === 'Review');
        const selectedId = flagged ? flagged.partId : (parts[0]?.partId || null);

        set({
          lots,
          activeLot: active,
          parts,
          predictions,
          selectedPartId: selectedId,
          auditEvents,
          isLoading: false,
        });
      } else {
        set({ isLoading: false });
      }
    } catch (err) {
      console.error('Failed to load initial data:', err);
      set({ isLoading: false });
    }
  },

  setActiveLot: async (lotId: string) => {
    set({ isLoading: true });
    try {
      const lot = await api.getLot(lotId);
      if (lot) {
        const parts = await api.getParts(lot.id);
        const predictions = await api.getPredictions(lot.id);
        const auditEvents = await api.getAuditLog(lot.id);

        const flagged = parts.find(p => p.status === 'Reject' || p.status === 'Review');
        const selectedId = flagged ? flagged.partId : (parts[0]?.partId || null);

        set({
          activeLot: lot,
          parts,
          predictions,
          selectedPartId: selectedId,
          selectedPartIds: new Set(),
          auditEvents,
          isLoading: false,
        });
      }
    } catch (err) {
      console.error('Failed to switch active lot:', err);
      set({ isLoading: false });
    }
  },

  selectPart: (partId: string) => {
    set({ selectedPartId: partId });
  },

  navigatePart: (direction: 'next' | 'prev') => {
    const { parts, selectedPartId } = get();
    if (parts.length === 0) return;

    const currentIndex = parts.findIndex(p => p.partId === selectedPartId);
    let nextIndex = currentIndex;

    if (direction === 'next') {
      nextIndex = currentIndex < parts.length - 1 ? currentIndex + 1 : 0;
    } else {
      nextIndex = currentIndex > 0 ? currentIndex - 1 : parts.length - 1;
    }

    set({ selectedPartId: parts[nextIndex].partId });
  },

  togglePartSelection: (partId: string) => {
    const { selectedPartIds } = get();
    const updated = new Set(selectedPartIds);
    if (updated.has(partId)) {
      updated.delete(partId);
    } else {
      updated.add(partId);
    }
    set({ selectedPartIds: updated });
  },

  selectAllParts: (filteredIds?: string[]) => {
    const { parts } = get();
    const ids = filteredIds ? filteredIds : parts.map(p => p.partId);
    set({ selectedPartIds: new Set(ids) });
  },

  clearPartSelection: () => {
    set({ selectedPartIds: new Set() });
  },

  applyDecision: async (partId: string, newStatus: PartStatus, reason: string) => {
    const { activeLot, inspector, parts } = get();
    if (!activeLot) return;

    const part = parts.find(p => p.partId === partId);
    if (!part) return;

    const prevStatus = part.status;
    const now = new Date().toISOString();

    const decision: Decision = {
      partId,
      lotId: activeLot.id,
      previousStatus: prevStatus,
      newStatus,
      reason,
      inspector,
      updatedAt: now,
    };

    await api.submitDecision(decision);

    // Update in-memory parts
    const updatedParts = parts.map(p => {
      if (p.partId === partId) {
        return {
          ...p,
          status: newStatus,
          reason,
          inspector,
          updatedAt: now,
          isFlagged: newStatus !== 'Accept',
        };
      }
      return p;
    });

    const updatedAudit = await api.getAuditLog(activeLot.id);
    set({ parts: updatedParts, auditEvents: updatedAudit });
  },

  applyBulkDecisions: async (newStatus: PartStatus, reason?: string) => {
    const { activeLot, inspector, parts, selectedPartIds } = get();
    if (!activeLot || selectedPartIds.size === 0) return;

    const now = new Date().toISOString();
    const defaultReason = reason || `Bulk ${newStatus.toLowerCase()} by inspector`;

    const decisions: Decision[] = Array.from(selectedPartIds).map(partId => {
      const part = parts.find(p => p.partId === partId);
      return {
        partId,
        lotId: activeLot.id,
        previousStatus: part ? part.status : 'Review',
        newStatus,
        reason: defaultReason,
        inspector,
        updatedAt: now,
      };
    });

    await api.submitBulkDecisions(decisions);

    const updatedParts = parts.map(p => {
      if (selectedPartIds.has(p.partId)) {
        return {
          ...p,
          status: newStatus,
          reason: defaultReason,
          inspector,
          updatedAt: now,
          isFlagged: newStatus !== 'Accept',
        };
      }
      return p;
    });

    const updatedAudit = await api.getAuditLog(activeLot.id);
    set({ parts: updatedParts, selectedPartIds: new Set(), auditEvents: updatedAudit });
  },

  updateDevSettings: (newSettings: Partial<DevSettings>) => {
    const current = get().devSettings;
    const merged = { ...current, ...newSettings };
    set({ devSettings: merged });

    // Re-initialize MockApi with new seed/size
    api.initialize(merged.seed, merged.lotSize);
    get().fetchInitialData();
  },

  setShortcutModalOpen: (open: boolean) => {
    set({ isShortcutModalOpen: open });
  },

  setDevModalOpen: (open: boolean) => {
    set({ isDevModalOpen: open });
  },

  ingestCsvLot: async (csvContent: string): Promise<boolean> => {
    set({ isLoading: true });
    try {
      const res = await api.ingestCsv(csvContent);
      if (res.requiredColumnsFound && res.parsedParts.length > 0) {
        await get().fetchInitialData();
        return true;
      }
      set({ isLoading: false });
      return false;
    } catch (err) {
      console.error('Ingest failed:', err);
      set({ isLoading: false });
      return false;
    }
  },
}));
