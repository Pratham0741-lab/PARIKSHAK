"""
Early-interval feature construction shared by Module B and the evaluation harness.

Only 0h and 24h readings are ever turned into features. Rows for any other interval are
dropped before feature construction, and `assert_no_future_features` guards the final matrix.
"""

from __future__ import annotations

import re
from typing import Iterable, Tuple

import numpy as np
import pandas as pd

PARAMETERS: Tuple[str, ...] = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
EARLY_INTERVALS: Tuple[int, int] = (0, 24)
TARGET_INTERVAL: int = 168

_FUTURE_PATTERN = re.compile(r"(^|_)(96|168)(h)?($|_)")


class FutureLeakageError(AssertionError):
    """Raised when a feature derived from 96h/168h readings reaches a model input."""


def assert_no_future_features(columns: Iterable[str]) -> None:
    offending = [c for c in columns if _FUTURE_PATTERN.search(str(c))]
    if offending:
        raise FutureLeakageError(f"96h/168h-derived columns in feature matrix: {offending}")


def pivot_intervals(df: pd.DataFrame, intervals: Iterable[int]) -> pd.DataFrame:
    """Wide table (component_id, lot_id, {param}_{interval}) for the requested intervals."""
    intervals = tuple(intervals)
    sub = df[df["interval_hours"].isin(intervals)]
    wide = sub.pivot_table(
        index=["component_id", "lot_id"], columns="interval_hours", values=list(PARAMETERS)
    )
    wide.columns = [f"{p}_{h}" for p, h in wide.columns]
    return wide.reset_index().sort_values(["lot_id", "component_id"]).reset_index(drop=True)


def _mad(x: np.ndarray) -> float:
    med = np.median(x)
    return float(max(np.median(np.abs(x - med)) * 1.4826, 1e-9))


def build_early_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Part-level and lot-level features derived ONLY from 0h and 24h readings.

    Returns a frame indexed by component_id with a `lot_id` column plus numeric features.
    Parts missing either early reading are dropped (they cannot receive a Module B forecast).
    """
    early = df[df["interval_hours"].isin(EARLY_INTERVALS)]
    wide = pivot_intervals(early, EARLY_INTERVALS)
    needed = [f"{p}_{h}" for p in PARAMETERS for h in EARLY_INTERVALS]
    wide = wide.dropna(subset=needed)

    feats = pd.DataFrame({"component_id": wide["component_id"], "lot_id": wide["lot_id"]})
    for p in PARAMETERS:
        v0 = wide[f"{p}_0"].to_numpy(float)
        v24 = wide[f"{p}_24"].to_numpy(float)
        feats[f"{p}_v0"] = v0
        feats[f"{p}_v24"] = v24
        feats[f"{p}_delta"] = v24 - v0
        feats[f"{p}_ratio"] = v24 / np.maximum(v0, 1e-6)
        feats[f"{p}_slope24"] = (v24 - v0) / 24.0

    # Lot-relative context: each lot is summarised from its own 0h/24h readings.
    for _, idx in feats.groupby("lot_id").groups.items():
        rows = feats.loc[idx]
        for p in PARAMETERS:
            feats.loc[idx, f"{p}_lot_dist24"] = rows[f"{p}_v24"] - float(np.median(rows[f"{p}_v24"]))
            feats.loc[idx, f"{p}_lot_delta"] = rows[f"{p}_delta"] - float(np.median(rows[f"{p}_delta"]))

    feats = feats.set_index("component_id")
    assert_no_future_features(feats.columns)
    return feats


def feature_columns(feats: pd.DataFrame) -> list:
    cols = [c for c in feats.columns if c != "lot_id"]
    assert_no_future_features(cols)
    return cols


def extract_targets(df: pd.DataFrame) -> pd.DataFrame:
    """168h values per component (training targets / held-out ground truth)."""
    tgt = df[df["interval_hours"] == TARGET_INTERVAL].set_index("component_id")
    return tgt[list(PARAMETERS)].rename(columns={p: f"{p}_168" for p in PARAMETERS})
