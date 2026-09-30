import React, { useEffect } from 'react';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { CostCurve } from '../data/types';

const pct = (x: number) => `${(100 * x).toFixed(1)}%`;

/** Held-out performance computed by the backend from out-of-fold predictions and ground truth. */
export const ModelPerformanceScreen: React.FC = () => {
  const { metrics, costCurves, loadMetrics, mode } = useStore();
  useEffect(() => {
    loadMetrics();
  }, [loadMetrics, mode]);

  if (mode === 'offline') {
    return (
      <div className="p-6 font-mono text-xs text-muted">
        Performance metrics are not available in offline demo mode. They require labelled, held-out evaluation, which only the
        backend performs (no labels exist in the frontend). Switch the data source to the backend.
      </div>
    );
  }
  if (!metrics) return <div className="p-6 font-mono text-xs text-muted">Loading metrics from the backend…</div>;
  const m = metrics;

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-y-auto p-4 font-mono text-xs">
      <div className="pb-2 border-b border-hairline mb-4">
        <div className="font-bold text-sm text-main">Model performance (held-out)</div>
        <div className="text-[11px] text-muted font-sans mt-0.5">{m.protocol}</div>
        <div className="text-[11px] text-muted font-sans">
          Scored parts: <strong className="text-main">{m.totalComponents}</strong> ({m.outOfFold} out-of-fold, {m.inSample} in-sample) ·
          unlabelled parts excluded: {m.excludedWithoutGroundTruth} · thresholds: A {m.thresholds?.threshold_a?.toFixed(3) ?? 'off'}, B k {m.thresholds?.threshold_b?.toFixed(3) ?? 'off'} ({m.thresholds?.strategy ?? '–'})
        </div>
      </div>

      <div className="grid grid-cols-8 gap-4 p-3 bg-panel border border-hairline mb-4">
        <Stat label="Recall" value={pct(m.recall)} />
        <Stat label="Precision" value={pct(m.precision)} />
        <Stat label="F2 (β=2)" value={pct(m.f2)} />
        <Stat label="Escapes (FN)" value={String(m.fn)} bad />
        <Stat label={`Weighted cost (FN×${m.fnCost} + FP×${m.fpCost})`} value={m.weightedCost.toFixed(0)} />
        <Stat label="Cost per 1,000 parts" value={m.costPer1000.toFixed(0)} />
        <Stat label="168h leakage MAE" value={`${m.maeLeakage.toFixed(3)} µA`} />
        <Stat label="Linear baseline MAE" value={`${m.linearMaeLeakage.toFixed(3)} µA`} />
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-4 border border-hairline p-3">
          <div className="font-sans font-bold mb-2">Confusion matrix (flag = REVIEW or REJECT)</div>
          <table className="w-full text-center border-collapse border border-hairline">
            <thead><tr className="bg-panel text-muted"><th /><th className="border-l border-hairline">Flagged</th><th className="border-l border-hairline">Passed</th></tr></thead>
            <tbody>
              <tr className="border-t border-hairline h-8"><td className="bg-panel text-muted text-left px-2">Defective</td><td className="font-bold">{m.tp}</td><td className="font-bold bg-reject-bg text-reject">{m.fn} (escape)</td></tr>
              <tr className="border-t border-hairline h-8"><td className="bg-panel text-muted text-left px-2">Good</td><td>{m.fp}</td><td className="text-accept font-semibold">{m.tn}</td></tr>
            </tbody>
          </table>
          <div className="text-[10px] text-muted font-sans mt-2">
            Cost of flagging every part would be {(m.fp + m.tn) * m.fpCost}; of flagging none {(m.tp + m.fn) * m.fnCost}.
          </div>
        </div>
        <CurvePanel title="Module A threshold vs weighted cost" curve={costCurves.A} />
        <CurvePanel title="Module B k vs weighted cost" curve={costCurves.B} />
      </div>
      <div className="text-[10px] text-muted font-sans mt-3">
        Curves sweep one module's threshold over the persisted out-of-fold scores with the other at its chosen value (diagnostic).
        Operational thresholds were chosen on inner cross-validation of the training lots, never on these curves.
        Full protocol and train-vs-held-out comparison: SIH26170_EVALUATION_REPORT.md.
      </div>
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string; bad?: boolean }> = ({ label, value, bad }) => (
  <div>
    <span className="text-muted text-[11px] font-sans block mb-0.5">{label}</span>
    <span className={`text-lg font-bold tabular-nums ${bad ? 'text-reject' : 'text-main'}`}>{value}</span>
  </div>
);

const CurvePanel: React.FC<{ title: string; curve: CostCurve | null }> = ({ title, curve }) => {
  const w = 340, h = 160;
  if (!curve || curve.points.length === 0) return <div className="col-span-4 border border-hairline p-3 text-muted">{title}: no data</div>;
  const pts = curve.points;
  const x = d3.scaleLinear().domain(d3.extent(pts, p => p.threshold) as [number, number]).range([40, w - 10]);
  const y = d3.scaleLinear().domain([0, d3.max(pts, p => p.weightedCost) ?? 1]).range([h - 20, 10]);
  const yr = d3.scaleLinear().domain([0, 1]).range([h - 20, 10]);
  const best = pts.reduce((a, b) => (b.weightedCost < a.weightedCost ? b : a));
  return (
    <div className="col-span-4 border border-hairline p-3">
      <div className="font-sans font-bold mb-1">{title}</div>
      <svg width={w} height={h}>
        {y.ticks(4).map(t => <g key={t}><line x1={40} x2={w - 10} y1={y(t)} y2={y(t)} stroke="#E5E8EB" /><text x={36} y={y(t) + 3} textAnchor="end" className="text-[9px] fill-muted">{t}</text></g>)}
        <path d={d3.line<typeof pts[number]>().x(p => x(p.threshold)).y(p => y(p.weightedCost))(pts) || ''} stroke="#1C2328" strokeWidth={2} fill="none" />
        <path d={d3.line<typeof pts[number]>().x(p => x(p.threshold)).y(p => yr(p.recall))(pts) || ''} stroke="#2E8B57" strokeDasharray="3 2" fill="none" />
        {curve.chosenThreshold != null && x(curve.chosenThreshold) >= 40 && x(curve.chosenThreshold) <= w - 10 && (
          <line x1={x(curve.chosenThreshold)} x2={x(curve.chosenThreshold)} y1={10} y2={h - 20} stroke="#D63A2F" />
        )}
        {x.ticks(5).map(t => <text key={t} x={x(t)} y={h - 5} textAnchor="middle" className="text-[9px] fill-muted">{t}</text>)}
      </svg>
      <div className="text-[10px] text-muted font-sans">
        — cost, - - recall; red: chosen {curve.chosenThreshold == null ? '(module off)' : curve.chosenThreshold.toFixed(3)}. Lowest cost on this curve: {best.weightedCost} at {best.threshold.toFixed(3)} (FN {best.fn}, FP {best.fp}).
      </div>
    </div>
  );
};
