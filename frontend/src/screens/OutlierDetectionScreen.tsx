import React, { useState, useMemo } from 'react';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { calculateMedian, calculateMAD, calculateRobustZ } from '../lib/analytics/robustZ';

export const OutlierDetectionScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, selectPart, activeLot } = useStore();

  const [activeMethod, setActiveMethod] = useState<'Robust Z-score' | 'Isolation Forest' | 'Mahalanobis'>('Robust Z-score');
  const [sensitivity, setSensitivity] = useState<number>(1.0);
  const [showOnlyFlagged, setShowOnlyFlagged] = useState<boolean>(false);

  // Selected part
  const selectedPart = useMemo(() => {
    return parts.find(p => p.partId === selectedPartId) || parts[0] || null;
  }, [parts, selectedPartId]);

  const selectedPrediction = useMemo(() => {
    if (!selectedPart) return null;
    return predictions[selectedPart.partId] || null;
  }, [predictions, selectedPart]);

  // Dynamic live calculation of outlier thresholds based on sensitivity
  const {
    median168h,
    mad168h,
    scaledMad,
    zThreshold,
    ifThreshold,
    mdThreshold,
    flaggedPartsSet,
    histogramBins,
  } = useMemo(() => {
    const vals = parts.map(p => p.readings[168] || p.current168h);
    const med = calculateMedian(vals);
    const mad = calculateMAD(vals, med);
    const smad = Math.max(mad * 1.4826, 1e-6);

    // Thresholds scaled inversely or directly with sensitivity
    const zThresh = 3.0 / sensitivity;
    const ifThresh = Math.max(0.4, 0.65 - (sensitivity - 1.0) * 0.15);
    const mdThresh = 3.5 / sensitivity;

    const flagged = new Set<string>();

    for (const p of parts) {
      const pred = predictions[p.partId];
      if (!pred) continue;

      let isOut = false;
      if (activeMethod === 'Robust Z-score') {
        const z = calculateRobustZ(p.readings[168] || 0, med, mad);
        if (Math.abs(z) >= zThresh) isOut = true;
      } else if (activeMethod === 'Isolation Forest') {
        if (pred.isolationForestScore >= ifThresh) isOut = true;
      } else if (activeMethod === 'Mahalanobis') {
        if (pred.mahalanobisDistance >= mdThresh) isOut = true;
      }

      if (isOut) flagged.add(p.partId);
    }

    // Build log histogram bins
    const maxVal = Math.max(activeLot?.staticLimitUa ?? 50, d3.max(vals) || 60);
    const binGen = d3
      .bin<number, number>()
      .domain([0.1, maxVal * 1.2])
      .thresholds(30);
    const bins = binGen(vals);

    return {
      median168h: med,
      mad168h: mad,
      scaledMad: smad,
      zThreshold: zThresh,
      ifThreshold: ifThresh,
      mdThreshold: mdThresh,
      flaggedPartsSet: flagged,
      histogramBins: bins,
    };
  }, [parts, predictions, activeMethod, sensitivity, activeLot]);

  // Method flags for selected part
  const selectedMethods = useMemo(() => {
    if (!selectedPart || !selectedPrediction) return [];

    const zScore = Math.abs(calculateRobustZ(selectedPart.readings[168] || 0, median168h, mad168h));
    const ifScore = selectedPrediction.isolationForestScore;
    const mdScore = selectedPrediction.mahalanobisDistance;

    return [
      {
        method: 'Robust Z-score',
        score: zScore.toFixed(1),
        flag: zScore >= zThreshold,
      },
      {
        method: 'Isolation Forest',
        score: ifScore.toFixed(2),
        flag: ifScore >= ifThreshold,
      },
      {
        method: 'Mahalanobis',
        score: mdScore.toFixed(1),
        flag: mdScore >= mdThreshold,
      },
    ];
  }, [selectedPart, selectedPrediction, median168h, mad168h, zThreshold, ifThreshold, mdThreshold]);

  const staticLimit = activeLot?.staticLimitUa ?? 50.0;

  return (
    <div className="w-full h-full flex bg-workspace overflow-hidden divide-x divide-hairline">
      {/* LEFT: Distribution Chart with Rug Plot */}
      <div className="flex-1 min-w-0 flex flex-col p-4 overflow-hidden">
        {/* Title & Metadata Strip */}
        <div className="flex items-center justify-between pb-3 border-b border-hairline mb-3 font-mono text-xs">
          <div>
            <span className="font-bold text-sm text-main">
              Iddq Distribution with Outlier Detection (168h)
            </span>
            <div className="text-[11px] text-muted mt-0.5">
              Active Method:{' '}
              <strong className="text-main font-semibold">{activeMethod}</strong> (Sensitivity:{' '}
              {sensitivity.toFixed(1)}x)
            </div>
          </div>
          <div className="text-right text-[11px] text-muted">
            <span>
              Flagged Outliers:{' '}
              <strong className="text-reject font-bold">{flaggedPartsSet.size}</strong> /{' '}
              {parts.length} parts
            </span>
          </div>
        </div>

        {/* Histogram + Rug Plot Canvas/SVG */}
        <div className="flex-1 min-h-0 relative bg-workspace border border-hairline p-4">
          <svg className="w-full h-full overflow-visible">
            {histogramBins.length > 0 && (() => {
              const w = 620;
              const h = 260;
              const maxCount = d3.max(histogramBins, b => b.length) || 1;

              const xSc = d3.scaleLog().clamp(true).domain([0.1, 1000]).range([50, w]);
              const ySc = d3.scaleLinear().domain([0, maxCount]).range([h, 20]);

              const medX = xSc(median168h);
              const madLowerX = xSc(Math.max(0.1, median168h - 2 * scaledMad));
              const madUpperX = xSc(median168h + 2 * scaledMad);
              const limitX = xSc(staticLimit);

              return (
                <g>
                  {/* Robust MAD Range Shading */}
                  <rect
                    x={madLowerX}
                    y={20}
                    width={Math.max(1, madUpperX - madLowerX)}
                    height={h - 20}
                    fill="#2E7D4F"
                    fillOpacity={0.06}
                  />

                  {/* Histogram Bars */}
                  {histogramBins.map((bin, i) => {
                    const x0 = xSc(Math.max(0.1, bin.x0 || 0.1));
                    const x1 = xSc(Math.max(0.1, bin.x1 || 0.1));
                    const bw = Math.max(1.5, x1 - x0 - 1);
                    const bh = h - ySc(bin.length);

                    return (
                      <rect
                        key={`bar-${i}`}
                        x={x0}
                        y={ySc(bin.length)}
                        width={bw}
                        height={bh}
                        fill="#B0B7BC"
                        opacity={0.8}
                      />
                    );
                  })}

                  {/* Rug Plot (Individual ticks along baseline) */}
                  <g transform={`translate(0, ${h + 4})`}>
                    {parts.map(p => {
                      const v = p.readings[168] || 0;
                      const x = xSc(Math.max(0.1, v));
                      const isFlagged = flaggedPartsSet.has(p.partId);
                      const isSel = p.partId === selectedPartId;

                      return (
                        <line
                          key={`rug-${p.partId}`}
                          x1={x}
                          x2={x}
                          y1={0}
                          y2={isSel ? 14 : isFlagged ? 10 : 6}
                          stroke={isSel ? '#D63A2F' : isFlagged ? '#D63A2F' : '#8A949B'}
                          strokeWidth={isSel ? 2 : 1}
                          strokeOpacity={isSel ? 1 : isFlagged ? 0.9 : 0.4}
                          className="cursor-pointer"
                          onClick={() => selectPart(p.partId)}
                        />
                      );
                    })}
                  </g>

                  {/* Median Line */}
                  <line x1={medX} x2={medX} y1={20} y2={h} stroke="#5F6B73" strokeWidth={1.5} strokeDasharray="3 2" />
                  <text x={medX} y={15} textAnchor="middle" className="text-[10px] font-mono fill-muted">
                    Median: {median168h.toFixed(2)} µA
                  </text>

                  {/* MAD Range Annotation */}
                  <text x={(madLowerX + madUpperX) / 2} y={32} textAnchor="middle" className="text-[9px] font-mono fill-accept">
                    Robust MAD range ({median168h.toFixed(1)} ± 2 MAD)
                  </text>

                  {/* Static Limit Line */}
                  <line x1={limitX} x2={limitX} y1={20} y2={h} stroke="#D63A2F" strokeWidth={1.5} strokeDasharray="4 2" />
                  <text x={limitX} y={15} textAnchor="middle" className="text-[10px] font-mono fill-reject font-bold">
                    Static limit: {staticLimit} µA
                  </text>

                  {/* Selected Part Marker & Callout */}
                  {selectedPart && (() => {
                    const selV = selectedPart.readings[168] || 0;
                    const selX = xSc(Math.max(0.1, selV));
                    const isFlagged = flaggedPartsSet.has(selectedPart.partId);

                    return (
                      <g>
                        <circle cx={selX} cy={h} r={5} fill="#D63A2F" stroke="#FFFFFF" strokeWidth={2} />
                        <line x1={selX} x2={selX + 25} y1={h} y2={h - 35} stroke="#D63A2F" strokeWidth={1} />
                        <g transform={`translate(${selX + 25}, ${h - 50})`}>
                          <rect width={110} height={42} fill="#FFFFFF" stroke="#D63A2F" strokeWidth={1} rx={2} />
                          <text x={6} y={14} className="font-mono text-xs font-bold fill-reject">
                            {selectedPart.partId}
                          </text>
                          <text x={6} y={26} className="font-mono text-[11px] fill-main">
                            {selV.toFixed(1)} µA{' '}
                            <tspan className="text-reject">
                              ({Math.abs(calculateRobustZ(selV, median168h, mad168h)).toFixed(1)}σ)
                            </tspan>
                          </text>
                          <text x={6} y={36} className="font-mono text-[9px] fill-muted">
                            {isFlagged ? 'Flagged Outlier' : 'Nominal'}
                          </text>
                        </g>
                      </g>
                    );
                  })()}

                  {/* X Axis Log Scale Labels */}
                  {[0.1, 1, 10, 100, 1000].map(val => (
                    <text key={`x-lbl-${val}`} x={xSc(val)} y={h + 26} textAnchor="middle" className="text-[10px] font-mono fill-muted">
                      {val}
                    </text>
                  ))}
                  <text x={w / 2} y={h + 38} textAnchor="middle" className="text-xs font-sans fill-muted">
                    Iddq (µA) [Log Scale]
                  </text>
                </g>
              );
            })()}
          </svg>
        </div>
      </div>

      {/* RIGHT: Detection Methods Table & Sensitivity Controls */}
      <div className="w-[310px] shrink-0 bg-panel p-4 flex flex-col font-mono text-xs overflow-y-auto">
        {/* Method Comparison Table for Selected Part */}
        <div className="pb-3 border-b border-hairline mb-4">
          <div className="font-sans font-bold text-xs text-main mb-2">
            Detection Methods ({selectedPart?.partId || 'None'})
          </div>
          <table className="w-full text-left border-collapse border border-hairline text-xs bg-workspace">
            <thead>
              <tr className="h-[26px] bg-panel border-b border-hairline text-muted">
                <th className="px-2 font-medium">Method</th>
                <th className="px-2 text-right font-medium">Score</th>
                <th className="px-2 text-center font-medium">Flag</th>
              </tr>
            </thead>
            <tbody>
              {selectedMethods.map((m, i) => (
                <tr key={`meth-${i}`} className="h-[28px] border-b border-hairline/40">
                  <td className="px-2 font-sans">{m.method}</td>
                  <td className="px-2 text-right tabular-nums">{m.score}</td>
                  <td className="px-2 text-center font-bold">
                    {m.flag ? (
                      <span className="text-reject">✓</span>
                    ) : (
                      <span className="text-muted">–</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Live Controls */}
        <div className="space-y-4">
          <div>
            <label className="block font-sans text-xs text-muted mb-1 font-medium">
              Primary Detection Engine:
            </label>
            <div className="space-y-1.5 font-sans">
              {(['Robust Z-score', 'Isolation Forest', 'Mahalanobis'] as const).map(meth => (
                <label key={meth} className="flex items-center gap-2 cursor-pointer text-xs">
                  <input
                    type="radio"
                    name="method"
                    checked={activeMethod === meth}
                    onChange={() => setActiveMethod(meth)}
                    className="accent-toprail"
                  />
                  <span className={activeMethod === meth ? 'font-semibold text-main' : 'text-muted'}>
                    {meth}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Sensitivity Slider */}
          <div>
            <div className="flex justify-between items-center mb-1 font-sans">
              <span className="text-xs text-muted font-medium">Sensitivity:</span>
              <span className="font-mono text-xs font-bold text-main">
                {sensitivity.toFixed(1)}x
              </span>
            </div>
            <input
              type="range"
              min={0.5}
              max={2.5}
              step={0.1}
              value={sensitivity}
              onChange={e => setSensitivity(Number(e.target.value))}
              className="w-full accent-toprail cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-muted font-sans mt-0.5">
              <span>0.5x (Conservative)</span>
              <span>1.0x</span>
              <span>2.5x (Aggressive)</span>
            </div>
          </div>

          {/* Checkbox: Show only flagged parts */}
          <div>
            <label className="flex items-center gap-2 cursor-pointer font-sans text-xs">
              <input
                type="checkbox"
                checked={showOnlyFlagged}
                onChange={e => setShowOnlyFlagged(e.target.checked)}
                className="accent-toprail"
              />
              <span className="text-main">Show only flagged parts</span>
            </label>
          </div>

          {/* Flagged parts mini-list */}
          <div className="pt-2 border-t border-hairline">
            <span className="font-sans text-[11px] text-muted block mb-1.5 font-medium">
              Flagged Parts List ({flaggedPartsSet.size}):
            </span>
            <div className="max-h-[160px] overflow-y-auto border border-hairline bg-workspace divide-y divide-hairline/40">
              {Array.from(flaggedPartsSet).map(id => (
                <div
                  key={`flagged-${id}`}
                  onClick={() => selectPart(id)}
                  className={`px-2 py-1 flex justify-between cursor-pointer text-xs ${
                    id === selectedPartId ? 'bg-panel font-bold text-reject' : 'hover:bg-panel/40'
                  }`}
                >
                  <span>{id}</span>
                  <span className="text-[10px] text-reject uppercase">Flagged</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
