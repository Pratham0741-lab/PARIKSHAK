import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';
import { PARAM_LABEL, PARAM_UNIT, Param, Part, Prediction } from '../../data/types';

interface DriftTracePlotProps {
  /** Parameter plotted (the lot's parameter); part.readings already hold its values. */
  param: Param;
  parts: Part[];
  selectedPart: Part | null;
  prediction: Prediction | null;
  staticLimit: number | null;
  yAxisMode: 'linear' | 'log';
  showPredicted: boolean;
  showInterval: boolean;
  showSafetySlope: boolean;
  onSelectPart: (partId: string) => void;
}

const INTERVALS = [0, 24, 96, 168];

/** Leakage trajectories for the lot; forecast, 90% interval and lot safety slope for the selected part (all from the backend). */
export const DriftTracePlot: React.FC<DriftTracePlotProps> = ({
  param, parts, selectedPart, prediction, staticLimit, yAxisMode, showPredicted, showInterval, showSafetySlope, onSelectPart,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const [dim, setDim] = useState({ width: 700, height: 420 });
  useEffect(() => {
    const onResize = () => ref.current && ref.current.clientWidth > 0 && setDim({ width: ref.current.clientWidth, height: ref.current.clientHeight });
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const m = { top: 24, right: 30, bottom: 40, left: 55 };
  const drift = prediction?.moduleB?.perParam[param] ?? null;

  const { x, y, ticks } = useMemo(() => {
    let maxY = staticLimit != null ? staticLimit * 1.15 : 1;
    for (const p of parts) for (const t of INTERVALS) maxY = Math.max(maxY, (p.readings[t] ?? 0) * 1.05);
    if (drift?.intervalUpper != null) maxY = Math.max(maxY, drift.intervalUpper * 1.05);
    const xs = d3.scaleLinear().domain([0, 168]).range([m.left, dim.width - m.right]);
    const ys = yAxisMode === 'log'
      ? d3.scaleLog().clamp(true).domain([0.5, Math.max(maxY, 10)]).range([dim.height - m.bottom, m.top])
      : d3.scaleLinear().domain([0, maxY]).range([dim.height - m.bottom, m.top]);
    return { x: xs, y: ys, ticks: ys.ticks(6) };
  }, [parts, drift, staticLimit, yAxisMode, dim]); // eslint-disable-line react-hooks/exhaustive-deps

  const line = d3.line<{ t: number; v: number }>().x(d => x(d.t)).y(d => y(Math.max(0.5, d.v)));
  const pts = (p: Part) => INTERVALS.map(t => ({ t, v: p.readings[t] })).filter((d): d is { t: number; v: number } => d.v != null);

  const v0 = selectedPart?.readings[0] ?? null;
  const v24 = selectedPart?.readings[24] ?? null;

  return (
    <div ref={ref} className="w-full h-full relative select-none bg-workspace">
      <svg width={dim.width} height={dim.height} className="block">
        {ticks.map(t => (
          <g key={t}>
            <line x1={m.left} x2={dim.width - m.right} y1={y(t)} y2={y(t)} stroke="#E5E8EB" />
            <text x={m.left - 6} y={y(t) + 3} textAnchor="end" className="text-[10px] font-mono fill-muted">{t}</text>
          </g>
        ))}
        {INTERVALS.map(t => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={m.top} y2={dim.height - m.bottom} stroke={t === 24 ? '#8A949B' : '#E5E8EB'} strokeDasharray={t === 24 ? '2 2' : undefined} />
            <text x={x(t)} y={dim.height - m.bottom + 16} textAnchor="middle" className="text-[10px] font-mono fill-muted">{t}h{t === 24 ? ' (decision)' : ''}</text>
          </g>
        ))}
        <text transform="rotate(-90)" x={-(dim.height / 2)} y={14} textAnchor="middle" className="text-xs font-sans fill-muted">{PARAM_LABEL[param]} ({PARAM_UNIT[param]})</text>
        {staticLimit != null && (
          <g>
            <line x1={m.left} x2={dim.width - m.right} y1={y(staticLimit)} y2={y(staticLimit)} stroke="#5F6B73" strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={m.left + 6} y={y(staticLimit) - 4} className="text-[10px] font-mono fill-muted">Static limit {staticLimit} {PARAM_UNIT[param]}</text>
          </g>
        )}
        {parts.map(p => p.id === selectedPart?.id ? null : (
          <path key={p.id} d={line(pts(p)) || ''} fill="none" stroke={p.isFlagged ? '#E0A39E' : '#B0B7BC'} strokeOpacity={0.4}
            className="cursor-pointer" onClick={() => onSelectPart(p.partId)} />
        ))}
        {showSafetySlope && v0 != null && drift?.safetySlope != null && (
          <g>
            <line x1={x(0)} y1={y(v0)} x2={x(168)} y2={y(v0 + drift.safetySlope * 168)} stroke="#1C2328" strokeDasharray="4 3" />
            <text x={x(168) - 4} y={y(v0 + drift.safetySlope * 168) + 14} textAnchor="end" className="text-[10px] font-mono fill-main">
              lot safety slope {drift.safetySlope.toFixed(4)} {PARAM_UNIT[param]}/h
            </text>
          </g>
        )}
        {showInterval && v24 != null && drift?.intervalLower != null && drift.intervalUpper != null && (
          <path d={`M ${x(24)} ${y(v24)} L ${x(168)} ${y(drift.intervalUpper)} L ${x(168)} ${y(Math.max(0.5, drift.intervalLower))} Z`} fill="#D63A2F" fillOpacity={0.1} stroke="#D63A2F" strokeOpacity={0.3} />
        )}
        {showPredicted && v24 != null && drift?.forecast168h != null && (
          <path d={line([{ t: 24, v: v24 }, { t: 168, v: drift.forecast168h }]) || ''} fill="none" stroke="#D63A2F" strokeWidth={2} strokeDasharray="4 3" />
        )}
        {selectedPart && (
          <g>
            <path d={line(pts(selectedPart)) || ''} fill="none" stroke="#1C2328" strokeWidth={2.5} />
            {pts(selectedPart).map(pt => <circle key={pt.t} cx={x(pt.t)} cy={y(Math.max(0.5, pt.v))} r={4} fill={pt.t <= 24 ? '#1C2328' : '#FFFFFF'} stroke="#1C2328" strokeWidth={1.5} />)}
          </g>
        )}
      </svg>
    </div>
  );
};
