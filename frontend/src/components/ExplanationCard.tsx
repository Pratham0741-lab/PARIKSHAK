'use client';

import React, { useState } from 'react';
import { ExplanationResponse } from '@/lib/types';
import { RiskCategoryBadge, VerdictBadge } from '@/components/VerdictBadge';
import {
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Activity,
  Layers,
  Zap,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

interface ExplanationCardProps {
  explanation: ExplanationResponse;
}

export function ExplanationCard({ explanation }: ExplanationCardProps) {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(true);

  const getActionColor = (action: string) => {
    if (action === 'QUARANTINE_FLIGHT_HARDWARE') return 'bg-rose-500/10 text-rose-400 border-rose-500/30';
    if (action === 'HOLD_FOR_96H_CHECK') return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  };

  return (
    <div className="aerospace-panel p-6">
      {/* Header */}
      <div className="flex flex-col justify-between gap-4 border-b border-slate-800 pb-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-cyan-400 uppercase tracking-widest">
              Local Deterministic Explainability Engine
            </span>
            <span className="rounded bg-cyan-950/40 px-2 py-0.5 text-[10px] font-mono text-cyan-400 border border-cyan-500/30">
              ZERO-LLM AUDIT COMPLIANT
            </span>
          </div>
          <h2 className="mt-1 text-lg font-bold font-mono text-slate-100">
            Inspection Verdict Rationale: {explanation.serial_number}
          </h2>
        </div>

        <div className="flex items-center gap-3">
          <RiskCategoryBadge category={explanation.risk_category} />
          <VerdictBadge verdict={explanation.verdict} />
        </div>
      </div>

      {/* Recommended Action & Primary Driver Bar */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 font-mono">
          <div className="text-[10px] text-slate-400 uppercase">Recommended QA Action</div>
          <div className={`mt-1 inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-semibold ${getActionColor(explanation.recommended_action)}`}>
            <span>{explanation.recommended_action.replace(/_/g, ' ')}</span>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 font-mono">
          <div className="text-[10px] text-slate-400 uppercase">Primary Driver Parameter</div>
          <div className="mt-1 flex items-center gap-1.5 text-xs font-semibold text-cyan-300">
            <Zap className="h-3.5 w-3.5 text-cyan-400" />
            <span>{explanation.primary_parameter}</span>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 font-mono">
          <div className="text-[10px] text-slate-400 uppercase">Implied Drift Velocity</div>
          <div className="mt-1 text-xs font-semibold text-slate-200">
            <span className={explanation.drift_metrics.drift_slope_ua_per_hr >= 0.12 ? 'text-amber-400 font-bold' : 'text-slate-300'}>
              {explanation.drift_metrics.drift_slope_ua_per_hr.toFixed(4)} uA/hr
            </span>
          </div>
        </div>
      </div>

      {/* Executive Summary */}
      <div className="mt-4 rounded-lg border border-cyan-500/20 bg-cyan-950/20 p-4">
        <div className="flex items-center gap-2 text-xs font-mono font-semibold text-cyan-300">
          <FileText className="h-4 w-4 text-cyan-400" />
          <span>EXECUTIVE SUMMARY</span>
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-slate-300 font-sans">
          {explanation.executive_summary}
        </p>
      </div>

      {/* Parameter Excursions & MAD Breakdown Table */}
      <div className="mt-6">
        <h3 className="text-xs font-mono font-semibold text-slate-200 uppercase tracking-wider mb-2">
          Parametric Lot Excursions (MAD Normalization)
        </h3>
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-xs font-mono">
            <thead className="border-b border-slate-800 bg-slate-900/80 text-[10px] text-slate-400 uppercase">
              <tr>
                <th className="py-2.5 px-3">Parameter</th>
                <th className="py-2.5 px-3 text-right">0h Reading</th>
                <th className="py-2.5 px-3 text-right">24h Reading</th>
                <th className="py-2.5 px-3 text-right">0h Lot Median</th>
                <th className="py-2.5 px-3 text-right">Scale (MAD)</th>
                <th className="py-2.5 px-3 text-right">Peak Excursion</th>
                <th className="py-2.5 px-3 text-center">Safety Ceiling</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-slate-900/30">
              {Object.entries(explanation.parameter_metrics).map(([key, data]) => {
                const val0 = data.intervals?.[0]?.value;
                const val24 = data.intervals?.[24]?.value;
                const med0 = data.intervals?.[0]?.lot_median;
                const mad0 = data.intervals?.[0]?.lot_mad;
                const maxZ = data.max_abs_z_mad;

                return (
                  <tr key={key} className="hover:bg-slate-800/30">
                    <td className="py-2.5 px-3 font-semibold text-slate-200">{data.label}</td>
                    <td className="py-2.5 px-3 text-right text-slate-300">{val0 ?? 'N/A'}</td>
                    <td className="py-2.5 px-3 text-right text-slate-300">{val24 ?? 'N/A'}</td>
                    <td className="py-2.5 px-3 text-right text-slate-400">{med0 ?? 'N/A'}</td>
                    <td className="py-2.5 px-3 text-right text-slate-400">{mad0 ?? 'N/A'}</td>
                    <td className="py-2.5 px-3 text-right">
                      <span
                        className={`font-semibold ${
                          maxZ >= 4.0
                            ? 'text-rose-400'
                            : maxZ >= 2.5
                            ? 'text-amber-400'
                            : 'text-emerald-400'
                        }`}
                      >
                        {maxZ.toFixed(2)} MAD
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-center text-slate-400">{data.ceiling}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Collapsible Technical Markdown Details */}
      <div className="mt-6 border-t border-slate-800 pt-4">
        <button
          onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
          className="flex w-full items-center justify-between text-xs font-mono text-slate-400 hover:text-slate-200 transition-colors"
        >
          <span className="font-semibold uppercase tracking-wider">
            Technical Audit Trace (Markdown Report)
          </span>
          {showTechnicalDetails ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>

        {showTechnicalDetails && (
          <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/70 p-4 font-mono text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap leading-relaxed">
            {explanation.technical_justification}
          </div>
        )}
      </div>
    </div>
  );
}
