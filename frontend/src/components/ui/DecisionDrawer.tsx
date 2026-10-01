import React, { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { MIN_COMMENT_LENGTH, useStore } from '../../store/useStore';
import { PartStatus } from '../../data/types';
import { Button } from './primitives';

const OPTIONS: { status: PartStatus; label: string; hint: string; cls: string }[] = [
  { status: 'Accept', label: 'PASS (accept part)', hint: 'Release the part', cls: 'text-accept' },
  { status: 'Review', label: 'REVIEW (re-test)', hint: 'Keep under review / re-test', cls: 'text-review' },
  { status: 'Reject', label: 'REJECT (quarantine)', hint: 'Remove the part from the lot', cls: 'text-reject' },
];

/** Every disposition change (single, bulk or keyboard) goes through this drawer: a mandatory written comment and
 * the inspector ID; the backend writes the audit log. */
export const DecisionDrawer: React.FC = () => {
  const { decisionDialog, closeDecisionDialog, submitDecision, parts, inspector, setInspector, mode } = useStore();
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
        <Dialog.Overlay className="fixed inset-0 bg-navy/40 z-50" />
        <Dialog.Content className="fixed right-0 top-0 h-full w-[440px] max-w-full bg-workspace border-l border-hairline z-50 p-6 flex flex-col gap-4 focus:outline-none"
          data-testid="decision-drawer">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-card font-semibold text-main">Review decision</Dialog.Title>
            <Dialog.Close aria-label="Close" className="text-muted hover:text-main"><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className="text-sm text-muted">
            {serials.length === 1 ? <>Part <strong className="text-main">{serials[0]}</strong></> : <><strong className="text-main">{serials.length}</strong> parts: {serials.slice(0, 6).join(', ')}{serials.length > 6 ? ', …' : ''}</>}
            {mode === 'offline' && <span className="text-review"> · offline demo: not persisted</span>}
          </Dialog.Description>
          <fieldset>
            <legend className="text-sm font-semibold text-main mb-2">Disposition</legend>
            <div role="radiogroup" className="flex flex-col gap-2">
              {OPTIONS.map(o => (
                <label key={o.status} className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${status === o.status ? 'border-navy bg-panel' : 'border-hairline'}`}>
                  <input type="radio" name="disposition" value={o.status} checked={status === o.status} onChange={() => setStatus(o.status)} className="mt-1" />
                  <span><span className={`font-semibold ${o.cls}`}>{o.label}</span><span className="block text-xs text-muted">{o.hint}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="text-sm font-semibold text-main">Inspector ID
            <input value={inspector} onChange={e => setInspector(e.target.value)} placeholder="badge ID"
              className="mt-1 block w-full rounded-lg border border-hairline px-3 py-2 font-normal focus:outline-none focus:border-navy" />
          </label>
          <label className="text-sm font-semibold text-main">Engineering justification <span className="font-normal text-muted">(required, at least {MIN_COMMENT_LENGTH} characters)</span>
            <textarea autoFocus value={comment} onChange={e => setComment(e.target.value)} rows={5} data-testid="decision-comment"
              className="mt-1 block w-full rounded-lg border border-hairline p-3 font-normal focus:outline-none focus:border-navy" />
          </label>
          {error && <div className="text-sm text-reject" role="alert">{error}</div>}
          <div className="mt-auto flex justify-end gap-2">
            <Button onClick={closeDecisionDialog}>Cancel</Button>
            <Button variant="primary" onClick={onSubmit} disabled={tooShort || busy}>{busy ? 'Saving…' : 'Record decision'}</Button>
          </div>
          <p className="text-xs text-muted">The decision, comment and inspector ID are written to the audit log.</p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
