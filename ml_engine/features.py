"""
Early-interval feature construction shared by Module B and the evaluation harness.

Only 0h and 24h readings are ever turned into features. Rows for any other interval are
dropped before feature construction, and `assert_no_future_features` guards the final matrix.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Tuple

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


def available_params(df: pd.DataFrame, intervals: Iterable[int] = EARLY_INTERVALS) -> Tuple[str, ...]:
    """Parameters (in canonical order) that have data at every requested interval. Files may carry
    any non-empty subset of leakage / IDDQ / delay; missing parameters are never fabricated."""
    out = []
    for p in PARAMETERS:
        if p not in df.columns:
            continue
        sub = df.loc[df["interval_hours"].isin(tuple(intervals)), ["interval_hours", p]].dropna()
        if set(sub["interval_hours"].unique()) >= set(intervals):
            out.append(p)
    return tuple(out)


def pivot_intervals(df: pd.DataFrame, intervals: Iterable[int], params: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Wide table (component_id, lot_id, {param}_{interval}) for the requested intervals."""
    intervals = tuple(intervals)
    params = tuple(params) if params is not None else available_params(df, intervals)
    sub = df[df["interval_hours"].isin(intervals)]
    wide = sub.pivot_table(
        index=["component_id", "lot_id"], columns="interval_hours", values=list(params)
    )
    wide.columns = [f"{p}_{h}" for p, h in wide.columns]
    return wide.reset_index().sort_values(["lot_id", "component_id"]).reset_index(drop=True)


def _mad(x: np.ndarray) -> float:
    med = np.median(x)
    return float(max(np.median(np.abs(x - med)) * 1.4826, 1e-9))


FEATURE_SETS = ("v1", "v2")


def build_early_features(df: pd.DataFrame, feature_set: str = "v1", params: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """
    Part-level and lot-level features derived ONLY from 0h and 24h readings.

    v1: the original set (values, delta, ratio, 24h slope, distance of 24h/delta from lot median).
    v2: v1 plus relative delta and lot-relative context from the part's own lot: lot median and
        scaled MAD of 0h, 24h and delta, robust z-scores of each vs the lot, and values
        normalised by the lot median.

    Returns a frame indexed by component_id with a `lot_id` column plus numeric features.
    Parts missing either early reading are dropped (they cannot receive a Module B forecast).
    """
    early = df[df["interval_hours"].isin(EARLY_INTERVALS)]
    params = tuple(params) if params is not None else available_params(early)
    if not params:
        raise ValueError("no parameter has both 0h and 24h readings")
    wide = pivot_intervals(early, EARLY_INTERVALS, params)
    needed = [f"{p}_{h}" for p in params for h in EARLY_INTERVALS]
    wide = wide.dropna(subset=needed)

    feats = pd.DataFrame({"component_id": wide["component_id"], "lot_id": wide["lot_id"]})
    for p in params:
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
        for p in params:
            feats.loc[idx, f"{p}_lot_dist24"] = rows[f"{p}_v24"] - float(np.median(rows[f"{p}_v24"]))
            feats.loc[idx, f"{p}_lot_delta"] = rows[f"{p}_delta"] - float(np.median(rows[f"{p}_delta"]))

    if feature_set == "v2":
        for p in params:
            feats[f"{p}_rel_delta"] = feats[f"{p}_delta"] / np.maximum(feats[f"{p}_v0"], 1e-6)
        for _, idx in feats.groupby("lot_id").groups.items():
            rows = feats.loc[idx]
            for p in params:
                for name in ("v0", "v24", "delta"):
                    col = rows[f"{p}_{name}"].to_numpy(float)
                    med, mad = float(np.median(col)), _mad(col)
                    feats.loc[idx, f"{p}_{name}_lot_median"] = med
                    feats.loc[idx, f"{p}_{name}_lot_mad"] = mad
                    feats.loc[idx, f"{p}_{name}_lot_z"] = (col - med) / mad
                for name in ("v0", "v24"):
                    med = float(np.median(rows[f"{p}_{name}"]))
                    feats.loc[idx, f"{p}_{name}_over_lot_median"] = rows[f"{p}_{name}"].to_numpy(float) / max(med, 1e-9)
    elif feature_set != "v1":
        raise ValueError(f"unknown feature_set {feature_set!r}; expected one of {FEATURE_SETS}")

    # Lot-level test condition from lot METADATA (not a reading): burn-in temperature. NaN when unknown,
    # which LightGBM treats as missing. Constant within a lot, never derived from 96h/168h.
    if "temperature_c" in early.columns:
        temp = early.groupby("component_id")["temperature_c"].first()
        feats["lot_temperature_c"] = feats["component_id"].map(temp).astype(float).to_numpy()
    else:
        feats["lot_temperature_c"] = np.nan

    feats = feats.set_index("component_id")
    assert_no_future_features(feats.columns)
    return feats


def feature_columns(feats: pd.DataFrame) -> list:
    cols = [c for c in feats.columns if c != "lot_id"]
    assert_no_future_features(cols)
    return cols


def extract_targets(df: pd.DataFrame, params: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """168h values per component (training targets / held-out ground truth)."""
    params = tuple(params) if params is not None else tuple(p for p in PARAMETERS if p in df.columns)
    tgt = df[df["interval_hours"] == TARGET_INTERVAL].set_index("component_id")
    return tgt[list(params)].rename(columns={p: f"{p}_168" for p in params})
