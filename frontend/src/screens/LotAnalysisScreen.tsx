import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { INTERVALS, PARAMS, PARAM_LABEL, PARAM_UNIT, Param, lotLimit, lotParam } from '../data/types';
import { Card, EmptyState, StatTile, StatusPill, fmt, int, pct } from '../components/ui/primitives';
import { LineChart } from '../components/ui/charts';
import { lotRates, lotStatusRule, robust, STATUS_Z, valuesAt } from '../lib/lotStats';

type Method = 'sum_positive' | 'max_positive' | 'mean_abs';
const METHODS: { id: Method; label: string; note: string }[] = [
  { id: 'sum_positive', label: 'Sum of positive robust z (production)', note: 'the statistic Module A uses (chosen on development seeds)' },
  { id: 'max_positive', label: 'Largest positive robust z', note: 'what-if: single worst parameter' },
  { id: 'mean_abs', label: 'Mean |robust z|', note: 'what-if: symmetric, counts low values too' },
];

export const LotAnalysisScreen: React.FC = () => {
  const { activeLot, lots, parts, predictions, config, setActiveLot } = useStore();
  const navigate = useNavigate();
  const param = lotParam(activeLot);
  const unit = PARAM_UNIT[param];
  const limit = lotLimit(activeLot, param, config?.datasheetLimits);
  const used = ((activeLot?.sourceDetail?.parameters_used as string[] | undefined) ?? [...PARAMS]) as Param[];

  const perT = useMemo(() => INTERVALS.map(t => ({ t, r: robust(valuesAt(parts, param, t)), mean: (() => {
    const v = valuesAt(parts, param, t); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  })() })), [parts, param]);
  const decision = perT.find(x => x.t === 24)?.r ?? null;
  const flags = useMemo(() => {
    let a = 0, b = 0;
    for (const p of parts) { if (predictions[p.partId]?.moduleA?.flag) a++; if (predictions[p.partId]?.moduleB?.flag) b++; }
    return { a, b };
  }, [parts, predictions]);
  const measurements = perT.filter(x => x.r).length;

  // ---- Module A what-if (does not change verdicts)
  const prodThreshold = useMemo(() => Object.values(predictions).find(p => p.moduleA?.threshold != null)?.moduleA?.threshold ?? null, [predictions]);
  const [method, setMethod] = useState<Method>('sum_positive');
  const [thr, setThr] = useState<number>(2);
  useEffect(() => { if (prodThreshold != null) setThr(Number(prodThreshold.toFixed(2))); }, [prodThreshold]);
  const scored = useMemo(() => parts.map(p => {
    const z = Object.entries(predictions[p.partId]?.moduleA?.robustZ ?? {}).filter(([k]) => used.includes(k as Param)).map(([, v]) => v as number);
    if (z.length === 0) return { id: p.partId, s: null as number | null };
    const s = method === 'sum_positive' ? z.reduce((a, v) => a + Math.max(0, v), 0)
      : method === 'max_positive' ? Math.max(0, ...z) : z.reduce((a, v) => a + Math.abs(v), 0) / z.length;
    return { id: p.partId, s };
  }), [parts, predictions, method, used]);
  const nScored = scored.filter(x => x.s != null).length;
  const whatIf = scored.filter(x => x.s != null && (x.s as number) >= thr).length;
  const prodCount = method === 'sum_positive' ? flags.a : null;

  // ---- Lot mean trend + drift watch (rule: lot mean rate 0h->24h above the lot's calculated safety slope)
  const slope = useMemo(() => {
    const s = parts.map(p => predictions[p.partId]?.moduleB?.perParam[param]?.safetySlope).find(v => v != null);
    return s ?? null;
  }, [parts, predictions, param]);
  const m0 = perT[0].mean, m24 = perT[1].mean;
  const meanRate = m0 != null && m24 != null ? (m24 - m0) / 24 : null;
  const driftWatch = meanRate != null && slope != null && meanRate > slope;

  const statusOf = useMemo(() => lotStatusRule(lots), [lots]);
  const recent = useMemo(() => [...lots].sort((a, b) => b.createdAt.localeCompare(a.createdAt) || b.lotNumber.localeCompare(a.lotNumber)).slice(0, 12), [lots]);

  if (!activeLot) return <EmptyState title="No lot loaded" />;
  const dataMax = Math.max(...perT.map(x => (x.r ? x.r.median + x.r.mad : 0))) || 1;
  const limitOnScale = limit != null && limit <= 2 * dataMax; // a far-away limit is noted, not drawn
  const maxMed = (limitOnScale ? Math.max(dataMax, limit as number) : dataMax) * 1.1;

  return (
    <div className="space-y-5 max-w-[1500px]" data-testid="lot-analysis">
      <section className="bg-workspace border border-hairline rounded-card px-5 py-4 flex items-center gap-10">
        <div><div className="text-xs font-semibold text-muted uppercase">Lot</div><div className="text-card font-semibold">{activeLot.lotNumber}</div></div>
        <div className="text-sm text-muted">{int(parts.length)} parts · {measurements} measurement points · {activeLot.source === 'CSV_INGEST' ? 'ingested' : 'synthetic'} · created {new Date(activeLot.createdAt).toLocaleDateString()}</div>
      </section>

      <div className="grid grid-cols-4 gap-4">
        <StatTile label={`Lot median at 24h (${PARAM_LABEL[param]})`} value={decision ? `${fmt(decision.median)} ${unit}` : 'n/a'} sub={decision ? `${decision.n} parts with a 24h reading` : 'no 24h readings'} />
        <StatTile label="MAD at 24h" value={decision ? `${fmt(decision.mad)} ${unit}` : 'n/a'} sub="median absolute deviation" />
        <StatTile label="Anomalies (Module A)" value={int(flags.a)} tone="review" sub={parts.length ? `${pct(flags.a / parts.length)} of parts` : undefined} />
        <StatTile label="Drift flags (Module B)" value={int(flags.b)} tone="review" sub={parts.length ? `${pct(flags.b / parts.length)} of parts` : undefined} />
      </div>

      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-5">
        <Card title="Lot distribution by measurement" subtitle={`Median ± MAD of ${PARAM_LABEL[param]} (${unit}) at each burn-in point`} testId="per-time-bars">
          <div className="space-y-5 pt-2">
            {perT.map(({ t, r }) => (
              <div key={t} className="grid grid-cols-[48px_1fr_120px] items-center gap-3">
                <span className="text-md font-semibold">{t}h</span>
                <div className="relative h-3 bg-panel rounded-full">
                  {r && <>
                    <div className="absolute inset-y-0 left-0 rounded-full bg-info" style={{ width: `${(100 * r.median) / maxMed}%` }} />
                    <div className="absolute inset-y-[-3px] bg-info/25 rounded" style={{ left: `${(100 * Math.max(0, r.median - r.mad)) / maxMed}%`, width: `${(100 * 2 * r.mad) / maxMed}%` }} title={`median ± MAD`} />
                  </>}
                  {limit != null && limitOnScale && <div className="absolute inset-y-[-5px] w-0.5 bg-[var(--chart-limit-static)]" style={{ left: `${Math.min(100, (100 * limit) / maxMed)}%` }} title={`static limit ${limit} ${unit}`} />}
                </div>
                <span className="text-right text-md font-semibold tabular-nums">{r ? `${fmt(r.median)} ± ${fmt(r.mad)} ${unit}` : 'no readings'}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted mt-4">Bar: median; light band: median ± MAD; dark tick: static limit ({limit ?? 'n/a'} {unit}{limit != null && !limitOnScale ? ', off scale' : ''}). 96h/168h are shown for traceability; decisions use 0h/24h only.</p>
        </Card>

        <Card title="Lot mean trend" subtitle={`${PARAM_LABEL[param]} (${unit}) over burn-in hours`} testId="lot-mean-trend"
          actions={meanRate != null && slope != null ? (
            <StatusPill status={driftWatch ? 'REVIEW' : 'PASS'} label={driftWatch ? 'Drift watch' : 'Within slope'} />
          ) : undefined}>
          <LineChart height={240} xLabel="burn-in hours" yLabel={`mean ${PARAM_LABEL[param]} (${unit})`}
            xTicks={INTERVALS.map(t => ({ x: t, label: `${t}h` }))}
            series={[{ id: 'mean', label: 'lot mean', color: 'var(--status-info)', points: perT.map(x => ({ x: x.t, y: x.mean })) },
              ...(slope != null && m0 != null ? [{ id: 'slope', label: `lot safety slope ${slope.toFixed(4)} ${unit}/h (from 0h mean)`, color: 'var(--chart-limit-safety)', dashed: true,
                points: [{ x: 0, y: m0 }, { x: 168, y: m0 + slope * 168 }] }] : [])]} />
          <p className="text-xs text-muted mt-2">Drift watch rule: lot mean rate 0h→24h ({meanRate != null ? `${meanRate.toFixed(4)} ${unit}/h` : 'n/a'}) above the lot's calculated safety slope ({slope != null ? `${slope.toFixed(4)} ${unit}/h` : 'n/a'}).</p>
        </Card>
      </div>

      <Card title="Module A sensitivity (what-if)" subtitle="Recomputed live from the backend's per-parameter robust z; does not change any verdict" testId="module-a-whatif">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-6 items-start">
          <div className="space-y-3">
            <label className="block text-sm font-medium">Decision statistic
              <select value={method} onChange={e => setMethod(e.target.value as Method)} className="mt-1 block w-full rounded-lg border border-hairline px-2 py-1.5">
                {METHODS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
              <span className="text-xs text-muted">{METHODS.find(m => m.id === method)?.note}</span>
            </label>
            <label className="block text-sm font-medium">Threshold: <span className="tabular-nums">{thr.toFixed(2)}</span>
              <input type="range" min={0} max={10} step={0.05} value={thr} onChange={e => setThr(Number(e.target.value))} className="block w-full mt-1" aria-label="Module A threshold" />
              <span className="text-xs text-muted">production threshold {prodThreshold != null ? prodThreshold.toFixed(3) : 'n/a'} (chosen by FN-weighted cost on training lots)</span>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <StatTile label="Parts above threshold" value={int(whatIf)} sub={nScored ? `${pct(whatIf / nScored)} of ${nScored} scored parts` : 'no Module A scores'} tone="info" testId="whatif-count" />
            <StatTile label="Module A flags (production)" value={prodCount != null ? int(prodCount) : 'n/a'} sub={prodCount != null ? 'persisted model verdicts' : 'production uses the sum statistic'} />
          </div>
        </div>
      </Card>

      <Card title="Recent lots" subtitle={`Rates from model verdicts; status rule: "Monitoring" if the Module A or Module B flag rate is above the cross-lot median by more than ${STATUS_Z} robust SDs`} testId="recent-lots">
        <table className="w-full text-md">
          <thead><tr className="text-left text-sm text-muted border-b border-hairline">
            <th className="py-2 font-semibold">Lot</th><th className="font-semibold text-right">Parts</th><th className="font-semibold text-right">Anomaly rate (A)</th>
            <th className="font-semibold text-right">Drift rate (B)</th><th className="font-semibold text-right">Flag rate</th><th className="font-semibold pl-6">Status</th>
          </tr></thead>
          <tbody>
            {recent.map(l => {
              const r = lotRates(l), s = statusOf(l);
              return (
                <tr key={l.id} className={`border-b border-hairline-subtle ${l.id === activeLot.id ? 'bg-info-bg' : 'hover:bg-panel'}`}>
                  <td className="py-2"><button className="font-semibold hover:underline" onClick={() => { setActiveLot(l.id); navigate('/lot'); }}>{l.lotNumber}</button></td>
                  <td className="text-right tabular-nums">{int(r.n)}</td>
                  <td className="text-right tabular-nums">{pct(r.anomalyRate)}</td>
                  <td className="text-right tabular-nums">{pct(r.driftRate)}</td>
                  <td className="text-right tabular-nums">{pct(r.flagRate)}</td>
                  <td className="pl-6"><span title={s.why} className={`font-semibold ${s.status === 'Monitoring' ? 'text-review' : s.status === 'Stable' ? 'text-accept' : 'text-muted'}`}>{s.status}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
};
