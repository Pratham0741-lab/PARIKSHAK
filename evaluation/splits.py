"""
Lot-grouped data splitting. Splits are always made over LOTS, never over parts, so a lot's
parts (and its lot-level statistics) are never shared between training and test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

import numpy as np


@dataclass(frozen=True)
class LotFold:
    fold: int
    train_lots: frozenset
    test_lots: frozenset


class LotLeakageError(AssertionError):
    """Raised when a lot (or part) appears on both sides of a split."""


def lot_group_kfold(lot_ids: Iterable, n_splits: int = 5, seed: int = 42) -> List[LotFold]:
    """
    Deterministic GroupKFold over lots: lots are shuffled with `seed` and dealt round-robin
    into `n_splits` folds. Every lot is in exactly one test fold.
    """
    lots = sorted({str(l) for l in lot_ids})
    if n_splits < 2 or n_splits > len(lots):
        raise ValueError(f"n_splits={n_splits} invalid for {len(lots)} lots")
    order = np.random.default_rng(seed).permutation(len(lots))
    shuffled = [lots[i] for i in order]
    folds: List[LotFold] = []
    for k in range(n_splits):
        test = frozenset(shuffled[k::n_splits])
        train = frozenset(lots) - test
        assert_disjoint(train, test)
        folds.append(LotFold(fold=k, train_lots=train, test_lots=test))
    return folds


def lot_holdout_split(lot_ids: Iterable, test_fraction: float = 0.3, seed: int = 42) -> LotFold:
    """Single lot-level holdout (used when one fixed test set is wanted)."""
    lots = sorted({str(l) for l in lot_ids})
    n_test = max(1, int(round(len(lots) * test_fraction)))
    order = np.random.default_rng(seed).permutation(len(lots))
    test = frozenset(lots[i] for i in order[:n_test])
    train = frozenset(lots) - test
    assert_disjoint(train, test)
    return LotFold(fold=0, train_lots=train, test_lots=test)


def assert_disjoint(train: Sequence, test: Sequence, what: str = "lot") -> None:
    overlap = set(map(str, train)) & set(map(str, test))
    if overlap:
        raise LotLeakageError(f"{len(overlap)} {what}(s) in both train and test: {sorted(overlap)[:5]}")
