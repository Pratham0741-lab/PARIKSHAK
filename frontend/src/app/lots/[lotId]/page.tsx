'use client';

import React, { useEffect, useState, use } from 'react';
import Link from 'next/link';
import {
  Layers,
  ArrowLeft,
  Activity,
  Sliders,
  Filter,
  ArrowRight,
  AlertTriangle,
  CheckCircle,
  XCircle,
  ExternalLink,
} from 'lucide-react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Area,
} from 'recharts';
import { api } from '@/lib/api';
import {
  ComponentListItem,
  LotDistributionResponse,
  ParameterDistribution,
  ScreeningVerdict,
} from '@/lib/types';
import { VerdictBadge } from '@/components/VerdictBadge';

interface PageProps {
  params: Promise<{ lotId: string }>;
}

export default function LotDistributionPage({ params }: PageProps) {
  const { lotId } = use(params);

  const [distribution, setDistribution] = useState<LotDistributionResponse | null>(null);
  const [components, setComponents] = useState<ComponentListItem[]>([]);
  const [selectedParamKey, setSelectedParamKey] = useState<'leakage_current_ua' | 'iddq_ma' | 'propagation_delay_ns'>(
    'leakage_current_ua'
  );
  const [verdictFilter, setVerdictFilter] = useState<string>('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadLotData() {
      try {
        setLoading(true);
        setError(null);

        const [distData, compData] = await Promise.all([
          api.getLotDistribution(lotId),
          api.getComponents({ lot_id: lotId, page_size: 100 }),
        ]);

        setDistribution(distData);
        setComponents(compData.items);
      } catch (err: any) {
        setError(err?.message || 'Failed to load lot distributions.');
      } finally {
        setLoading(false);
      }
    }

    loadLotData();
  }, [lotId]);

  const activeParam: ParameterDistribution | undefined = distribution?.parameters.find(
    (p) => p.parameter === selectedParamKey
  );

  const chartData =
    activeParam?.intervals.map((item) => ({
      interval: `${item.interval_hours}h`,
      min: item.min,
      p25: item.p25,
      median: item.median,
      p75: item.p75,
      max: item.max,
      mad: item.mad,
      madUpper: Number((item.median + 2 * item.mad).toFixed(3)),
      madLower: Number(Math.max(0, item.median - 2 * item.mad).toFixed(3)),
    })) || [];

  const filteredComponents = components.filter((c) => {
    if (verdictFilter === 'ALL') return true;
    return c.verdict === verdictFilter;
  });

  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 lg:px-8">
      {/* Back button and Header */}
      <div className="mb-6 flex flex-col gap-2">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-xs font-mono text-cyan-400 hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back to Fleet Overview</span>
        </Link>

        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-slate-400 uppercase tracking-widest">
                Parametric Distribution Envelope
              </span>
              {distribution && (
                <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-mono text-slate-300">
                  Wafer: {distribution.wafer_id}
                </span>
              )}
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100 sm:text-3xl font-mono">
              Lot {distribution?.lot_number || 'Loading...'}
            </h1>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-rose-500/30 bg-rose-950/30 p-4 text-sm text-rose-300">
          <div className="flex items-center gap-2 font-semibold">
            <XCircle className="h-5 w-5 text-rose-400" />
            <span>Error</span>
          </div>
          <p className="mt-1 text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {/* Metric Selector Tabs */}
      <div className="mb-6 flex flex-wrap gap-2 border-b border-slate-800 pb-4">
        {[
          { key: 'leakage_current_ua', label: 'Leakage Current (I_leak)', unit: 'uA', max: 50.0 },
          { key: 'iddq_ma', label: 'Quiescent Supply (I_DDQ)', unit: 'mA', max: 5.0 },
          { key: 'propagation_delay_ns', label: 'Propagation Delay (t_pd)', unit: 'ns', max: 8.0 },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setSelectedParamKey(tab.key as any)}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-medium font-mono transition-colors ${
              selectedParamKey === tab.key
                ? 'border border-cyan-500/50 bg-cyan-950/40 text-cyan-300 glow-cyan'
                : 'border border-slate-800 bg-slate-900/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Main Chart Section */}
      <div className="aerospace-panel p-6">
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-sm font-semibold font-mono text-slate-100 uppercase tracking-wider">
              {activeParam?.label || 'Parametric Trajectory'}
            </h2>
            <p className="text-xs text-slate-400">
              Robust Median with shaded ±2×MAD normal envelope against the absolute datasheet ceiling.
            </p>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-cyan-400"></span>
              <span className="text-slate-300">Lot Median</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded bg-cyan-500/20 border border-cyan-500/40"></span>
              <span className="text-slate-300">±2×MAD Boundary</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 bg-rose-500"></span>
              <span className="text-rose-400 font-semibold">Datasheet Max ({activeParam?.datasheet_max} {activeParam?.unit})</span>
            </div>
          </div>
        </div>

        {/* Recharts Composed Chart */}
        <div className="mt-6 h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 15, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="interval" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }} />
              <YAxis stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }} />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    const d = payload[0].payload;
                    return (
                      <div className="rounded-lg border border-slate-700 bg-slate-900/95 p-3 text-xs shadow-xl backdrop-blur font-mono">
                        <div className="font-bold text-cyan-400 border-b border-slate-800 pb-1 mb-1.5">
                          Interval {label}
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-300">
                          <div>Max Reading:</div>
                          <div className="text-right text-rose-400 font-bold">{d.max} {activeParam?.unit}</div>
                          <div>Upper MAD (+2σ):</div>
                          <div className="text-right text-cyan-300">{d.madUpper} {activeParam?.unit}</div>
                          <div>Lot Median:</div>
                          <div className="text-right text-white font-bold">{d.median} {activeParam?.unit}</div>
                          <div>Lower MAD (-2σ):</div>
                          <div className="text-right text-cyan-300">{d.madLower} {activeParam?.unit}</div>
                          <div>Min Reading:</div>
                          <div className="text-right text-slate-400">{d.min} {activeParam?.unit}</div>
                          <div>Scale (MAD):</div>
                          <div className="text-right text-slate-400">{d.mad} {activeParam?.unit}</div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />

              {/* Shaded MAD band */}
              <Area
                type="monotone"
                dataKey="madUpper"
                stroke="none"
                fill="#06b6d4"
                fillOpacity={0.12}
              />
              <Area
                type="monotone"
                dataKey="madLower"
                stroke="none"
                fill="#090d16"
                fillOpacity={1}
              />

              {/* Lot median line */}
              <Line
                type="monotone"
                dataKey="median"
                stroke="#06b6d4"
                strokeWidth={3}
                dot={{ fill: '#06b6d4', r: 4 }}
                activeDot={{ r: 6 }}
              />

              {/* Datasheet limit ceiling */}
              {activeParam?.datasheet_max && (
                <ReferenceLine
                  y={activeParam.datasheet_max}
                  stroke="#f43f5e"
                  strokeDasharray="4 4"
                  strokeWidth={2}
                  label={{
                    value: `CEILING ${activeParam.datasheet_max} ${activeParam.unit}`,
                    fill: '#f43f5e',
                    fontSize: 10,
                    position: 'insideTopRight',
                    fontFamily: 'monospace',
                  }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Components in this Lot Table */}
      <div className="aerospace-panel mt-8 p-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-sm font-semibold font-mono text-slate-100 uppercase tracking-wider">
              Components in Lot ({filteredComponents.length})
            </h2>
            <p className="text-xs text-slate-400">
              Individual units tracked through burn-in milestones. Click to inspect full degradation trajectory.
            </p>
          </div>

          {/* Verdict Filter Buttons */}
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900/80 p-1 text-xs">
            {['ALL', 'PASS', 'REVIEW', 'REJECT'].map((status) => (
              <button
                key={status}
                onClick={() => setVerdictFilter(status)}
                className={`rounded px-2.5 py-1 font-mono transition-colors ${
                  verdictFilter === status
                    ? 'bg-slate-800 text-cyan-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="border-b border-slate-800 text-[11px] text-slate-400 uppercase">
              <tr>
                <th className="pb-2">Serial Number</th>
                <th className="pb-2">Physical Defect Label</th>
                <th className="pb-2">Triage Verdict</th>
                <th className="pb-2 text-right">Module A Outlier Score</th>
                <th className="pb-2 text-right">168h Forecast (Leakage)</th>
                <th className="pb-2 text-right">Drift Velocity</th>
                <th className="pb-2 text-right">Inspect</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredComponents.map((comp) => (
                <tr key={comp.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-3 font-semibold text-slate-200">
                    <Link
                      href={`/components/${comp.id}`}
                      className="hover:text-cyan-400 hover:underline flex items-center gap-1.5"
                    >
                      <span>{comp.serial_number}</span>
                    </Link>
                  </td>
                  <td className="py-3">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-[10px] ${
                        comp.ground_truth_label === 'NORMAL'
                          ? 'bg-slate-800 text-slate-400'
                          : 'bg-amber-950/60 text-amber-300 border border-amber-500/30'
                      }`}
                    >
                      {comp.ground_truth_label}
                    </span>
                  </td>
                  <td className="py-3">
                    <VerdictBadge verdict={comp.verdict} />
                  </td>
                  <td className="py-3 text-right text-slate-300">
                    {comp.module_a_score !== null ? comp.module_a_score.toFixed(3) : 'N/A'}
                  </td>
                  <td className="py-3 text-right">
                    {comp.pred_leakage_168h !== null ? (
                      <span className={comp.pred_leakage_168h >= 50.0 ? 'text-rose-400 font-bold' : 'text-slate-300'}>
                        {comp.pred_leakage_168h.toFixed(2)} uA
                      </span>
                    ) : (
                      'N/A'
                    )}
                  </td>
                  <td className="py-3 text-right text-slate-400">
                    {comp.drift_slope_ua_per_hr !== null ? `${comp.drift_slope_ua_per_hr.toFixed(4)} uA/h` : 'N/A'}
                  </td>
                  <td className="py-3 text-right">
                    <Link
                      href={`/components/${comp.id}`}
                      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] font-medium text-cyan-400 hover:bg-cyan-950/40 hover:border-cyan-500/40 transition-colors"
                    >
                      <span>Trajectory</span>
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  </td>
                </tr>
              ))}

              {filteredComponents.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-slate-500">
                    No components found matching verdict filter '{verdictFilter}'.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
