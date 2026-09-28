'use client';

import React, { useEffect, useState, use } from 'react';
import Link from 'next/link';
import {
  Cpu,
  ArrowLeft,
  Activity,
  ShieldCheck,
  Clock,
  Layers,
  Zap,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  FileCheck,
} from 'lucide-react';
import { api } from '@/lib/api';
import {
  ComponentProfileResponse,
  ExplanationResponse,
  ReviewActionResponse,
} from '@/lib/types';
import { VerdictBadge } from '@/components/VerdictBadge';
import { DriftTrajectoryChart } from '@/components/DriftTrajectoryChart';
import { ExplanationCard } from '@/components/ExplanationCard';
import { ReviewActionModal } from '@/components/ReviewActionModal';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ComponentDetailPage({ params }: PageProps) {
  const { id } = use(params);

  const [profile, setProfile] = useState<ComponentProfileResponse | null>(null);
  const [explanation, setExplanation] = useState<ExplanationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReviewModalOpen, setIsReviewModalOpen] = useState(false);
  const [auditSuccessBanner, setAuditSuccessBanner] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [profData, expData] = await Promise.all([
        api.getComponentProfile(id),
        api.getComponentExplanation(id),
      ]);
      setProfile(profData);
      setExplanation(expData);
    } catch (err: any) {
      setError(err?.message || 'Failed to load component telemetry.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [id]);

  const handleReviewSuccess = (review: ReviewActionResponse) => {
    setAuditSuccessBanner(
      `Audit review recorded successfully by ${review.inspector_id}: Disposition set to ${review.disposition}.`
    );
    loadData();
  };

  if (loading && !profile) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-16 text-center font-mono text-cyan-400">
        Loading component telemetry and running deterministic explainability engine...
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-16">
        <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-6 text-sm text-rose-300 font-mono">
          <div className="flex items-center gap-2 font-bold">
            <XCircle className="h-5 w-5 text-rose-400" />
            <span>Telemetry Acquisition Error</span>
          </div>
          <p className="mt-2 text-xs">{error || 'Component record not found.'}</p>
          <Link href="/" className="mt-4 inline-block text-xs text-cyan-400 underline">
            Return to Fleet Overview
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 lg:px-8">
      {/* Navigation Breadcrumb */}
      <div className="mb-4 flex items-center justify-between">
        <Link
          href={`/lots/${profile.lot_id}`}
          className="inline-flex items-center gap-1.5 text-xs font-mono text-cyan-400 hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back to Lot {profile.lot_number}</span>
        </Link>

        <button
          onClick={() => setIsReviewModalOpen(true)}
          className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/50 bg-cyan-950/60 px-4 py-2 font-mono text-xs font-semibold text-cyan-300 hover:bg-cyan-900/60 transition-colors glow-cyan"
        >
          <ShieldCheck className="h-4 w-4" />
          <span>Perform QA Review / Override</span>
        </button>
      </div>

      {auditSuccessBanner && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/30 p-4 font-mono text-xs text-emerald-300">
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          <span>{auditSuccessBanner}</span>
        </div>
      )}

      {/* Component Header Identity Card */}
      <div className="aerospace-panel mb-8 p-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2 font-mono text-xs text-slate-400">
              <Cpu className="h-4 w-4 text-cyan-400" />
              <span>PART TELEMETRY & SCREENING TRACE</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold font-mono tracking-tight text-white sm:text-3xl">
                {profile.serial_number}
              </h1>
              <VerdictBadge verdict={profile.prediction?.verdict} />
              {profile.is_datasheet_breached && (
                <span className="rounded bg-rose-950/60 px-2 py-0.5 font-mono text-[10px] font-bold text-rose-300 border border-rose-500/40">
                  DATASHEET BREACHED
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs font-mono sm:grid-cols-4">
            <div className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
              <div className="text-[10px] text-slate-500 uppercase">Manufacturing Lot</div>
              <div className="font-semibold text-slate-200">{profile.lot_number}</div>
            </div>

            <div className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
              <div className="text-[10px] text-slate-500 uppercase">Wafer ID</div>
              <div className="font-semibold text-slate-200">{profile.wafer_id}</div>
            </div>

            <div className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
              <div className="text-[10px] text-slate-500 uppercase">Ground Truth Defect</div>
              <div className="font-semibold text-amber-400">{profile.ground_truth_label}</div>
            </div>

            <div className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
              <div className="text-[10px] text-slate-500 uppercase">Module A Score</div>
              <div className="font-semibold text-cyan-300">
                {profile.prediction ? profile.prediction.module_a_score.toFixed(3) : 'N/A'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Grid: Trajectory Chart & Raw Readings */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* Trajectory Multi-Line Chart */}
        <div className="aerospace-panel p-6 lg:col-span-2">
          <div className="mb-4">
            <h2 className="text-sm font-semibold font-mono text-slate-100 uppercase tracking-wider">
              Parametric Trajectory & 168h Degradation Forecast
            </h2>
            <p className="text-xs text-slate-400">
              Measured interval progression overlaid with shaded lot normal envelope and LightGBM 168h forecast trajectory.
            </p>
          </div>

          <DriftTrajectoryChart
            readings={profile.readings}
            lotEnvelope={profile.lot_envelope}
            prediction={profile.prediction}
          />
        </div>

        {/* Raw Measurements Table */}
        <div className="aerospace-panel p-6">
          <h2 className="text-sm font-semibold font-mono text-slate-100 uppercase tracking-wider mb-2">
            ATE Test Readings
          </h2>
          <p className="text-xs text-slate-400 mb-4">
            Sensor telemetry recorded at discrete burn-in milestones.
          </p>

          <div className="space-y-3 font-mono text-xs">
            {profile.readings.map((r) => (
              <div
                key={r.interval_hours}
                className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 hover:bg-slate-800/40 transition-colors"
              >
                <div className="flex items-center justify-between border-b border-slate-800 pb-1 mb-2">
                  <span className="font-bold text-cyan-400">{r.interval_hours}h Milestone</span>
                  <span className="text-[10px] text-slate-500">
                    {new Date(r.recorded_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-slate-300 text-[11px]">
                  <div>
                    <div className="text-slate-500 text-[9px] uppercase">Leakage</div>
                    <div className={r.leakage_current_ua >= 50.0 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {r.leakage_current_ua.toFixed(2)} uA
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500 text-[9px] uppercase">IDDQ</div>
                    <div className={r.iddq_ma >= 5.0 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {r.iddq_ma.toFixed(3)} mA
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500 text-[9px] uppercase">Delay</div>
                    <div className={r.propagation_delay_ns >= 8.0 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {r.propagation_delay_ns.toFixed(2)} ns
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Deterministic Explainability Panel */}
      {explanation && (
        <div className="mt-8">
          <ExplanationCard explanation={explanation} />
        </div>
      )}

      {/* QA Review Audit Ledger */}
      <div className="aerospace-panel mt-8 p-6">
        <div className="flex items-center gap-2 mb-2">
          <FileCheck className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-semibold font-mono text-slate-100 uppercase tracking-wider">
            QA Inspector Audit Trail ({profile.reviews.length} Records)
          </h2>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Immutable records of human review actions, disposition overrides, and flight assurance justifications.
        </p>

        {profile.reviews.length > 0 ? (
          <div className="space-y-3 font-mono text-xs">
            {profile.reviews.map((rev) => (
              <div
                key={rev.id}
                className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-200">Badge ID: {rev.inspector_id}</span>
                    <span className="rounded bg-cyan-950/60 px-2 py-0.5 text-[10px] text-cyan-300 border border-cyan-500/30">
                      Disposition: {rev.disposition}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {new Date(rev.reviewed_at).toLocaleString()}
                  </div>
                </div>
                <p className="text-slate-300 font-sans text-xs whitespace-pre-wrap">
                  {rev.inspector_notes}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-800 p-6 text-center text-xs font-mono text-slate-500">
            No human inspector reviews recorded yet. Click "Perform QA Review / Override" to record an audit action.
          </div>
        )}
      </div>

      {/* Review Modal */}
      <ReviewActionModal
        componentId={profile.id}
        serialNumber={profile.serial_number}
        isOpen={isReviewModalOpen}
        onClose={() => setIsReviewModalOpen(false)}
        onSuccess={handleReviewSuccess}
      />
    </div>
  );
}
