"""
LFR-1: the labels-free rule for "defective", used when a file carries no ground-truth labels.

It needs the part's 168h reading, so it is a TRUTH definition (for training thresholds on an
uploaded training file and for scoring), never an inference input: /judge/predict and every model
see only 0h/24h readings.

A part is DEFECTIVE under LFR-1 if, for any monitored parameter present in the file:
  LIMIT  its 168h value is at or above the static limit (supplied per file, else the datasheet limit), or
  DRIFT  its relative drift r = ln(v168 / v24) is an upper outlier within its lot:
             r > median_lot(r) + Z_CUT * s_lot(r),   and v168 > v24, or
  LEVEL  its 168h value is an upper outlier within its lot:
             v168 > median_lot(v168) + Z_CUT * s_lot(v168).
  s_lot = 1.4826 * MAD (a consistent estimate of the standard deviation), falling back to
  1.2533 * mean absolute deviation when the MAD is 0.

Z_CUT = 3.5 is the Iglewicz & Hoaglin (1993) modified-z outlier cut-off. It is fixed in advance and
is not tuned on any data. Lots smaller than MIN_LOT_PARTS use file-wide statistics instead.
When several criteria apply, the label reported is the first one in the order LIMIT, DRIFT, LEVEL.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

RULE_ID = "LFR-1"
Z_CUT = 3.5
MIN_LOT_PARTS = 10
EPS = 1e-12

RULE_TEXT = (
    f"{RULE_ID}: a part is defective if, for any monitored parameter, its 168h value is at or above the static "
    f"limit (LIMIT); or its drift ln(v168/v24) exceeds its lot's median by more than {Z_CUT} robust SDs, "
    f"i.e. 1.4826 x MAD (DRIFT); or its 168h value exceeds its lot's median by more than {Z_CUT} robust SDs "
    f"(LEVEL). The cut-off {Z_CUT} is the Iglewicz-Hoaglin modified-z value, fixed in advance. The rule needs "
    "168h readings, so it defines ground truth only and is never a model input."
)


def _robust_scale(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    if mad > 0:
        return float(mad)
    return float(np.mean(np.abs(x - med)) * 1.2533)


def _upper_outlier(values: pd.Series, groups: pd.Series) -> pd.Series:
    out = pd.Series(False, index=values.index)
    sizes = groups.map(groups.value_counts())
    small = sizes < MIN_LOT_PARTS
    for _lot, idx in values[~small].groupby(groups[~small]).groups.items():
        v = values.loc[idx].to_numpy(float)
        med, s = np.nanmedian(v), _robust_scale(v)
        out.loc[idx] = np.isfinite(v) & (v > med + Z_CUT * max(s, EPS))
    if small.any():  # file-wide statistics for lots too small for their own
        v_all = values.to_numpy(float)
        med, s = np.nanmedian(v_all), _robust_scale(v_all)
        v = values[small].to_numpy(float)
        out.loc[small[small].index] = np.isfinite(v) & (v > med + Z_CUT * max(s, EPS))
    return out


def apply_rule(df: pd.DataFrame, params, limits: Optional[Dict[str, float]] = None) -> pd.DataFrame:
    """
    df: long readings (component_id, lot_id, interval_hours, <params>), including 24h and 168h.
    Returns one row per component with 168h data: ground_truth_flag, ground_truth_label, rule_detail.
    """
    from ml_engine.verdict_engine import ScreeningVerdictEngine

    limits = {**ScreeningVerdictEngine.datasheet_limits(), **(limits or {})}
    comp = df.drop_duplicates("component_id").set_index("component_id")
    lots = comp["lot_id"].astype(str)
    v24 = df[df["interval_hours"] == 24].drop_duplicates("component_id").set_index("component_id")
    v168 = df[df["interval_hours"] == 168].drop_duplicates("component_id").set_index("component_id")
    ids = v168.index
    label = pd.Series("NORMAL", index=ids, dtype=object)
    detail = pd.Series("", index=ids, dtype=object)
    for crit in ("LIMIT", "DRIFT", "LEVEL"):
        for p in params:
            if p not in v168.columns:
                continue
            e = v168[p].astype(float)
            if crit == "LIMIT":
                hit = e >= limits[p]
            elif crit == "DRIFT":
                s = v24[p].reindex(ids).astype(float) if p in v24.columns else pd.Series(np.nan, index=ids)
                r = np.log(np.maximum(e, EPS) / np.maximum(s, EPS))
                hit = _upper_outlier(r, lots.reindex(ids)) & (e > s)
            else:
                hit = _upper_outlier(e, lots.reindex(ids))
            new = hit.fillna(False).astype(bool) & (label == "NORMAL")
            label[new] = crit
            detail[new] = f"{crit} on {p}"
    return pd.DataFrame({"ground_truth_flag": label != "NORMAL", "ground_truth_label": label,
                         "rule_detail": detail}, index=ids)
