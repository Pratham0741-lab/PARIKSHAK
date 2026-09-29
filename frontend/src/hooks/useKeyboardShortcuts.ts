import { useEffect } from 'react';
import { useStore } from '../store/useStore';

export function useKeyboardShortcuts() {
  const {
    selectedPartId,
    selectedPartIds,
    navigatePart,
    applyDecision,
    applyBulkDecisions,
    setShortcutModalOpen,
  } = useStore();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable;

      // Global shortcut help
      if (e.key === '?' && !isInput) {
        e.preventDefault();
        setShortcutModalOpen(true);
        return;
      }

      // Focus search
      if (e.key === '/' && !isInput) {
        e.preventDefault();
        const searchInput = document.querySelector<HTMLInputElement>(
          'input[placeholder*="Search"], input[type="search"], input[data-search]'
        );
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
        return;
      }

      if (isInput) return;

      if (e.key === 'j' || e.key === 'J') {
        e.preventDefault();
        navigatePart('next');
      } else if (e.key === 'k' || e.key === 'K') {
        e.preventDefault();
        navigatePart('prev');
      } else if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        if (selectedPartIds.size > 0) {
          applyBulkDecisions('Accept', 'Bulk accepted via shortcut (A)');
        } else if (selectedPartId) {
          applyDecision(selectedPartId, 'Accept', 'Accepted via shortcut (A)');
        }
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        if (selectedPartIds.size > 0) {
          applyBulkDecisions('Review', 'Bulk escalated to review via shortcut (R)');
        } else if (selectedPartId) {
          applyDecision(selectedPartId, 'Review', 'Escalated to review via shortcut (R)');
        }
      } else if (e.key === 'x' || e.key === 'X') {
        e.preventDefault();
        if (selectedPartIds.size > 0) {
          applyBulkDecisions('Reject', 'Bulk rejected via shortcut (X)');
        } else if (selectedPartId) {
          applyDecision(selectedPartId, 'Reject', 'Quarantined via shortcut (X)');
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedPartId, selectedPartIds, navigatePart, applyDecision, applyBulkDecisions, setShortcutModalOpen]);
}
