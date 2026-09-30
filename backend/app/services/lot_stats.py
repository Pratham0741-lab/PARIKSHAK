"""Robust per-lot, per-interval statistics of the observed readings (for lot envelope bands)."""

from __future__ import annotations

from typing import Any, Dict, List, Union

import numpy as np
import pandas as pd

PARAMETERS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
INTERVALS = (0, 24, 96, 168)


def compute_lot_statistics(lot_readings: Union[pd.DataFrame, List[Dict[str, Any]]]) -> Dict[str, Dict[int, Dict[str, float]]]:
    """{param: {interval: {median, mad, min, p25, p75, max}}} computed from the lot's readings."""
    df = pd.DataFrame(lot_readings) if isinstance(lot_readings, list) else lot_readings
    stats: Dict[str, Dict[int, Dict[str, float]]] = {}
    for p in PARAMETERS:
        stats[p] = {}
        if p not in df.columns:
            continue
        for h in INTERVALS:
            vals = df.loc[df["interval_hours"] == h, p].dropna().to_numpy(dtype=float)
            if len(vals) == 0:
                continue
            med = float(np.median(vals))
            stats[p][h] = {
                "median": med,
                "mad": max(float(np.median(np.abs(vals - med))), 1e-6),
                "min": float(vals.min()),
                "p25": float(np.percentile(vals, 25)),
                "p75": float(np.percentile(vals, 75)),
                "max": float(vals.max()),
            }
    return stats
