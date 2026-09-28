'use client';

import React, { useState } from 'react';
import { api } from '@/lib/api';
import { ReviewDisposition, ReviewActionResponse } from '@/lib/types';
import { ShieldCheck, X, AlertCircle, CheckCircle2 } from 'lucide-react';

interface ReviewActionModalProps {
  componentId: string;
  serialNumber: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (review: ReviewActionResponse) => void;
}

export function ReviewActionModal({
  componentId,
  serialNumber,
  isOpen,
  onClose,
  onSuccess,
}: ReviewActionModalProps) {
  const [inspectorId, setInspectorId] = useState('ISRO-QA-CHIEF');
  const [disposition, setDisposition] = useState<ReviewDisposition>('QUARANTINED');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inspectorId.trim() || !notes.trim()) {
      setError('Both Inspector Badge ID and Engineering Justification notes are required.');
      return;
    }

    try {
      setSubmitting(true);
      setError(null);
      const res = await api.submitReviewAction(componentId, {
        inspector_id: inspectorId.trim(),
        disposition,
        inspector_notes: notes.trim(),
      });
      onSuccess(res);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to submit inspector action.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="aerospace-panel w-full max-w-lg overflow-hidden border border-slate-700 bg-slate-900 p-6 shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-400" />
            <h3 className="font-mono text-base font-bold text-slate-100">
              QA Inspector Review Action
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="rounded border border-slate-800 bg-slate-950/60 p-2.5 font-mono text-xs text-slate-300">
            Target Component: <span className="font-bold text-cyan-400">{serialNumber}</span>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded border border-rose-500/30 bg-rose-950/40 p-3 text-xs text-rose-300">
              <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Inspector Badge ID */}
          <div>
            <label className="block font-mono text-xs text-slate-400 uppercase tracking-wider mb-1">
              Inspector Badge ID / Engineer Key *
            </label>
            <input
              type="text"
              value={inspectorId}
              onChange={(e) => setInspectorId(e.target.value)}
              placeholder="e.g. ENG-ISRO-412"
              required
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          {/* Disposition Dropdown */}
          <div>
            <label className="block font-mono text-xs text-slate-400 uppercase tracking-wider mb-1">
              Human Disposition Decision *
            </label>
            <select
              value={disposition}
              onChange={(e) => setDisposition(e.target.value as ReviewDisposition)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ACCEPTED">ACCEPTED (Cleared for Spaceflight Payload)</option>
              <option value="QUARANTINED">QUARANTINED (High Drift / Latent Flaw Risk)</option>
              <option value="RE_TEST">RE_TEST (Mandate Extended 96h/168h Burn-In)</option>
            </select>
          </div>

          {/* Justification Notes */}
          <div>
            <label className="block font-mono text-xs text-slate-400 uppercase tracking-wider mb-1">
              Engineering Justification & Audit Notes *
            </label>
            <textarea
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Detail MAD excursion rationale, thermal kinetics assessment, and flight assurance decision..."
              required
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-sans text-xs text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-700 px-4 py-2 font-mono text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-md border border-cyan-500/50 bg-cyan-600 px-4 py-2 font-mono text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50 glow-cyan transition-colors"
            >
              {submitting ? 'Recording Action...' : 'Commit Review Audit'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
