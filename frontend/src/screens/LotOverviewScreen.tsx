import React, { useMemo, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { StatusMarker } from '../components/common/StatusMarker';
import { LotConditions } from '../components/common/LotConditions';
import { calculateMedian, calculateMAD } from '../lib/analytics/robustZ';
import { Search, ArrowUpDown } from 'lucide-react';

type SortKey = 'partId' | 'val0' | 'val24' | 'val96' | 'val168' | 'rate' | 'status';

const fmt = (v: number | null | undefined, nd = 2) => (v == null ? '–' : v.toFixed(nd));

export const LotOverviewScreen: React.FC = () => {
  const navigate = useNavigate();
  const { parts, predictions, activeLot, selectedPartId, selectPart, config } = useStore();
  const [searchTerm, setSearchTerm] = useState('');
  const [sortColumn, setSortColumn] = useState<SortKey>('partId');
  const [sortAsc, setSortAsc] = useState(true);
  const staticLimit = config?.datasheetLimits.leakage_current_ua ?? null;

  // Distribution of the 24h leakage reading (the latest reading available at decision time).
  const stats = useMemo(() => {
    const vals = parts.map(p => p.readings[24]).filter((v): v is number => v != null);
    if (vals.length === 0) return null;
    const med = calculateMedian(vals);
    const mad = calculateMAD(vals, med);
    const maxVal = Math.max(staticLimit ?? 0, d3.max(vals) || 1) * 1.1;
    const bins = d3.bin<number, number>().domain([0, maxVal]).thresholds(30)(vals);
    return {
      bins, med, mad, maxVal,
      aboveLimit: staticLimit == null ? 0 : parts.filter(p => [0, 24].some(t => (p.readings[t] ?? 0) > staticLimit)).length,
      flagged: parts.filter(p => p.isFlagged).length,
      insufficient: parts.filter(p => p.insufficientData).length,
      byInspector: parts.filter(p => p.statusSource === 'inspector').length,
    };
  }, [parts, staticLimit]);

  const rate = (serial: string) => predictions[serial]?.moduleB?.perParam.leakage_current_ua?.predictedRate ?? null;

  const rows = useMemo(() => {
    const q = searchTerm.toLowerCase();
    const r = parts.filter(p => p.partId.toLowerCase().includes(q) || p.reason.toLowerCase().includes(q) || p.status.toLowerCase().includes(q));
    const key = (p: typeof parts[number]): number | string => {
      switch (sortColumn) {
        case 'val0': return p.readings[0] ?? -Infinity;
        case 'val24': return p.readings[24] ?? -Infinity;
        case 'val96': return p.readings[96] ?? -Infinity;
        case 'val168': return p.readings[168] ?? -Infinity;
        case 'rate': return rate(p.partId) ?? -Infinity;
        case 'status': return p.status;
        default: return p.partId;
      }
    };
    return [...r].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * (sortAsc ? 1 : -1));
  }, [parts, searchTerm, sortColumn, sortAsc, predictions]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSort = (col: SortKey) => {
    if (sortColumn === col) setSortAsc(!sortAsc);
    else { setSortColumn(col); setSortAsc(true); }
  };

  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => parentRef.current, estimateSize: () => 28, overscan: 10 });
  const pct = (n: number) => `${((n / (parts.length || 1)) * 100).toFixed(1)}%`;

  const header = (label: string, col: SortKey, span: string, right = true) => (
    <div onClick={() => handleSort(col)} className={`${span} flex items-center gap-1 cursor-pointer hover:text-main ${right ? 'justify-end' : ''}`}>
      <span>{label}</span><ArrowUpDown size={10} />
    </div>
  );

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden">
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between text-xs font-mono">
        <div>
          <span className="font-bold text-sm text-main">Lot Overview {activeLot?.lotNumber}</span>
          <div className="text-[11px] text-muted flex gap-4 mt-0.5 font-sans">
            <span>Source: <strong className="text-main font-mono">{activeLot?.source}</strong></span>
            <span>Wafer: <strong className="text-main font-mono">{activeLot?.waferId ?? '–'}</strong></span>
            <span>Parts: <strong className="text-main font-mono">{parts.length.toLocaleString()}</strong></span>
            <span>Model verdicts: <strong className="text-main font-mono">{activeLot ? `${activeLot.passCount} pass / ${activeLot.reviewCount} review / ${activeLot.rejectCount} reject` : '–'}</strong></span>
          </div>
          <LotConditions lot={activeLot} className="text-[11px] text-muted mt-0.5 font-sans" />
        </div>
        <div className="text-right text-[11px] text-muted font-sans">
          <div>Created: <span className="font-mono text-main">{activeLot?.createdAt ? new Date(activeLot.createdAt).toLocaleString() : '–'}</span></div>
          <div>Status: <span className="font-semibold font-mono text-main">{activeLot?.status}</span></div>
        </div>
      </div>

      <div className="h-[140px] border-b border-hairline px-4 py-2 flex items-center justify-between bg-workspace shrink-0">
        <div className="flex-1 h-full pr-8">
          <div className="text-[11px] font-mono text-muted mb-1 flex items-center justify-between">
            <span className="font-semibold text-main">Leakage distribution at 24h (latest reading at decision time)</span>
            {stats && <span>Median <strong className="text-main">{stats.med.toFixed(2)} µA</strong> (MAD {stats.mad.toFixed(2)})</span>}
          </div>
          <svg className="w-full h-[95px] overflow-visible">
            {stats && (() => {
              const w = 450, h = 75;
              const maxCount = d3.max(stats.bins, b => b.length) || 1;
              const x = d3.scaleLinear().domain([0, stats.maxVal]).range([0, w]);
              const y = d3.scaleLinear().domain([0, maxCount]).range([h, 0]);
              return (
                <g transform="translate(10, 8)">
                  {stats.bins.map((b, i) => (
                    <rect key={i} x={x(b.x0 || 0)} y={y(b.length)} width={Math.max(1, x(b.x1 || 0) - x(b.x0 || 0) - 1)} height={h - y(b.length)}
                      fill={staticLimit != null && (b.x0 || 0) >= staticLimit ? '#D63A2F' : '#B0B7BC'} opacity={0.85} />
                  ))}
                  <line x1={x(stats.med)} x2={x(stats.med)} y1={0} y2={h} stroke="#5F6B73" strokeWidth={1.5} strokeDasharray="3 2" />
                  <text x={x(stats.med)} y={-2} textAnchor="middle" className="text-[9px] font-mono fill-muted">median {stats.med.toFixed(1)}</text>
                  {staticLimit != null && (
                    <>
                      <line x1={x(staticLimit)} x2={x(staticLimit)} y1={0} y2={h} stroke="#D63A2F" strokeWidth={1.5} strokeDasharray="4 2" />
                      <text x={x(staticLimit)} y={-2} textAnchor="middle" className="text-[9px] font-mono fill-reject font-bold">datasheet limit {staticLimit} µA</text>
                    </>
                  )}
                </g>
              );
            })()}
          </svg>
        </div>
        {stats && (
          <div className="w-[270px] pl-6 border-l border-hairline space-y-1.5 text-xs font-sans">
            <div><span className="text-muted">Above datasheet limit (0h/24h): </span><span className="font-mono text-reject font-bold">{stats.aboveLimit} ({pct(stats.aboveLimit)})</span></div>
            <div><span className="text-muted">Flagged (model or inspector): </span><span className="font-mono text-reject font-bold">{stats.flagged} ({pct(stats.flagged)})</span></div>
            <div><span className="text-muted">Decided by inspector: </span><span className="font-mono text-main">{stats.byInspector}</span></div>
            <div><span className="text-muted">Insufficient data: </span><span className="font-mono text-main">{stats.insufficient}</span></div>
          </div>
        )}
      </div>

      <div className="h-[36px] border-b border-hairline px-4 flex items-center gap-2 bg-panel shrink-0">
        <div className="relative flex items-center">
          <Search size={12} className="absolute left-2 text-muted" />
          <input type="text" data-search placeholder="Filter by part, reason, status… (/)" value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            className="bg-workspace border border-hairline pl-7 pr-3 py-0.5 text-xs font-mono text-main placeholder:text-muted focus:outline-none w-[280px]" />
        </div>
        <span className="text-muted text-[11px] font-mono">Showing {rows.length} of {parts.length} parts</span>
      </div>

      <div className="h-[28px] bg-panel border-b border-hairline grid grid-cols-12 items-center px-4 text-[11px] font-mono text-muted shrink-0 select-none">
        {header('Part ID', 'partId', 'col-span-2', false)}
        {header('0h µA', 'val0', 'col-span-1')}
        {header('24h µA', 'val24', 'col-span-1')}
        {header('96h µA', 'val96', 'col-span-1')}
        {header('168h µA', 'val168', 'col-span-1')}
        {header('Pred. µA/h', 'rate', 'col-span-1')}
        <div className="col-span-2 pl-4">{header('Status', 'status', '', false)}</div>
        <div className="col-span-3">Reason</div>
      </div>

      <div ref={parentRef} className="flex-1 overflow-y-auto font-mono text-xs select-none">
        <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}>
          {rowVirtualizer.getVirtualItems().map(vr => {
            const part = rows[vr.index];
            if (!part) return null;
            const r = rate(part.partId);
            return (
              <div key={part.id} onClick={() => selectPart(part.partId)} onDoubleClick={() => { selectPart(part.partId); navigate('/components'); }}
                title="Click to select, double-click for component detail"
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: `${vr.size}px`, transform: `translateY(${vr.start}px)` }}
                className={`grid grid-cols-12 items-center px-4 border-b border-hairline/40 cursor-pointer ${part.partId === selectedPartId ? 'bg-panel border-l-2 border-l-reject font-semibold' : 'hover:bg-panel/50'} text-main`}>
                <span className={`col-span-2 truncate ${part.isFlagged ? 'text-reject font-bold' : ''}`}>{part.partId}</span>
                {[0, 24, 96, 168].map(t => (
                  <span key={t} className="col-span-1 text-right tabular-nums text-muted">
                    {fmt(part.readings[t])}{part.allReadings.find(x => x.intervalHours === t)?.imputed.length ? '*' : ''}
                  </span>
                ))}
                <span className="col-span-1 text-right tabular-nums text-muted">{fmt(r, 4)}</span>
                <div className="col-span-2 pl-4"><StatusMarker status={part.status} /></div>
                <span className="col-span-3 truncate text-muted text-[11px] font-sans">{part.reason}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="h-[20px] px-4 text-[10px] text-muted font-sans border-t border-hairline bg-panel flex items-center shrink-0">
        * value imputed at ingest (display only; never used by a model or metric). 96h/168h are shown for traceability; decisions use 0h/24h.
      </div>
    </div>
  );
};
