/**
 * Raw CSV preview only (first rows as a grid). Validation, imputation and ingest rules live in the
 * backend (POST /api/v1/ingest/validate and /api/v1/ingest) so there is a single authoritative
 * implementation; nothing here fills or alters values.
 */

import Papa from 'papaparse';

export function previewCsv(text: string, maxRows = 15): string[][] {
  const parsed = Papa.parse<string[]>(text.trim(), { skipEmptyLines: true });
  return (parsed.data || []).slice(0, maxRows);
}

/** Example header for the ingest format (documentation for the upload screen). */
export const INGEST_HEADER = [
  'part_id',
  'leakage_current_ua_0h', 'iddq_ma_0h', 'propagation_delay_ns_0h',
  'leakage_current_ua_24h', 'iddq_ma_24h', 'propagation_delay_ns_24h',
  'leakage_current_ua_96h', 'iddq_ma_96h', 'propagation_delay_ns_96h',
  'leakage_current_ua_168h', 'iddq_ma_168h', 'propagation_delay_ns_168h',
];
