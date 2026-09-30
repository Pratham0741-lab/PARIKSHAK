import React from 'react';
import { useStore } from '../../store/useStore';

export const StatusFooter: React.FC = () => {
  const { parts, selectedPartId, activeLot, api, config } = useStore();
  const flaggedCount = parts.filter(p => p.isFlagged).length;

  return (
    <footer className="h-[22px] bg-panel border-t border-hairline px-3 flex items-center justify-between text-[11px] font-mono text-muted select-none shrink-0">
      <div className="flex items-center gap-4">
        <span><strong className="text-main font-semibold">{parts.length.toLocaleString()}</strong> parts in lot</span>
        <span className="text-hairline">|</span>
        <span>Selected: <strong className="text-main">{selectedPartId || 'None'}</strong></span>
        <span className="text-hairline">|</span>
        <span>Flagged: <span className={flaggedCount > 0 ? 'text-reject font-medium' : 'text-accept'}>{flaggedCount}</span></span>
        {activeLot && (<><span className="text-hairline">|</span><span>Lot: {activeLot.lotNumber}</span></>)}
        <span className="text-hairline">|</span>
        <span title={config?.latestRun?.protocol}>{api.description}{config?.latestRun ? ` · model run ${new Date(config.latestRun.createdAt).toLocaleString()}` : ''}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-dim">
        <span><kbd className="bg-workspace px-1 border border-hairline text-main">J</kbd>/<kbd className="bg-workspace px-1 border border-hairline text-main">K</kbd> row</span>
        <span><kbd className="bg-workspace px-1 border border-hairline text-accept font-semibold">A</kbd>/<kbd className="bg-workspace px-1 border border-hairline text-review font-semibold">R</kbd>/<kbd className="bg-workspace px-1 border border-hairline text-reject font-semibold">X</kbd> decide (comment required)</span>
        <span><kbd className="bg-workspace px-1 border border-hairline text-main">/</kbd> search</span>
        <span><kbd className="bg-workspace px-1 border border-hairline text-main">?</kbd> help</span>
      </div>
    </footer>
  );
};
