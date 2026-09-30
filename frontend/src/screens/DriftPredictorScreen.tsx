import React, { useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useStore } from '../store/useStore';
import { Sparkline } from '../components/common/Sparkline';
import { DriftTracePlot } from '../components/drift/DriftTracePlot';
import { PARAMS, PARAM_LABEL, PARAM_UNIT } from '../data/types';
import { Search } from 'lucide-react';

const f = (v: number | null | undefined, nd = 3) => (v == null ? '–' : v.toFixed(nd));

export const DriftPredictorScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, selectPart, config, mode } = useStore();
  const [search, setSearch] = useState('');
  const [filterMode, setFilterMode] = useState<'all' | 'flagged' | 'moduleB'>('all');
  const [yAxisMode, setYAxisMode] = useState<'linear' | 'log'>('linear');
  const [showPredicted, setShowPredicted] = useState(true);
  const [showInterval, setShowInterval] = useState(true);
  const [showSafetySlope, setShowSafetySlope] = useState(true);
  const staticLimit = config?.datasheetLimits.leakage_current_ua ?? null;

  const filtered = useMemo(() => parts.filter(p => {
    if (!p.partId.toLowerCase().includes(search.toLowerCase())) return false;
    if (filterMode === 'flagged') return p.isFlagged;
    if (filterMode === 'moduleB') return !!predictions[p.partId]?.moduleB?.flag;
    return true;
  }), [parts, predictions, search, filterMode]);

  const part = parts.find(p => p.partId === selectedPartId) ?? parts[0] ?? null;
  const pred = part ? predictions[part.partId] ?? null : null;
  const b = pred?.moduleB ?? null;
  const leak = b?.perParam.leakage_current_ua ?? null;

  const listRef = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: filtered.length, getScrollElement: () => listRef.current, estimateSize: () => 28, overscan: 10 });

  return (
    <div className="w-full h-full flex divide-x divide-hairline overflow-hidden bg-workspace font-mono text-xs">
      <div className="w-[230px] shrink-0 flex flex-col bg-panel overflow-hidden">
        <div className="p-2 border-b border-hairline bg-workspace">
          <div className="font-semibold text-main mb-1.5">Parts in lot ({parts.length})</div>
          <div className="relative flex items-center">
            <Search size={12} className="absolute left-2 text-muted" />
            <input data-search value={search} onChange={e => setSearch(e.target.value)} placeholder="Search part… (/)"
              className="w-full bg-panel border border-hairline pl-7 pr-2 py-1 focus:outline-none" />
          </div>
        </div>
        <div className="h-[26px] grid grid-cols-12 items-center px-2 text-[11px] text-muted uppercase border-b border-hairline">
          <span className="col-span-5">Part</span><span className="col-span-4 text-right">Fcst 168h</span><span className="col-span-3 text-right">Trend</span>
        </div>
        <div ref={listRef} className="flex-1 overflow-y-auto">
          <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
            {virt.getVirtualItems().map(vr => {
              const p = filtered[vr.index];
              const fc = predictions[p.partId]?.moduleB?.perParam.leakage_current_ua?.forecast168h ?? null;
              return (
                <div key={p.id} onClick={() => selectPart(p.partId)}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: vr.size, transform: `translateY(${vr.start}px)` }}
                  className={`grid grid-cols-12 items-center px-2 border-b border-hairline/40 cursor-pointer ${p.partId === part?.partId ? 'bg-white border-l-2 border-l-reject font-bold' : 'hover:bg-workspace/80'}`}>
                  <span className={`col-span-5 truncate ${p.isFlagged ? 'text-reject' : ''}`}>{p.partId}</span>
                  <span className="col-span-4 text-right tabular-nums">{f(fc, 2)}</span>
                  <div className="col-span-3 flex justify-end"><Sparkline readings={p.readings} isFlagged={p.isFlagged} /></div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="h-[42px] border-b border-hairline px-3 flex items-center justify-between shrink-0">
          <span className="font-semibold text-main">Module B: 168h forecast from 0h/24h{mode === 'offline' ? ' (offline demo: linear extrapolation, not the ML model)' : ''}</span>
          <div className="flex items-center gap-3">
            <select value={yAxisMode} onChange={e => setYAxisMode(e.target.value as 'linear' | 'log')} className="bg-panel border border-hairline px-1.5 py-0.5"><option value="linear">Linear</option><option value="log">Log</option></select>
            <select value={filterMode} onChange={e => setFilterMode(e.target.value as typeof filterMode)} className="bg-panel border border-hairline px-1.5 py-0.5">
              <option value="all">All parts</option><option value="flagged">Flagged</option><option value="moduleB">Module B flag</option>
            </select>
            <label className="flex items-center gap-1"><input type="checkbox" checked={showPredicted} onChange={e => setShowPredicted(e.target.checked)} />forecast</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={showInterval} onChange={e => setShowInterval(e.target.checked)} />interval</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={showSafetySlope} onChange={e => setShowSafetySlope(e.target.checked)} />safety slope</label>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <DriftTracePlot parts={filtered} selectedPart={part} prediction={pred} staticLimit={staticLimit} yAxisMode={yAxisMode}
            showPredicted={showPredicted} showInterval={showInterval} showSafetySlope={showSafetySlope} onSelectPart={selectPart} />
        </div>
        <div className="h-[26px] border-t border-hairline bg-panel px-4 flex items-center gap-5 text-[11px] text-muted shrink-0">
          <span>● measured (filled = used by the model: 0h, 24h)</span>
          <span className="text-reject">- - forecast</span>
          <span>shaded: {pred?.intervalCoverageTarget ? `${Math.round(pred.intervalCoverageTarget * 100)}% prediction interval (conformal)` : 'no interval available'}</span>
          <span>- - lot safety slope</span>
        </div>
      </div>

      <div className="w-[300px] shrink-0 bg-panel overflow-y-auto p-3">
        {part && b ? (
          <>
            <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
              <span className="text-sm font-bold">{part.partId}</span>
              <span className={`px-2 py-0.5 text-[11px] font-semibold border ${b.flag ? 'border-reject text-reject bg-reject-bg' : 'border-accept text-accept bg-accept-bg'}`}>
                {b.flag ? 'Module B flag' : 'Within safety slope'}
              </span>
            </div>
            <div className="font-semibold mb-1">Leakage (driver of the decision: {b.driver ? PARAM_LABEL[b.driver] : '–'})</div>
            <div className="space-y-1 mb-3">
              <Row k="Reading 0h / 24h" v={`${f(part.readings[0], 2)} / ${f(part.readings[24], 2)} µA`} />
              <Row k="Forecast 168h" v={`${f(leak?.forecast168h, 2)} µA`} strong />
              <Row k="Prediction interval" v={leak?.intervalLower != null ? `${f(leak.intervalLower, 2)} – ${f(leak.intervalUpper, 2)} µA` : 'not available'} />
              <Row k="Predicted drift rate" v={`${f(leak?.predictedRate, 5)} µA/h`} strong={!!leak?.exceedsSafetySlope} />
              <Row k="Lot median rate" v={`${f(leak?.lotMedianRate, 5)} µA/h`} />
              <Row k="Lot spread" v={`${f(leak?.lotSpread, 5)} µA/h`} />
              <Row k="k (learned)" v={f(b.thresholdK, 2)} />
              <Row k="Lot safety slope" v={`${f(leak?.safetySlope, 5)} µA/h`} />
              <div className="text-[10px] text-muted font-sans">safety slope = lot median + k × lot spread (from this lot's 0h/24h-based forecasts)</div>
              <Row k="Measured 168h (after the fact)" v={part.readings[168] != null ? `${f(part.readings[168], 2)} µA` : '–'} />
              {staticLimit != null && <Row k="Forecast vs datasheet limit" v={leak?.forecast168h != null && leak.forecast168h >= staticLimit ? `REACHES ${staticLimit} µA` : `below ${staticLimit} µA`} />}
            </div>
            <div className="font-semibold mb-1">All parameters</div>
            <table className="w-full text-[11px]">
              <thead className="text-muted"><tr><th className="text-left">Param</th><th className="text-right">Fcst</th><th className="text-right">z</th><th className="text-right">Slope?</th></tr></thead>
              <tbody>
                {PARAMS.map(p => {
                  const d = b.perParam[p];
                  if (!d) return null;
                  return (
                    <tr key={p}><td>{PARAM_LABEL[p]}</td><td className="text-right">{f(d.forecast168h, 3)} {PARAM_UNIT[p]}</td>
                      <td className="text-right">{d.lotSpread && d.predictedRate != null && d.lotMedianRate != null ? ((d.predictedRate - d.lotMedianRate) / d.lotSpread).toFixed(2) : '–'}</td>
                      <td className={`text-right ${d.exceedsSafetySlope ? 'text-reject font-bold' : ''}`}>{d.exceedsSafetySlope ? 'exceeds' : 'ok'}</td></tr>
                  );
                })}
              </tbody>
            </table>
            {pred?.cvFold != null && <div className="text-[10px] text-muted font-sans mt-3">Out-of-fold prediction (lot fold {pred.cvFold}): the model never saw this lot.</div>}
          </>
        ) : (
          <div className="text-muted p-4 text-center">{part?.insufficientData ? 'Insufficient data: no Module B forecast.' : 'Select a part.'}</div>
        )}
      </div>
    </div>
  );
};

const Row: React.FC<{ k: string; v: string; strong?: boolean }> = ({ k, v, strong }) => (
  <div className="flex justify-between gap-2"><span className="text-muted font-sans">{k}</span><span className={strong ? 'font-bold text-reject' : 'text-main'}>{v}</span></div>
);
