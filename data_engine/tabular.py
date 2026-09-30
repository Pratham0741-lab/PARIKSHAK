"""
Read an uploaded burn-in table (CSV text) into the long reading format used by ml_engine:
    component_id, lot_id, interval_hours, <parameter columns present>, [temperature_c],
    [ground_truth_flag, ground_truth_label]

Accepted layouts:
  * wide: one row per part, columns <parameter>_<h>h (e.g. leakage_current_ua_24h);
  * long: one row per part and interval, with an interval column (interval_hours) and one column per parameter.
Any subset of the three parameters is accepted if every parameter present has both 0h and 24h columns.
96h is optional and ignored by the models. 168h is needed only for training and scoring.
Missing or non-numeric cells stay NaN (never 0) and are listed in `issues`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ml_engine.features import PARAMETERS

ID_ALIASES = ("component_id", "part_id", "serial_number", "serial", "part")
LOT_ALIASES = ("lot_id", "lot_number", "lot", "lot_no")
INTERVAL_ALIASES = ("interval_hours", "interval", "hours", "time_h")
FLAG_ALIASES = ("ground_truth_flag", "defective", "is_defective", "defect_flag")
LABEL_ALIASES = ("ground_truth_label", "defect_type", "label", "class")
TEMP_ALIASES = ("temperature_c", "temperature", "temp_c", "burn_in_temperature")
INTERVALS = (0, 24, 96, 168)
NORMAL_LABELS = ("", "NORMAL", "OK", "PASS", "GOOD", "NONE")
TRUE_STRINGS = {"true", "1", "yes", "y", "t", "defective", "fail"}


class TableError(ValueError):
    pass


@dataclass
class Table:
    df: pd.DataFrame
    params: List[str]
    layout: str
    has_labels: bool
    has_168h: bool
    n_parts: int
    n_lots: int
    issues: List[Dict[str, Any]] = field(default_factory=list)
    sha256: str = ""

    def summary(self) -> Dict[str, Any]:
        return {"layout": self.layout, "parameters": self.params, "has_labels": self.has_labels,
                "has_168h": self.has_168h, "n_parts": self.n_parts, "n_lots": self.n_lots,
                "n_issues": len(self.issues), "issues": self.issues[:200]}


def _pick(cols: List[str], aliases) -> Optional[str]:
    return next((a for a in aliases if a in cols), None)


def _to_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(TRUE_STRINGS)


def read_table(text: str) -> Table:
    import hashlib

    raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, skipinitialspace=True)
    raw.columns = [c.strip().lower() for c in raw.columns]
    cols = list(raw.columns)
    id_col = _pick(cols, ID_ALIASES)
    if id_col is None:
        raise TableError(f"no part-ID column (expected one of {', '.join(ID_ALIASES)})")
    lot_col, iv_col = _pick(cols, LOT_ALIASES), _pick(cols, INTERVAL_ALIASES)
    issues: List[Dict[str, Any]] = []

    def num(series: pd.Series, name: str) -> pd.Series:
        s = series.astype(str).str.strip()
        v = pd.to_numeric(s, errors="coerce")
        bad = (s != "") & v.isna()
        for i in np.flatnonzero(bad.to_numpy())[:100]:
            issues.append({"row": int(i) + 2, "column": name, "message": f"non-numeric value {s.iloc[i]!r}; treated as missing"})
        return v.where(np.isfinite(v))

    if iv_col is not None:
        layout = "long"
        params = [p for p in PARAMETERS if p in cols]
        long = pd.DataFrame({"component_id": raw[id_col].str.strip(),
                             "interval_hours": pd.to_numeric(raw[iv_col], errors="coerce")})
        for p in params:
            long[p] = num(raw[p], p)
        long["lot_id"] = raw[lot_col].str.strip() if lot_col else "FILE"
        extra_src = raw
    else:
        layout = "wide"
        params = [p for p in PARAMETERS if all(f"{p}_{h}h" in cols for h in (0, 24))]
        rows = []
        for h in INTERVALS:
            present = [p for p in params if f"{p}_{h}h" in cols]
            if not present:
                continue
            part = pd.DataFrame({"component_id": raw[id_col].str.strip(), "interval_hours": h})
            for p in params:
                part[p] = num(raw[f"{p}_{h}h"], f"{p}_{h}h") if p in present else np.nan
            part["lot_id"] = raw[lot_col].str.strip() if lot_col else "FILE"
            part["_row"] = np.arange(len(raw)) + 2
            rows.append(part)
        long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
        extra_src = pd.concat([raw] * max(1, len(rows)), ignore_index=True)
    if not params:
        raise TableError("no parameter columns with both 0h and 24h readings "
                         f"(expected e.g. {PARAMETERS[0]}_0h and {PARAMETERS[0]}_24h)")

    long = long[long["component_id"] != ""]
    long = long[long["interval_hours"].isin(INTERVALS)].copy()
    long["interval_hours"] = long["interval_hours"].astype(int)
    dup = long.duplicated(["component_id", "interval_hours"], keep="first")
    if dup.any():
        for cid in long.loc[dup, "component_id"].unique()[:100]:
            issues.append({"part_id": cid, "message": "duplicate part ID; first occurrence kept"})
        long = long[~dup]

    idx = long.index
    tcol = _pick(cols, TEMP_ALIASES)
    if tcol:
        long["temperature_c"] = pd.to_numeric(extra_src.loc[idx, tcol], errors="coerce").to_numpy()
    fcol, lcol = _pick(cols, FLAG_ALIASES), _pick(cols, LABEL_ALIASES)
    has_labels = fcol is not None
    if fcol:
        long["ground_truth_flag"] = _to_bool(extra_src.loc[idx, fcol]).to_numpy()
        # a label is attributed to the part: take the first non-empty per component
        per = long.assign(_f=long["ground_truth_flag"]).groupby("component_id")["_f"].max()
        long["ground_truth_flag"] = long["component_id"].map(per)
    if lcol and lcol != fcol:
        long["ground_truth_label"] = extra_src.loc[idx, lcol].astype(str).str.strip().str.upper().to_numpy()
        per = long[long["ground_truth_label"] != ""].groupby("component_id")["ground_truth_label"].first()
        long["ground_truth_label"] = long["component_id"].map(per).fillna("")
    if lcol and not fcol:  # a class column alone also counts as labels
        has_labels = True
        long["ground_truth_flag"] = ~long["ground_truth_label"].isin(NORMAL_LABELS)
    long = long.drop(columns=["_row"], errors="ignore").sort_values(["component_id", "interval_hours"])
    long = long.reset_index(drop=True)

    early = long[long["interval_hours"].isin((0, 24))]
    counts = early.dropna(subset=params).groupby("component_id")["interval_hours"].nunique()
    incomplete = sorted(set(long["component_id"]) - set(counts[counts == 2].index))
    for cid in incomplete[:100]:
        issues.append({"part_id": cid, "message": "missing a 0h/24h value; part cannot be scored (sent to REVIEW)"})
    long["insufficient_data"] = long["component_id"].isin(incomplete)

    return Table(df=long, params=params, layout=layout, has_labels=has_labels,
                 has_168h=bool((long["interval_hours"] == 168).any()),
                 n_parts=int(long["component_id"].nunique()), n_lots=int(long["lot_id"].nunique()),
                 issues=issues, sha256=hashlib.sha256(text.encode()).hexdigest())
