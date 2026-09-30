"""
Out-of-fold (cross-fitted) prediction over lots.

For each lot-fold the model factory builds a fresh model, which is fitted on the TRAINING
lots only (all intervals + labels). The TEST lots are passed to `predict` through
`early_readings_only`, i.e. with 96h/168h readings and every label column removed.
Ground truth is extracted separately by `extract_truth` and never passed to a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

import pandas as pd

from evaluation.splits import LotFold, assert_disjoint, lot_group_kfold
from ml_engine.features import PARAMETERS, TARGET_INTERVAL
from ml_engine.module_b_drift import linear_extrapolation_baseline
from ml_engine.screening import early_readings_only

TRUTH_COLUMNS = ("ground_truth_flag", "ground_truth_label")


@dataclass
class FoldRecord:
    fold: int
    train_lots: frozenset
    test_lots: frozenset
    train_component_ids: frozenset
    test_component_ids: frozenset
    predicted_component_ids: frozenset = field(default_factory=frozenset)


@dataclass
class CrossFitResult:
    predictions: pd.DataFrame
    folds: List[FoldRecord]
    models: Dict[int, object]


def extract_truth(df: pd.DataFrame) -> pd.DataFrame:
    """Held-out ground truth: defect labels and true 168h values, one row per component."""
    meta = df.drop_duplicates("component_id").set_index("component_id")
    truth = pd.DataFrame(index=meta.index)
    truth["lot_id"] = meta["lot_id"].astype(str)
    for c in TRUTH_COLUMNS:
        if c in meta.columns:
            truth[c] = meta[c]
    t168 = df[df["interval_hours"] == TARGET_INTERVAL].set_index("component_id")
    for p in PARAMETERS:
        truth[f"true_{p}_168h"] = t168[p].reindex(truth.index)
    truth.index = truth.index.astype(str)
    truth.index.name = "component_id"
    return truth.sort_index()


def cross_fit_predict(
    df: pd.DataFrame,
    model_factory: Callable[[], object],
    n_splits: int = 5,
    seed: int = 42,
    folds: List[LotFold] | None = None,
) -> CrossFitResult:
    df = df.copy()
    df["lot_id"] = df["lot_id"].astype(str)
    df["component_id"] = df["component_id"].astype(str)
    folds = folds or lot_group_kfold(df["lot_id"].unique(), n_splits=n_splits, seed=seed)

    preds: List[pd.DataFrame] = []
    records: List[FoldRecord] = []
    models: Dict[int, object] = {}
    for f in folds:
        train_df = df[df["lot_id"].isin(f.train_lots)]
        test_df = df[df["lot_id"].isin(f.test_lots)]
        rec = FoldRecord(
            fold=f.fold,
            train_lots=f.train_lots,
            test_lots=f.test_lots,
            train_component_ids=frozenset(train_df["component_id"]),
            test_component_ids=frozenset(test_df["component_id"]),
        )
        assert_disjoint(rec.train_lots, rec.test_lots)
        assert_disjoint(rec.train_component_ids, rec.test_component_ids, what="component")

        model = model_factory()
        model.fit(train_df)
        hidden = early_readings_only(test_df)          # no 96h/168h, no labels
        out = model.predict(hidden)
        out["component_id"] = out["component_id"].astype(str)

        baseline = linear_extrapolation_baseline(hidden)
        for p in PARAMETERS:
            out[f"baseline_{p}_168h"] = out["component_id"].map(baseline[f"{p}_168"].rename(index=str))
        out["cv_fold"] = f.fold
        rec.predicted_component_ids = frozenset(out["component_id"])
        records.append(rec)
        models[f.fold] = model
        preds.append(out)

    predictions = pd.concat(preds, ignore_index=True).sort_values("component_id").reset_index(drop=True)
    for c in TRUTH_COLUMNS:
        if c in predictions.columns:
            raise AssertionError(f"ground-truth column '{c}' leaked into predictions")
    return CrossFitResult(predictions=predictions, folds=records, models=models)
