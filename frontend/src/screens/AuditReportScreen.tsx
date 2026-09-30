import React, { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/useStore';
import { Printer, Download } from 'lucide-react';
import { StatusMarker } from '../components/common/StatusMarker';
import { LotConditions } from '../components/common/LotConditions';

export const AuditReportScreen: React.FC = () => {
  const { parts, predictions, activeLot, auditEvents, inspector, config, api } = useStore();
  const [docHash, setDocHash] = useState<string>('computing…');

  const counts = useMemo(() => ({
    accept: parts.filter(p => p.status === 'Accept').length,
    review: parts.filter(p => p.status === 'Review').length,
    reject: parts.filter(p => p.status === 'Reject').length,
    byInspector: parts.filter(p => p.statusSource === 'inspector').length,
  }), [parts]);
  const total = parts.length || 1;
  const flagged = parts.filter(p => p.isFlagged);

  const csvRows = useMemo(() => {
    const header = ['part_id', 'leak_0h', 'leak_24h', 'leak_96h', 'leak_168h', 'forecast_168h', 'interval_lower', 'interval_upper',
      'module_a_score', 'threshold_a', 'module_b_z', 'threshold_b', 'model_verdict', 'status', 'status_source', 'inspector', 'reason'];
    const q = (v: unknown) => (v == null ? '' : typeof v === 'string' ? `"${v.replace(/"/g, '""')}"` : String(v));
    return [header.join(','), ...parts.map(p => {
      const pr = predictions[p.partId];
      const l = pr?.moduleB?.perParam.leakage_current_ua;
      return [p.partId, p.readings[0], p.readings[24], p.readings[96], p.readings[168], l?.forecast168h, l?.intervalLower, l?.intervalUpper,
        pr?.moduleA?.score, pr?.moduleA?.threshold, pr?.moduleB?.score, pr?.moduleB?.thresholdK, pr?.verdict, p.status, p.statusSource,
        p.inspector, p.reason].map(q).join(',');
    })].join('\n');
  }, [parts, predictions]);

  // Hash of the exact exported content (not a placeholder): changes whenever any row changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(csvRows));
        const hex = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
        if (!cancelled) setDocHash(hex);
      } catch {
        if (!cancelled) setDocHash('unavailable (Web Crypto not supported in this context)');
      }
    })();
    return () => { cancelled = true; };
  }, [csvRows]);

  const exportCsv = () => {
    const url = URL.createObjectURL(new Blob([csvRows], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${activeLot?.lotNumber || 'lot'}_screening_report.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="w-full h-full flex bg-pagebg overflow-hidden divide-x divide-hairline">
      <div className="flex-1 overflow-y-auto p-6 flex justify-center bg-[#CDD2D6]">
        <div className="w-[640px] min-h-[842px] bg-white border border-hairline shadow-sm p-8 text-main font-mono text-[11px] select-text space-y-4">
          <div className="border-b-2 border-toprail pb-3 flex justify-between">
            <div>
              <h1 className="font-bold text-base tracking-wider uppercase">PARIKSHAK</h1>
              <h2 className="font-sans text-xs font-semibold text-muted">Burn-in screening report</h2>
            </div>
            <div className="text-right text-[10px] text-muted">
              <div>Lot: <strong className="text-main">{activeLot?.lotNumber}</strong> ({activeLot?.source})</div>
              <div>Generated: {new Date().toLocaleString()}</div>
              <div>Parts: {parts.length}</div>
              <div>Data source: {api.description}</div>
            </div>
          </div>

          <Section title="1. Disposition summary">
            <div className="grid grid-cols-3 gap-2 p-2 bg-panel border border-hairline text-center">
              <div><div className="text-muted text-[10px]">Accept</div><strong className="text-accept">{counts.accept} ({((counts.accept / total) * 100).toFixed(1)}%)</strong></div>
              <div><div className="text-muted text-[10px]">Reject</div><strong className="text-reject">{counts.reject} ({((counts.reject / total) * 100).toFixed(1)}%)</strong></div>
              <div><div className="text-muted text-[10px]">Review</div><strong className="text-review">{counts.review} ({((counts.review / total) * 100).toFixed(1)}%)</strong></div>
            </div>
            <div className="text-[10px] text-muted mt-1">{counts.byInspector} dispositions set by an inspector; the rest are model verdicts.</div>
          </Section>

          <Section title={`2. Flagged parts (${flagged.length})`}>
            <table className="w-full text-left border-collapse border border-hairline text-[10px]">
              <thead><tr className="bg-panel text-muted"><th className="p-1">Part</th><th className="p-1 text-right">24h µA</th><th className="p-1 text-right">Fcst 168h</th><th className="p-1 text-right">A score</th><th className="p-1 text-right">B z</th><th className="p-1">Reason</th><th className="p-1">Status</th></tr></thead>
              <tbody>
                {flagged.slice(0, 40).map(p => {
                  const pr = predictions[p.partId];
                  return (
                    <tr key={p.id} className="border-t border-hairline/40">
                      <td className="p-1 font-semibold">{p.partId}</td>
                      <td className="p-1 text-right">{p.readings[24]?.toFixed(2) ?? '–'}</td>
                      <td className="p-1 text-right">{pr?.moduleB?.perParam.leakage_current_ua?.forecast168h?.toFixed(2) ?? '–'}</td>
                      <td className="p-1 text-right">{pr?.moduleA?.score?.toFixed(2) ?? '–'}</td>
                      <td className="p-1 text-right">{pr?.moduleB?.score?.toFixed(2) ?? '–'}</td>
                      <td className="p-1 truncate max-w-[150px] text-muted">{p.reason}</td>
                      <td className="p-1"><StatusMarker status={p.status} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {flagged.length > 40 && <div className="text-[10px] text-muted mt-1">… {flagged.length - 40} more in the CSV export.</div>}
          </Section>

          <Section title="3. Screening configuration">
            <div className="space-y-0.5 text-[10px]">
              <div>Burn-in test conditions: <LotConditions lot={activeLot} /></div>
              <div>Datasheet limits: {config ? Object.entries(config.datasheetLimits).map(([k, v]) => `${k} ${v}`).join(', ') : '–'}</div>
              <div>Decision cost: FN {Number.isNaN(config?.fnCost) ? '–' : config?.fnCost} / FP {Number.isNaN(config?.fpCost) ? '–' : config?.fpCost} · threshold strategy {config?.thresholdStrategy}</div>
              <div>Model run: {config?.latestRun ? `${config.latestRun.id} (${new Date(config.latestRun.createdAt).toLocaleString()})` : 'n/a'}</div>
              <div className="text-muted">{config?.latestRun?.protocol}</div>
            </div>
          </Section>

          <Section title="4. Sign-off">
            <div className="grid grid-cols-3 gap-4 p-2 bg-panel border border-hairline text-[10px]">
              <div><div className="text-muted mb-1">Inspector ID</div><strong>{inspector || '(not set)'}</strong></div>
              <div><div className="text-muted mb-1">Signature</div><div className="border-b border-main h-4" /></div>
              <div><div className="text-muted mb-1">Date</div><div className="border-b border-main h-4" /></div>
            </div>
          </Section>

          <div className="pt-3 border-t border-hairline text-[9px] text-muted break-all">
            SHA-256 of the exported CSV content: <strong className="text-main">{docHash}</strong>
          </div>
        </div>
      </div>

      <div className="w-[320px] shrink-0 bg-panel flex flex-col font-mono text-xs">
        <div className="p-3 border-b border-hairline flex gap-2">
          <button onClick={() => window.print()} className="flex-1 bg-workspace border border-hairline py-1 flex items-center justify-center gap-1"><Printer size={12} /> Print</button>
          <button onClick={exportCsv} className="flex-1 bg-toprail text-white py-1 flex items-center justify-center gap-1"><Download size={12} /> Export CSV</button>
        </div>
        <div className="p-3 font-sans font-bold">Audit log ({auditEvents.length})</div>
        <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
          {auditEvents.length === 0 && <div className="text-muted">No audit events for this lot yet.</div>}
          {auditEvents.map(e => (
            <div key={e.id} className="border border-hairline bg-workspace p-2">
              <div className="flex justify-between text-[10px] text-muted"><span>{new Date(e.timestamp).toLocaleString()}</span><span>{e.category}</span></div>
              <div className="font-semibold">{e.action} · {e.actor}</div>
              <div className="text-[10px] text-muted font-sans">{e.details}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div>
    <div className="font-sans font-bold text-xs uppercase border-b border-hairline pb-1 mb-2">{title}</div>
    {children}
  </div>
);
