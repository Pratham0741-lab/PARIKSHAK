import React, { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/useStore';
import { PARAMS, PARAM_LABEL, Param } from '../data/types';
import { ModelReport, ScoreBlock, getModelReport } from '../data/modelApi';
import { BarRow, Button, Card, EmptyState, ErrorState, LoadingState, StatTile, fmt, int, pct } from '../components/ui/primitives';
import { LineChart, ScatterPlot } from '../components/ui/charts';
import { JudgeScreen } from './JudgeScreen';

const trainNote = (t: ScoreBlock | null | undefined, f: (b: ScoreBlock) => string) => (t ? `train (optimistic, in-sample): ${f(t)}` : 'train metrics: n/a (not persisted for this run)');

export const ModelScreen: React.FC = () => {
  const { metrics, costCurves, loadMetrics, mode, config } = useStore();
  const [report, setReport] = useState<ModelReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fn, setFn] = useState<number | null>(null);
  const [fp, setFp] = useState<number | null>(null);
  const [fiParam, setFiParam] = useState<Param>('leakage_current_ua');

  useEffect(() => {
    if (mode === 'offline') return;
    loadMetrics();
    getModelReport().then(setReport).catch(e => setErr(String(e)));
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (metrics && fn == null) { setFn(metrics.fnCost); setFp(metrics.fpCost); } }, [metrics]); // eslint-disable-line react-hooks/exhaustive-deps

  const scatter = useMemo(() => {
    const pts = report?.predicted_vs_actual.points ?? [];
    if (!pts.length) return null;
    const err = pts.map(p => p.pred - p.actual), lin = pts.map(p => p.linear - p.actual);
    const withPi = pts.filter(p => p.lo != null && p.hi != null);
    return {
      n: pts.length,
      mae: err.reduce((a, e) => a + Math.abs(e), 0) / pts.length,
      rmse: Math.sqrt(err.reduce((a, e) => a + e * e, 0) / pts.length),
      linMae: lin.reduce((a, e) => a + Math.abs(e), 0) / pts.length,
      coverage: withPi.length ? withPi.filter(p => p.actual >= (p.lo as number) && p.actual <= (p.hi as number)).length / withPi.length : null,
      points: pts.map(p => ({ x: p.pred, y: p.actual })),
    };
  }, [report]);

  if (mode === 'offline') return <EmptyState title="Model performance needs the backend" reason="Held-out metrics require labelled lots evaluated out-of-fold on the server. Switch the data source to Backend." />;
  if (err) return <ErrorState message={`Could not load the model report: ${err}`} />;
  if (!metrics || !report) return <LoadingState what="model report" />;

  const m = metrics, tr = report.train_optimistic, split = report.split;
  const n = m.tp + m.fp + m.fn + m.tn;
  const fnRate = m.tp + m.fn ? m.fn / (m.tp + m.fn) : null;
  const flagAll = m.fpCost * (m.fp + m.tn), flagNone = m.fnCost * (m.tp + m.fn);
  const current = report.registry.find(r => r.current);
  const fi = (report.feature_importance as ModelReport['feature_importance'] & { per_parameter?: Record<string, { label: string; share: number }[]> }).per_parameter ?? {};
  const curve = costCurves.A;
  const lr = (report.held_out.regression ?? {}).leakage_current_ua;
  const trR = tr?.regression?.leakage_current_ua;

  return (
    <div className="space-y-5 max-w-[1500px]" data-testid="model-performance">
      <p className="text-sm text-muted">Held-out validation: {split ? `${split.method}, ${split.n_lots} labelled lots / ${int(split.n_parts)} parts` : report.protocol}; every part predicted by a model that never saw its lot. Train (optimistic, in-sample) values are shown beside for the gap only.</p>
      <div className="grid grid-cols-4 gap-4">
        <StatTile label="Recall (A ∪ B, held-out)" value={pct(m.recall)} tone="info" sub={<>FN rate {pct(fnRate)} · {trainNote(tr, b => pct(b.detection.recall))}</>} />
        <StatTile label="Module B MAE (168h leakage, held-out)" value={`${fmt(m.maeLeakage, 3)} µA`} tone="info" sub={<>linear baseline {fmt(m.linearMaeLeakage, 3)} µA · {trainNote(tr, () => (trR ? `${fmt(trR.model.mae, 3)} µA` : 'n/a'))}</>} />
        <StatTile label="Precision (held-out)" value={pct(m.precision)} tone="info" sub={<>F2 {pct(m.f2)} · {trainNote(tr, b => pct(b.detection.precision))}</>} />
        <StatTile label="Model version" value={current ? current.id.slice(0, 8) : 'n/a'} tone="info" sub={current ? `screening run, trained ${new Date(current.created_at).toLocaleString()}` : 'no screening run'} />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)_minmax(0,1.2fr)] gap-5">
        <Card title="Combined decision (held-out)" subtitle={`Module A ∪ Module B ∪ static limit · ${int(n)} parts`} testId="decision-bars">
          <BarRow label="Recall" value={m.recall} text={pct(m.recall)} />
          <BarRow label="Precision" value={m.precision} text={pct(m.precision)} />
          <BarRow label="False-negative rate" value={fnRate ?? 0} text={pct(fnRate)} tone="reject" />
          <BarRow label="Flag rate" value={n ? (m.tp + m.fp) / n : 0} text={pct(n ? (m.tp + m.fp) / n : null)} tone="review" />
          <BarRow label="F2" value={m.f2} text={pct(m.f2)} />
          <p className="text-xs text-muted mt-2">Thresholds: Module A {fmt(m.thresholds?.threshold_a, 3)}, Module B k {fmt(m.thresholds?.threshold_b, 3)} ({config?.thresholdStrategy ?? 'n/a'}), chosen by FN-weighted cost on inner CV of the training lots.</p>
        </Card>
        <Card title="Held-out decision matrix" subtitle="Ground truth is used only here, for scoring" testId="decision-matrix">
          <table className="w-full text-center text-md border-separate border-spacing-2">
            <thead><tr><th /><th className="text-sm text-muted font-semibold">Actual normal</th><th className="text-sm text-muted font-semibold">Actual defect</th></tr></thead>
            <tbody>
              <tr><th className="text-sm text-muted font-semibold">Pred. PASS</th>
                <td className="rounded-lg border border-hairline py-3 font-semibold tabular-nums">{int(m.tn)}<div className="text-xs text-muted font-normal">TN</div></td>
                <td className="rounded-lg border-2 border-reject bg-reject-bg py-3 font-bold text-reject tabular-nums" data-testid="fn-cell">{int(m.fn)}<div className="text-xs font-semibold">FN (escapes)</div></td></tr>
              <tr><th className="text-sm text-muted font-semibold">Pred. flag</th>
                <td className="rounded-lg border border-hairline py-3 font-semibold tabular-nums">{int(m.fp)}<div className="text-xs text-muted font-normal">FP</div></td>
                <td className="rounded-lg border border-hairline bg-accept-bg py-3 font-semibold text-accept tabular-nums">{int(m.tp)}<div className="text-xs font-normal">TP</div></td></tr>
            </tbody>
          </table>
        </Card>
        <Card title="Module B · predicted vs actual 168h" subtitle={`Leakage (µA), ${scatter?.n ?? 0} held-out parts`} testId="pred-vs-actual">
          {!scatter ? <EmptyState title="No predicted/actual pairs" /> : <>
            <ScatterPlot height={230} points={scatter.points} xLabel="predicted 168h (µA)" yLabel="actual 168h (µA)" />
            <div className="grid grid-cols-2 gap-x-4 text-sm mt-2">
              <span>MAE <strong>{fmt(scatter.mae, 3)} µA</strong></span><span>RMSE <strong>{fmt(scatter.rmse, 3)} µA</strong></span>
              <span>Linear baseline MAE <strong>{fmt(scatter.linMae, 3)} µA</strong></span><span>90% interval coverage <strong>{pct(scatter.coverage)}</strong></span>
            </div>
            {lr && <p className="text-xs text-muted mt-1">Run-level: MAE {fmt(lr.model.mae, 3)}, RMSE {fmt(lr.model.rmse, 3)} µA.</p>}
          </>}
        </Card>
      </div>

      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-5">
        <Card title="Decision cost" subtitle="FN-weighted cost of the persisted held-out decisions; thresholds stay as trained" testId="cost-panel"
          actions={<div className="flex items-center gap-2 text-sm">
            <label>FN weight <input type="number" min={0} step={1} value={fn ?? ''} onChange={e => setFn(Number(e.target.value))} className="w-16 rounded border border-hairline px-1" aria-label="FN weight" /></label>
            <label>FP weight <input type="number" min={0} step={0.5} value={fp ?? ''} onChange={e => setFp(Number(e.target.value))} className="w-16 rounded border border-hairline px-1" aria-label="FP weight" /></label>
            <Button onClick={() => loadMetrics({ fnCost: fn ?? undefined, fpCost: fp ?? undefined })}>Apply</Button>
          </div>}>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <StatTile label="Model cost" value={int(m.weightedCost)} tone={m.weightedCost < flagAll ? 'pass' : 'reject'} colorValue sub={`FN×${m.fnCost} + FP×${m.fpCost}`} />
            <StatTile label="Flag everything" value={int(flagAll)} sub="every part to review" />
            <StatTile label="Flag nothing" value={int(flagNone)} sub="every defect escapes" />
          </div>
          {curve && curve.points.length > 0 ? (
            <LineChart height={220} xLabel="Module A threshold (Module B at its chosen k)" yLabel="weighted cost"
              xTicks={curve.points.filter((_, i) => i % Math.ceil(curve.points.length / 6) === 0).map(p => ({ x: p.threshold, label: p.threshold.toFixed(1) }))}
              series={[{ id: 'cost', label: 'cost vs threshold', color: 'var(--status-info)', width: 2, points: curve.points.map(p => ({ x: p.threshold, y: p.weightedCost })) },
                ...(curve.chosenThreshold != null ? [{ id: 'chosen', label: `chosen threshold ${curve.chosenThreshold.toFixed(3)}`, color: 'var(--accent)', points: [{ x: curve.chosenThreshold, y: Math.min(...curve.points.map(p => p.weightedCost)) }] }] : [])]}
              hLines={[{ y: flagAll, label: 'flag everything', color: 'var(--status-reject)' }]} />
          ) : <EmptyState title="No cost curve" />}
        </Card>
        <Card title="Top explanation features" subtitle={`Module B, LightGBM total gain share (${PARAM_LABEL[fiParam]} model)`} testId="feature-importance"
          actions={<select aria-label="Model" value={fiParam} onChange={e => setFiParam(e.target.value as Param)} className="rounded-lg border border-hairline px-2 py-1 text-sm">
            {PARAMS.filter(p => fi[p]).map(p => <option key={p} value={p}>{PARAM_LABEL[p]}</option>)}</select>}>
          {(fi[fiParam] ?? []).length === 0 ? <EmptyState title="No feature importance" reason="The model artifact is not available." /> :
            (fi[fiParam] ?? []).slice(0, 8).map((f, i) => <BarRow key={f.label} label={f.label} value={f.share} max={(fi[fiParam] ?? [])[0].share} text={pct(f.share)} tone={i < 2 ? 'reject' : 'review'} />)}
        </Card>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-5">
        <Card title="Model registry" subtitle="Screening runs persisted by the pipeline" testId="registry">
          {report.registry.length === 0 ? <EmptyState title="No screening runs" /> : (
            <table className="w-full text-md">
              <thead><tr className="text-left text-sm text-muted border-b border-hairline"><th className="py-2 font-semibold">Run</th><th className="font-semibold">Status</th><th className="font-semibold">Trained</th><th className="font-semibold text-right">Held-out recall</th></tr></thead>
              <tbody>{report.registry.map(r => (
                <tr key={r.id} className="border-b border-hairline-subtle">
                  <td className="py-2 font-mono text-sm" title={r.artifact ?? undefined}>{r.id.slice(0, 8)}</td>
                  <td><span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${r.current ? 'bg-accept-bg text-accept' : 'bg-panel text-muted'}`}>{r.current ? 'Current' : 'Archived'}</span></td>
                  <td className="text-sm">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="text-right tabular-nums">{pct(r.held_out_recall)}</td>
                </tr>))}</tbody>
            </table>
          )}
          {report.registry.length === 1 && <p className="text-xs text-muted mt-2">Only the current run exists; earlier runs appear here after the pipeline is re-run.</p>}
        </Card>
        <Card title="Judge mode" subtitle="Train on a file, predict on a file, score against truth (identical to python -m evaluation.score)">
          <JudgeScreen />
        </Card>
      </div>
    </div>
  );
};
