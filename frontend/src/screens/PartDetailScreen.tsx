import React, { useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { INTERVALS, PARAM_LABEL, PARAM_UNIT, Param, lotLimit, lotParam } from '../data/types';
import { reasonFromVerdict } from '../data/api';
import { Card, EmptyState, LoadingState, StatusPill, fmt } from '../components/ui/primitives';
import { LineChart } from '../components/ui/charts';
import { anomalyScore } from '../lib/exportCsv';
import { robust, valuesAt } from '../lib/lotStats';

/** Signed horizontal bar centred on zero. */
const SignedBar: React.FC<{ label: string; value: number; max: number; text: string }> = ({ label, value, max, text }) => {
  const w = Math.min(1, Math.abs(value) / (max || 1)) * 50;
  return (
    <div className="grid grid-cols-[minmax(110px,40%)_1fr_64px] items-center gap-2 py-1 text-sm">
      <span className="truncate" title={label}>{label}</span>
      <div className="relative h-2.5 bg-panel rounded-full">
        <div className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
        <div className={`absolute inset-y-0 rounded-full ${value >= 0 ? 'bg-reject' : 'bg-info'}`}
          style={value >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
      </div>
      <span className="text-right tabular-nums">{text}</span>
    </div>
  );
};

export const PartDetailScreen: React.FC = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { activeLot, parts, predictions, explanations, loadExplanation, selectedPartId, selectPart, openDecisionDialog, config } = useStore();
  const partId = id ? decodeURIComponent(id) : selectedPartId;

  // URL -> selection, and selection (J/K) -> URL
  useEffect(() => { if (id && parts.some(p => p.partId === partId) && selectedPartId !== partId) selectPart(partId as string); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (selectedPartId && selectedPartId !== partId) navigate(`/part/${encodeURIComponent(selectedPartId)}`, { replace: true });
  }, [selectedPartId]); // eslint-disable-line react-hooks/exhaustive-deps

  const part = parts.find(p => p.partId === partId) ?? null;
  const pos = part ? parts.indexOf(part) + 1 : 0;
  const pred = part ? predictions[part.partId] : undefined;
  const exp = part ? explanations[part.partId] : undefined;
  useEffect(() => { if (part) loadExplanation(part.partId); }, [part, loadExplanation]);

  const param: Param = lotParam(activeLot);
  const unit = PARAM_UNIT[param];
  const limit = lotLimit(activeLot, param, config?.datasheetLimits);
  const lotMed = useMemo(() => INTERVALS.map(t => ({ t, r: robust(valuesAt(parts, param, t)) })), [parts, param]);

  if (!activeLot) return <EmptyState title="No lot loaded" />;
  if (!part) {
    return <EmptyState title={partId ? `Part ${partId} is not in lot ${activeLot.lotNumber}` : 'No part selected'}
      reason="Choose the part's lot in the header, or open a part from the Review Queue or Overview alerts." />;
  }

  const d = pred?.moduleB?.perParam[param] ?? null;
  const v0 = part.readings[0], v24 = part.readings[24];
  const score = anomalyScore(pred);
  const dataMax = Math.max(...INTERVALS.map(t => part.readings[t] ?? 0), ...lotMed.map(x => (x.r ? x.r.median + x.r.mad : 0)), d?.intervalUpper ?? 0, d?.forecast168h ?? 0);
  const limitOnScale = limit != null && limit <= 2 * dataMax;

  const aRatio = pred?.moduleA?.threshold ? pred.moduleA.score / pred.moduleA.threshold : null;
  const bRatio = pred?.moduleB?.score != null && pred.moduleB.thresholdK ? pred.moduleB.score / pred.moduleB.thresholdK : null;
  const primary = aRatio != null && bRatio != null ? (aRatio >= bRatio ? 'A' : 'B') : aRatio != null ? 'A' : 'B';
  const aTop = exp?.moduleA.contributions.find(c => c.parameter === exp.moduleA.topContributor);
  const breached = exp ? (Object.entries(exp.staticLimit.observedBreach).filter(([, v]) => v).map(([k]) => k)
    .concat(Object.entries(exp.staticLimit.forecastBreach).filter(([, v]) => v).map(([k]) => `${k} (forecast)`))) : [];
  const aZ = exp?.moduleA.contributions.filter(c => c.robustZ != null) ?? [];
  const bC = (exp?.moduleB.contributions ?? []).filter(c => c.feature !== '__other__').slice(0, 6);
  const maxZ = Math.max(1, ...aZ.map(c => Math.abs(c.robustZ as number)));
  const maxC = Math.max(1e-9, ...bC.map(c => Math.abs(c.value)));

  return (
    <div className="space-y-5 max-w-[1500px]" data-testid="part-detail">
      <p className="text-sm text-muted">Explainable inspection view · evidence behind the model decision · <kbd className="px-1 border border-hairline rounded">J</kbd>/<kbd className="px-1 border border-hairline rounded">K</kbd> next/previous part</p>
      <section className="bg-workspace border border-hairline rounded-card px-6 py-5 flex items-center gap-8 flex-wrap">
        <StatusPill status={pred?.verdict ?? null} className="text-sm px-3 py-1" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[24px] font-semibold">Part {part.partId}</h2>
          <div className="text-md text-muted">Lot {activeLot.lotNumber} · position {pos} / {parts.length}
            {part.statusSource === 'inspector' && <> · inspector decision <StatusPill status={part.status} className="ml-1" /></>}</div>
        </div>
        <div className="text-center"><div className="text-sm text-muted font-semibold">Anomaly score</div>
          <div className={`text-[26px] font-semibold tabular-nums ${score != null && score >= 1 ? 'text-reject' : 'text-main'}`}>{fmt(score, 2)}</div>
          <div className="text-xs text-muted">≥ 1 means a module flags</div></div>
        <div className="text-center"><div className="text-sm text-muted font-semibold">Predicted 168h</div>
          <div className={`text-[26px] font-semibold tabular-nums ${pred?.moduleB?.flag ? 'text-review' : 'text-main'}`}>{d?.forecast168h != null ? `${fmt(d.forecast168h)} ${unit}` : 'n/a'}</div>
          <div className="text-xs text-muted">{d?.intervalLower != null ? `90% interval ${fmt(d.intervalLower)} – ${fmt(d.intervalUpper)} ${unit}` : part.insufficientData ? 'insufficient 0h/24h data' : 'no interval'}</div></div>
      </section>

      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-5">
        <Card title={`${PARAM_LABEL[param]} drift`} subtitle={`Part vs lot median · ${unit}${limit != null && !limitOnScale ? ` · static limit ${limit} ${unit} is off scale` : ''}`} testId="trajectory">
          <LineChart height={300} xLabel="burn-in hours" yLabel={`${PARAM_LABEL[param]} (${unit})`}
            xTicks={INTERVALS.map(t => ({ x: t, label: t === 24 ? '24h (decision)' : `${t}h` }))}
            bands={[
              { id: 'mad', label: 'lot median ± MAD', color: 'var(--chart-neutral)', points: lotMed.filter(x => x.r).map(x => ({ x: x.t, lo: x.r!.median - x.r!.mad, hi: x.r!.median + x.r!.mad })) },
              ...(v24 != null && d?.intervalLower != null && d.intervalUpper != null
                ? [{ id: 'pi', label: '90% prediction interval', color: 'var(--status-reject)', points: [{ x: 24, lo: v24, hi: v24 }, { x: 168, lo: d.intervalLower, hi: d.intervalUpper }] }] : []),
            ]}
            hLines={limit != null && limitOnScale ? [{ y: limit, label: `static limit ${limit} ${unit}`, color: 'var(--chart-limit-static)' }] : []}
            series={[
              { id: 'median', label: 'lot median', color: 'var(--chart-neutral)', points: lotMed.map(x => ({ x: x.t, y: x.r?.median ?? null })) },
              { id: 'part', label: `part (measured; 96h/168h shown after the fact)`, color: 'var(--status-reject)', points: INTERVALS.map(t => ({ x: t, y: part.readings[t] })) },
              ...(v24 != null && d?.forecast168h != null ? [{ id: 'fc', label: 'forecast from 0h/24h', color: 'var(--status-reject)', dashed: true, width: 2, points: [{ x: 24, y: v24 }, { x: 168, y: d.forecast168h }] }] : []),
              ...(v0 != null && d?.safetySlope != null ? [{ id: 'slope', label: `lot safety slope ${d.safetySlope.toFixed(4)} ${unit}/h`, color: 'var(--chart-limit-safety)', dashed: true, width: 1.5, points: [{ x: 0, y: v0 }, { x: 168, y: v0 + d.safetySlope * 168 }] }] : []),
            ]} />
        </Card>

        <Card title="Why this part was flagged" subtitle={pred ? `${reasonFromVerdict(pred.verdictReason)} → ${pred.verdict}` : 'No model prediction'} testId="why-flagged">
          {!exp ? <LoadingState what="explanation" /> : (
            <div className="space-y-3">
              <div className="border-b border-hairline pb-3">
                <div className="flex justify-between text-sm font-semibold"><span>Lot-relative outlier (Module A)</span>
                  <span className={exp.moduleA.flag ? (primary === 'A' ? 'text-reject' : 'text-review') : 'text-muted'}>{exp.moduleA.flag ? (primary === 'A' ? 'Primary' : 'Secondary') : 'Not flagged'}</span></div>
                <div className="text-[20px] font-semibold tabular-nums">score {fmt(exp.moduleA.score)} <span className="text-sm text-muted font-normal">vs threshold {fmt(exp.moduleA.threshold)}</span></div>
                {aTop?.robustZ != null && <div className="text-sm text-muted">largest: {PARAM_LABEL[aTop.parameter]} {aTop.robustZ >= 0 ? '+' : ''}{aTop.robustZ.toFixed(2)} robust z vs lot median</div>}
              </div>
              <div className="border-b border-hairline pb-3">
                <div className="flex justify-between text-sm font-semibold"><span>Drift vs lot safety slope (Module B)</span>
                  <span className={exp.moduleB.flag ? (primary === 'B' ? 'text-reject' : 'text-review') : 'text-muted'}>{exp.moduleB.flag ? (primary === 'B' ? 'Primary' : 'Secondary') : 'Not flagged'}</span></div>
                <div className="text-[20px] font-semibold tabular-nums">z {fmt(exp.moduleB.score)} <span className="text-sm text-muted font-normal">vs k {fmt(exp.moduleB.thresholdK)}</span></div>
                {d?.predictedRate != null && <div className="text-sm text-muted">{PARAM_LABEL[param]} predicted rate {d.predictedRate.toFixed(4)} vs slope {fmt(d.safetySlope, 4)} {unit}/h</div>}
              </div>
              <div>
                <div className="flex justify-between text-sm font-semibold"><span>Static limit</span>
                  <span className={breached.length ? 'text-reject' : 'text-muted'}>{breached.length ? 'Breach' : 'Within'}</span></div>
                <div className="text-sm text-muted">{breached.length ? breached.map(b => PARAM_LABEL[b.split(' ')[0] as Param] ?? b).join(', ') : 'no observed or forecast breach'}</div>
              </div>
              <div className="pt-2">
                <div className="text-sm font-semibold mb-1">Signed contributions</div>
                {aZ.map(c => <SignedBar key={c.parameter} label={`A · ${PARAM_LABEL[c.parameter]} robust z`} value={c.robustZ as number} max={maxZ} text={(c.robustZ as number).toFixed(2)} />)}
                {bC.map(c => <SignedBar key={c.feature} label={`B · ${c.label}`} value={c.value} max={maxC} text={c.value.toFixed(3)} />)}
                <p className="text-xs text-muted mt-1">A: robust z per parameter (positive adds to the score). B: TreeSHAP contributions to the {PARAM_LABEL[exp.moduleB.driver]} forecast ({exp.moduleB.targetSpace ?? 'model'} space); red raises it.</p>
              </div>
            </div>
          )}
        </Card>
      </div>

      <section className="bg-navy text-white rounded-card px-6 py-5 flex items-start justify-between gap-6" data-testid="evidence">
        <div className="min-w-0">
          <h2 className="text-card font-semibold">Inspector evidence</h2>
          <p className="text-md text-[#DCE4F0] mt-1 whitespace-pre-line">{exp?.summary ?? 'Loading the generated justification…'}</p>
        </div>
        <button onClick={() => openDecisionDialog(part.status, [part.partId])} data-testid="open-decision"
          className="shrink-0 rounded-full bg-review-bg text-review font-semibold px-5 py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan">Open review decision</button>
      </section>
    </div>
  );
};
