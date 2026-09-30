import React, { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useStore } from '../../store/useStore';
import { DEFAULT_API_URL } from '../../data/api';
import { X, RefreshCw } from 'lucide-react';

/** Data-source switch (backend vs offline demo) and the offline demo generator settings. */
export const DevControlModal: React.FC = () => {
  const { isDevModalOpen, setDevModalOpen, offlineSettings, updateOfflineSettings, mode, setMode } = useStore();
  const [seed, setSeed] = useState(offlineSettings.seed);
  const [lotSize, setLotSize] = useState(offlineSettings.lotSize);
  const [defectRate, setDefectRate] = useState(offlineSettings.defectRate * 100);
  const [staticLimit, setStaticLimit] = useState(offlineSettings.staticLimitUa);

  useEffect(() => {
    if (isDevModalOpen) {
      setSeed(offlineSettings.seed);
      setLotSize(offlineSettings.lotSize);
      setDefectRate(offlineSettings.defectRate * 100);
      setStaticLimit(offlineSettings.staticLimitUa);
    }
  }, [isDevModalOpen, offlineSettings]);

  const applyOffline = async () => {
    setDevModalOpen(false);
    await updateOfflineSettings({ seed, lotSize, defectRate: defectRate / 100, staticLimitUa: staticLimit });
    if (mode !== 'offline') await setMode('offline');
  };

  return (
    <Dialog.Root open={isDevModalOpen} onOpenChange={setDevModalOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[460px] bg-workspace border border-hairline p-4 z-50 focus:outline-none font-mono text-xs">
          <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
            <Dialog.Title className="font-semibold tracking-wider text-main uppercase">Data source</Dialog.Title>
            <Dialog.Close className="text-muted hover:text-main"><X size={14} /></Dialog.Close>
          </div>

          <div className="space-y-2 mb-4">
            <button onClick={async () => { setDevModalOpen(false); await setMode('http'); }}
              className={`w-full text-left p-2 border ${mode === 'http' ? 'border-toprail bg-panel' : 'border-hairline'}`}>
              <div className="font-semibold text-main">Backend (default)</div>
              <div className="text-muted font-sans">{DEFAULT_API_URL}: ML models, learned thresholds, intervals, explanations, held-out metrics.</div>
            </button>
            <div className={`p-2 border ${mode === 'offline' ? 'border-review bg-review-bg' : 'border-hairline'}`}>
              <div className="font-semibold text-main">Offline demo</div>
              <div className="text-muted font-sans mb-2">
                Seeded synthetic lot screened by simple client rules on 0h/24h readings. Not the ML model; no labels, no metrics.
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <label className="text-muted w-28">Seed</label>
                  <input type="number" value={seed} onChange={e => setSeed(Number(e.target.value))} className="flex-1 bg-panel border border-hairline px-2 py-0.5" />
                  <button onClick={() => setSeed(Math.floor(Math.random() * 10000))} className="text-muted hover:text-main" title="Random seed"><RefreshCw size={11} /></button>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-muted w-28">Parts</label>
                  <select value={lotSize} onChange={e => setLotSize(Number(e.target.value))} className="flex-1 bg-panel border border-hairline px-2 py-0.5">
                    {[100, 400, 1000, 2500].map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-muted w-28">Defect rate {defectRate.toFixed(1)}%</label>
                  <input type="range" min={0} max={25} step={0.5} value={defectRate} onChange={e => setDefectRate(Number(e.target.value))} className="flex-1 accent-toprail" />
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-muted w-28">Static limit (µA)</label>
                  <input type="number" value={staticLimit} onChange={e => setStaticLimit(Number(e.target.value))} className="flex-1 bg-panel border border-hairline px-2 py-0.5" />
                </div>
              </div>
              <div className="flex justify-end mt-2">
                <button onClick={applyOffline} className="bg-toprail text-white px-3 py-1">Generate offline demo lot</button>
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
