import React from 'react';
import { ScreeningVerdict, RiskCategory, ReviewDisposition } from '@/lib/types';

interface VerdictBadgeProps {
  verdict?: ScreeningVerdict | string | null;
  className?: string;
}

export function VerdictBadge({ verdict, className = '' }: VerdictBadgeProps) {
  if (!verdict) {
    return (
      <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-mono font-medium bg-slate-800 text-slate-400 border border-slate-700 ${className}`}>
        PENDING
      </span>
    );
  }

  const v = String(verdict).toUpperCase();

  if (v === 'PASS') {
    return (
      <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 ${className}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
        PASS
      </span>
    );
  }

  if (v === 'REVIEW') {
    return (
      <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-mono font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30 ${className}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
        REVIEW
      </span>
    );
  }

  if (v === 'REJECT') {
    return (
      <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-mono font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30 ${className}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-rose-400"></span>
        REJECT
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-mono font-medium bg-slate-800 text-slate-300 border border-slate-700 ${className}`}>
      {v}
    </span>
  );
}

export function RiskCategoryBadge({ category }: { category: RiskCategory | string }) {
  const cat = String(category).toUpperCase();

  if (cat === 'CRITICAL_RUNAWAY') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-mono font-semibold bg-rose-950/60 text-rose-300 border border-rose-500/40 glow-rose">
        <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse"></span>
        CRITICAL RUNAWAY
      </span>
    );
  }

  if (cat === 'LATENT_LOT_OUTLIER') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-mono font-semibold bg-amber-950/60 text-amber-300 border border-amber-500/40">
        <span className="h-2 w-2 rounded-full bg-amber-500"></span>
        LATENT LOT OUTLIER
      </span>
    );
  }

  if (cat === 'SUBTLE_DEGRADATION') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-mono font-semibold bg-blue-950/60 text-cyan-300 border border-cyan-500/40">
        <span className="h-2 w-2 rounded-full bg-cyan-400"></span>
        SUBTLE DEGRADATION
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-mono font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-500/40">
      <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
      NOMINAL
    </span>
  );
}
