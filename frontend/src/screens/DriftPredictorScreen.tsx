import React, { useState, useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useStore } from '../store/useStore';
import { Sparkline } from '../components/common/Sparkline';
import { DriftTracePlot } from '../components/drift/DriftTracePlot';
import { Search } from 'lucide-react';

export const DriftPredictorScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, selectPart, activeLot } = useStore();

  const [searchTerm, setSearchTerm] = useState('');
  const [activeCenterTab, setActiveCenterTab] = useState<'Trajectory' | 'Distribution' | 'Feature View'>('Trajectory');
  const [xAxisMode] = useState<'linear' | 'log'>('linear');
  const [yAxisMode, setYAxisMode] = useState<'linear' | 'log'>('log');
  const [filterMode, setFilterMode] = useState<'all' | 'flagged' | 'selected'>('all');
  const [showPredicted, setShowPredicted] = useState(true);
  const [showConfidenceBand, setShowConfidenceBand] = useState(true);
  const [showSafetySlope, setShowSafetySlope] = useState(true);

  // Filtered parts for left list
  const filteredParts = useMemo(() => {
    return parts.filter(p => {
      const matchSearch = p.partId.toLowerCase().includes(searchTerm.toLowerCase());
      if (filterMode === 'flagged') return matchSearch && p.isFlagged;
      if (filterMode === 'selected') return matchSearch && p.partId === selectedPartId;
      return matchSearch;
    });
  }, [parts, searchTerm, filterMode, selectedPartId]);

  // Selected part & prediction object
  const selectedPart = useMemo(() => {
    return parts.find(p => p.partId === selectedPartId) || parts[0] || null;
  }, [parts, selectedPartId]);

  const selectedPrediction = useMemo(() => {
    if (!selectedPart) return null;
    return predictions[selectedPart.partId] || null;
  }, [predictions, selectedPart]);

  // Virtualization for parts list
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filteredParts.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 10,
  });

  const staticLimit = activeLot?.staticLimitUa ?? 50.0;
  const safetySlopeLimit = activeLot?.safetySlopeLimitUaPerHr ?? 0.15;

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-workspace">
      {/* Workspace Area: 3 Columns */}
      <div className="flex-1 min-h-0 flex divide-x divide-hairline overflow-hidden">
        {/* ========================================================================= */}
        {/* COLUMN 1 (LEFT): Virtualized Searchable Parts List (~230px) */}
        {/* ========================================================================= */}
        <div className="w-[230px] shrink-0 flex flex-col bg-panel border-r border-hairline overflow-hidden">
          {/* Header */}
          <div className="p-2 border-b border-hairline bg-workspace">
            <div className="flex items-center justify-between text-xs font-mono font-semibold text-main mb-1.5">
              <span>Parts in Lot ({parts.length.toLocaleString()})</span>
            </div>
            {/* Search Input */}
            <div className="relative flex items-center">
              <Search size={12} className="absolute left-2 text-muted" />
              <input
                type="text"
                data-search
                placeholder="Search Part ID... (/)"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="w-full bg-panel border border-hairline pl-7 pr-2 py-1 text-xs font-mono text-main placeholder:text-muted focus:outline-none focus:border-toprail"
              />
            </div>
          </div>

          {/* Table Header */}
          <div className="h-[26px] bg-panel border-b border-hairline grid grid-cols-12 items-center px-2 text-[11px] font-mono text-muted uppercase">
            <span className="col-span-5">Part ID</span>
            <span className="col-span-4 text-right">168h (µA)</span>
            <span className="col-span-3 text-right">Trend</span>
          </div>

          {/* Virtualized Rows List */}
          <div ref={parentRef} className="flex-1 overflow-y-auto font-mono text-xs select-none">
            <div
              style={{
                height: `${rowVirtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative',
              }}
            >
              {rowVirtualizer.getVirtualItems().map(virtualRow => {
                const part = filteredParts[virtualRow.index];
                if (!part) return null;
                const isSelected = part.partId === selectedPartId;
                const val168 = part.readings[168] ?? part.current168h;

                return (
                  <div
                    key={part.partId}
                    onClick={() => selectPart(part.partId)}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className={`grid grid-cols-12 items-center px-2 border-b border-hairline/40 cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-white border-l-2 border-l-reject font-bold text-main'
                        : 'hover:bg-workspace/80 text-main'
                    }`}
                  >
                    <span
                      className={`col-span-5 truncate text-xs ${
                        part.isFlagged ? 'text-reject font-semibold' : 'text-main'
                      }`}
                    >
                      {part.partId}
                    </span>
                    <span
                      className={`col-span-4 text-right tabular-nums text-xs ${
                        part.isFlagged ? 'text-reject font-semibold' : 'text-muted'
                      }`}
                    >
                      {val168.toFixed(2)}
                    </span>
                    <div className="col-span-3 flex justify-end">
                      <Sparkline readings={part.readings} isFlagged={part.isFlagged} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Left Footer */}
          <div className="h-[24px] bg-panel border-t border-hairline px-2 flex items-center justify-between text-[11px] font-mono text-muted">
            <span>{filteredParts.length} parts</span>
            <span>{selectedPartId ? '1 selected' : '0 selected'}</span>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* COLUMN 2 (CENTER): Trajectory View & Plot (flex-1) */}
        {/* ========================================================================= */}
        <div className="flex-1 min-w-0 flex flex-col bg-workspace overflow-hidden">
          {/* Center Header Controls Strip */}
          <div className="h-[42px] border-b border-hairline px-3 flex items-center justify-between bg-workspace shrink-0">
            {/* View Sub-tabs */}
            <div className="flex items-center space-x-1">
              {(['Trajectory', 'Distribution', 'Feature View'] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveCenterTab(tab)}
                  className={`px-3 py-1 font-sans text-xs transition-colors border ${
                    activeCenterTab === tab
                      ? 'bg-toprail text-white border-toprail font-medium'
                      : 'bg-panel text-muted border-hairline hover:text-main'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Axes & Display Controls */}
            <div className="flex items-center gap-3 font-mono text-xs">
              <div className="flex items-center gap-1">
                <span className="text-muted text-[11px]">Y-Axis:</span>
                <select
                  value={yAxisMode}
                  onChange={e => setYAxisMode(e.target.value as 'linear' | 'log')}
                  className="bg-panel border border-hairline px-1.5 py-0.5 text-main text-xs focus:outline-none"
                >
                  <option value="linear">Linear</option>
                  <option value="log">Log</option>
                </select>
              </div>

              <div className="flex items-center gap-1">
                <span className="text-muted text-[11px]">Show:</span>
                <select
                  value={filterMode}
                  onChange={e => setFilterMode(e.target.value as 'all' | 'flagged' | 'selected')}
                  className="bg-panel border border-hairline px-1.5 py-0.5 text-main text-xs focus:outline-none"
                >
                  <option value="all">All parts</option>
                  <option value="flagged">Flagged only</option>
                  <option value="selected">Selected only</option>
                </select>
              </div>

              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showPredicted}
                  onChange={e => setShowPredicted(e.target.checked)}
                  className="accent-toprail"
                />
                <span className="text-muted text-[11px]">Show predicted</span>
              </label>

              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showConfidenceBand}
                  onChange={e => setShowConfidenceBand(e.target.checked)}
                  className="accent-toprail"
                />
                <span className="text-muted text-[11px]">Show confidence band</span>
              </label>

              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showSafetySlope}
                  onChange={e => setShowSafetySlope(e.target.checked)}
                  className="accent-toprail"
                />
                <span className="text-muted text-[11px]">Show safety slope</span>
              </label>
            </div>
          </div>

          {/* Subheader Title */}
          <div className="px-4 pt-2.5 pb-1 flex items-center justify-between text-xs font-mono font-semibold text-main">
            <span>Iddq Drift Trajectories (0h → 168h)</span>
          </div>

          {/* Main Chart Body */}
          <div className="flex-1 min-h-0 relative">
            <DriftTracePlot
              parts={filteredParts}
              selectedPart={selectedPart}
              prediction={selectedPrediction}
              staticLimit={staticLimit}
              safetySlopeLimit={safetySlopeLimit}
              xAxisMode={xAxisMode}
              yAxisMode={yAxisMode}
              showPredicted={showPredicted}
              showConfidenceBand={showConfidenceBand}
              showSafetySlope={showSafetySlope}
              onSelectPart={selectPart}
            />
          </div>

          {/* Bottom Chart Legend */}
          <div className="h-[28px] border-t border-hairline bg-panel px-4 flex items-center gap-6 font-mono text-[11px] text-muted shrink-0">
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-[2px] bg-trace-neutral inline-block" />
              <span>Normal parts ({parts.filter(p => !p.isFlagged).length})</span>
            </div>
            {selectedPart && (
              <div className="flex items-center gap-1.5">
                <span className="w-3.5 h-[2.5px] bg-reject inline-block" />
                <span className="text-reject font-medium">{selectedPart.partId} (flagged)</span>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-0 border-t border-dashed border-reject inline-block" />
              <span>Forecast</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-2 bg-reject/10 border border-reject/30 inline-block" />
              <span>Confidence band (95%)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-0 border-t border-dashed border-main inline-block" />
              <span>Safety slope ({safetySlopeLimit} µA/h)</span>
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* COLUMN 3 (RIGHT): Inspector Panel (~285px) */}
        {/* ========================================================================= */}
        <div className="w-[285px] shrink-0 flex flex-col bg-panel overflow-y-auto border-l border-hairline p-3 font-mono text-xs">
          {selectedPart && selectedPrediction ? (
            <>
              {/* Part ID and Risk Banner */}
              <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
                <span className="text-sm font-bold tracking-tight text-main">
                  Part: {selectedPart.partId}
                </span>
                <span
                  className={`px-2 py-0.5 text-[11px] font-semibold uppercase border ${
                    selectedPart.isFlagged
                      ? 'border-reject text-reject bg-reject-bg'
                      : 'border-accept text-accept bg-accept-bg'
                  }`}
                >
                  {selectedPart.isFlagged ? 'High Risk' : 'Nominal'}
                </span>
              </div>

              {/* Part Metadata Table */}
              <div className="space-y-1.5 text-xs pb-3 border-b border-hairline mb-3">
                <div className="flex justify-between">
                  <span className="text-muted font-sans">Lot ID:</span>
                  <span className="text-main">{activeLot?.lotNumber}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted font-sans">Package:</span>
                  <span className="text-main">{activeLot?.package}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted font-sans">Device type:</span>
                  <span className="text-main">{activeLot?.deviceType}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted font-sans">Date code:</span>
                  <span className="text-main">{activeLot?.dateCode}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted font-sans">Test condition:</span>
                  <span className="text-main">{activeLot?.testCondition}</span>
                </div>
              </div>

              {/* Drift Metrics */}
              <div className="mb-3 pb-3 border-b border-hairline">
                <div className="font-sans font-semibold text-xs text-main mb-2">Drift Metrics</div>
                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Current (168h):</span>
                    <span className="text-main">{selectedPart.current168h.toFixed(1)} µA</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Predicted 168h:</span>
                    <span
                      className={`font-bold ${
                        selectedPrediction.predicted168h > staticLimit ? 'text-reject' : 'text-main'
                      }`}
                    >
                      {selectedPrediction.predicted168h.toFixed(1)} µA
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Slope:</span>
                    <span
                      className={`font-bold ${
                        selectedPrediction.exceedsSafetySlope ? 'text-reject' : 'text-main'
                      }`}
                    >
                      {selectedPrediction.slopeUaPerHr.toFixed(2)} µA/h
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Residual:</span>
                    <span className="text-main">{selectedPrediction.residualUa.toFixed(1)} µA</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Prediction interval (95%):</span>
                    <span className="text-main">
                      {selectedPrediction.ciLowerUa.toFixed(1)} – {selectedPrediction.ciUpperUa.toFixed(1)} µA
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Safety slope limit:</span>
                    <span className="text-main">{safetySlopeLimit.toFixed(2)} µA/h</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Exceeds safety slope:</span>
                    <span
                      className={`font-semibold ${
                        selectedPrediction.exceedsSafetySlope ? 'text-reject' : 'text-accept'
                      }`}
                    >
                      {selectedPrediction.exceedsSafetySlope ? 'Yes' : 'No'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Static datasheet limit:</span>
                    <span className="text-main">{staticLimit.toFixed(0)} µA</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted font-sans">Passes static limit:</span>
                    <span
                      className={`font-semibold ${
                        selectedPrediction.passesStaticLimit ? 'text-accept' : 'text-reject'
                      }`}
                    >
                      {selectedPrediction.passesStaticLimit ? 'Yes' : 'No'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Model Confidence */}
              <div className="mb-3 pb-3 border-b border-hairline">
                <div className="font-sans font-semibold text-xs text-main mb-1.5">Model Confidence</div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-3 bg-hairline/40 rounded-[2px] overflow-hidden">
                    <div
                      className="h-full bg-accept"
                      style={{ width: `${selectedPrediction.modelConfidence * 100}%` }}
                    />
                  </div>
                  <span className="text-xs font-bold text-main">
                    {selectedPrediction.modelConfidence.toFixed(2)}
                  </span>
                </div>
              </div>

              {/* Notes */}
              <div>
                <div className="font-sans font-semibold text-xs text-main mb-1.5">Notes</div>
                <div className="bg-workspace border border-hairline p-2 text-[11px] leading-relaxed text-muted font-mono">
                  {selectedPrediction.notes}
                </div>
              </div>
            </>
          ) : (
            <div className="text-muted text-xs p-4 text-center">No part selected</div>
          )}
        </div>
      </div>
    </div>
  );
};
