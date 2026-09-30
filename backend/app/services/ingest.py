"""
CSV ingest: parsing and validation of burn-in readings for a new (unlabelled) lot.

Format (wide, one row per part):
    part_id, leakage_current_ua_0h, iddq_ma_0h, propagation_delay_ns_0h,
             leakage_current_ua_24h, iddq_ma_24h, propagation_delay_ns_24h,
             [optional: the same three parameters for 96h and 168h]

Rules (values are never zero-filled):
  * a missing required column rejects the whole file (nothing is ingested);
  * rows with an empty part ID are rejected; repeated part IDs keep the first row, later rows are rejected;
  * non-numeric, negative or empty cells are treated as missing;
  * a missing 0h/24h cell is imputed with the lot median of that column, the cell is recorded in
    `imputed_fields`, and the part is marked `insufficient_data` - it receives no Module A/B score
    and is sent to REVIEW. Imputed values are for display only and never enter a model or a metric;
  * a missing 96h/168h cell is imputed the same way (display only) unless all three parameters of
    that interval are missing, in which case no reading is stored for that interval.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

PARAMETERS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
REQUIRED_INTERVALS = (0, 24)
OPTIONAL_INTERVALS = (96, 168)
PART_ID_ALIASES = ("part_id", "serial_number", "serial", "part")


def column(p: str, h: int) -> str:
    return f"{p}_{h}h"


REQUIRED_COLUMNS = [column(p, h) for h in REQUIRED_INTERVALS for p in PARAMETERS]


@dataclass
class Issue:
    row: int
    message: str
    severity: str  # "error" (row/cell rejected) | "warning" (value imputed)
    part_id: Optional[str] = None
    column: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ParsedPart:
    part_id: str
    row: int
    # interval -> parameter -> value (None = missing)
    values: Dict[int, Dict[str, Optional[float]]]
    imputed: Dict[int, List[str]] = field(default_factory=dict)
    insufficient_data: bool = False


@dataclass
class IngestResult:
    ok: bool
    parts: List[ParsedPart]
    issues: List[Issue]
    rows_total: int = 0
    rows_rejected: int = 0
    duplicate_part_ids: int = 0
    non_numeric_cells: int = 0
    missing_cells: int = 0
    imputed_cells: int = 0
    missing_columns: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)  # lot-level test conditions found in the file

    @property
    def insufficient_data_parts(self) -> int:
        return sum(1 for p in self.parts if p.insufficient_data)

    def summary(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "rows_total": self.rows_total,
            "parts_accepted": len(self.parts),
            "rows_rejected": self.rows_rejected,
            "duplicate_part_ids": self.duplicate_part_ids,
            "non_numeric_cells": self.non_numeric_cells,
            "missing_cells": self.missing_cells,
            "imputed_cells": self.imputed_cells,
            "insufficient_data_parts": self.insufficient_data_parts,
            "missing_columns": self.missing_columns,
            "conditions_in_file": self.conditions,
            "issues": [i.as_dict() for i in self.issues],
        }


def _parse_cell(raw: Optional[str]):
    """Returns (value or None, problem) where problem is None | 'missing' | 'non_numeric' | 'negative'."""
    if raw is None or raw.strip() == "":
        return None, "missing"
    try:
        v = float(raw.strip())
    except ValueError:
        return None, "non_numeric"
    if not np.isfinite(v):
        return None, "non_numeric"
    if v < 0:
        return None, "negative"
    return v, None


CONDITION_COLUMNS = {
    "temperature_c": ("temperature_c", "temperature", "temp_c", "temp", "burn_in_temperature"),
    "test_parameter": ("test_parameter", "parameter", "param"),
    "unit": ("unit", "units"),
    "static_limit": ("static_limit", "limit", "datasheet_limit", "spec_limit"),
}


def _lot_conditions(header: List[str], rows: List[List[str]], issues: List[Issue]) -> Dict[str, Any]:
    """Optional lot-level condition columns: one value per lot (the most common value if rows disagree)."""
    found: Dict[str, Any] = {}
    for key, aliases in CONDITION_COLUMNS.items():
        col = next((header.index(a) for a in aliases if a in header), None)
        if col is None:
            continue
        values = [r[col].strip() for r in rows if col < len(r) and r[col].strip()]
        if not values:
            continue
        common = max(set(values), key=values.count)
        if len(set(values)) > 1:
            issues.append(Issue(0, f"Column {header[col]!r} has {len(set(values))} different values; using the most "
                                   f"common one ({common!r}) for the lot", "warning", column=header[col]))
        if key in ("temperature_c", "static_limit"):
            try:
                found[key] = float(common)
            except ValueError:
                issues.append(Issue(0, f"Column {header[col]!r} value {common!r} is not numeric; ignored", "error",
                                    column=header[col]))
        else:
            found[key] = common
    return found


def parse_csv(text: str) -> IngestResult:
    reader = csv.reader(io.StringIO(text.strip()))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return IngestResult(ok=False, parts=[], issues=[Issue(0, "CSV is empty", "error")])

    header = [h.strip().lower() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    id_col = next((a for a in PART_ID_ALIASES if a in idx), None)
    missing = ([] if id_col else ["part_id"]) + [c for c in REQUIRED_COLUMNS if c not in idx]
    if missing:
        return IngestResult(
            ok=False, parts=[], rows_total=len(rows) - 1, missing_columns=missing,
            issues=[Issue(1, f"Missing required column(s): {', '.join(missing)}", "error")],
        )
    optional_present = [h for h in OPTIONAL_INTERVALS if all(column(p, h) in idx for p in PARAMETERS)]

    res = IngestResult(ok=True, parts=[], issues=[], rows_total=len(rows) - 1)
    res.conditions = _lot_conditions(header, rows[1:], res.issues)
    seen: Dict[str, int] = {}
    for rnum, r in enumerate(rows[1:], start=2):
        pid = r[idx[id_col]].strip() if idx[id_col] < len(r) else ""
        if not pid:
            res.rows_rejected += 1
            res.issues.append(Issue(rnum, "Empty part ID; row rejected", "error"))
            continue
        if pid in seen:
            res.rows_rejected += 1
            res.duplicate_part_ids += 1
            res.issues.append(Issue(rnum, f"Duplicate part ID (first seen on row {seen[pid]}); row rejected", "error", pid))
            continue
        seen[pid] = rnum

        values: Dict[int, Dict[str, Optional[float]]] = {}
        for h in (*REQUIRED_INTERVALS, *optional_present):
            values[h] = {}
            for p in PARAMETERS:
                c = column(p, h)
                raw = r[idx[c]] if idx[c] < len(r) else None
                v, problem = _parse_cell(raw)
                values[h][p] = v
                if problem == "missing":
                    res.missing_cells += 1
                elif problem:
                    res.non_numeric_cells += 1
                    res.issues.append(Issue(rnum, f"{'Negative' if problem == 'negative' else 'Non-numeric'} value "
                                                  f"{raw!r}; treated as missing", "error", pid, c))
        res.parts.append(ParsedPart(part_id=pid, row=rnum, values=values))

    # Impute missing cells with the lot median of that column (display only), never with 0.
    for h in (*REQUIRED_INTERVALS, *optional_present):
        for p in PARAMETERS:
            observed = [pp.values[h][p] for pp in res.parts if pp.values[h][p] is not None]
            med = float(np.median(observed)) if observed else None
            for pp in res.parts:
                if pp.values[h][p] is not None:
                    continue
                if h in OPTIONAL_INTERVALS and all(pp.values[h][q] is None for q in PARAMETERS):
                    continue  # whole interval absent: store no reading
                if med is None:
                    continue
                pp.values[h][p] = med
                pp.imputed.setdefault(h, []).append(p)
                res.imputed_cells += 1
                if h in REQUIRED_INTERVALS:
                    pp.insufficient_data = True
                res.issues.append(Issue(pp.row, f"Missing {column(p, h)} imputed with lot median {med:.4g} "
                                                f"(display only)", "warning", pp.part_id, column(p, h)))
    for pp in res.parts:
        if any(pp.values[h][p] is None for h in REQUIRED_INTERVALS for p in PARAMETERS):
            pp.insufficient_data = True
    return res
