import React, { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Activity, BarChart3, Boxes, ClipboardList, Download, FileText, HelpCircle, LayoutGrid, LineChart as LineIcon, RefreshCw, Sliders, Upload,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';
import { DEFAULT_API_URL } from '../../data/api';
import { getHealth } from '../../data/modelApi';
import { PARAM_LABEL, PARAM_UNIT, Param, lotParam } from '../../data/types';
import { KeyboardHelpModal } from './KeyboardHelpModal';
import { DevControlModal } from './DevControlModal';
import { DecisionDrawer } from '../ui/DecisionDrawer';
import { Button, ErrorState, LoadingState } from '../ui/primitives';
import { download, lotCsv } from '../../lib/exportCsv';
import { sourceTag } from '../../lib/sourceTag';

export const NAV = [
  { to: '/', label: 'Overview', icon: LayoutGrid, end: true },
  { to: '/lot', label: 'Lot Analysis', icon: LineIcon },
  { to: '/part', label: 'Part Detail', icon: Boxes },
  { to: '/review', label: 'Review Queue', icon: ClipboardList },
  { to: '/trends', label: 'Trends', icon: Activity },
  { to: '/model', label: 'Model Performance', icon: BarChart3 },
  { to: '/ingest', label: 'Ingest', icon: Upload },
  { to: '/reports', label: 'Reports', icon: FileText },
];

const TITLES: Record<string, { title: string; sub: string }> = {
  '': { title: 'Screening Overview', sub: 'Verdicts for the selected lot from Module A (lot-relative outliers) and Module B (drift forecast).' },
  lot: { title: 'Lot Analysis', sub: 'Lot behaviour, robust spread and burn-in progression.' },
  part: { title: 'Part Detail', sub: 'Evidence behind the model decision for one part.' },
  review: { title: 'Review Queue', sub: 'Flagged parts awaiting an inspector decision.' },
  trends: { title: 'Trends & Reliability', sub: 'Flag rates across lots and measurement risk by burn-in point.' },
  model: { title: 'Model Performance', sub: 'Held-out validation of Module A, Module B and the combined decision; judge mode.' },
  ingest: { title: 'Ingest', sub: 'Validate, store and screen a new lot from CSV.' },
  reports: { title: 'Reports', sub: 'Lot report, export and audit log.' },
};

const SystemBlock: React.FC = () => {
  const { mode, activeLot, config, metrics, lots, setDevModalOpen, setShortcutModalOpen, inspector, setInspector, judgeSource } = useStore();
  const location = useLocation();
  const [health, setHealth] = useState<boolean | null>(null);
  const [recompute, setRecompute] = useState<{ ok: boolean; text: string; bad: string[] } | null>(null);
  useEffect(() => {
    if (mode === 'offline') return;
    let alive = true;
    const tick = () => getHealth().then(h => alive && setHealth(h));
    tick();
    const t = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [mode]);

  const tag = sourceTag(activeLot, mode) + (location.pathname.startsWith('/model') && judgeSource ? ` · judge mode: ${judgeSource}` : '');

  // Debug: recompute visible metrics and lot counts from raw rows (backend /debug/recompute) and compare.
  const runRecompute = async () => {
    try {
      const r = await (await fetch(`${DEFAULT_API_URL}/debug/recompute`)).json();
      const b = r.benchmark;
      const rows: [string, number | null | undefined, number | null | undefined][] = [];
      if (metrics) rows.push(['recall', metrics.recall, b.recall], ['precision', metrics.precision, b.precision], ['F2', metrics.f2, b.f2_score],
        ['weighted cost', metrics.weightedCost, b.weighted_cost], ['TP', metrics.tp, b.true_positives], ['FP', metrics.fp, b.false_positives],
        ['FN', metrics.fn, b.false_negatives], ['TN', metrics.tn, b.true_negatives], ['MAE', metrics.maeLeakage, b.module_b_mae_leakage],
        ['linear MAE', metrics.linearMaeLeakage, b.linear_baseline_mae_leakage]);
      for (const l of lots) {
        const c = r.lots[l.id] ?? { pass: 0, review: 0, reject: 0 };
        rows.push([`${l.lotNumber} pass`, l.passCount, c.pass], [`${l.lotNumber} review`, l.reviewCount, c.review], [`${l.lotNumber} reject`, l.rejectCount, c.reject]);
      }
      const bad = rows.filter(([, s, v]) => s == null || v == null || Math.abs(s - v) >= 1e-4).map(([k, s, v]) => `${k}: shown ${s} vs raw ${v}`);
      setRecompute({ ok: bad.length === 0, bad, text: bad.length ? `${bad.length} of ${rows.length} values differ from raw data` : `all ${rows.length} visible values match raw data` });
    } catch (e) {
      setRecompute({ ok: false, bad: [], text: e instanceof Error ? e.message : String(e) });
    }
  };

  const run = config?.latestRun;
  return (
    <div className="mt-auto px-4 pb-4 text-xs text-[#C9D3E3] space-y-2" data-testid="data-source">
      <div className="text-[13px] font-semibold tracking-wide text-[#8FA3C2] uppercase">System</div>
      <div>
        <div className="text-[#8FA3C2]">Data source</div>
        <div className="text-white font-medium break-words" data-testid="data-source-tag" title={(activeLot?.sourceDetail as { sha256?: string } | null)?.sha256}>{tag}</div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${mode === 'offline' ? 'bg-[#F5A524]' : health ? 'bg-[#34D399]' : health === false ? 'bg-[#F87171]' : 'bg-[#8FA3C2]'}`} />
        <span data-testid="api-health">{mode === 'offline' ? 'offline demo (in-browser)' : health ? 'API connected' : health === false ? 'API unreachable' : 'checking API…'}</span>
      </div>
      <div>
        <div className="text-[#8FA3C2]">Model</div>
        <div className="text-white font-mono text-[11px] break-all" title={run?.protocol}>{run ? `run ${run.id.slice(0, 8)}` : 'n/a (no screening run)'}</div>
        {run && <div>trained {new Date(run.createdAt).toLocaleString()}</div>}
      </div>
      <label className="block">
        <span className="text-[#8FA3C2]">Inspector ID</span>
        <input value={inspector} onChange={e => setInspector(e.target.value)} placeholder="set badge ID"
          className="mt-0.5 block w-full rounded-md bg-navy-deep border border-[#2A4772] px-2 py-1 text-white placeholder:text-[#6B7FA3] focus:outline-none focus:border-cyan" />
      </label>
      <div className="flex flex-wrap gap-1.5 pt-1">
        {mode !== 'offline' && (
          <button onClick={runRecompute} className="inline-flex items-center gap-1 rounded-md bg-navy-deep px-2 py-1 hover:text-white" title="Debug: recompute visible metrics from raw rows">
            <RefreshCw size={12} /> Recompute
          </button>
        )}
        <button onClick={() => setDevModalOpen(true)} className="inline-flex items-center gap-1 rounded-md bg-navy-deep px-2 py-1 hover:text-white"><Sliders size={12} /> Source</button>
        <button onClick={() => setShortcutModalOpen(true)} className="inline-flex items-center gap-1 rounded-md bg-navy-deep px-2 py-1 hover:text-white" aria-label="Keyboard shortcuts"><HelpCircle size={12} /> Keys</button>
      </div>
      {recompute && (
        <div className={recompute.ok ? 'text-[#34D399]' : 'text-[#F87171]'} data-testid="recompute-result" title={recompute.bad.join('\n')}>{recompute.text}</div>
      )}
    </div>
  );
};

const Header: React.FC = () => {
  const { lots, activeLot, setActiveLot, parts, predictions } = useStore();
  const location = useLocation();
  const key = location.pathname.split('/')[1] ?? '';
  const t = TITLES[key] ?? TITLES[''];
  const param: Param = lotParam(activeLot);
  const used = (activeLot?.sourceDetail?.parameters_used as string[] | undefined) ?? ['leakage_current_ua', 'iddq_ma', 'propagation_delay_ns'];
  const assumed = (f: string) => activeLot?.conditionsAssumed.includes(f) ? <span className="ml-1 text-[10px] text-[#F5C27A]" title="Not supplied; documented default">(assumed)</span> : null;
  return (
    <header className="bg-navy text-white px-8 pt-3 pb-4 shrink-0">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <nav aria-label="Breadcrumb" className="text-sm text-[#C9D3E3]">PARIKSHAK <span className="mx-1">/</span> {t.title}</nav>
          <h1 className="text-title font-semibold mt-0.5">{t.title}</h1>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {lots.length > 0 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-[#C9D3E3]">Lot</span>
              <select value={activeLot?.id ?? ''} onChange={e => setActiveLot(e.target.value)} aria-label="Select lot"
                className="bg-navy-deep border border-[#2A4772] rounded-lg px-2 py-1.5 text-white max-w-[240px] focus:outline-none focus:border-cyan">
                {lots.map(l => <option key={l.id} value={l.id}>{l.lotNumber}{l.source === 'CSV_INGEST' ? ' (ingested)' : ''}</option>)}
              </select>
            </label>
          )}
          <Button variant="primary" disabled={!activeLot || parts.length === 0} onClick={() => activeLot && download(`${activeLot.lotNumber}_screening.csv`, lotCsv(activeLot, parts, predictions))}>
            <Download size={15} /> Export
          </Button>
        </div>
      </div>
      {activeLot && (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-[#C9D3E3]" data-testid="test-conditions">
          <span>Parameter <strong className="text-white">{PARAM_LABEL[param]}</strong>{assumed('test_parameter')}</span>
          <span>Unit <strong className="text-white">{PARAM_UNIT[param]}</strong>{activeLot.unit && activeLot.testParameter === param ? assumed('unit') : null}</span>
          <span>Temperature <strong className="text-white">{activeLot.temperatureC == null ? 'n/a' : `${activeLot.temperatureC} °C`}</strong>{assumed('temperature_c')}</span>
          <span>Parameters used <strong className="text-white" data-testid="parameters-used">{used.map(p => PARAM_LABEL[p as Param] ?? p).join(', ')}</strong></span>
          {activeLot.supplier && <span>Supplier <strong className="text-white">{activeLot.supplier}</strong></span>}
        </div>
      )}
      <p className="sr-only">{t.sub}</p>
    </header>
  );
};

export const AppShell: React.FC = () => {
  const { fetchInitialData, isLoading, error, mode, setDevModalOpen } = useStore();
  useKeyboardShortcuts();
  useEffect(() => { fetchInitialData(); }, [fetchInitialData]);
  const location = useLocation();
  const key = location.pathname.split('/')[1] ?? '';

  return (
    <div className="h-screen w-screen flex bg-pagebg text-main overflow-hidden">
      <aside className="w-[248px] shrink-0 bg-navy flex flex-col" aria-label="Main navigation">
        <div className="px-5 pt-6 pb-4">
          <div className="text-white text-[26px] font-bold tracking-wide leading-none">PARIKSHAK</div>
          <div className="text-[11px] font-semibold tracking-widest text-[#8FA3C2] mt-1.5 uppercase">Burn-in anomaly screening</div>
          <div className="h-px bg-[#2A4772] mt-4" />
        </div>
        <nav className="px-3 space-y-1.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg pl-3 pr-2 py-2.5 text-[15px] font-medium border-l-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan ${
                isActive || (to === '/part' && location.pathname.startsWith('/part')) ? 'bg-navy-deep text-white border-cyan' : 'bg-navy-deep/60 text-[#C9D3E3] border-transparent hover:text-white'}`}>
              <Icon size={17} /> {label}
            </NavLink>
          ))}
        </nav>
        <SystemBlock />
      </aside>
      <div className="flex-1 min-w-0 flex flex-col">
        <Header />
        {mode === 'offline' && (
          <div className="bg-review-bg text-review text-sm px-8 py-1.5 border-b border-review/20">
            Offline demo: synthetic data screened by simple client rules on 0h/24h readings (not the ML model).{' '}
            <button className="underline" onClick={() => setDevModalOpen(true)}>Switch to backend</button>
          </div>
        )}
        <main className="flex-1 min-h-0 overflow-auto px-8 py-6" id={`screen-${key || 'overview'}`}>
          {error && <div className="mb-4"><ErrorState message={error} onRetry={fetchInitialData} /></div>}
          {isLoading ? <LoadingState what="lots" /> : <Outlet />}
        </main>
      </div>
      <KeyboardHelpModal />
      <DevControlModal />
      <DecisionDrawer />
    </div>
  );
};
