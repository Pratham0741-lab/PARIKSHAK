import React, { useMemo, useState } from 'react';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { PARAMS, PARAM_LABEL, PARAM_UNIT, lotLimit, lotParam } from '../data/types';

type Metric = 'score' | 'mahalanobis' | 'isolation';
const METRIC_LABEL: Record<Metric, string> = {
  score: 'Decision score: sum of positive robust z vs own lot',
  mahalanobis: 'Mahalanobis distance (diagnostic)',
  isolation: 'Isolation Forest score (diagnostic)',
};

export const OutlierDetectionScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, selectPart, config, mode, activeLot } = useStore();
  const param = lotParam(activeLot);
  const [metric, setMetric] = useState<Metric>('score');
  const [whatIf, setWhatIf] = useState<number | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const staticLimit = lotLimit(activeLot, param, config?.datasheetLimits);

  const rows = useMemo(() => parts.map(p => {
    const a = predictions[p.partId]?.moduleA ?? null;
    const val = a == null ? null : metric === 'score' ? a.score : metric === 'mahalanobis' ? a.mahalanobis : a.isolation;
    const passesStatic = staticLimit == null ? null : [0, 24].every(t => (p.readings[t] ?? 0) <= staticLimit);
    return { p, a, val, passesStatic };
  }), [parts, predictions, metric, staticLimit]);

  const threshold = rows.find(r => r.a)?.a?.threshold ?? null; // learned (same for every part of a run)
  const effective = whatIf ?? threshold;
  const values = rows.map(r => r.val).filter((v): v is number => v != null);
  const whatIfCount = effective == null || metric !== 'score' ? null : rows.filter(r => r.a && r.a.score >= effective).length;

  const sel = rows.find(r => r.p.partId === selectedPartId) ?? null;
  const listed = rows.filter(r => r.a && (!onlyFlagged || r.a.flag)).sort((x, y) => (y.a!.score - x.a!.score));

  const w = 560, h = 180;
  const x = d3.scaleLinear().domain([0, (d3.max(values) ?? 1) * 1.05]).range([30, w - 10]);
  const bins = d3.bin<number, number>().domain(x.domain() as [number, number]).thresholds(40)(values);
  const y = d3.scaleLinear().domain([0, d3.max(bins, b => b.length) ?? 1]).range([h - 20, 10]);

  return (
    <div className="w-full h-full flex bg-workspace overflow-hidden divide-x divide-hairline font-mono text-xs">
      <div className="flex-1 min-w-0 flex flex-col p-4 overflow-hidden">
        <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
          <div>
            <div className="font-bold text-sm text-main">Module A: lot-relative outlier detection</div>
            <div className="text-[11px] text-muted font-sans">
              Each part is compared with its own lot's median and MAD (0h/24h mean). Threshold learned by FN-weighted cost minimisation{mode === 'offline' ? ' (offline demo: fixed demo rule)' : ''}.
            </div>
          </div>
          <select value={metric} onChange={e => setMetric(e.target.value as Metric)} className="bg-panel border border-hairline px-2 py-0.5">
            {(Object.keys(METRIC_LABEL) as Metric[]).map(m => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
          </select>
        </div>

        <svg width={w} height={h} className="shrink-0">
          {bins.map((b, i) => (
            <rect key={i} x={x(b.x0 ?? 0)} y={y(b.length)} width={Math.max(1, x(b.x1 ?? 0) - x(b.x0 ?? 0) - 1)} height={h - 20 - y(b.length)} fill="#B0B7BC" />
          ))}
          {x.ticks(8).map(t => <text key={t} x={x(t)} y={h - 5} textAnchor="middle" className="text-[9px] fill-muted">{t}</text>)}
          {metric === 'score' && threshold != null && (
            <g><line x1={x(threshold)} x2={x(threshold)} y1={5} y2={h - 20} stroke="#D63A2F" strokeWidth={2} />
              <text x={x(threshold) + 3} y={14} className="text-[10px] fill-reject">learned threshold {threshold.toFixed(2)}</text></g>
          )}
          {metric === 'score' && whatIf != null && (
            <line x1={x(whatIf)} x2={x(whatIf)} y1={5} y2={h - 20} stroke="#1C2328" strokeDasharray="3 2" />
          )}
          {sel?.val != null && <circle cx={x(sel.val)} cy={h - 22} r={4} fill="#D63A2F" />}
        </svg>

        {metric === 'score' && threshold != null && (
          <div className="flex items-center gap-3 py-2 border-b border-hairline text-[11px]">
            <span className="text-muted font-sans">What-if threshold (does not change any decision):</span>
            <input type="range" min={0} max={(d3.max(values) ?? 10)} step={0.05} value={effective ?? 0}
              onChange={e => setWhatIf(Number(e.target.value))} className="w-[200px] accent-toprail" />
            <span>{effective?.toFixed(2)} → {whatIfCount} parts would be flagged by Module A</span>
            {whatIf != null && <button className="underline text-muted" onClick={() => setWhatIf(null)}>reset</button>}
          </div>
        )}

        <div className="flex items-center justify-between py-2">
          <span className="font-semibold text-main">{onlyFlagged ? 'Parts flagged by Module A' : 'All parts'} ({listed.length})</span>
          <label className="flex items-center gap-1 text-muted"><input type="checkbox" checked={onlyFlagged} onChange={e => setOnlyFlagged(e.target.checked)} /> flagged only</label>
        </div>
        <div className="flex-1 overflow-y-auto border border-hairline">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-panel text-muted text-[11px]">
              <tr><th className="px-2">Part</th><th className="px-2 text-right">Score</th>{PARAMS.map(p => <th key={p} className="px-2 text-right">z {PARAM_LABEL[p]}</th>)}<th className="px-2 text-right">24h {PARAM_LABEL[param]} ({PARAM_UNIT[param]})</th><th className="px-2">Static limit</th></tr>
            </thead>
            <tbody>
              {listed.map(r => (
                <tr key={r.p.id} onClick={() => selectPart(r.p.partId)} className={`h-[24px] border-b border-hairline/40 cursor-pointer ${r.p.partId === selectedPartId ? 'bg-panel font-semibold' : 'hover:bg-panel/40'}`}>
                  <td className="px-2">{r.p.partId}</td>
                  <td className={`px-2 text-right ${r.a!.flag ? 'text-reject font-bold' : ''}`}>{r.a!.score.toFixed(2)}</td>
                  {PARAMS.map(p => <td key={p} className="px-2 text-right tabular-nums">{r.a!.robustZ[p] != null ? (r.a!.robustZ[p] as number).toFixed(1) : '–'}</td>)}
                  <td className="px-2 text-right tabular-nums">{r.p.readings[24]?.toFixed(2) ?? '–'}</td>
                  <td className={`px-2 ${r.passesStatic ? 'text-accept' : 'text-reject'}`}>{r.passesStatic == null ? '–' : r.passesStatic ? 'passes' : 'BREACH'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="w-[300px] shrink-0 p-3 bg-panel overflow-y-auto">
        {sel?.a ? (
          <>
            <div className="font-bold text-sm mb-2">{sel.p.partId}</div>
            <div className="space-y-1 pb-2 border-b border-hairline mb-2">
              <div className="flex justify-between"><span className="text-muted">Decision score</span><span className={sel.a.flag ? 'text-reject font-bold' : ''}>{sel.a.score.toFixed(3)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Learned threshold</span><span>{sel.a.threshold == null ? 'module off' : sel.a.threshold.toFixed(3)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Module A flag</span><span className={sel.a.flag ? 'text-reject font-bold' : 'text-accept'}>{sel.a.flag ? 'LOT OUTLIER' : 'no'}</span></div>
              <div className="flex justify-between"><span className="text-muted">Static limit (0h/24h)</span><span className={sel.passesStatic ? 'text-accept' : 'text-reject'}>{sel.passesStatic ? `passes (${staticLimit} ${PARAM_UNIT[param]})` : 'BREACH'}</span></div>
              {sel.a.mahalanobis != null && <div className="flex justify-between"><span className="text-muted">Mahalanobis (diag.)</span><span>{sel.a.mahalanobis.toFixed(2)}</span></div>}
              {sel.a.isolation != null && <div className="flex justify-between"><span className="text-muted">Isolation score (diag.)</span><span>{sel.a.isolation.toFixed(2)}</span></div>}
            </div>
            <div className="font-semibold mb-1">Robust z vs own lot (lot-MAD units)</div>
            {PARAMS.filter(p => sel.a!.robustZ[p] != null).map(p => {
              const z = sel.a!.robustZ[p] as number;
              const wpx = Math.min(120, Math.abs(z) * 10);
              return (
                <div key={p} className="flex items-center gap-2 mb-1">
                  <span className="w-20 text-muted">{PARAM_LABEL[p]}</span>
                  <div className="relative w-[240px] h-3 bg-workspace border border-hairline">
                    <div className="absolute top-0 bottom-0 border-l border-hairline" style={{ left: 120 }} />
                    <div className={`absolute top-0 bottom-0 ${z >= 0 ? 'bg-reject' : 'bg-accept'}`} style={{ left: z >= 0 ? 120 : 120 - wpx, width: wpx }} />
                  </div>
                  <span className="w-10 text-right">{z.toFixed(1)}</span>
                </div>
              );
            })}
            <div className="text-[10px] text-muted font-sans mt-2">
              Positive z adds to the decision score. Values: part {PARAM_UNIT.leakage_current_ua} vs lot median; see Components for the full explanation.
            </div>
          </>
        ) : (
          <div className="text-muted p-4 text-center">{sel ? 'No Module A score (insufficient data).' : 'Select a part.'}</div>
        )}
      </div>
    </div>
  );
};
