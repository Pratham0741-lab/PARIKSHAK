import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { useStore } from '../store/useStore';
import { PARAM_UNIT, Part, lotParam } from '../data/types';
import { reasonFromVerdict } from '../data/api';
import { Button, Card, Chip, EmptyState, StatusPill, fmt } from '../components/ui/primitives';
import { Column, DataTable } from '../components/ui/DataTable';
import { anomalyScore } from '../lib/exportCsv';

type Filter = 'all' | 'high' | 'unassigned';

/** Flagged parts of the selected lot (model verdict REVIEW/REJECT, or an inspector status other than Accept).
 * High risk = model verdict REJECT. Unassigned = no inspector decision yet. */
export const ReviewQueueScreen: React.FC = () => {
  const { activeLot, parts, predictions, selectedPartIds, togglePartSelection, selectAllParts, clearPartSelection, openDecisionDialog } = useStore();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const param = lotParam(activeLot);
  const unit = PARAM_UNIT[param];

  const queue = useMemo(() => parts.filter(p => {
    const v = predictions[p.partId]?.verdict;
    return v === 'REVIEW' || v === 'REJECT' || p.status !== 'Accept';
  }), [parts, predictions]);
  const counts = useMemo(() => ({
    all: queue.length,
    high: queue.filter(p => predictions[p.partId]?.verdict === 'REJECT').length,
    unassigned: queue.filter(p => p.statusSource !== 'inspector').length,
  }), [queue, predictions]);
  const rows = useMemo(() => queue.filter(p => {
    if (filter === 'high' && predictions[p.partId]?.verdict !== 'REJECT') return false;
    if (filter === 'unassigned' && p.statusSource === 'inspector') return false;
    const s = q.trim().toLowerCase();
    return !s || p.partId.toLowerCase().includes(s) || (activeLot?.lotNumber.toLowerCase().includes(s) ?? false) || p.reason.toLowerCase().includes(s);
  }), [queue, filter, q, predictions, activeLot]);

  const columns: Column<Part>[] = [
    { key: 'part', header: 'Part', width: 'minmax(150px,1.3fr)', render: p => <span className="font-semibold font-mono text-sm truncate">{p.partId}</span>, sortValue: p => p.partId },
    { key: 'lot', header: 'Lot', width: 'minmax(110px,1fr)', render: () => <span className="truncate">{activeLot?.lotNumber}</span> },
    { key: 'verdict', header: 'Verdict', width: '150px', render: p => (
      <span className="flex items-center gap-1"><StatusPill status={predictions[p.partId]?.verdict ?? null} />
        {p.statusSource === 'inspector' && <span title={`inspector: ${p.inspector ?? ''}`}><StatusPill status={p.status} label={`→ ${p.status === 'Accept' ? 'PASS' : p.status.toUpperCase()}`} /></span>}</span>),
      sortValue: p => predictions[p.partId]?.verdict ?? '' },
    { key: 'score', header: 'Anomaly', width: '100px', align: 'right', render: p => { const s = anomalyScore(predictions[p.partId]); return <span className={`tabular-nums font-semibold ${s != null && s >= 1 ? 'text-reject' : ''}`}>{fmt(s, 2)}</span>; },
      sortValue: p => anomalyScore(predictions[p.partId]) },
    { key: 'pred', header: `Pred. 168h (${unit})`, width: '130px', align: 'right', render: p => <span className="tabular-nums pr-6">{fmt(predictions[p.partId]?.moduleB?.perParam[param]?.forecast168h)}</span>,
      sortValue: p => predictions[p.partId]?.moduleB?.perParam[param]?.forecast168h ?? null },
    { key: 'reason', header: 'Primary reason', width: 'minmax(200px,2fr)', render: p => <span className="text-muted truncate" title={predictions[p.partId]?.verdictReason}>{reasonFromVerdict(predictions[p.partId]?.verdictReason ?? p.reason)}</span> },
    { key: 'open', header: 'Action', width: '90px', render: p => <Button variant="primary" className="!py-1" onClick={() => navigate(`/part/${encodeURIComponent(p.partId)}`)}>Open</Button> },
  ];

  if (!activeLot) return <EmptyState title="No lot loaded" />;
  const sel = [...selectedPartIds].filter(id => rows.some(r => r.partId === id));
  return (
    <div className="space-y-4 max-w-[1500px] flex flex-col h-full" data-testid="review-queue">
      <p className="text-sm text-muted">Flagged parts of lot {activeLot.lotNumber} awaiting or carrying an inspector decision. Switch lots in the header.</p>
      <section className="bg-workspace border border-hairline rounded-card px-5 py-3 flex items-center gap-3 flex-wrap">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-dim" />
          <input data-search value={q} onChange={e => setQ(e.target.value)} placeholder="Search part ID, lot or reason (/)"
            className="pl-9 pr-3 py-2 w-[320px] rounded-lg border border-hairline bg-panel focus:outline-none focus:border-navy" aria-label="Search" />
        </label>
        <Chip active={filter === 'all'} tone="info" onClick={() => setFilter('all')} testId="chip-all">All {counts.all}</Chip>
        <Chip active={filter === 'high'} tone="reject" onClick={() => setFilter('high')} testId="chip-high">High risk {counts.high}</Chip>
        <Chip active={filter === 'unassigned'} tone="review" onClick={() => setFilter('unassigned')} testId="chip-unassigned">Unassigned {counts.unassigned}</Chip>
        <div className="ml-auto flex items-center gap-2 text-sm">
          {sel.length > 0 && <span className="text-muted">{sel.length} selected</span>}
          <Button disabled={sel.length === 0} onClick={() => openDecisionDialog('Review', sel)} data-testid="bulk-decision">Bulk decision…</Button>
          {sel.length > 0 && <Button variant="ghost" onClick={clearPartSelection}>Clear</Button>}
        </div>
      </section>
      <Card className="flex-1 min-h-0" bodyClassName="!p-0">
        {queue.length === 0 ? <EmptyState title="Nothing to review" reason="No part in this lot is flagged by the model." /> : (
          <DataTable columns={columns} rows={rows} rowKey={p => p.partId} height="calc(100vh - 420px)" testId="queue-table"
            onOpen={p => navigate(`/part/${encodeURIComponent(p.partId)}`)} initialSort={{ key: 'score', dir: 'desc' }}
            emptyText="No part matches the search and filter."
            selectable={{ selected: selectedPartIds, toggle: togglePartSelection, setAll: keys => (keys.length ? selectAllParts(keys) : clearPartSelection()) }} />
        )}
      </Card>
      <div className="text-sm text-muted">Showing {rows.length} of {queue.length} flagged parts · High risk = model verdict REJECT · Unassigned = no inspector decision yet · every decision needs a written comment and is audit-logged</div>
    </div>
  );
};
