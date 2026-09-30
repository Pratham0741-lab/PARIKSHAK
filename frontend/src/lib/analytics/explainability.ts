/**
 * Nearest-neighbour lookup of parts with similar EARLY behaviour (0h/24h leakage), so an inspector
 * can compare a part with similar parts and their current dispositions. Feature contributions and
 * justification text are NOT computed here: they come from the backend explainer.
 */

import { Part } from '../../data/types';

export interface SimilarPartMatch {
  partId: string;
  lotId: string;
  leakage0h: number | null;
  leakage24h: number | null;
  status: Part['status'];
  distance: number;
}

export function findSimilarParts(target: Part, allParts: Part[], limit = 5): SimilarPartMatch[] {
  const t0 = target.readings[0];
  const t24 = target.readings[24];
  if (t0 == null || t24 == null) return [];
  return allParts
    .filter(p => p.id !== target.id && p.readings[0] != null && p.readings[24] != null)
    .map(p => ({ p, d: Math.hypot((p.readings[0] as number) - t0, (p.readings[24] as number) - t24) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, limit)
    .map(({ p, d }) => ({
      partId: p.partId, lotId: p.lotId, leakage0h: p.readings[0], leakage24h: p.readings[24], status: p.status,
      distance: Number(d.toFixed(3)),
    }));
}
