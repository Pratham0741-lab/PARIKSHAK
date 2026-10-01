import React, { useEffect, useMemo } from 'react';
import * as d3 from 'd3';
import { useStore } from '../store/useStore';
import { StatusMarker } from '../components/common/StatusMarker';
import { findSimilarParts } from '../lib/analytics/explainability';
import { PARAMS, PARAM_LABEL, PARAM_UNIT, Param, lotLimit, lotParam } from '../data/types';

const f = (v: number | null | undefined, nd = 3) => (v == null ? '–' : v.toFixed(nd));

export const ComponentDetailScreen: React.FC = () => {
  const { parts, predictions, selectedPartId, explanations, loadExplanation, config, openDecisionDialog, mode, activeLot } = useStore();
  const param = lotParam(activeLot);
  const unit = PARAM_UNIT[param];
  const part = parts.find(p => p.partId === selectedPartId) ?? parts[0] ?? null;
  const pred = part ? predictions[part.partId] : undefined;
  const exp = part ? explanations[part.partId] : undefined;

  useEffect(() => {
    if (part) loadExplanation(part.partId);
  }, [part, loadExplanation]);

  const similar = useMemo(() => (part ? findSimilarParts(part, parts, 5) : []), [part, parts]);
  if (!part) return <div className="p-6 text-muted font-mono text-xs">No parts in this lot.</div>;

  const bContrib = exp?.moduleB.contributions ?? [];
  const maxB = Math.max(1e-9, ...bContrib.map(c => Math.abs(c.value)));
  const aContrib = exp?.moduleA.contributions ?? [];
  const maxA = Math.max(1e-9, ...aContrib.map(c => Math.abs(c.robustZ ?? 0)));

  return (
    <div className="w-full h-full flex flex-col bg-workspace overflow-hidden font-mono text-xs">
      <div className="border-b border-hairline px-4 py-2 bg-panel flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span className="font-bold text-sm text-main">Component {part.partId}</span>
          <StatusMarker status={part.status} />
          <span className="text-muted font-sans">{part.statusSource === 'inspector' ? `set by inspector ${part.inspector}` : `model verdict ${pred?.verdict ?? '–'}`}</span>
        </div>
        <div className="flex gap-2">
          {(['Accept', 'Review', 'Reject'] as const).map(s => (
            <button key={s} onClick={() => openDecisionDialog(s, [part.partId])} className="bg-workspace border border-hairline px-2 py-0.5 hover:border-toprail">{s}…</button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 p-4 grid grid-cols-12 gap-4 overflow-y-auto">
        <div className="col-span-5 space-y-4">
          <Panel title="Readings (0h/24h used by the models; 96h/168h shown for traceability)">
            <table className="w-full">
              <thead className="text-muted text-[11px]"><tr><th className="text-left">Param</th>{[0, 24, 96, 168].map(t => <th key={t} className="text-right">{t}h</th>)}</tr></thead>
              <tbody>
                {PARAMS.map(p => (
                  <tr key={p}>
                    <td className="text-muted">{PARAM_LABEL[p]} ({PARAM_UNIT[p]})</td>
                    {[0, 24, 96, 168].map(t => {
                      const r = part.allReadings.find(x => x.intervalHours === t);
                      return <td key={t} className="text-right tabular-nums">{r && r.values[p] != null ? r.values[p].toFixed(3) : '–'}{r?.imputed.includes(p) ? '*' : ''}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {part.allReadings.some(r => r.imputed.length) && <div className="text-[10px] text-review mt-1 font-sans">* imputed at ingest (lot median; display only). Part marked insufficient data.</div>}
            <MiniTrajectory readings={part.readings} forecast={pred?.moduleB?.perParam[param]?.forecast168h ?? null}
              lower={pred?.moduleB?.perParam[param]?.intervalLower ?? null} upper={pred?.moduleB?.perParam[param]?.intervalUpper ?? null}
              limit={lotLimit(activeLot, param, config?.datasheetLimits)} />
          </Panel>

          <Panel title="Module A decomposition: robust z vs own lot (score = sum of positive z)">
            {exp ? (
              <>
                {aContrib.map(c => (
                  <Bar key={c.parameter} label={PARAM_LABEL[c.parameter as Param]} value={c.robustZ ?? 0} max={maxA}
                    right={`z ${f(c.robustZ, 2)} · ${f(c.value, 3)} vs lot ${f(c.lotMedian, 3)}`} />
                ))}
                <div className="text-muted mt-1">score {f(exp.moduleA.score, 3)} vs learned threshold {exp.moduleA.threshold == null ? 'off' : f(exp.moduleA.threshold, 3)} → <strong className={exp.moduleA.flag ? 'text-reject' : 'text-accept'}>{exp.moduleA.flag ? 'flag' : 'no flag'}</strong></div>
              </>
            ) : <Unavailable part={part} exp={exp} mode={mode} />}
          </Panel>
        </div>

        <div className="col-span-7 space-y-4">
          <Panel title={`Module B feature contributions to the ${exp ? PARAM_LABEL[exp.moduleB.driver] : ''} forecast (TreeSHAP, LightGBM pred_contrib)`}>
            {exp ? (
              <>
                {bContrib.map(c => (
                  <Bar key={c.feature} label={c.label} value={c.value} max={maxB} wide
                    right={c.effectPctOnForecast != null ? `${c.effectPctOnForecast >= 0 ? '+' : ''}${c.effectPctOnForecast.toFixed(1)}%` : c.value.toFixed(4)} />
                ))}
                <div className="text-[10px] text-muted font-sans mt-1">
                  Signed contributions in the model's target space ({exp.moduleB.targetSpace}); % = multiplicative effect on the 168h forecast. Largest: <strong>{exp.moduleB.topContributor}</strong>.
                </div>
              </>
            ) : <Unavailable part={part} exp={exp} mode={mode} />}
          </Panel>

          <Panel title="QA justification (generated from this part's model outputs)">
            <div className="bg-panel border border-hairline p-3 text-[11px] leading-relaxed text-main select-text whitespace-pre-wrap">
              {exp ? exp.summary : pred ? pred.verdictReason : part.reason}
            </div>
            {exp?.cvFold != null && <div className="text-[10px] text-muted mt-1 font-sans">Out-of-fold prediction (lot fold {exp.cvFold}).</div>}
          </Panel>

          <Panel title={`Parts with the most similar 0h/24h ${PARAM_LABEL[param]} (current dispositions)`}>
            <table className="w-full">
              <thead className="text-muted text-[11px]"><tr><th className="text-left">Part</th><th className="text-right">0h {unit}</th><th className="text-right">24h {unit}</th><th className="text-right">Distance</th><th className="pl-3 text-left">Status</th></tr></thead>
              <tbody>
                {similar.map(s => (
                  <tr key={s.partId}><td>{s.partId}</td><td className="text-right">{f(s.leakage0h, 2)}</td><td className="text-right">{f(s.leakage24h, 2)}</td><td className="text-right">{s.distance}</td><td className="pl-3"><StatusMarker status={s.status} /></td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      </div>
    </div>
  );
};

const Panel: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="border border-hairline p-3 bg-workspace">
    <div className="font-sans font-bold text-xs text-main mb-2">{title}</div>
    {children}
  </div>
);

const Bar: React.FC<{ label: string; value: number; max: number; right: string; wide?: boolean }> = ({ label, value, max, right, wide }) => {
  const half = 50 * Math.min(1, Math.abs(value) / max);
  return (
    <div className="grid grid-cols-12 items-center gap-2 mb-1">
      <span className={`${wide ? 'col-span-5' : 'col-span-3'} truncate text-muted font-sans`} title={label}>{label}</span>
      <div className={`${wide ? 'col-span-4' : 'col-span-5'} relative h-3 bg-panel border border-hairline`}>
        <div className="absolute top-0 bottom-0 left-1/2 border-l border-hairline" />
        <div className={`absolute top-0 bottom-0 ${value >= 0 ? 'bg-reject' : 'bg-accept'}`}
          style={value >= 0 ? { left: '50%', width: `${half}%` } : { right: '50%', width: `${half}%` }} />
      </div>
      <span className={`${wide ? 'col-span-3' : 'col-span-4'} text-right tabular-nums`}>{right}</span>
    </div>
  );
};

const Unavailable: React.FC<{ part: { insufficientData: boolean }; exp: unknown; mode: string }> = ({ part, exp, mode }) => (
  <div className="text-muted italic">
    {exp === undefined ? 'Loading…' : mode === 'offline' ? 'Not available in offline demo mode (requires the backend model).'
      : part.insufficientData ? 'No model score: insufficient data at ingest.' : 'No explanation available.'}
  </div>
);

const MiniTrajectory: React.FC<{ readings: Record<number, number | null>; forecast: number | null; lower: number | null; upper: number | null; limit: number | null }> = ({ readings, forecast, lower, upper, limit }) => {
  const w = 360, h = 120;
  const pts = [0, 24, 96, 168].map(t => ({ t, v: readings[t] })).filter((d): d is { t: number; v: number } => d.v != null);
  const maxV = Math.max(limit ?? 0, upper ?? 0, ...pts.map(p => p.v)) * 1.1 || 1;
  const x = d3.scaleLinear().domain([0, 168]).range([30, w - 10]);
  const y = d3.scaleLinear().domain([0, maxV]).range([h - 18, 6]);
  const line = d3.line<{ t: number; v: number }>().x(d => x(d.t)).y(d => y(d.v));
  const v24 = readings[24];
  return (
    <svg width={w} height={h} className="mt-2">
      {limit != null && <line x1={30} x2={w - 10} y1={y(limit)} y2={y(limit)} stroke="#D63A2F" strokeDasharray="3 2" />}
      {v24 != null && lower != null && upper != null && <path d={`M ${x(24)} ${y(v24)} L ${x(168)} ${y(upper)} L ${x(168)} ${y(lower)} Z`} fill="#D63A2F" fillOpacity={0.1} />}
      {v24 != null && forecast != null && <path d={line([{ t: 24, v: v24 }, { t: 168, v: forecast }]) || ''} stroke="#D63A2F" strokeDasharray="4 3" fill="none" />}
      <path d={line(pts) || ''} stroke="#1C2328" strokeWidth={2} fill="none" />
      {[0, 24, 96, 168].map(t => <text key={t} x={x(t)} y={h - 4} textAnchor="middle" className="text-[9px] fill-muted">{t}h</text>)}
    </svg>
  );
};
