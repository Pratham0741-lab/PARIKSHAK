import React, { useState, useMemo } from 'react';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { findSimilarParts } from '../lib/analytics/explainability';
import { StatusMarker } from '../components/common/StatusMarker';

export const ComponentDetailScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, activeLot } = useStore();
  const [activeTab, setActiveTab] = useState<'Overview' | 'Explainability' | 'Similar Parts'>('Overview');

  const selectedPart = useMemo(() => {
    return parts.find(p => p.partId === selectedPartId) || parts[0] || null;
  }, [parts, selectedPartId]);

  const selectedPrediction = useMemo(() => {
    if (!selectedPart) return null;
    return predictions[selectedPart.partId] || null;
  }, [predictions, selectedPart]);

  // Dynamic similar parts calculation
  const similarParts = useMemo(() => {
    if (!selectedPart) return [];
    return findSimilarParts(selectedPart, parts, 5);
  }, [selectedPart, parts]);

  const staticLimit = activeLot?.staticLimitUa ?? 50.0;

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden">
      {/* 1. Header Strip */}
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-6">
          <span className="font-bold text-sm text-main">
            Component: {selectedPart?.partId}
          </span>
          <div className="flex space-x-1">
            {(['Overview', 'Explainability', 'Similar Parts'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1 font-sans text-xs border ${
                  activeTab === tab
                    ? 'bg-toprail text-white border-toprail font-medium'
                    : 'bg-workspace text-muted border-hairline hover:text-main'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        <div className="text-muted text-xs">
          Lot: <strong className="text-main">{activeLot?.lotNumber}</strong>
        </div>
      </div>

      {/* 2. Main Two-Row Layout */}
      <div className="flex-1 min-h-0 p-4 flex flex-col gap-4 overflow-y-auto">
        {/* UPPER ROW: Mini Trajectory (Left) + Feature Contributions (Right) */}
        <div className="h-[210px] grid grid-cols-12 gap-4 shrink-0">
          {/* Mini Trajectory */}
          <div className="col-span-5 border border-hairline p-3 bg-workspace flex flex-col">
            <span className="font-mono text-xs font-bold text-main mb-2">
              Iddq Trajectory ({selectedPart?.partId})
            </span>
            <div className="flex-1 min-h-0 relative">
              {selectedPart && (() => {
                const intervals = [0, 24, 96, 168];
                const pts = intervals.map(t => ({ t, v: selectedPart.readings[t] || 0 }));
                const w = 260;
                const h = 130;
                const maxV = Math.max(staticLimit * 1.1, d3.max(pts, d => d.v) || 50);

                const xSc = d3.scaleLinear().domain([0, 168]).range([35, w - 15]);
                const ySc = d3.scaleLinear().domain([0, maxV]).range([h - 20, 10]);

                const lineGen = d3
                  .line<{ t: number; v: number }>()
                  .x(d => xSc(d.t))
                  .y(d => ySc(d.v));

                return (
                  <svg className="w-full h-full overflow-visible">
                    {/* Gridlines */}
                    {intervals.map(t => (
                      <g key={`t-${t}`}>
                        <line x1={xSc(t)} x2={xSc(t)} y1={10} y2={h - 20} stroke="#E5E8EB" strokeWidth={1} />
                        <text x={xSc(t)} y={h - 5} textAnchor="middle" className="text-[9px] font-mono fill-muted">
                          {t}h
                        </text>
                      </g>
                    ))}

                    {/* Static Limit Line */}
                    <line x1={35} x2={w - 15} y1={ySc(staticLimit)} y2={ySc(staticLimit)} stroke="#D63A2F" strokeDasharray="3 2" />
                    <text x={38} y={ySc(staticLimit) - 4} className="text-[8px] font-mono fill-reject">
                      Limit {staticLimit} µA
                    </text>

                    {/* Path */}
                    <path d={lineGen(pts) || ''} fill="none" stroke="#D63A2F" strokeWidth={2} />

                    {/* Points */}
                    {pts.map((pt, i) => (
                      <circle key={`pt-${i}`} cx={xSc(pt.t)} cy={ySc(pt.v)} r={3.5} fill="#D63A2F" stroke="#FFFFFF" strokeWidth={1} />
                    ))}
                  </svg>
                );
              })()}
            </div>
          </div>

          {/* Feature Contributions (SHAP / Tree Attribution) */}
          <div className="col-span-7 border border-hairline p-3 bg-workspace flex flex-col font-mono text-xs">
            <span className="font-sans font-bold text-xs text-main mb-2">
              Feature Contributions (SHAP / Tree Attribution)
            </span>
            <div className="flex-1 min-h-0 space-y-2 py-1">
              {selectedPrediction?.featureContributions.map(fc => {
                const isPositive = fc.value >= 0;
                const absVal = Math.min(3.0, Math.abs(fc.value));
                const barWidthPct = (absVal / 3.0) * 100;

                return (
                  <div key={fc.feature} className="grid grid-cols-12 items-center text-xs">
                    <span className="col-span-3 text-muted truncate font-sans text-xs">{fc.feature}</span>
                    <div className="col-span-7 flex items-center h-4 bg-panel relative border border-hairline">
                      <div className="w-1/2 h-full border-r border-hairline" />
                      {isPositive ? (
                        <div
                          className="h-full bg-reject"
                          style={{
                            width: `${barWidthPct / 2}%`,
                            position: 'absolute',
                            left: '50%',
                          }}
                        />
                      ) : (
                        <div
                          className="h-full bg-accept"
                          style={{
                            width: `${barWidthPct / 2}%`,
                            position: 'absolute',
                            right: '50%',
                          }}
                        />
                      )}
                    </div>
                    <span
                      className={`col-span-2 text-right font-bold tabular-nums ${
                        isPositive ? 'text-reject' : 'text-accept'
                      }`}
                    >
                      {isPositive ? `+${fc.value.toFixed(2)}` : fc.value.toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* LOWER ROW: QA Justification (Left) + Similar Parts (Right) */}
        <div className="flex-1 min-h-[200px] grid grid-cols-12 gap-4">
          {/* QA Justification (Monospace Lab Note) */}
          <div className="col-span-6 border border-hairline p-3 bg-workspace flex flex-col">
            <span className="font-mono text-xs font-bold text-main mb-2">
              QA Justification (auto-generated)
            </span>
            <div className="flex-1 bg-panel border border-hairline p-3 font-mono text-[11px] leading-relaxed text-main select-text">
              {selectedPrediction?.notes}
            </div>
          </div>

          {/* Similar Past Parts Table */}
          <div className="col-span-6 border border-hairline p-3 bg-workspace flex flex-col font-mono text-xs">
            <span className="font-sans font-bold text-xs text-main mb-2">
              Similar Past Parts (Nearest Neighbors)
            </span>
            <div className="flex-1 border border-hairline overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="h-[26px] bg-panel border-b border-hairline text-muted font-bold text-[11px]">
                    <th className="px-2">Part ID</th>
                    <th className="px-2">Lot ID</th>
                    <th className="px-2 text-right">Final Iddq</th>
                    <th className="px-2">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {similarParts.map((sp, idx) => (
                    <tr key={`sim-${idx}`} className="h-[28px] border-b border-hairline/40 hover:bg-panel/40">
                      <td className="px-2 font-semibold text-main">{sp.partId}</td>
                      <td className="px-2 text-muted">{sp.lotId}</td>
                      <td className="px-2 text-right tabular-nums">{sp.finalIddq.toFixed(1)} µA</td>
                      <td className="px-2">
                        <StatusMarker status={sp.outcome === 'Passed' ? 'Accept' : 'Reject'} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
