import React, { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useStore } from '../../store/useStore';
import { X, RefreshCw } from 'lucide-react';

export const DevControlModal: React.FC = () => {
  const { isDevModalOpen, setDevModalOpen, devSettings, updateDevSettings } = useStore();

  const [seed, setSeed] = useState(devSettings.seed);
  const [lotSize, setLotSize] = useState(devSettings.lotSize);
  const [defectRate, setDefectRate] = useState(devSettings.defectRate * 100);
  const [staticLimit, setStaticLimit] = useState(devSettings.staticLimitUa);
  const [safetySlope, setSafetySlope] = useState(devSettings.safetySlopeLimit);

  const handleApply = () => {
    updateDevSettings({
      seed,
      lotSize,
      defectRate: defectRate / 100,
      staticLimitUa: staticLimit,
      safetySlopeLimit: safetySlope,
    });
    setDevModalOpen(false);
  };

  const handleRandomSeed = () => {
    setSeed(Math.floor(Math.random() * 10000));
  };

  return (
    <Dialog.Root open={isDevModalOpen} onOpenChange={setDevModalOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[440px] bg-workspace border border-hairline p-4 z-50 focus:outline-none">
          <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
            <Dialog.Title className="font-mono font-semibold text-xs tracking-wider text-main uppercase">
              Synthetic Demo Generator Controls
            </Dialog.Title>
            <Dialog.Close className="text-muted hover:text-main">
              <X size={14} />
            </Dialog.Close>
          </div>

          <p className="text-xs text-muted mb-4 font-sans">
            Adjust semiconductor physics parameters to generate deterministic burn-in wafer datasets.
          </p>

          <div className="space-y-3 font-mono text-xs">
            {/* PRNG Seed */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-muted font-sans text-xs">PRNG Seed:</label>
                <button
                  onClick={handleRandomSeed}
                  className="text-[11px] text-muted hover:text-main flex items-center gap-1"
                >
                  <RefreshCw size={10} /> Randomize
                </button>
              </div>
              <input
                type="number"
                value={seed}
                onChange={e => setSeed(Number(e.target.value))}
                className="w-full bg-panel border border-hairline px-2 py-1 text-main font-mono"
              />
            </div>

            {/* Lot Size */}
            <div>
              <label className="block text-muted font-sans text-xs mb-1">Lot Size (Total Parts):</label>
              <select
                value={lotSize}
                onChange={e => setLotSize(Number(e.target.value))}
                className="w-full bg-panel border border-hairline px-2 py-1 text-main font-mono"
              >
                <option value={50}>50 parts (quick probe)</option>
                <option value={200}>200 parts (prototype lot)</option>
                <option value={1000}>1,000 parts (production batch)</option>
                <option value={1248}>1,248 parts (full space wafer)</option>
                <option value={2500}>2,500 parts (stress test)</option>
              </select>
            </div>

            {/* Defect Rate */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-muted font-sans text-xs">Latent Defect Rate:</label>
                <span>{defectRate.toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min={1}
                max={25}
                step={0.5}
                value={defectRate}
                onChange={e => setDefectRate(Number(e.target.value))}
                className="w-full accent-toprail cursor-pointer"
              />
            </div>

            {/* Static Limit & Safety Slope */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-muted font-sans text-xs mb-1">Static Limit (µA):</label>
                <input
                  type="number"
                  value={staticLimit}
                  onChange={e => setStaticLimit(Number(e.target.value))}
                  className="w-full bg-panel border border-hairline px-2 py-1 text-main font-mono"
                />
              </div>
              <div>
                <label className="block text-muted font-sans text-xs mb-1">Safety Slope (µA/h):</label>
                <input
                  type="number"
                  step={0.01}
                  value={safetySlope}
                  onChange={e => setSafetySlope(Number(e.target.value))}
                  className="w-full bg-panel border border-hairline px-2 py-1 text-main font-mono"
                />
              </div>
            </div>
          </div>

          <div className="mt-5 pt-3 border-t border-hairline flex justify-end gap-2">
            <button
              onClick={() => setDevModalOpen(false)}
              className="bg-panel border border-hairline px-3 py-1 text-xs text-muted hover:text-main"
            >
              Cancel
            </button>
            <button
              onClick={handleApply}
              className="bg-toprail text-white text-xs px-3 py-1 hover:bg-toprail/90 font-mono"
            >
              Generate Demo Lot
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
