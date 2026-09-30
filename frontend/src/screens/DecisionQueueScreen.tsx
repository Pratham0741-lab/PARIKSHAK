import React, { useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useStore } from '../store/useStore';
import { StatusMarker } from '../components/common/StatusMarker';
import { Search } from 'lucide-react';

const f = (v: number | null | undefined, nd = 2) => (v == null ? '–' : v.toFixed(nd));

export const DecisionQueueScreen: React.FC = () => {
  const {
    parts, predictions, selectedPartId, selectPart, selectedPartIds, togglePartSelection, selectAllParts,
    clearPartSelection, openDecisionDialog, auditEvents,
  } = useStore();
  const [search, setSearch] = useState('');
  const [show, setShow] = useState<'flagged' | 'all' | 'undecided'>('flagged');
  const [statusFilter, setStatusFilter] = useState('All');

  const rows = useMemo(() => parts.filter(p => {
    if (!p.partId.toLowerCase().includes(search.toLowerCase())) return false;
    if (show === 'flagged' && !p.isFlagged) return false;
    if (show === 'undecided' && p.statusSource === 'inspector') return false;
    return statusFilter === 'All' || p.status === statusFilter;
  }), [parts, search, show, statusFilter]);

  const ref = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => ref.current, estimateSize: () => 28, overscan: 10 });
  const active = parts.find(p => p.partId === selectedPartId) ?? null;
  const ap = active ? predictions[active.partId] : undefined;
  const history = active ? auditEvents.filter(e => e.partId === active.id) : [];
  const allChecked = rows.length > 0 && rows.every(r => selectedPartIds.has(r.partId));

  return (
    <div className="w-full h-full flex bg-workspace overflow-hidden divide-x divide-hairline font-mono text-xs">
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-hairline bg-panel flex items-center justify-between shrink-0">
          <div className="flex items-center gap-4">
            <span className="font-bold text-sm text-main">Decision queue ({parts.filter(p => p.isFlagged).length} flagged)</span>
            <select value={show} onChange={e => setShow(e.target.value as typeof show)} className="bg-workspace border border-hairline px-2 py-0.5">
              <option value="flagged">Flagged only</option><option value="undecided">Awaiting inspector</option><option value="all">All parts</option>
            </select>
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="bg-workspace border border-hairline px-2 py-0.5">
              {['All', 'Reject', 'Review', 'Accept'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="relative flex items-center">
            <Search size={12} className="absolute left-2 text-muted" />
            <input data-search value={search} onChange={e => setSearch(e.target.value)} placeholder="Search part… (/)"
              className="bg-workspace border border-hairline pl-7 pr-2 py-0.5 w-[170px] focus:outline-none" />
          </div>
        </div>

        <div className="h-[28px] bg-panel border-b border-hairline grid grid-cols-12 items-center px-4 text-[11px] text-muted uppercase shrink-0">
          <div className="col-span-2 flex items-center gap-2">
            <input type="checkbox" checked={allChecked} onChange={() => (allChecked ? clearPartSelection() : selectAllParts(rows.map(r => r.partId)))} />
            <span>Part</span>
          </div>
          <span className="col-span-1 text-right">A score</span>
          <span className="col-span-1 text-right">B z</span>
          <span className="col-span-1 text-right">Fcst µA</span>
          <span className="col-span-1 pl-2">Model</span>
          <span className="col-span-3 pl-2">Reason</span>
          <span className="col-span-2 pl-2">Status</span>
          <span className="col-span-1">By</span>
        </div>

        <div ref={ref} className="flex-1 overflow-y-auto">
          <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
            {virt.getVirtualItems().map(vr => {
              const p = rows[vr.index];
              const pr = predictions[p.partId];
              return (
                <div key={p.id} onClick={() => selectPart(p.partId)}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: vr.size, transform: `translateY(${vr.start}px)` }}
                  className={`grid grid-cols-12 items-center px-4 border-b border-hairline/40 cursor-pointer ${p.partId === selectedPartId ? 'bg-panel border-l-2 border-l-reject' : 'hover:bg-panel/50'}`}>
                  <div className="col-span-2 flex items-center gap-2" onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={selectedPartIds.has(p.partId)} onChange={() => togglePartSelection(p.partId)} />
                    <span className={p.isFlagged ? 'text-reject font-bold' : ''} onClick={() => selectPart(p.partId)}>{p.partId}</span>
                  </div>
                  <span className={`col-span-1 text-right tabular-nums ${pr?.moduleA?.flag ? 'text-reject font-semibold' : 'text-muted'}`}>{f(pr?.moduleA?.score)}</span>
                  <span className={`col-span-1 text-right tabular-nums ${pr?.moduleB?.flag ? 'text-reject font-semibold' : 'text-muted'}`}>{f(pr?.moduleB?.score)}</span>
                  <span className="col-span-1 text-right tabular-nums text-muted">{f(pr?.moduleB?.perParam.leakage_current_ua?.forecast168h, 1)}</span>
                  <span className="col-span-1 pl-2 text-muted">{pr?.verdict ?? '–'}</span>
                  <span className="col-span-3 pl-2 truncate text-muted text-[11px] font-sans">{p.reason}</span>
                  <div className="col-span-2 pl-2"><StatusMarker status={p.status} /></div>
                  <span className="col-span-1 text-muted text-[11px] truncate">{p.statusSource === 'inspector' ? p.inspector : 'model'}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="h-[42px] bg-panel border-t border-hairline px-4 flex items-center justify-between shrink-0">
          <span className="text-muted"><strong className="text-main">{selectedPartIds.size}</strong> selected</span>
          <div className="flex items-center gap-2">
            <button onClick={() => openDecisionDialog('Accept')} disabled={selectedPartIds.size === 0} className="bg-workspace border border-hairline text-accept font-semibold px-3 py-1 disabled:opacity-40">Accept… (A)</button>
            <button onClick={() => openDecisionDialog('Review')} disabled={selectedPartIds.size === 0} className="bg-workspace border border-hairline text-review font-semibold px-3 py-1 disabled:opacity-40">Review… (R)</button>
            <button onClick={() => openDecisionDialog('Reject')} disabled={selectedPartIds.size === 0} className="bg-workspace border border-reject text-reject font-semibold px-3 py-1 disabled:opacity-40">Reject… (X)</button>
          </div>
        </div>
      </div>

      <div className="w-[300px] shrink-0 bg-panel p-4 overflow-y-auto">
        <div className="pb-2 border-b border-hairline mb-3 font-sans font-bold text-main">Decision trace {active ? `· ${active.partId}` : ''}</div>
        {active ? (
          <div className="space-y-3">
            <div className="flex justify-between"><span className="text-muted">Current status</span><StatusMarker status={active.status} /></div>
            <div className="flex justify-between"><span className="text-muted">Set by</span><span>{active.statusSource === 'inspector' ? active.inspector : active.statusSource}</span></div>
            {ap ? (
              <div className="space-y-1 border-t border-hairline pt-2">
                <div className="flex justify-between"><span className="text-muted">Model verdict</span><span className="font-semibold">{ap.verdict}</span></div>
                <div className="flex justify-between"><span className="text-muted">Module A score / threshold</span><span>{f(ap.moduleA?.score)} / {ap.moduleA?.threshold == null ? 'off' : f(ap.moduleA.threshold)}</span></div>
                <div className="flex justify-between"><span className="text-muted">Module B z / k</span><span>{f(ap.moduleB?.score)} / {ap.moduleB?.thresholdK == null ? 'off' : f(ap.moduleB.thresholdK)}</span></div>
                <div className="text-[11px] text-muted font-sans bg-workspace border border-hairline p-2 whitespace-pre-wrap">{ap.verdictReason}</div>
              </div>
            ) : <div className="text-muted">No model prediction{active.insufficientData ? ' (insufficient data)' : ''}.</div>}
            <div className="flex gap-2 pt-2 border-t border-hairline">
              {(['Accept', 'Review', 'Reject'] as const).map(s => (
                <button key={s} onClick={() => openDecisionDialog(s, [active.partId])} className="flex-1 bg-workspace border border-hairline py-1 hover:border-toprail">{s}…</button>
              ))}
            </div>
            <div className="text-[10px] text-muted font-sans">Every decision requires a written justification and is recorded in the audit log.</div>
            {history.length > 0 && (
              <div className="border-t border-hairline pt-2">
                <div className="font-semibold mb-1">History</div>
                {history.map(h => <div key={h.id} className="text-[11px] mb-1"><span className="text-muted">{new Date(h.timestamp).toLocaleString()} · {h.actor}</span><div>{h.details}</div></div>)}
              </div>
            )}
          </div>
        ) : <div className="text-muted text-center p-4">No part selected</div>}
      </div>
    </div>
  );
};
