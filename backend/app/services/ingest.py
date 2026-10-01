"""
CSV ingest: validation of burn-in readings for a new (unlabelled) lot.

Parsing is done by data_engine/tabular.py, the same reader judge mode uses. It accepts:
  * wide, long and tidy layouts;
  * case-insensitive and fuzzy header aliases (Iddq_0h, I_0, T0, "leakage (nA) @ 24 h", ...);
  * units nA/uA/mA/A and ps/ns/us, converted to uA / mA / ns. A converted or implausible unit must be
    confirmed before the lot is stored;
  * a streamed parse (large files are never held as one string).

Rules (values are never zero-filled):
  * any subset of the three parameters is accepted if each present parameter has 0h and 24h columns;
    absent parameters are stored as NULL and screened by the same pipeline fitted without them
    (`parameters_used`, see services/screening_service.model_for_parameters);
  * rows with an empty part ID are rejected; repeated part IDs keep the first row, later rows are rejected;
  * non-numeric, negative or empty cells are treated as missing (listed with their file line);
  * a missing 0h/24h cell is imputed with the lot median of that column, the cell is recorded in
    `imputed_fields`, and the part is marked `insufficient_data` - it receives no Module A/B score
    and is sent to REVIEW. Imputed values are for display only and never enter a model or a metric;
  * a missing 96h/168h cell is imputed the same way (display only) unless all three parameters of
    that interval are missing, in which case no reading is stored for that interval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from data_engine.tabular import Table, TableError, read_table

PARAMETERS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
REQUIRED_INTERVALS = (0, 24)
OPTIONAL_INTERVALS = (96, 168)


def column(p: str, h: int) -> str:
    return f"{p}_{h}h"


REQUIRED_COLUMNS = [column(p, h) for h in REQUIRED_INTERVALS for p in PARAMETERS]


@dataclass
class Issue:
    row: int
    message: str
    severity: str  # "error" (row/cell rejected) | "warning" (value imputed, column ignored, unit check)
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
    layout: Optional[str] = None
    column_map: List[Dict[str, Any]] = field(default_factory=list)
    units: Dict[str, Any] = field(default_factory=dict)
    needs_unit_confirmation: bool = False
    sha256: str = ""
    n_lots_in_file: int = 0
    parameters_used: List[str] = field(default_factory=list)

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
            "layout": self.layout,
            "column_map": self.column_map,
            "units": self.units,
            "needs_unit_confirmation": self.needs_unit_confirmation,
            "sha256": self.sha256,
            "n_lots_in_file": self.n_lots_in_file,
            "parameters_used": self.parameters_used,
            "issues": [i.as_dict() for i in self.issues[:1000]],
            "issues_truncated": max(0, len(self.issues) - 1000),
        }


def _missing_required(column_map: List[Dict[str, Any]], present_params: List[str]) -> List[str]:
    mapped = {(c.get("param"), c.get("hour")) for c in column_map if c.get("role") == "reading"}
    long_params = {c.get("param") for c in column_map if c.get("role") == "reading" and c.get("hour") is None}
    return [column(p, h) for h in REQUIRED_INTERVALS for p in PARAMETERS
            if (p, h) not in mapped and not (p in long_params and p in present_params)]


def parse_csv(source, test_parameter: Optional[str] = None, units: Optional[Dict[str, str]] = None) -> IngestResult:
    """`source`: CSV text or a text stream. `units`: {parameter: unit} overrides for the file's units."""
    try:
        t: Table = read_table(source, default_parameter=test_parameter, unit_overrides=units)
    except TableError as exc:
        missing = _missing_required(exc.column_map, []) if exc.column_map else []
        return IngestResult(ok=False, parts=[], issues=[Issue(1, str(exc), "error")], missing_columns=missing,
                            column_map=exc.column_map)
    except ValueError as exc:  # e.g. an unknown test_parameter
        return IngestResult(ok=False, parts=[], issues=[Issue(1, str(exc), "error")])

    res = IngestResult(ok=True, parts=[], issues=[Issue(**i) for i in t.issues], rows_total=t.rows_total,
                       rows_rejected=t.rows_rejected, duplicate_part_ids=t.duplicate_part_ids,
                       non_numeric_cells=t.non_numeric_cells, missing_cells=t.missing_cells,
                       conditions=t.conditions, layout=t.layout, column_map=t.column_map,
                       units=t.units, needs_unit_confirmation=t.needs_unit_confirmation, sha256=t.sha256,
                       n_lots_in_file=t.n_lots, parameters_used=list(t.params))
    params = list(t.params)
    if len(params) < len(PARAMETERS):
        res.issues.insert(0, Issue(1, f"Parameters used: {', '.join(params)}. The others are absent; the lot is screened "
                                      "by the same pipeline fitted on the training lots without them.", "warning"))

    if t.n_lots > 1:
        res.issues.insert(0, Issue(1, f"The file lists {t.n_lots} lots; ingest stores them as ONE lot, so lot-relative "
                                      "statistics mix them. Split the file per lot for correct screening.", "warning"))
    df = t.df
    order = sorted(df["component_id"].unique(), key=lambda c: t.part_rows.get(str(c), 0))
    by_part = {cid: g for cid, g in df.groupby("component_id", sort=False)}
    intervals_present = set(df["interval_hours"].unique())
    for cid in order:
        g = by_part[cid].set_index("interval_hours")
        values: Dict[int, Dict[str, Optional[float]]] = {}
        for h in (*REQUIRED_INTERVALS, *OPTIONAL_INTERVALS):
            if h not in intervals_present:
                continue
            values[h] = {p: (None if p not in params or h not in g.index or not np.isfinite(g.at[h, p])
                             else float(g.at[h, p])) for p in PARAMETERS}
        res.parts.append(ParsedPart(part_id=str(cid), row=t.part_rows.get(str(cid), 0), values=values))

    # Impute missing cells with the lot median of that column (display only), never with 0.
    for h in (*REQUIRED_INTERVALS, *OPTIONAL_INTERVALS):
        if h not in intervals_present:
            continue
        for p in params:
            observed = [pp.values[h][p] for pp in res.parts if pp.values[h][p] is not None]
            med = float(np.median(observed)) if observed else None
            for pp in res.parts:
                if pp.values[h][p] is not None:
                    continue
                if h in OPTIONAL_INTERVALS and all(pp.values[h][q] is None for q in params):
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
        if any(pp.values.get(h, {}).get(p) is None for h in REQUIRED_INTERVALS for p in params):
            pp.insufficient_data = True
    res.issues.sort(key=lambda i: (i.row, i.severity != "error"))
    return res
