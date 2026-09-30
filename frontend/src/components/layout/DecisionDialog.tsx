import React, { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { MIN_COMMENT_LENGTH, useStore } from '../../store/useStore';
import { PartStatus } from '../../data/types';

/** Every disposition change (single, bulk or keyboard) goes through here and needs a comment. */
export const DecisionDialog: React.FC = () => {
  const { decisionDialog, closeDecisionDialog, submitDecision, parts, inspector, mode } = useStore();
  const [status, setStatus] = useState<PartStatus>(decisionDialog.status);
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (decisionDialog.open) {
      setStatus(decisionDialog.status);
      setComment('');
      setError(null);
    }
  }, [decisionDialog.open, decisionDialog.status]);

  const serials = decisionDialog.partIds.map(id => parts.find(p => p.id === id)?.partId ?? id);
  const tooShort = comment.trim().length < MIN_COMMENT_LENGTH;

  const onSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      await submitDecision(status, comment, decisionDialog.partIds);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={decisionDialog.open} onOpenChange={o => !o && closeDecisionDialog()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[460px] bg-workspace border border-hairline p-4 z-50 focus:outline-none font-mono text-xs">
          <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
            <Dialog.Title className="font-semibold tracking-wider text-main uppercase">Record inspector decision</Dialog.Title>
            <Dialog.Close className="text-muted hover:text-main"><X size={14} /></Dialog.Close>
          </div>
          <div className="text-muted mb-2 font-sans">
            {serials.length === 1 ? <>Part <strong className="text-main">{serials[0]}</strong></> : <><strong className="text-main">{serials.length}</strong> parts: {serials.slice(0, 6).join(', ')}{serials.length > 6 ? ', …' : ''}</>}
            {' '}· Inspector <strong className="text-main">{inspector || '(not set)'}</strong>
            {mode === 'offline' && <span className="text-review"> · offline demo: not persisted</span>}
          </div>
          <div className="flex gap-2 mb-3">
            {(['Accept', 'Review', 'Reject'] as PartStatus[]).map(s => (
              <button key={s} onClick={() => setStatus(s)}
                className={`flex-1 py-1 border ${status === s ? (s === 'Reject' ? 'bg-reject text-white border-reject' : s === 'Review' ? 'bg-review text-white border-review' : 'bg-accept text-white border-accept') : 'bg-panel border-hairline text-muted'}`}>
                {s}
              </button>
            ))}
          </div>
          <label className="block text-muted font-sans mb-1">Engineering justification (required, min {MIN_COMMENT_LENGTH} characters)</label>
          <textarea autoFocus value={comment} onChange={e => setComment(e.target.value)} rows={4}
            className="w-full bg-panel border border-hairline p-2 text-main focus:outline-none focus:border-toprail" />
          {error && <div className="mt-2 text-reject">{error}</div>}
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={closeDecisionDialog} className="bg-panel border border-hairline px-3 py-1 text-muted hover:text-main">Cancel</button>
            <button onClick={onSubmit} disabled={tooShort || busy}
              className="bg-toprail text-white px-3 py-1 disabled:opacity-40">{busy ? 'Saving…' : 'Record decision'}</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
