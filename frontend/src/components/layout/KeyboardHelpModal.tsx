import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useStore } from '../../store/useStore';
import { X } from 'lucide-react';

export const KeyboardHelpModal: React.FC = () => {
  const { isShortcutModalOpen, setShortcutModalOpen } = useStore();

  const shortcuts = [
    { key: 'J', desc: 'Select next row / component in table or list' },
    { key: 'K', desc: 'Select previous row / component in table or list' },
    { key: 'A', desc: 'Mark selected part as Accept' },
    { key: 'R', desc: 'Mark selected part as Review (escalate to QA)' },
    { key: 'X', desc: 'Mark selected part as Reject (quarantine)' },
    { key: '/', desc: 'Focus active search input' },
    { key: '?', desc: 'Toggle keyboard shortcuts help dialog' },
    { key: 'Esc', desc: 'Close open modal or dialog' },
  ];

  return (
    <Dialog.Root open={isShortcutModalOpen} onOpenChange={setShortcutModalOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[420px] bg-workspace border border-hairline p-4 z-50 focus:outline-none">
          <div className="flex items-center justify-between pb-2 border-b border-hairline mb-3">
            <Dialog.Title className="font-mono font-semibold text-xs tracking-wider text-main uppercase">
              Keyboard Navigation Shortcuts
            </Dialog.Title>
            <Dialog.Close className="text-muted hover:text-main">
              <X size={14} />
            </Dialog.Close>
          </div>

          <p className="text-xs text-muted mb-3 font-sans">
            PARIKSHAK supports rapid test-bench keyboard control for aerospace inspection efficiency.
          </p>

          <div className="space-y-1.5 font-mono text-xs">
            {shortcuts.map(s => (
              <div
                key={s.key}
                className="flex items-center justify-between py-1 px-1.5 hover:bg-panel border-b border-hairline/40"
              >
                <kbd className="bg-panel px-2 py-0.5 border border-hairline font-semibold text-main">
                  {s.key}
                </kbd>
                <span className="text-muted font-sans text-xs">{s.desc}</span>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-2 border-t border-hairline flex justify-end">
            <button
              onClick={() => setShortcutModalOpen(false)}
              className="bg-toprail text-white text-xs px-3 py-1 hover:bg-toprail/90"
            >
              Close
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
