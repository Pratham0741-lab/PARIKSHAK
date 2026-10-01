import { Lot } from '../data/types';

/**
 * Permanent data-source tag, derived from the active lot's stored provenance:
 *   UPLOADED: <file> | SYNTHETIC seed=<n> generator=<name> | MANUAL ENTRY (pasted CSV without a file name).
 */
export function sourceTag(lot: Lot | null, mode: string): string {
  if (mode === 'offline') {
    const seed = (lot?.sourceDetail as { seed?: number } | null)?.seed;
    return `SYNTHETIC seed=${seed ?? '?'} generator=offline-demo (in-browser)`;
  }
  const d = (lot?.sourceDetail ?? {}) as { kind?: string; file?: string; generator?: string; seed?: number };
  if (!lot) return 'NO DATA LOADED';
  if (d.kind === 'SYNTHETIC') return `SYNTHETIC seed=${d.seed} generator=${d.generator}`;
  if (d.kind === 'UPLOADED') return !d.file || d.file === '(pasted CSV)' ? 'MANUAL ENTRY' : `UPLOADED: ${d.file}`;
  if (lot.source === 'SYNTHETIC') return 'SYNTHETIC (seed/generator not recorded: seeded before provenance tracking)';
  return `UNKNOWN SOURCE (${lot.source})`;
}
