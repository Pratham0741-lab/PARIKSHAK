"""
Calculated, lot-relative safety slope for Module B early rejection.

For every parameter p, each part's predicted 168h drift rate is

    r_p = (forecast_168h_p - reading_0h_p) / 168            (units per hour)

where the forecast comes from Module B (0h/24h inputs only). Within the part's OWN lot:

    median_p = median(r_p over the lot)
    spread_p = max(1.4826 * MAD(r_p over the lot), floor_p)
    safety_slope_p(lot) = median_p + k * spread_p

`floor_p` stops a very uniform lot from producing a near-zero spread. It is half the median
lot spread of r_p across the TRAINING lots. `k` is Module B's decision threshold, chosen by
FN-weighted cost minimisation on out-of-fold validation data (evaluation/thresholds.py);
3.0 is only a cold-start default. A part is flagged when r_p >= safety_slope_p for any p,
which is equivalent to

    module_b_score = max_p (r_p - median_p) / spread_p  >=  k.

Nothing here reads 96h/168h measurements: the forecast is made from 0h/24h and the lot
statistics are computed from those forecasts.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from ml_engine.features import PARAMETERS

HOURS = 168.0
COLD_START_K = 3.0
FLOOR_FRACTION = 0.5
PRED_COLUMN = {
    "leakage_current_ua": "pred_leakage_168h",
    "iddq_ma": "pred_iddq_168h",
    "propagation_delay_ns": "pred_delay_168h",
}
RATE_UNITS = {"leakage_current_ua": "uA/h", "iddq_ma": "mA/h", "propagation_delay_ns": "ns/h"}


def _scaled_mad(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else 0.0


def drift_rates(preds: pd.DataFrame, v0: pd.DataFrame) -> pd.DataFrame:
    """Predicted drift rate per parameter. `preds` has pred_* columns, `v0` has 0h readings; both keyed by component_id."""
    out = pd.DataFrame({"component_id": preds["component_id"].to_numpy(), "lot_id": preds["lot_id"].to_numpy()})
    v0i = v0.set_index("component_id")
    for p in PARAMETERS:
        if p not in v0i.columns or preds[PRED_COLUMN[p]].isna().all():
            out[f"rate_{p}"] = np.nan  # parameter not in the data: no rate, no safety slope
            continue
        start = v0i.loc[preds["component_id"], p].to_numpy(float)
        out[f"rate_{p}"] = (preds[PRED_COLUMN[p]].to_numpy(float) - start) / HOURS
    return out


def spread_floors(rates: pd.DataFrame) -> Dict[str, float]:
    """Half the median per-lot scaled MAD of each parameter's rate (computed on training lots)."""
    floors = {}
    for p in PARAMETERS:
        if rates[f"rate_{p}"].isna().all():
            floors[p] = float("nan")
            continue
        spreads = [_scaled_mad(g[f"rate_{p}"].to_numpy()) for _, g in rates.groupby("lot_id")]
        floors[p] = max(FLOOR_FRACTION * float(np.median(spreads)) if spreads else 0.0, 1e-9)
    return floors


def lot_statistics(rates: pd.DataFrame, floors: Dict[str, float]) -> pd.DataFrame:
    """Per-part lot median / spread of each parameter's predicted rate (from the part's own lot)."""
    out = rates.copy()
    present = [p for p in PARAMETERS if not out[f"rate_{p}"].isna().all() and np.isfinite(floors.get(p, np.nan))]
    for p in PARAMETERS:
        if p not in present:
            for c in ("lot_median", "lot_spread", "z"):
                out[f"{c}_{p}"] = np.nan
            continue
        col = f"rate_{p}"
        med = out.groupby("lot_id")[col].transform("median")
        mad = out.groupby("lot_id")[col].transform(lambda s: _scaled_mad(s.to_numpy()))
        out[f"lot_median_{p}"] = med
        out[f"lot_spread_{p}"] = np.maximum(mad, floors[p])
        out[f"z_{p}"] = (out[col] - med) / out[f"lot_spread_{p}"]
    zcols = [f"z_{p}" for p in present]
    out["module_b_score"] = out[zcols].max(axis=1)
    out["module_b_driver"] = out[zcols].idxmax(axis=1).str.replace("z_", "", regex=False)
    return out


def safety_slopes(stats: pd.DataFrame, k: float) -> pd.DataFrame:
    """safety_slope_p = lot median + k * lot spread, per part (identical within a lot)."""
    out = pd.DataFrame({"component_id": stats["component_id"]})
    for p in PARAMETERS:
        out[f"safety_slope_{p}"] = stats[f"lot_median_{p}"] + (k if np.isfinite(k) else np.nan) * stats[f"lot_spread_{p}"]
    return out
