import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Upload } from 'lucide-react';
import { useStore } from '../store/useStore';
import { INTERVALS, PARAMS, PARAM_LABEL, PARAM_UNIT, Param, lotLimit, lotParam } from '../data/types';
import { reasonFromVerdict } from '../data/api';
import { Button, Card, EmptyState, StatTile, StatusPill, fmt, int, pct, toneOf } from '../components/ui/primitives';
import { HistValue, Histogram } from '../components/ui/charts';
import { anomalyScore } from '../lib/exportCsv';
import { lotRates } from '../lib/lotStats';

const TOP_N = 6;

export const OverviewScreen: React.FC = () => {
  const { activeLot, lots, parts, predictions, config, explanations, loadExplanation } = useStore();
  const navigate = useNavigate();
  const defaultParam = lotParam(activeLot);
  const used = ((activeLot?.sourceDetail?.parameters_used as string[] | undefined) ?? [...PARAMS]) as Param[];
  const [param, setParam] = useState<Param>(defaultParam);
  const [t, setT] = useState<number>(24);
  useEffect(() => setParam(defaultParam), [defaultParam]);

  const counts = useMemo(() => {
    const c = { n: parts.length, PASS: 0, REVIEW: 0, REJECT: 0, A: 0, B: 0, undecided: 0 };
    for (const p of parts) {
      const pr = predictions[p.partId];
      if (pr?.verdict) c[pr.verdict] += 1;
      if (pr?.moduleA?.flag) c.A += 1;
      if (pr?.moduleB?.flag) c.B += 1;
      if (pr && pr.verdict !== 'PASS' && p.statusSource === 'model') c.undecided += 1;
    }
    return c;
  }, [parts, predictions]);

  // delta vs the previous lot in the list (only when one exists)
  const idx = lots.findIndex(l => l.id === activeLot?.id);
  const prev = idx > 0 ? lots[idx - 1] : null;
  const prevRate = prev ? lotRates(prev).flagRate : null;
  const flagRate = counts.n ? (counts.REVIEW + counts.REJECT) / counts.n : null;
  const delta = prevRate != null && flagRate != null ? (flagRate - prevRate) * 100 : null;

  const hist: HistValue[] = useMemo(() => parts.flatMap(p => {
    const v = p.allReadings.find(r => r.intervalHours === t)?.values[param];
    return v != null && Number.isFinite(v) ? [{ v, status: predictions[p.partId]?.verdict ?? null }] : [];
  }), [parts, predictions, param, t]);

  const alerts = useMemo(() => parts
    .map(p => ({ p, pr: predictions[p.partId], s: anomalyScore(predictions[p.partId]) }))
    .filter(x => x.pr && x.pr.verdict !== 'PASS' && x.pr.verdict != null)
    .sort((a, b) => (b.s ?? -Infinity) - (a.s ?? -Infinity))
    .slice(0, TOP_N), [parts, predictions]);
  useEffect(() => { alerts.forEach(a => loadExplanation(a.p.partId)); }, [alerts, loadExplanation]);

  if (!activeLot) return <EmptyState title="No lot loaded" reason="Seed the database or ingest a lot." />;
  const sharePct = (k: number) => (counts.n ? pct(k / counts.n) : 'n/a');
  const unit = PARAM_UNIT[param];
  const alertLine = (partId: string, fallback: string) => {
    const e = explanations[partId];
    if (!e) return fallback;
    const bits: string[] = [];
    const a = e.moduleA.contributions.find(c => c.parameter === e.moduleA.topContributor);
    if (e.moduleA.flag && a?.robustZ != null) bits.push(`${PARAM_LABEL[a.parameter]} ${a.robustZ >= 0 ? '+' : ''}${a.robustZ.toFixed(1)} robust z vs lot`);
    const d = predictions[partId]?.moduleB?.perParam[e.moduleB.driver];
    if (e.moduleB.flag && d?.forecast168h != null) bits.push(`${PARAM_LABEL[e.moduleB.driver]} 168h forecast ${d.forecast168h.toFixed(2)} ${PARAM_UNIT[e.moduleB.driver]}, rate above lot safety slope`);
    if (Object.values(e.staticLimit.forecastBreach).some(Boolean)) bits.push('forecast reaches static limit');
    return bits.length ? bits.join(' · ') : fallback;
  };

  return (
    <div className="space-y-5 max-w-[1500px]" data-testid="overview">
      <p className="text-sm text-muted">Lot {activeLot.lotNumber} · {int(counts.n)} parts · verdicts from 0h/24h readings (model; inspector decisions shown in the Review Queue)</p>
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Parts screened" value={int(counts.n)} tone="info"
          sub={delta != null ? `flag rate ${delta >= 0 ? '+' : ''}${delta.toFixed(1)} pp vs ${prev?.lotNumber}` : 'no previous lot to compare'} />
        <StatTile label="PASS" value={int(counts.PASS)} tone="pass" colorValue sub={`${sharePct(counts.PASS)} of parts`} />
        <StatTile label="REVIEW" value={int(counts.REVIEW)} tone="review" colorValue sub={`${sharePct(counts.REVIEW)} of parts`} />
        <StatTile label="REJECT" value={int(counts.REJECT)} tone="reject" colorValue sub={`${sharePct(counts.REJECT)} of parts`} />
      </div>

      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-5">
        <Card title="Lot distribution" subtitle={`${PARAM_LABEL[param]} · ${t}h · ${unit}`} testId="overview-histogram"
          actions={<>
            <select aria-label="Parameter" value={param} onChange={e => setParam(e.target.value as Param)} className="rounded-lg border border-hairline px-2 py-1 text-sm">
              {used.map(p => <option key={p} value={p}>{PARAM_LABEL[p]}</option>)}
            </select>
            <select aria-label="Time point" value={t} onChange={e => setT(Number(e.target.value))} className="rounded-lg border border-hairline px-2 py-1 text-sm">
              {INTERVALS.map(h => <option key={h} value={h}>{h}h{h === 24 ? ' (decision)' : ''}</option>)}
            </select>
          </>}>
          <Histogram values={hist} xLabel={`${PARAM_LABEL[param]} at ${t}h`} unit={unit} limit={lotLimit(activeLot, param, config?.datasheetLimits)} />
        </Card>
        <Card title="Combined verdict" subtitle="Module A ∪ Module B ∪ static limit">
          <ul className="space-y-4">
            {([['PASS', 'Within lot envelope and safety slope'], ['REVIEW', 'One module flags: inspector decision needed'], ['REJECT', 'Both modules, or a static-limit breach']] as const).map(([v, d]) => (
              <li key={v} className="grid grid-cols-[84px_1fr] items-center gap-3">
                <StatusPill status={v} className="justify-center" />
                <div><div className="text-[22px] font-semibold tabular-nums">{int(counts[v])}</div><div className="text-sm text-muted">{d}</div></div>
              </li>
            ))}
          </ul>
          <div className="mt-4 pt-3 border-t border-hairline text-sm text-muted grid grid-cols-2 gap-2">
            <span>Module A flags <strong className="text-main">{int(counts.A)}</strong></span>
            <span>Module B flags <strong className="text-main">{int(counts.B)}</strong></span>
          </div>
        </Card>
      </div>

      <Card title="Priority alerts" subtitle={`Highest anomaly score among flagged parts (top ${TOP_N}; score = max of Module A score / threshold and Module B z / k)`} testId="priority-alerts">
        {alerts.length === 0 ? <EmptyState title="No flagged parts in this lot" /> : (
          <ul className="grid grid-cols-2 gap-x-8 gap-y-3">
            {alerts.map(({ p, pr, s }) => (
              <li key={p.partId}>
                <button className="w-full flex items-start gap-3 text-left rounded-lg p-1 hover:bg-panel focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan" onClick={() => navigate(`/part/${encodeURIComponent(p.partId)}`)}>
                  <StatusPill status={pr!.verdict} label={p.partId} tone={toneOf(pr!.verdict)} className="shrink-0 font-mono" />
                  <span className="text-md text-main">{alertLine(p.partId, reasonFromVerdict(pr!.verdictReason))} <span className="text-muted">· score {fmt(s, 2)}</span></span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <section className="bg-navy text-white rounded-card px-6 py-5 flex items-center justify-between gap-6" data-testid="inspector-strip">
        <div>
          <h2 className="text-card font-semibold">Inspector view</h2>
          <p className="text-sm text-[#C9D3E3] mt-1">Each flag links to the part's trajectory, lot distribution and the evidence behind the decision.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={() => navigate('/ingest')} className="!bg-transparent !text-white !border-[#2A4772]"><Upload size={15} /> Ingest lot</Button>
          <button onClick={() => navigate('/review')} className="inline-flex items-center gap-2 rounded-full bg-review-bg text-review font-semibold px-5 py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan">
            {int(counts.undecided)} awaiting decision in review queue <ArrowRight size={15} />
          </button>
        </div>
      </section>
    </div>
  );
};
