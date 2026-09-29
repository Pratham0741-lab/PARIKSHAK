import React, { useState, useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useStore } from '../store/useStore';
import { StatusMarker } from '../components/common/StatusMarker';
import { PartStatus } from '../data/types';
import { Search } from 'lucide-react';

export const DecisionQueueScreen: React.FC = () => {
  const {
    parts,
    predictions,
    selectedPartId,
    selectPart,
    selectedPartIds,
    togglePartSelection,
    selectAllParts,
    clearPartSelection,
    applyDecision,
    applyBulkDecisions,
  } = useStore();

  const [searchTerm, setSearchTerm] = useState('');
  const [filterShow, setFilterShow] = useState<'flagged' | 'all'>('flagged');
  const [filterStatus, setFilterStatus] = useState<string>('All');
  const [filterReason, setFilterReason] = useState<string>('All');

  // Override panel state
  const [overrideStatus, setOverrideStatus] = useState<PartStatus>('Reject');
  const [overrideReason, setOverrideReason] = useState<string>('');
  const [commentModalOpen, setCommentModalOpen] = useState(false);
  const [bulkComment, setBulkComment] = useState('');

  // Selected part for single inspector override
  const activeSelectedPart = useMemo(() => {
    return parts.find(p => p.partId === selectedPartId) || parts.find(p => p.isFlagged) || parts[0] || null;
  }, [parts, selectedPartId]);

  // Unique reasons for filter dropdown
  const uniqueReasons = useMemo(() => {
    const set = new Set(parts.map(p => p.reason).filter(Boolean));
    return ['All', ...Array.from(set)];
  }, [parts]);

  // Filtered parts
  const filteredParts = useMemo(() => {
    return parts.filter(p => {
      const matchSearch = p.partId.toLowerCase().includes(searchTerm.toLowerCase());
      const matchFlagged = filterShow === 'all' || p.isFlagged;
      const matchStatus = filterStatus === 'All' || p.status === filterStatus;
      const matchReason = filterReason === 'All' || p.reason === filterReason;
      return matchSearch && matchFlagged && matchStatus && matchReason;
    });
  }, [parts, searchTerm, filterShow, filterStatus, filterReason]);

  // Virtualization
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filteredParts.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 10,
  });

  const handleSelectAllToggle = () => {
    if (selectedPartIds.size === filteredParts.length && filteredParts.length > 0) {
      clearPartSelection();
    } else {
      selectAllParts(filteredParts.map(p => p.partId));
    }
  };

  const handleApplyOverride = async () => {
    if (!activeSelectedPart || !overrideReason.trim()) return;
    await applyDecision(activeSelectedPart.partId, overrideStatus, overrideReason.trim());
    setOverrideReason('');
  };

  return (
    <div className="w-full h-full flex bg-workspace overflow-hidden divide-x divide-hairline">
      {/* LEFT: Decision Queue Table + Filters + Bulk Action Bar */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Header & Filter Controls Strip */}
        <div className="p-3 border-b border-hairline bg-panel flex items-center justify-between font-mono text-xs shrink-0">
          <div className="flex items-center gap-4">
            <span className="font-bold text-sm text-main">
              Decision Queue ({parts.filter(p => p.isFlagged).length} flagged parts)
            </span>

            <div className="flex items-center gap-1.5">
              <span className="text-muted text-[11px]">Show:</span>
              <select
                value={filterShow}
                onChange={e => setFilterShow(e.target.value as 'flagged' | 'all')}
                className="bg-workspace border border-hairline px-2 py-0.5 text-main text-xs focus:outline-none"
              >
                <option value="flagged">Flagged only</option>
                <option value="all">All parts</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-muted text-[11px]">Status:</span>
              <select
                value={filterStatus}
                onChange={e => setFilterStatus(e.target.value)}
                className="bg-workspace border border-hairline px-2 py-0.5 text-main text-xs focus:outline-none"
              >
                <option value="All">All</option>
                <option value="Reject">Reject</option>
                <option value="Review">Review</option>
                <option value="Accept">Accept</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-muted text-[11px]">Reason:</span>
              <select
                value={filterReason}
                onChange={e => setFilterReason(e.target.value)}
                className="bg-workspace border border-hairline px-2 py-0.5 text-main text-xs focus:outline-none max-w-[130px]"
              >
                {uniqueReasons.map(r => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="relative flex items-center">
            <Search size={12} className="absolute left-2 text-muted" />
            <input
              type="text"
              data-search
              placeholder="Search Part ID... (/)"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="bg-workspace border border-hairline pl-7 pr-2 py-0.5 text-xs font-mono text-main placeholder:text-muted focus:outline-none w-[170px]"
            />
          </div>
        </div>

        {/* Dense Table Header */}
        <div className="h-[28px] bg-panel border-b border-hairline grid grid-cols-12 items-center px-4 text-[11px] font-mono text-muted uppercase shrink-0 select-none">
          <div className="col-span-1 flex items-center gap-2">
            <input
              type="checkbox"
              checked={selectedPartIds.size > 0 && selectedPartIds.size === filteredParts.length}
              onChange={handleSelectAllToggle}
              className="accent-toprail cursor-pointer"
            />
            <span>Part ID</span>
          </div>
          <span className="col-span-1 text-right">Score</span>
          <span className="col-span-2 text-right">Predicted 168h</span>
          <span className="col-span-1 text-right">Slope</span>
          <span className="col-span-3 pl-3">Reason</span>
          <span className="col-span-2 pl-2">Status</span>
          <span className="col-span-1">Inspector</span>
          <span className="col-span-1 text-right">Updated</span>
        </div>

        {/* Virtualized Table Body */}
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
              const pred = predictions[part.partId];
              const isChecked = selectedPartIds.has(part.partId);
              const isRowSelected = part.partId === selectedPartId;

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
                  className={`grid grid-cols-12 items-center px-4 border-b border-hairline/40 cursor-pointer transition-colors ${
                    isRowSelected
                      ? 'bg-panel border-l-2 border-l-reject font-medium text-main'
                      : 'hover:bg-panel/50 text-main'
                  }`}
                >
                  <div
                    className="col-span-1 flex items-center gap-2 truncate"
                    onClick={e => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => togglePartSelection(part.partId)}
                      className="accent-toprail cursor-pointer"
                    />
                    <span className={part.isFlagged ? 'text-reject font-bold' : ''}>{part.partId}</span>
                  </div>
                  <span className={`col-span-1 text-right tabular-nums ${part.isFlagged ? 'text-reject font-semibold' : 'text-muted'}`}>
                    {pred?.anomalyScore.toFixed(1) || '0.0'}
                  </span>
                  <span className={`col-span-2 text-right tabular-nums ${part.isFlagged ? 'text-reject font-semibold' : 'text-muted'}`}>
                    {pred?.predicted168h.toFixed(1) || part.current168h.toFixed(1)} µA
                  </span>
                  <span className={`col-span-1 text-right tabular-nums ${part.slope > 0.15 ? 'text-reject font-semibold' : 'text-muted'}`}>
                    {part.slope.toFixed(2)}
                  </span>
                  <span className="col-span-3 pl-3 truncate text-muted text-[11px] font-sans">
                    {part.reason}
                  </span>
                  <div className="col-span-2 pl-2">
                    <StatusMarker status={part.status} />
                  </div>
                  <span className="col-span-1 text-muted text-[11px] truncate">
                    {part.inspector || '–'}
                  </span>
                  <span className="col-span-1 text-right text-muted text-[10px] truncate">
                    {part.updatedAt ? new Date(part.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '–'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Bottom Bulk Action Bar */}
        <div className="h-[42px] bg-panel border-t border-hairline px-4 flex items-center justify-between font-mono text-xs shrink-0">
          <span className="text-muted">
            <strong className="text-main">{selectedPartIds.size}</strong> selected
          </span>

          <div className="flex items-center gap-2">
            <button
              onClick={() => applyBulkDecisions('Accept', 'Bulk accept action')}
              disabled={selectedPartIds.size === 0}
              className="bg-workspace border border-hairline hover:border-accept text-accept font-semibold px-3 py-1 disabled:opacity-40"
            >
              Accept (A)
            </button>
            <button
              onClick={() => applyBulkDecisions('Review', 'Bulk review action')}
              disabled={selectedPartIds.size === 0}
              className="bg-workspace border border-hairline hover:border-review text-review font-semibold px-3 py-1 disabled:opacity-40"
            >
              Review (R)
            </button>
            <button
              onClick={() => applyBulkDecisions('Reject', 'Bulk reject action')}
              disabled={selectedPartIds.size === 0}
              className="bg-workspace border border-reject text-reject font-semibold px-3 py-1 disabled:opacity-40 hover:bg-reject/5"
            >
              Reject (X)
            </button>
            <button
              onClick={() => setCommentModalOpen(true)}
              disabled={selectedPartIds.size === 0}
              className="bg-workspace border border-hairline text-main px-3 py-1 hover:bg-panel disabled:opacity-40"
            >
              Add Comment
            </button>
          </div>
        </div>
      </div>

      {/* RIGHT: Inspector Override Panel (~290px) */}
      <div className="w-[290px] shrink-0 bg-panel p-4 flex flex-col font-mono text-xs overflow-y-auto">
        <div className="pb-2 border-b border-hairline mb-3 flex items-center justify-between">
          <span className="font-sans font-bold text-xs text-main">Inspector Override</span>
          <span className="text-muted text-[11px]">{activeSelectedPart?.partId}</span>
        </div>

        {activeSelectedPart ? (
          <div className="space-y-4">
            <div className="flex justify-between items-center text-xs pb-2 border-b border-hairline">
              <span className="text-muted font-sans">Current status:</span>
              <StatusMarker status={activeSelectedPart.status} />
            </div>

            {/* New Status Radios */}
            <div>
              <label className="block text-muted font-sans text-xs mb-1.5 font-medium">New status:</label>
              <div className="space-y-1.5 font-sans">
                {(['Accept', 'Review', 'Reject'] as const).map(st => (
                  <label key={st} className="flex items-center gap-2 cursor-pointer text-xs">
                    <input
                      type="radio"
                      name="overrideStatus"
                      checked={overrideStatus === st}
                      onChange={() => setOverrideStatus(st)}
                      className="accent-toprail"
                    />
                    <StatusMarker status={st} />
                  </label>
                ))}
              </div>
            </div>

            {/* Reason Textarea (Required!) */}
            <div>
              <label className="block text-muted font-sans text-xs mb-1 font-medium">
                Reason (required):
              </label>
              <textarea
                rows={4}
                value={overrideReason}
                onChange={e => setOverrideReason(e.target.value)}
                placeholder="Enter engineering justification for disposition override..."
                className="w-full bg-workspace border border-hairline p-2 text-xs font-mono text-main placeholder:text-muted focus:outline-none resize-none"
              />
              <span className="text-[10px] text-muted block mt-0.5 font-sans">
                Immutable record logged to QA audit trail.
              </span>
            </div>

            {/* Action Buttons */}
            <div className="flex justify-end gap-2 pt-2 border-t border-hairline">
              <button
                onClick={() => setOverrideReason('')}
                className="bg-panel border border-hairline px-3 py-1 text-xs text-muted hover:text-main"
              >
                Cancel
              </button>
              <button
                onClick={handleApplyOverride}
                disabled={!overrideReason.trim()}
                className="bg-toprail text-white text-xs px-3 py-1 font-mono disabled:opacity-40 hover:bg-toprail/90"
              >
                Update
              </button>
            </div>
          </div>
        ) : (
          <div className="text-muted text-xs p-4 text-center">No part selected</div>
        )}
      </div>
    </div>
  );
};
