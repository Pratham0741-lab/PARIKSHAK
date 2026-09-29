import React, { useMemo, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { StatusMarker } from '../components/common/StatusMarker';
import { calculateMedian, calculateMAD } from '../lib/analytics/robustZ';
import { Search, ArrowUpDown } from 'lucide-react';

export const LotOverviewScreen: React.FC = () => {
  const navigate = useNavigate();
  const { parts, activeLot, selectedPartId, selectPart } = useStore();
  const [searchTerm, setSearchTerm] = useState('');
  const [sortColumn, setSortColumn] = useState<string>('partId');
  const [sortAsc, setSortAsc] = useState<boolean>(true);

  // Summary distribution stats for histogram
  const { histogramBins, median168h, mad168h, partsAboveWarn, partsAboveLimit, flaggedCount } = useMemo(() => {
    if (parts.length === 0) {
      return {
        histogramBins: [],
        median168h: 0,
        mad168h: 0,
        partsAboveWarn: 0,
        partsAboveLimit: 0,
        flaggedCount: 0,
      };
    }

    const vals = parts.map(p => p.readings[168] || p.current168h);
    const med = calculateMedian(vals);
    const mad = calculateMAD(vals, med);

    const warnLimit = 20.0;
    const critLimit = activeLot?.staticLimitUa ?? 50.0;

    const aboveWarn = parts.filter(p => (p.readings[168] || 0) > warnLimit).length;
    const aboveLimit = parts.filter(p => (p.readings[168] || 0) > critLimit).length;
    const flagged = parts.filter(p => p.isFlagged).length;

    // Build D3 histogram bins
    const maxVal = Math.max(critLimit * 1.2, d3.max(vals) || 60);
    const binGen = d3
      .bin<number, number>()
      .domain([0, maxVal])
      .thresholds(25);
    const bins = binGen(vals);

    return {
      histogramBins: bins,
      median168h: med,
      mad168h: mad,
      partsAboveWarn: aboveWarn,
      partsAboveLimit: aboveLimit,
      flaggedCount: flagged,
    };
  }, [parts, activeLot]);

  // Sorting and filtering
  const filteredAndSortedParts = useMemo(() => {
    let result = parts.filter(p =>
      p.partId.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.reason.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.status.toLowerCase().includes(searchTerm.toLowerCase())
    );

    result = [...result].sort((a, b) => {
      let vA: any = a.partId;
      let vB: any = b.partId;

      if (sortColumn === 'val0') {
        vA = a.readings[0] || 0;
        vB = b.readings[0] || 0;
      } else if (sortColumn === 'val24') {
        vA = a.readings[24] || 0;
        vB = b.readings[24] || 0;
      } else if (sortColumn === 'val96') {
        vA = a.readings[96] || 0;
        vB = b.readings[96] || 0;
      } else if (sortColumn === 'val168') {
        vA = a.readings[168] || 0;
        vB = b.readings[168] || 0;
      } else if (sortColumn === 'delta') {
        vA = a.delta;
        vB = b.delta;
      } else if (sortColumn === 'status') {
        vA = a.status;
        vB = b.status;
      }

      if (vA < vB) return sortAsc ? -1 : 1;
      if (vA > vB) return sortAsc ? 1 : -1;
      return 0;
    });

    return result;
  }, [parts, searchTerm, sortColumn, sortAsc]);

  const handleSort = (col: string) => {
    if (sortColumn === col) {
      setSortAsc(!sortAsc);
    } else {
      setSortColumn(col);
      setSortAsc(true);
    }
  };

  // Virtualization
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filteredAndSortedParts.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 10,
  });

  const staticLimit = activeLot?.staticLimitUa ?? 50.0;

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden">
      {/* 1. Lot Header Strip */}
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between text-xs font-mono">
        <div>
          <span className="font-bold text-sm text-main">
            Lot Overview {activeLot?.lotNumber}
          </span>
          <div className="text-[11px] text-muted flex gap-4 mt-0.5 font-sans">
            <span>Date code: <strong className="text-main font-mono">{activeLot?.dateCode}</strong></span>
            <span>Package: <strong className="text-main font-mono">{activeLot?.package}</strong></span>
            <span>Device: <strong className="text-main font-mono">{activeLot?.deviceType}</strong></span>
            <span>Test condition: <strong className="text-main font-mono">{activeLot?.testCondition}</strong></span>
            <span>Total parts: <strong className="text-main font-mono">{parts.length.toLocaleString()}</strong></span>
          </div>
        </div>
        <div className="text-right text-[11px] text-muted font-sans">
          <div>Started: <span className="font-mono text-main">{activeLot?.startedAt ? new Date(activeLot.startedAt).toLocaleDateString() : 'N/A'}</span></div>
          <div>Status: <span className="text-accept font-semibold font-mono">{activeLot?.status}</span></div>
        </div>
      </div>

      {/* 2. Histogram Strip & Summary Plain Text Counts (No KPI cards!) */}
      <div className="h-[140px] border-b border-hairline px-4 py-2 flex items-center justify-between bg-workspace shrink-0">
        {/* Histogram */}
        <div className="flex-1 h-full pr-8">
          <div className="text-[11px] font-mono text-muted mb-1 flex items-center justify-between">
            <span className="font-semibold text-main">Iddq Distribution (168h)</span>
            <span>
              Median: <strong className="text-main font-mono">{median168h.toFixed(2)} µA</strong> (±{mad168h.toFixed(2)} MAD)
            </span>
          </div>
          <svg className="w-full h-[95px] overflow-visible">
            {histogramBins.length > 0 && (() => {
              const maxCount = d3.max(histogramBins, b => b.length) || 1;
              const w = 450;
              const h = 75;
              const xSc = d3.scaleLinear().domain([0, d3.max(histogramBins, b => b.x1 || 0) || 60]).range([0, w]);
              const ySc = d3.scaleLinear().domain([0, maxCount]).range([h, 0]);

              const medX = xSc(median168h);
              const limitX = xSc(staticLimit);

              return (
                <g transform="translate(10, 5)">
                  {/* Bins */}
                  {histogramBins.map((bin, i) => {
                    const x0 = xSc(bin.x0 || 0);
                    const x1 = xSc(bin.x1 || 0);
                    const bw = Math.max(1, x1 - x0 - 1);
                    const bh = h - ySc(bin.length);
                    const isOverLimit = (bin.x0 || 0) >= staticLimit;

                    return (
                      <rect
                        key={`bin-${i}`}
                        x={x0}
                        y={ySc(bin.length)}
                        width={bw}
                        height={bh}
                        fill={isOverLimit ? '#D63A2F' : '#B0B7BC'}
                        opacity={0.85}
                      />
                    );
                  })}

                  {/* Median Line */}
                  <line x1={medX} x2={medX} y1={0} y2={h} stroke="#5F6B73" strokeWidth={1.5} strokeDasharray="3 2" />
                  <text x={medX} y={-2} textAnchor="middle" className="text-[9px] font-mono fill-muted">
                    Median: {median168h.toFixed(1)} µA
                  </text>

                  {/* Static Limit Line */}
                  {limitX <= w && (
                    <>
                      <line x1={limitX} x2={limitX} y1={0} y2={h} stroke="#D63A2F" strokeWidth={1.5} strokeDasharray="4 2" />
                      <text x={limitX} y={-2} textAnchor="middle" className="text-[9px] font-mono fill-reject font-bold">
                        Static limit: {staticLimit} µA
                      </text>
                    </>
                  )}
                </g>
              );
            })()}
          </svg>
        </div>

        {/* Summary Plain Text Counts (Strictly NO KPI cards!) */}
        <div className="w-[260px] pl-6 border-l border-hairline space-y-2 text-xs font-sans">
          <div>
            <span className="text-muted">Parts above 20 µA:</span>
            <div className="font-mono text-main font-semibold">
              {partsAboveWarn} ({((partsAboveWarn / (parts.length || 1)) * 100).toFixed(1)}%)
            </div>
          </div>
          <div>
            <span className="text-muted">Parts above 50 µA:</span>
            <div className="font-mono text-reject font-bold">
              {partsAboveLimit} ({((partsAboveLimit / (parts.length || 1)) * 100).toFixed(1)}%)
            </div>
          </div>
          <div>
            <span className="text-muted">Flagged by model:</span>
            <div className="font-mono text-reject font-bold">
              {flaggedCount} ({((flaggedCount / (parts.length || 1)) * 100).toFixed(1)}%)
            </div>
          </div>
        </div>
      </div>

      {/* 3. Filter and Search Bar */}
      <div className="h-[36px] border-b border-hairline px-4 flex items-center justify-between bg-panel shrink-0">
        <div className="flex items-center gap-2">
          <div className="relative flex items-center">
            <Search size={12} className="absolute left-2 text-muted" />
            <input
              type="text"
              placeholder="Filter by part, reason, status... (/)"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="bg-workspace border border-hairline pl-7 pr-3 py-0.5 text-xs font-mono text-main placeholder:text-muted focus:outline-none w-[280px]"
            />
          </div>
          <span className="text-muted text-[11px] font-mono">
            Showing {filteredAndSortedParts.length} of {parts.length} parts
          </span>
        </div>
      </div>

      {/* 4. Table Header (Sticky) */}
      <div className="h-[28px] bg-panel border-b border-hairline grid grid-cols-12 items-center px-4 text-[11px] font-mono text-muted uppercase shrink-0 select-none">
        <div
          onClick={() => handleSort('partId')}
          className="col-span-2 flex items-center gap-1 cursor-pointer hover:text-main"
        >
          <span>Part ID</span>
          <ArrowUpDown size={10} />
        </div>
        <div
          onClick={() => handleSort('val0')}
          className="col-span-1 text-right flex items-center justify-end gap-1 cursor-pointer hover:text-main"
        >
          <span>0h (µA)</span>
        </div>
        <div
          onClick={() => handleSort('val24')}
          className="col-span-1 text-right flex items-center justify-end gap-1 cursor-pointer hover:text-main"
        >
          <span>24h (µA)</span>
        </div>
        <div
          onClick={() => handleSort('val96')}
          className="col-span-1 text-right flex items-center justify-end gap-1 cursor-pointer hover:text-main"
        >
          <span>96h (µA)</span>
        </div>
        <div
          onClick={() => handleSort('val168')}
          className="col-span-1 text-right flex items-center justify-end gap-1 cursor-pointer hover:text-main"
        >
          <span>168h (µA)</span>
        </div>
        <div
          onClick={() => handleSort('delta')}
          className="col-span-1 text-right flex items-center justify-end gap-1 cursor-pointer hover:text-main"
        >
          <span>Δ (µA/h)</span>
        </div>
        <div
          onClick={() => handleSort('status')}
          className="col-span-2 pl-4 flex items-center gap-1 cursor-pointer hover:text-main"
        >
          <span>Status</span>
          <ArrowUpDown size={10} />
        </div>
        <div className="col-span-3">
          <span>Reason</span>
        </div>
      </div>

      {/* 5. Virtualized Table Body */}
      <div ref={parentRef} className="flex-1 overflow-y-auto font-mono text-xs select-none">
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {rowVirtualizer.getVirtualItems().map(virtualRow => {
            const part = filteredAndSortedParts[virtualRow.index];
            if (!part) return null;
            const isSelected = part.partId === selectedPartId;

            return (
              <div
                key={part.partId}
                onClick={() => selectPart(part.partId)}
                onDoubleClick={() => {
                  selectPart(part.partId);
                  navigate('/drift');
                }}
                title="Click to select, double-click to view drift trajectory"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className={`grid grid-cols-12 items-center px-4 border-b border-hairline/40 cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-panel border-l-2 border-l-reject font-semibold text-main'
                    : 'hover:bg-panel/50 text-main'
                }`}
              >
                <span className={`col-span-2 truncate ${part.isFlagged ? 'text-reject font-bold' : ''}`}>
                  {part.partId}
                </span>
                <span className="col-span-1 text-right tabular-nums text-muted">
                  {(part.readings[0] || 0).toFixed(2)}
                </span>
                <span className="col-span-1 text-right tabular-nums text-muted">
                  {(part.readings[24] || 0).toFixed(2)}
                </span>
                <span className="col-span-1 text-right tabular-nums text-muted">
                  {(part.readings[96] || 0).toFixed(2)}
                </span>
                <span className={`col-span-1 text-right tabular-nums ${part.isFlagged ? 'text-reject font-bold' : ''}`}>
                  {(part.readings[168] || 0).toFixed(2)}
                </span>
                <span className={`col-span-1 text-right tabular-nums ${part.slope > 0.15 ? 'text-reject' : 'text-muted'}`}>
                  {part.slope.toFixed(3)}
                </span>
                <div className="col-span-2 pl-4">
                  <StatusMarker status={part.status} />
                </div>
                <span className="col-span-3 truncate text-muted text-[11px] font-sans">
                  {part.reason}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
