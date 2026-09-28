'use client';

import React, { useState } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Area,
} from 'recharts';
import { ModelPredictionItem, ReadingItem, IntervalStats } from '@/lib/types';
import { Activity } from 'lucide-react';

interface DriftTrajectoryChartProps {
  readings: ReadingItem[];
  lotEnvelope: Record<string, Record<number, IntervalStats>> | null;
  prediction: ModelPredictionItem | null;
}

export function DriftTrajectoryChart({
  readings,
  lotEnvelope,
  prediction,
}: DriftTrajectoryChartProps) {
  const [paramKey, setParamKey] = useState<'leakage_current_ua' | 'iddq_ma' | 'propagation_delay_ns'>(
    'leakage_current_ua'
  );

  const paramConfig = {
    leakage_current_ua: {
      label: 'Leakage Current (I_leak)',
      unit: 'uA',
      ceiling: 50.0,
      predictedVal: prediction?.pred_leakage_168h,
    },
    iddq_ma: {
      label: 'Quiescent Supply (I_DDQ)',
      unit: 'mA',
      ceiling: 5.0,
      predictedVal: prediction?.pred_iddq_168h,
    },
    propagation_delay_ns: {
      label: 'Propagation Delay (t_pd)',
      unit: 'ns',
      ceiling: 8.0,
      predictedVal: prediction?.pred_delay_168h,
    },
  }[paramKey];

  // Construct interval data points for chart
  const readingMap = new Map<number, number>();
  readings.forEach((r) => {
    readingMap.set(r.interval_hours, r[paramKey]);
  });

  const intervals = [0, 24, 96, 168];
  const chartData = intervals.map((h) => {
    const actualVal = readingMap.get(h) ?? null;
    const lotStats = lotEnvelope?.[paramKey]?.[h];
    const lotMedian = lotStats ? lotStats.median : null;
    const mad = lotStats ? lotStats.mad : null;
    const upperMad = lotMedian !== null && mad !== null ? Number((lotMedian + 2 * mad).toFixed(3)) : null;
    const lowerMad = lotMedian !== null && mad !== null ? Number(Math.max(0, lotMedian - 2 * mad).toFixed(3)) : null;

    // Predicted projection line: connects 24h reading with 168h forecasted value
    let forecastVal: number | null = null;
    if (h === 24) {
      forecastVal = readingMap.get(24) ?? null;
    } else if (h === 168 && paramConfig.predictedVal !== undefined) {
      forecastVal = paramConfig.predictedVal;
    }

    return {
      interval: `${h}h`,
      hours: h,
      actual: actualVal,
      lotMedian,
      upperMad,
      lowerMad,
      forecast: forecastVal,
    };
  });

  return (
    <div className="w-full">
      {/* Parameter selector tabs */}
      <div className="mb-4 flex flex-wrap gap-2">
        {[
          { key: 'leakage_current_ua', label: 'Leakage (I_leak)' },
          { key: 'iddq_ma', label: 'IDDQ Current' },
          { key: 'propagation_delay_ns', label: 'Propagation Delay' },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setParamKey(tab.key as any)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-mono transition-colors ${
              paramKey === tab.key
                ? 'border border-cyan-500/50 bg-cyan-950/40 text-cyan-300 font-semibold'
                : 'border border-slate-800 bg-slate-900/60 text-slate-400 hover:text-slate-200'
            }`}
          >
            <Activity className="h-3 w-3" />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Legend & Summary Info */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-cyan-400"></span>
            <span className="text-slate-200 font-semibold">Measured Trajectory</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="h-0.5 w-4 bg-amber-400 border-t border-dashed border-amber-400"></span>
            <span className="text-amber-300">Module B 168h Forecast</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="h-2 w-4 rounded bg-cyan-500/20 border border-cyan-500/40"></span>
            <span className="text-slate-400">Lot ±2×MAD Band</span>
          </div>
        </div>

        <div className="text-rose-400 font-semibold">
          Ceiling: {paramConfig.ceiling} {paramConfig.unit}
        </div>
      </div>

      {/* Trajectory Composed Chart */}
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="interval" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }} />
            <YAxis stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (active && payload && payload.length) {
                  const d = payload[0].payload;
                  return (
                    <div className="rounded-lg border border-slate-700 bg-slate-900/95 p-3 text-xs shadow-xl backdrop-blur font-mono">
                      <div className="font-bold text-cyan-400 border-b border-slate-800 pb-1 mb-1">
                        Interval {label}
                      </div>
                      <div className="space-y-1 text-slate-300">
                        {d.actual !== null && (
                          <div className="flex justify-between gap-4">
                            <span>Measured Value:</span>
                            <span className="font-bold text-white">{d.actual} {paramConfig.unit}</span>
                          </div>
                        )}
                        {d.forecast !== null && (
                          <div className="flex justify-between gap-4">
                            <span className="text-amber-300">168h Forecast:</span>
                            <span className="font-bold text-amber-400">{d.forecast} {paramConfig.unit}</span>
                          </div>
                        )}
                        {d.lotMedian !== null && (
                          <div className="flex justify-between gap-4">
                            <span>Lot Median:</span>
                            <span className="text-slate-400">{d.lotMedian} {paramConfig.unit}</span>
                          </div>
                        )}
                        {d.upperMad !== null && (
                          <div className="flex justify-between gap-4">
                            <span>Lot Upper Band (+2σ):</span>
                            <span className="text-cyan-300">{d.upperMad} {paramConfig.unit}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }
                return null;
              }}
            />

            {/* Shaded lot normal envelope */}
            <Area
              type="monotone"
              dataKey="upperMad"
              stroke="none"
              fill="#06b6d4"
              fillOpacity={0.12}
            />
            <Area
              type="monotone"
              dataKey="lowerMad"
              stroke="none"
              fill="#090d16"
              fillOpacity={1}
            />

            {/* Actual measured points */}
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#22d3ee"
              strokeWidth={3}
              dot={{ fill: '#06b6d4', r: 5 }}
              activeDot={{ r: 7 }}
              connectNulls
            />

            {/* Module B Forecast Trajectory (Dashed) */}
            <Line
              type="linear"
              dataKey="forecast"
              stroke="#f59e0b"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ fill: '#f59e0b', r: 5 }}
              connectNulls
            />

            {/* Datasheet Limit Ceiling */}
            <ReferenceLine
              y={paramConfig.ceiling}
              stroke="#f43f5e"
              strokeDasharray="4 4"
              strokeWidth={2}
              label={{
                value: `CEILING ${paramConfig.ceiling} ${paramConfig.unit}`,
                fill: '#f43f5e',
                fontSize: 10,
                position: 'insideTopRight',
                fontFamily: 'monospace',
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
