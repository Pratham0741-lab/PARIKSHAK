import React, { useEffect, useRef, useState } from 'react';
import { Download, Upload, AlertTriangle } from 'lucide-react';
import { useStore } from '../store/useStore';
import { judgeApi, JudgeMetrics, JudgeModelInfo, JudgePrediction, JudgeRow } from '../data/judgeApi';

/**
 * Judge mode: train on a file with 168h readings (labels optional), predict from 0h/24h-only files,
 * download the export and score it against ground truth. Every number shown comes from the backend;
 * `python -m evaluation.score` reproduces the scoring panel exactly (the command is shown).
 */
const pct = (x: number | null | undefined) => (x == null ? 'n/a' : `${(100 * x).toFixed(1)}%`);
const num = (x: number | null | undefined, d = 4) => (x == null ? 'n/a' : x.toFixed(d));

const FilePick: React.FC<{ label: string; disabled?: boolean; onFile: (text: string, name: string) => void }> = ({ label, disabled, onFile }) => {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={ref} type="file" accept=".csv,text/csv" className="hidden" data-testid={`file-${label}`}
        onChange={e => {
          const f = e.target.files?.[0];
          if (!f) return;
          const r = new FileReader();
          r.onload = ev => onFile(String(ev.target?.result ?? ''), f.name);
          r.readAsText(f);
          e.target.value = '';
        }} />
      <button disabled={disabled} onClick={() => ref.current?.click()}
        className="bg-toprail text-white px-2.5 py-1 flex items-center gap-1 disabled:opacity-40"><Upload size={12} /> {label}</button>
    </>
  );
};

const MetricsBlock: React.FC<{ m: JudgeMetrics }> = ({ m }) => {
  const d = m.detection, c = m.confusion_matrix;
  const flagAll = m.trivial_policies.flag_all_parts.weighted_cost;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-2">
        {[['Recall', pct(d.recall)], ['Precision', pct(d.precision)], ['F2', pct(d.f2)],
          [`MAE (${m.primary_parameter})`, num(m.regression.mae)], ['RMSE', num(m.regression.rmse)],
          ['90% PI coverage', pct(m.interval.coverage)],
          [`Cost (FN×${d.cost_config.fn_cost} + FP×${d.cost_config.fp_cost})`, d.weighted_cost.toFixed(0)],
          ['Flag-everything cost', flagAll.toFixed(0)]].map(([k, v]) => (
          <div key={k} className="border border-hairline bg-workspace p-2"><div className="text-muted text-[10px]">{k}</div><div className="text-main font-bold text-sm">{v}</div></div>
        ))}
      </div>
      {d.weighted_cost >= flagAll && (
        <div className="text-review flex gap-1 items-center"><AlertTriangle size={12} /> The model's cost is not below flagging every part on this data.</div>
      )}
      <table className="border-collapse" data-testid="confusion-matrix">
        <thead><tr><th className="px-2" /><th className="px-2 border border-hairline">flagged</th><th className="px-2 border border-hairline">passed</th></tr></thead>
        <tbody>
          <tr><td className="px-2 border border-hairline">defective</td><td className="px-2 border border-hairline text-accept">TP {c.tp}</td><td className="px-2 border border-hairline text-reject">FN {c.fn}</td></tr>
          <tr><td className="px-2 border border-hairline">good</td><td className="px-2 border border-hairline text-review">FP {c.fp}</td><td className="px-2 border border-hairline">TN {c.tn}</td></tr>
        </tbody>
      </table>
      <div className="text-muted">Scored {m.n_scored} of {m.n_predictions} predicted parts{m.n_excluded_no_truth ? ` (${m.n_excluded_no_truth} without truth excluded)` : ''}.</div>
    </div>
  );
};

export const JudgeScreen: React.FC = () => {
  const { mode } = useStore();
  const [model, setModel] = useState<JudgeModelInfo | null>(null);
  const [rule, setRule] = useState<{ id: string; text: string } | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const [pred, setPred] = useState<JudgePrediction | null>(null);
  const [score, setScore] = useState<JudgeMetrics | null>(null);
  const [open, setOpen] = useState<JudgeRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const offline = mode === 'offline';

  const refresh = async () => {
    const r = await judgeApi.model();
    setModel(r.model);
    setRule(r.rule);
  };
  useEffect(() => { if (!offline) refresh().catch(e => setError(String(e))); }, [offline]);

  const guard = (f: () => Promise<void>) => async () => {
    setError(null);
    try { await f(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const train = (text: string, name: string) => guard(async () => {
    const j = await judgeApi.train(text, name);
    setJob(`${name}: ${j.message}`);
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const s = await judgeApi.job(j.id);
      setJob(`${name}: ${s.message}`);
      if (s.state === 'failed') throw new Error(s.message);
      if (s.state === 'done') break;
    }
    setJob(null);
    setPred(null);
    setScore(null);
    await refresh();
  })();

  const predict = (text: string, name: string) => guard(async () => {
    setPred(await judgeApi.predict(text, name));
    setScore(null);
  })();

  const scoreTruth = (text: string, name: string) => guard(async () => setScore(await judgeApi.score(text, name)))();

  if (offline) return <div className="p-4 font-mono text-xs text-review">Judge mode needs the backend (training and scoring run there). Switch data source to Backend.</div>;

  return (
    <div className="w-full h-full overflow-auto bg-workspace font-mono text-xs p-4 space-y-4">
      {error && <div className="border border-reject/40 bg-reject-bg text-reject p-2" role="alert">{error}</div>}

      <section className="border border-hairline bg-panel p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-bold text-sm text-main">1. Train (file with 168h readings; labels optional)</span>
          <FilePick label="Train on CSV" disabled={!!job} onFile={train} />
        </div>
        {job && <div className="text-review">Training {job}</div>}
        {model ? (
          <div className="space-y-2">
            <div className="text-main" data-testid="trained-on">Trained on <strong>{model.file}</strong>, {model.n_parts} parts, {model.n_lots} lots
              <span className="text-muted"> (sha256 {model.data_sha256.slice(0, 12)}…, parameters {model.parameters.join(', ')})</span></div>
            <div>Labels used for thresholds: <strong>{model.label_source}</strong></div>
            <div className={model.single_lot ? 'text-review font-bold' : ''}>Honest estimate: out-of-fold, {model.evaluation_split}</div>
            <div className="text-muted">Thresholds: Module A {num(model.thresholds.threshold_a, 3)}, Module B k {num(model.thresholds.threshold_b, 3)} ({model.thresholds.source})</div>
            <MetricsBlock m={model.oof_metrics} />
          </div>
        ) : <div className="text-muted italic">No judge-mode model trained yet.</div>}
        {rule && (
          <div className="border border-hairline bg-workspace p-2 text-[11px]" data-testid="defect-rule">
            <div className="font-bold text-main">Definition of "defective" when a file has no labels ({rule.id}); never required at inference</div>
            <div className="text-muted">{rule.text}</div>
          </div>
        )}
      </section>

      <section className="border border-hairline bg-panel p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-bold text-sm text-main">2. Predict (0h/24h; 96h and 168h are ignored if present)</span>
          <div className="flex gap-2">
            <FilePick label="Predict from CSV" disabled={!model} onFile={predict} />
            {pred && <a href={judgeApi.exportUrl} className="border border-hairline px-2.5 py-1 flex items-center gap-1 text-main"><Download size={12} /> preds.csv</a>}
          </div>
        </div>
        {pred && (
          <>
            <div>{pred.input.file}: {pred.input.n_parts} parts, {pred.input.n_lots} lots, {pred.flagged} flagged
              {pred.input.ignored_intervals.length > 0 && <span className="text-muted"> (ignored intervals: {pred.input.ignored_intervals.join('h, ')}h)</span>}</div>
            <div className="max-h-[320px] overflow-auto border border-hairline">
              <table className="w-full text-left border-collapse">
                <thead className="bg-panel sticky top-0"><tr>{['Part_ID', 'Predicted_168h', 'PI_low', 'PI_high', 'Anomaly_score', 'Flag', 'Reason'].map(h => <th key={h} className="px-2 py-1 border-b border-hairline">{h}</th>)}</tr></thead>
                <tbody>
                  {pred.rows.map(r => (
                    <tr key={r.Part_ID} onClick={() => setOpen(r)} className={`cursor-pointer hover:bg-panel ${r.Flag ? 'text-reject' : ''}`}>
                      <td className="px-2">{r.Part_ID}</td><td className="px-2">{num(r.Predicted_168h)}</td><td className="px-2">{num(r.PI_low)}</td>
                      <td className="px-2">{num(r.PI_high)}</td><td className="px-2">{num(r.Anomaly_score, 3)}</td><td className="px-2">{r.Flag}</td>
                      <td className="px-2 truncate max-w-[520px]" title={r.Reason}>{r.Reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {open?.explanation && (
              <div className="border border-hairline bg-workspace p-2" data-testid="judge-explanation">
                <div className="font-bold text-main">{open.Part_ID}</div>
                <div>{open.Reason}</div>
                <div>Module A: score {num(open.explanation.module_a.score, 3)} vs threshold {num(open.explanation.module_a.threshold, 3)}; largest contribution {open.explanation.module_a.top_parameter} (robust z {num(open.explanation.module_a.robust_z, 2)}, 0/24h mean {num(open.explanation.module_a.value_0_24h_mean)} vs lot median {num(open.explanation.module_a.lot_median)})</div>
                <div>Module B: drift z {num(open.explanation.module_b.score, 3)} vs k {num(open.explanation.module_b.k, 3)}; {open.explanation.module_b.top_parameter} predicted rate {num(open.explanation.module_b.predicted_rate, 5)} vs safety slope {num(open.explanation.module_b.safety_slope, 5)}</div>
                <div>Static limit: observed breach {String(open.explanation.static_limit.observed_breach)}, forecast breach {String(open.explanation.static_limit.forecast_breach)}</div>
              </div>
            )}
          </>
        )}
      </section>

      <section className="border border-hairline bg-panel p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-bold text-sm text-main">3. Score against ground truth</span>
          <FilePick label="Upload truth CSV" disabled={!pred} onFile={scoreTruth} />
        </div>
        <div className="text-muted">Truth file: the same parts with 168h readings. It uses the file's labels if it has them, else {rule?.id ?? 'the labels-free rule'}.</div>
        {score && (
          <div className="space-y-2" data-testid="judge-score">
            <div>Truth: <strong>{score.truth_source}</strong></div>
            <MetricsBlock m={score} />
            <div className="text-muted">Reproduce: <code className="text-main">{score.reproduce_with}</code></div>
          </div>
        )}
      </section>
    </div>
  );
};
