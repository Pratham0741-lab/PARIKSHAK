import React, { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { TopRail } from './TopRail';
import { StatusFooter } from './StatusFooter';
import { KeyboardHelpModal } from './KeyboardHelpModal';
import { DevControlModal } from './DevControlModal';
import { DecisionDialog } from './DecisionDialog';
import { useStore } from '../../store/useStore';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';

export const WorkspaceLayout: React.FC = () => {
  const { fetchInitialData, isLoading, error, mode, api, setDevModalOpen } = useStore();
  useKeyboardShortcuts();

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  return (
    <div className="h-screen w-screen flex flex-col bg-pagebg text-main overflow-hidden select-none">
      <TopRail />
      {mode === 'offline' && (
        <div className="bg-review-bg border-b border-review/40 text-review text-[11px] font-mono px-3 py-1 shrink-0">
          OFFLINE DEMO MODE: synthetic data screened by simple client rules on 0h/24h readings. This is not the ML model;
          intervals, feature contributions and performance metrics need the backend.{' '}
          <button className="underline" onClick={() => setDevModalOpen(true)}>Switch to backend</button>
        </div>
      )}
      {error && (
        <div className="bg-reject-bg border-b border-reject/40 text-reject text-[11px] font-mono px-3 py-1 shrink-0 flex justify-between">
          <span>{error}</span>
          <span>
            <button className="underline mr-3" onClick={() => fetchInitialData()}>Retry</button>
            <button className="underline" onClick={() => setDevModalOpen(true)}>Data source…</button>
          </span>
        </div>
      )}
      <main className="flex-1 min-h-0 flex flex-col overflow-hidden bg-workspace">
        {isLoading ? (
          <div className="flex-1 flex flex-col items-center justify-center font-mono text-xs text-muted">
            <div className="w-6 h-6 border-2 border-hairline border-t-toprail animate-spin mb-3" />
            <span>Loading from {api.description}…</span>
          </div>
        ) : (
          <Outlet />
        )}
      </main>
      <StatusFooter />
      <KeyboardHelpModal />
      <DevControlModal />
      <DecisionDialog />
    </div>
  );
};
