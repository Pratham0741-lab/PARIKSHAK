import React, { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { TopRail } from './TopRail';
import { StatusFooter } from './StatusFooter';
import { KeyboardHelpModal } from './KeyboardHelpModal';
import { DevControlModal } from './DevControlModal';
import { useStore } from '../../store/useStore';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';

export const WorkspaceLayout: React.FC = () => {
  const { fetchInitialData, isLoading } = useStore();
  useKeyboardShortcuts();

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  if (isLoading) {
    return (
      <div className="h-screen w-screen bg-pagebg flex flex-col items-center justify-center font-mono text-xs text-muted">
        <div className="w-6 h-6 border-2 border-hairline border-t-toprail animate-spin mb-3" />
        <span>INITIALIZING PARIKSHAK TEST INSTRUMENTATION...</span>
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-pagebg text-main overflow-hidden select-none">
      <TopRail />
      <main className="flex-1 min-h-0 flex flex-col overflow-hidden bg-workspace">
        <Outlet />
      </main>
      <StatusFooter />
      <KeyboardHelpModal />
      <DevControlModal />
    </div>
  );
};
