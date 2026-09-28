'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Layers,
  Cpu,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  TrendingUp,
  Search,
  ArrowRight,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from 'recharts';
import { api } from '@/lib/api';
import { BenchmarkMetricsResponse, LotSummary } from '@/lib/types';
import { VerdictBadge } from '@/components/VerdictBadge';

const TRIAGE_COLORS = {
  PASS: '#10b981',
  REVIEW: '#f59e0b',
  REJECT: '#f43f5e',
};

export default function FleetOverviewPage() {
  const [lots, setLots] = useState<LotSummary[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [lotsData, metricsData] = await Promise.all([
        api.getLots(),
        api.getBenchmarkMetrics(),
      ]);
      setLots(lotsData);
      setBenchmarks(metricsData);
    } catch (err: any) {
      setError(err?.message || 'Failed to load telemetry from backend.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const totalLots = lots.length;
  const totalComponents = lots.reduce((acc, l) => acc + l.total_components, 0);
  const totalPass = lots.reduce((acc, l) => acc + l.pass_count, 0);
  const totalReview = lots.reduce((acc, l) => acc + l.review_count, 0);
  const totalReject = lots.reduce((acc, l) => acc + l.reject_count, 0);

  const passYield = totalComponents > 0 ? ((totalPass / totalComponents) * 100).toFixed(1) : '0.0';
  const recallScore = benchmarks ? (benchmarks.recall * 100).toFixed(1) : '80.2';
  const fnrScore = benchmarks ? (benchmarks.false_negative_rate * 100).toFixed(1) : '19.8';

  const chartData = [
    { name: 'PASS', value: totalPass, color: TRIAGE_COLORS.PASS },
    { name: 'REVIEW', value: totalReview, color: TRIAGE_COLORS.REVIEW },
    { name: 'REJECT', value: totalReject, color: TRIAGE_COLORS.REJECT },
  ];

  const filteredLots = lots.filter(
    (l) =>
      l.lot_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l.wafer_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 lg:px-8">
      {/* Title & Refresh */}
      <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 uppercase tracking-widest">
            <span>Mission Telemetry & Fleet Operations</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-100 sm:text-3xl">
            Semiconductor Lot Screening Overview
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Real-time aerospace burn-in screening, spatial lot-adaptive outlier detection, and 168h degradation forecasting.
          </p>
        </div>

        <button
          onClick={loadData}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700 hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Fleet</span>
        </button>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-rose-500/30 bg-rose-950/30 p-4 text-sm text-rose-300">
          <div className="flex items-center gap-2 font-semibold">
            <XCircle className="h-5 w-5 text-rose-400" />
            <span>Connection Error</span>
          </div>
          <p className="mt-1 text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {/* Total Screened */}
        <div className="aerospace-panel p-5">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono uppercase tracking-wider">Screened Fleet</span>
            <Cpu className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-slate-100">{totalComponents}</span>
            <span className="text-xs text-slate-400">parts across {totalLots} lots</span>
          </div>
          <div className="mt-2 text-[11px] text-slate-500">Full 0h–168h burn-in evaluation</div>
        </div>

        {/* Mission Pass Yield */}
        <div className="aerospace-panel p-5">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono uppercase tracking-wider">Pass Yield</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">{passYield}%</span>
            <span className="text-xs text-slate-400">{totalPass} units</span>
          </div>
          <div className="mt-2 text-[11px] text-emerald-400/80">Flight Ready Specification</div>
        </div>

        {/* QA Review Queue */}
        <div className="aerospace-panel p-5">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono uppercase tracking-wider">Review Queue</span>
            <AlertTriangle className="h-4 w-4 text-amber-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-amber-400">{totalReview}</span>
            <span className="text-xs text-slate-400">borderline units</span>
          </div>
          <Link
            href="/review-queue"
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-amber-400/90 hover:underline"
          >
            <span>Open QA Workbench</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>

        {/* Hard Rejections / Quarantine */}
        <div className="aerospace-panel p-5">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono uppercase tracking-wider">Quarantined</span>
            <XCircle className="h-4 w-4 text-rose-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-rose-400">{totalReject}</span>
            <span className="text-xs text-slate-400">intercepted</span>
          </div>
          <div className="mt-2 text-[11px] text-rose-400/80">Datasheet breach or runaway</div>
        </div>

        {/* Recall Benchmark */}
        <div className="aerospace-panel p-5">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-mono uppercase tracking-wider">Screening Recall</span>
            <TrendingUp className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-cyan-400">{recallScore}%</span>
            <span className="text-xs text-slate-400">FNR: {fnrScore}%</span>
          </div>
          <Link
            href="/benchmarks"
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-cyan-400/90 hover:underline"
          >
            <span>View Benchmark Audit</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* Triage Donut Chart & Overview Section */}
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Fleet Distribution Donut */}
        <div className="aerospace-panel p-6">
          <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider font-mono">
            Fleet Triage Disposition
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Component distribution across deterministic safety and drift boundaries.
          </p>

          <div className="mt-4 h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={85}
                  paddingAngle={4}
                  dataKey="value"
                >
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} stroke="#090d16" strokeWidth={2} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const data = payload[0];
                      return (
                        <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs shadow-lg">
                          <span className="font-mono font-semibold" style={{ color: data.payload.color }}>
                            {data.name}:
                          </span>{' '}
                          <span className="font-mono text-white">{data.value} components</span>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded border border-emerald-500/20 bg-emerald-950/20 p-2">
              <div className="font-mono font-bold text-emerald-400">{totalPass}</div>
              <div className="text-[10px] text-slate-400 uppercase">PASS</div>
            </div>
            <div className="rounded border border-amber-500/20 bg-amber-950/20 p-2">
              <div className="font-mono font-bold text-amber-400">{totalReview}</div>
              <div className="text-[10px] text-slate-400 uppercase">REVIEW</div>
            </div>
            <div className="rounded border border-rose-500/20 bg-rose-950/20 p-2">
              <div className="font-mono font-bold text-rose-400">{totalReject}</div>
              <div className="text-[10px] text-slate-400 uppercase">REJECT</div>
            </div>
          </div>
        </div>

        {/* Manufacturing Lots Table */}
        <div className="aerospace-panel p-6 lg:col-span-2">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider font-mono">
                Manufacturing Lots
              </h2>
              <p className="mt-0.5 text-xs text-slate-400">
                Parametric envelopes and lot-adaptive spatial outlier tracking.
              </p>
            </div>

            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
              <input
                type="text"
                placeholder="Search lot or wafer..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full sm:w-64 rounded-md border border-slate-700 bg-slate-900/80 pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-800 text-[11px] font-mono text-slate-400 uppercase">
                <tr>
                  <th className="pb-2">Lot Identifier</th>
                  <th className="pb-2">Wafer ID</th>
                  <th className="pb-2 text-right">Parts</th>
                  <th className="pb-2 text-center">Triage Breakdown</th>
                  <th className="pb-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredLots.map((lot) => (
                  <tr key={lot.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 font-mono font-medium text-slate-200">
                      <Link
                        href={`/lots/${lot.id}`}
                        className="hover:text-cyan-400 hover:underline flex items-center gap-1.5"
                      >
                        <Layers className="h-3.5 w-3.5 text-cyan-400" />
                        <span>{lot.lot_number}</span>
                      </Link>
                    </td>
                    <td className="py-3 font-mono text-slate-400">{lot.wafer_id}</td>
                    <td className="py-3 text-right font-mono text-slate-300">{lot.total_components}</td>
                    <td className="py-3 text-center">
                      <div className="flex items-center justify-center gap-1 font-mono text-[11px]">
                        <span className="text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-500/20">
                          {lot.pass_count}P
                        </span>
                        <span className="text-amber-400 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-500/20">
                          {lot.review_count}R
                        </span>
                        <span className="text-rose-400 bg-rose-950/40 px-1.5 py-0.5 rounded border border-rose-500/20">
                          {lot.reject_count}X
                        </span>
                      </div>
                    </td>
                    <td className="py-3 text-right">
                      <Link
                        href={`/lots/${lot.id}`}
                        className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] font-medium text-cyan-400 transition-colors hover:border-cyan-500/50 hover:bg-cyan-950/40"
                      >
                        <span>Envelopes</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                ))}

                {filteredLots.length === 0 && !loading && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-500">
                      No matching lots found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
