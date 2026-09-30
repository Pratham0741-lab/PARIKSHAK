import { useEffect } from 'react';
import { useStore } from '../store/useStore';

/** J/K navigate; A/R/X open the decision dialog (a comment is always required); / search; ? help. */
export function useKeyboardShortcuts() {
  const { navigatePart, openDecisionDialog, setShortcutModalOpen, decisionDialog } = useStore();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable;
      if (decisionDialog.open) return;

      if (e.key === '?' && !isInput) {
        e.preventDefault();
        setShortcutModalOpen(true);
        return;
      }
      if (e.key === '/' && !isInput) {
        e.preventDefault();
        const searchInput = document.querySelector<HTMLInputElement>('input[data-search]');
        searchInput?.focus();
        searchInput?.select();
        return;
      }
      if (isInput) return;

      const k = e.key.toLowerCase();
      if (k === 'j') navigatePart('next');
      else if (k === 'k') navigatePart('prev');
      else if (k === 'a') openDecisionDialog('Accept');
      else if (k === 'r') openDecisionDialog('Review');
      else if (k === 'x') openDecisionDialog('Reject');
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navigatePart, openDecisionDialog, setShortcutModalOpen, decisionDialog.open]);
}
