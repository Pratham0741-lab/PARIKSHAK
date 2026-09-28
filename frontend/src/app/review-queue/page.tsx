'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ShieldAlert,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Search,
  CheckCircle2,
  Cpu,
  Layers,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { api } from '@/lib/api';
import { ComponentListItem, ReviewActionResponse } from '@/lib/types';
import { VerdictBadge } from '@/components/VerdictBadge';
import { ReviewActionModal } from '@/components/ReviewActionModal';

export default function ReviewQueuePage() {
  const [reviewComponents, setReviewComponents] = useState<ComponentListItem[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Modal State
  const [selectedComp, setSelectedComp] = useState<{ id: string; serial: string } | null>(null);
  const [bannerMessage, setBannerMessage] = useState<string | null>(null);

  const loadQueue = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getComponents({ verdict: 'REVIEW', page_size: 100 });
      setReviewComponents(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(err?.message || 'Failed to load review queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  const handleReviewSuccess = (review: ReviewActionResponse) => {
    setBannerMessage(
      `Component review confirmed: ${review.inspector_id} set disposition to ${review.disposition}.`
    );
    loadQueue();
  };

  const filteredItems = reviewComponents.filter(
    (c) =>
      c.serial_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.lot_number.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 lg:px-8">
      {/* Title & Refresh */}
      <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-amber-400 uppercase tracking-widest">
            <AlertTriangle className="h-4 w-4" />
            <span>Mission Assurance & Flight Clearance</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-100 sm:text-3xl font-mono">
            QA Review & Override Queue
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Dedicated triage workbench for borderline components flagged by Module A or Module B requiring senior engineering disposition.
          </p>
        </div>

        <button
          onClick={loadQueue}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700 hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Queue</span>
        </button>
      </div>

      {bannerMessage && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/30 p-4 font-mono text-xs text-emerald-300">
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          <span>{bannerMessage}</span>
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-rose-500/30 bg-rose-950/30 p-4 text-sm text-rose-300 font-mono">
          {error}
        </div>
      )}

      {/* Queue Summary Banner */}
      <div className="aerospace-panel mb-6 p-4">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-amber-500/30 bg-amber-950/40 text-amber-400">
              <ShieldAlert className="h-5 w-5" />
            </div>
            <div>
              <div className="text-xs font-mono text-slate-400 uppercase">Pending Review Items</div>
              <div className="text-xl font-bold font-mono text-amber-400">
                {totalCount} Units Awaiting Human Clearance
              </div>
            </div>
          </div>

          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search serial or lot..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full sm:w-64 rounded-md border border-slate-700 bg-slate-900/80 pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-amber-500 focus:outline-none font-mono"
            />
          </div>
        </div>
      </div>

      {/* Grid of Review Part Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filteredItems.map((comp) => (
          <div
            key={comp.id}
            className="aerospace-panel flex flex-col justify-between p-5 hover:border-amber-500/40 transition-colors"
          >
            <div>
              <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
                <span className="font-mono text-sm font-bold text-slate-100 flex items-center gap-1.5">
                  <Cpu className="h-4 w-4 text-amber-400" />
                  <span>{comp.serial_number}</span>
                </span>
                <VerdictBadge verdict={comp.verdict} />
              </div>

              <div className="space-y-2 text-xs font-mono text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-500">Lot:</span>
                  <span className="font-semibold text-slate-200">{comp.lot_number}</span>
                </div>

                <div className="flex justify-between">
                  <span className="text-slate-500">Defect Signature:</span>
                  <span className="text-amber-300 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-500/20 text-[10px]">
                    {comp.ground_truth_label}
                  </span>
                </div>

                <div className="flex justify-between">
                  <span className="text-slate-500">Module A Score:</span>
                  <span className="text-cyan-300 font-semibold">
                    {comp.module_a_score !== null ? comp.module_a_score.toFixed(3) : 'N/A'}
                  </span>
                </div>

                <div className="flex justify-between">
                  <span className="text-slate-500">168h Forecast:</span>
                  <span className={comp.pred_leakage_168h && comp.pred_leakage_168h >= 35.0 ? 'text-amber-400 font-bold' : 'text-slate-300'}>
                    {comp.pred_leakage_168h !== null ? `${comp.pred_leakage_168h.toFixed(2)} uA` : 'N/A'}
                  </span>
                </div>

                <div className="flex justify-between">
                  <span className="text-slate-500">Drift Slope:</span>
                  <span className="text-slate-400">
                    {comp.drift_slope_ua_per_hr !== null ? `${comp.drift_slope_ua_per_hr.toFixed(4)} uA/h` : 'N/A'}
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between gap-2 border-t border-slate-800 pt-3">
              <Link
                href={`/components/${comp.id}`}
                className="inline-flex items-center gap-1 text-[11px] font-mono text-cyan-400 hover:underline"
              >
                <span>Full Profile</span>
                <ArrowRight className="h-3 w-3" />
              </Link>

              <button
                onClick={() => setSelectedComp({ id: comp.id, serial: comp.serial_number })}
                className="inline-flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-950/50 px-3 py-1.5 font-mono text-xs font-semibold text-amber-300 hover:bg-amber-900/50 transition-colors"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>Review Action</span>
              </button>
            </div>
          </div>
        ))}

        {filteredItems.length === 0 && !loading && (
          <div className="col-span-full aerospace-panel p-12 text-center font-mono text-xs text-slate-500">
            No components currently pending in the QA Review Queue.
          </div>
        )}
      </div>

      {/* Review Modal */}
      {selectedComp && (
        <ReviewActionModal
          componentId={selectedComp.id}
          serialNumber={selectedComp.serial}
          isOpen={true}
          onClose={() => setSelectedComp(null)}
          onSuccess={handleReviewSuccess}
        />
      )}
    </div>
  );
}
