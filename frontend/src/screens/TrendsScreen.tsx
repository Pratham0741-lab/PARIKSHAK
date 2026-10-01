import React, { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/useStore';
import { INTERVALS, PARAMS, PARAM_LABEL, Param } from '../data/types';
import { ModelReport, getModelReport } from '../data/modelApi';
import { BarRow, Card, EmptyState, StatTile, int, pct } from '../components/ui/primitives';
import { BarChart, Heatmap, RiskLevel } from '../components/ui/charts';
import { HIGHLIGHT_Z, ROBUST_Z_CUT, highlightThreshold, lotRates, outsideFraction, valuesAt } from '../lib/lotStats';

type Metric = 'anomalyRate' | 'driftRate' | 'flagRate';
const METRIC_LABEL: Record<Metric, string> = { anomalyRate: 'Module A anomaly rate', driftRate: 'Module B drift rate', flagRate: 'flag rate (REVIEW + REJECT)' };

export const TrendsScreen: React.FC = () => {
  const { lots, activeLot, parts, metrics, loadMetrics, mode, setActiveLot } = useStore();
  const [report, setReport] = useState<ModelReport | null>(null);
  const [metric, setMetric] = useState<Metric>('anomalyRate');
  const [watch, setWatch] = useState(0.05);
  const [high, setHigh] = useState(0.15);
  useEffect(() => {
    if (mode === 'offline') return;
    if (!metrics) loadMetrics();
    getModelReport().then(setReport).catch(() => setReport(null));
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const totals = useMemo(() => {
    let n = 0, a = 0, b = 0, known = 0;
    for (const l of lots) {
      n += l.totalParts;
      if (l.moduleAFlagCount != null && l.moduleBFlagCount != null) { a += l.moduleAFlagCount; b += l.moduleBFlagCount; known += l.totalParts; }
    }
    return { n, anomaly: known ? a / known : null, drift: known ? b / known : null };
  }, [lots]);
  const fnRate = metrics && metrics.tp + metrics.fn > 0 ? metrics.fn / (metrics.tp + metrics.fn) : null;

  const series = useMemo(() => lots.map(l => ({ l, v: lotRates(l)[metric] })).filter((x): x is { l: typeof lots[number]; v: number } => x.v != null), [lots, metric]);
  const thr = highlightThreshold(series.map(s => s.v));
  const suppliers = useMemo(() => {
    const g = new Map<string, { n: number; flagged: number; lots: number }>();
    for (const l of lots) {
      if (!l.supplier) continue;
      const e = g.get(l.supplier) ?? { n: 0, flagged: 0, lots: 0 };
      e.n += l.totalParts; e.flagged += l.reviewCount + l.rejectCount; e.lots += 1;
      g.set(l.supplier, e);
    }
    return [...g.entries()].map(([s, e]) => ({ s, rate: e.n ? e.flagged / e.n : 0, ...e })).sort((a, b) => b.rate - a.rate);
  }, [lots]);

  const used = ((activeLot?.sourceDetail?.parameters_used as string[] | undefined) ?? [...PARAMS]) as Param[];
  const level = (f: number | null): RiskLevel => (f == null ? 'n/a' : f >= high ? 'High' : f >= watch ? 'Watch' : 'Low');

  if (lots.length === 0) return <EmptyState title="No lots" />;
  return (
    <div className="space-y-5 max-w-[1500px]" data-testid="trends">
      <p className="text-sm text-muted">Flag rates across all {lots.length} lots (model verdicts) and measurement risk for lot {activeLot?.lotNumber}.</p>
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Anomaly rate (Module A)" value={pct(totals.anomaly)} sub={`all lots, ${int(totals.n)} parts`} tone="review" />
        <StatTile label="Drift rate (Module B)" value={pct(totals.drift)} sub={`all lots, ${int(totals.n)} parts`} tone="review" />
        <StatTile label="False-negative rate (held-out)" value={pct(fnRate)} tone={fnRate != null ? 'reject' : 'neutral'}
          sub={metrics ? `FN ${metrics.fn} of ${metrics.tp + metrics.fn} defective · ${report?.split ? `${report.split.n_lots} labelled lots, ${report.split.method}` : 'labelled lots'}` : mode === 'offline' ? 'needs the backend' : 'loading…'} />
        <StatTile label="Lots monitored" value={int(lots.length)} sub={`${lots.filter(l => l.source === 'CSV_INGEST').length} ingested, ${lots.filter(l => l.source !== 'CSV_INGEST').length} synthetic`} />
      </div>

      <div className={`grid gap-5 ${suppliers.length ? 'grid-cols-[minmax(0,2fr)_minmax(0,1fr)]' : 'grid-cols-1'}`}>
        <Card title={`${METRIC_LABEL[metric][0].toUpperCase()}${METRIC_LABEL[metric].slice(1)} by lot`} testId="rate-by-lot"
          subtitle={`Percentage of parts per lot; red above the cross-lot median + ${HIGHLIGHT_Z} robust SD (${thr != null ? pct(thr) : 'n/a'})`}
          actions={<select aria-label="Metric" value={metric} onChange={e => setMetric(e.target.value as Metric)} className="rounded-lg border border-hairline px-2 py-1 text-sm">
            {(Object.keys(METRIC_LABEL) as Metric[]).map(k => <option key={k} value={k}>{METRIC_LABEL[k]}</option>)}</select>}>
          {series.length === 0 ? <EmptyState title="No per-lot flag counts" reason="Module A/B flag counts are not available in this data source." /> : (
            <BarChart height={300} xLabel="lot" yLabel="% of parts" format={v => `${Math.round(v * 100)}%`}
              bars={series.map(s => ({ key: s.l.id, label: s.l.lotNumber, value: s.v, highlight: thr != null && s.v > thr, title: `${s.l.lotNumber}: ${pct(s.v)} (${s.l.totalParts} parts)` }))}
              threshold={thr != null ? { value: thr, label: `median + ${HIGHLIGHT_Z} robust SD` } : undefined}
              onClick={id => setActiveLot(id)} />
          )}
        </Card>
        {suppliers.length > 0 && (
          <Card title="Supplier flag rate" subtitle="REVIEW + REJECT share of parts, lots grouped by the supplier field" testId="suppliers">
            {suppliers.map(s => <BarRow key={s.s} label={`${s.s} (${s.lots} lot${s.lots > 1 ? 's' : ''})`} value={s.rate} max={Math.max(...suppliers.map(x => x.rate))} text={pct(s.rate)} tone={thr != null && s.rate > thr ? 'reject' : 'info'} />)}
          </Card>
        )}
      </div>

      <Card title="Measurement risk by burn-in point" testId="risk-heatmap"
        subtitle={`Lot ${activeLot?.lotNumber}: share of parts outside the robust band (|x − median| > ${ROBUST_Z_CUT} × 1.4826 × MAD) per parameter and time point`}
        actions={<div className="flex items-center gap-3 text-sm">
          <label>Watch ≥ <input type="number" min={0} max={1} step={0.01} value={watch} onChange={e => setWatch(Number(e.target.value))} className="w-16 rounded border border-hairline px-1" /></label>
          <label>High ≥ <input type="number" min={0} max={1} step={0.01} value={high} onChange={e => setHigh(Number(e.target.value))} className="w-16 rounded border border-hairline px-1" /></label>
        </div>}>
        <Heatmap rows={used.map(p => PARAM_LABEL[p])} cols={INTERVALS.map(t => `${t}h`)}
          cell={(r, c) => {
            const p = used.find(x => PARAM_LABEL[x] === r) as Param;
            const t = Number(c.replace('h', ''));
            const vs = valuesAt(parts, p, t);
            const f = outsideFraction(vs);
            return { level: level(f), title: f == null ? 'no readings' : `${pct(f)} of ${vs.length} parts outside the robust band` };
          }} />
        <p className="text-xs text-muted mt-2">Low &lt; {pct(watch, 0)} ≤ Watch &lt; {pct(high, 0)} ≤ High. 96h/168h columns use readings measured after the decision point and are shown for traceability only.</p>
      </Card>
    </div>
  );
};
