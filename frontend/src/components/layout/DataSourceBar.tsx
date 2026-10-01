import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { DEFAULT_API_URL } from '../../data/api';
import { Lot } from '../../data/types';

/**
 * Permanent data-source tag shown on every screen, derived from the active lot's stored provenance:
 *   UPLOADED: <file>                       (CSV ingest; sha256 prefix in the tooltip)
 *   SYNTHETIC seed=<n> generator=<name>    (seeded generator)
 *   MANUAL ENTRY                           (pasted CSV with no file name)
 * On the Judge screen it shows the judge-mode files instead. Next to it, a debug "Recompute" button
 * recalculates the visible metrics and lot counts from raw database rows and compares them with what is shown.
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

interface Row { label: string; shown: number | null | undefined; recomputed: number | null | undefined }

export const DataSourceBar: React.FC = () => {
  const { activeLot, mode, metrics, lots, judgeSource } = useStore();
  const location = useLocation();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const onJudge = location.pathname === '/judge';
  const tag = onJudge ? (judgeSource ?? 'JUDGE MODE: no file loaded') : sourceTag(activeLot, mode);
  const sha = (activeLot?.sourceDetail as { sha256?: string } | null)?.sha256;

  const recompute = async () => {
    setErr(null);
    try {
      const r = await (await fetch(`${DEFAULT_API_URL}/debug/recompute`)).json();
      const b = r.benchmark;
      const out: Row[] = [];
      if (metrics) {
        out.push(
          { label: 'Model: recall', shown: metrics.recall, recomputed: b.recall },
          { label: 'Model: precision', shown: metrics.precision, recomputed: b.precision },
          { label: 'Model: F2', shown: metrics.f2, recomputed: b.f2_score },
          { label: 'Model: weighted cost', shown: metrics.weightedCost, recomputed: b.weighted_cost },
          { label: 'Model: TP', shown: metrics.tp, recomputed: b.true_positives },
          { label: 'Model: FP', shown: metrics.fp, recomputed: b.false_positives },
          { label: 'Model: FN', shown: metrics.fn, recomputed: b.false_negatives },
          { label: 'Model: TN', shown: metrics.tn, recomputed: b.true_negatives },
          { label: 'Model: leakage MAE', shown: metrics.maeLeakage, recomputed: b.module_b_mae_leakage },
          { label: 'Model: linear-baseline MAE', shown: metrics.linearMaeLeakage, recomputed: b.linear_baseline_mae_leakage },
        );
      }
      for (const l of lots) {
        const c = r.lots[l.id] ?? { pass: 0, review: 0, reject: 0, total: 0 };
        out.push(
          { label: `${l.lotNumber}: pass`, shown: l.passCount, recomputed: c.pass },
          { label: `${l.lotNumber}: review`, shown: l.reviewCount, recomputed: c.review },
          { label: `${l.lotNumber}: reject`, shown: l.rejectCount, recomputed: c.reject },
        );
      }
      setRows(out);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const same = (r: Row) => r.shown != null && r.recomputed != null && Math.abs(r.shown - r.recomputed) < 1e-4;
  const bad = rows?.filter(r => !same(r)) ?? [];

  return (
    <div className="relative bg-panel border-b border-hairline px-3 py-0.5 text-[11px] font-mono flex items-center justify-between shrink-0" data-testid="data-source">
      <span title={sha ? `sha256 ${sha}` : undefined}>
        <span className="text-muted">DATA SOURCE: </span><strong className="text-main" data-testid="data-source-tag">{tag}</strong>
        {!onJudge && activeLot && <span className="text-muted"> · lot {activeLot.lotNumber}</span>}
      </span>
      <span className="flex items-center gap-2">
        {rows && (
          <span className={bad.length ? 'text-reject' : 'text-accept'} data-testid="recompute-result">
            {bad.length ? `${bad.length} of ${rows.length} values differ from raw data` : `all ${rows.length} visible values match raw data`}
          </span>
        )}
        {err && <span className="text-reject">{err}</span>}
        {mode !== 'offline' && (
          <button onClick={recompute} className="flex items-center gap-1 text-muted hover:text-main" title="Debug: recompute visible metrics from raw rows">
            <RefreshCw size={11} /> Recompute
          </button>
        )}
      </span>
      {rows && bad.length > 0 && (
        <div className="absolute right-3 top-full z-50 bg-workspace border border-reject p-2 max-h-[300px] overflow-auto">
          {bad.map(r => <div key={r.label}>{r.label}: shown {String(r.shown)} vs raw {String(r.recomputed)}</div>)}
          <button className="underline mt-1" onClick={() => setRows(null)}>close</button>
        </div>
      )}
    </div>
  );
};
