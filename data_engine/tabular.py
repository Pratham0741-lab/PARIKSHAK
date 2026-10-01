"""
Robust reader for uploaded burn-in tables. Ingest, judge mode and the scoring CLI all use it.

Output: long readings in the ml_engine format
    component_id, lot_id, interval_hours, <parameters present, canonical units>, [temperature_c],
    [ground_truth_flag, ground_truth_label], insufficient_data

Layouts (detected from the header):
  wide   one row per part; one column per parameter and interval, e.g. leakage_current_ua_24h, Iddq_0h, I_0, T0
  long   one row per part and interval; an interval column plus one column per parameter
  tidy   one row per part, interval and parameter: part, interval, parameter, value [, unit]

Header matching is case-insensitive. Each header is split into words, a number (the interval in hours) and an
optional unit, e.g. "Iddq_0h", "leakage (nA) @ 24 h", "I_0", "T0", "tpd_168h_ps".
  * Parameter words: IDDQ = iddq/idd/iq/quiescent; delay = delay/tpd/tp/pd/propagation/prop;
    leakage = leakage/leak/ileak/il/i/ioff. A bare "I" means leakage current; IDDQ must be named.
    Misspellings are matched with difflib (similarity >= 0.8), and every fuzzy match is listed in `column_map`.
  * A reading column with no parameter word (T0, 0h, hr_24) belongs to the file's single monitored parameter
    (test_parameter; default leakage).
  * Intervals 0, 24, 96 and 168 h are used. Other intervals are reported and ignored. 96h is optional.
Units come from, in priority order: an explicit override, the header (nA/uA/mA/A, ps/ns/us), a `unit` column
(for the monitored parameter), else the canonical unit is assumed. Values are converted to the canonical units
(uA, mA, ns). A reading whose median is implausible for an assumed canonical unit raises `needs_unit_confirmation`.
Cells: blank, non-numeric or negative cells become NaN (never 0) and are listed in `issues` with their file line.
A repeated part ID (or part+interval in long/tidy files) keeps the first row and rejects the rest.
Parts missing a 0h or 24h value get `insufficient_data` (ingest imputes for display only and sends them to REVIEW).
Parsing is streamed row by row with csv.reader over a text stream, so a large upload is never held as one string.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, TextIO, Tuple

import numpy as np
import pandas as pd

from ml_engine.features import PARAMETERS

INTERVALS = (0, 24, 96, 168)
CANONICAL_UNIT = {"leakage_current_ua": "uA", "iddq_ma": "mA", "propagation_delay_ns": "ns"}
TO_CANONICAL = {  # multiply a value in <unit> by this to get the canonical unit
    "leakage_current_ua": {"pa": 1e-6, "na": 1e-3, "ua": 1.0, "ma": 1e3, "a": 1e6},
    "iddq_ma": {"na": 1e-6, "ua": 1e-3, "ma": 1.0, "a": 1e3},
    "propagation_delay_ns": {"ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9},
}
# Plausible 0h medians in canonical units; outside them an ASSUMED unit needs confirmation.
PLAUSIBLE = {"leakage_current_ua": (1e-3, 1e3), "iddq_ma": (1e-4, 1e2), "propagation_delay_ns": (1e-2, 1e3)}

PARAM_WORDS = {
    "iddq_ma": ("iddq", "idd", "iq", "quiescent"),
    "propagation_delay_ns": ("delay", "tpd", "tp", "pd", "propagation", "prop"),
    "leakage_current_ua": ("leakage", "leak", "ileak", "il", "i", "ioff"),
}
UNIT_WORDS = {"pa", "na", "ua", "ma", "a", "ps", "ns", "us", "ms", "s"}
FILLER_WORDS = {"h", "hr", "hrs", "hour", "hours", "t", "time", "at", "reading", "read", "val", "value", "current",
                "burn", "in", "bi", "after", "before", "meas", "measured"}
ROLE_ALIASES = {
    "id": ("component_id", "part_id", "part_no", "part_number", "serial_number", "serial", "part", "sn", "id",
           "device_id", "dut", "dut_id"),
    "lot": ("lot_id", "lot_number", "lot", "lot_no", "batch", "batch_id"),
    "interval": ("interval_hours", "interval", "hours", "time_h", "hour", "time", "t_h", "read_point", "readpoint"),
    "flag": ("ground_truth_flag", "defective", "is_defective", "defect_flag", "fail", "failed"),
    "label": ("ground_truth_label", "defect_type", "label", "class", "failure_mode"),
    "temperature": ("temperature_c", "temperature", "temp_c", "temp", "burn_in_temperature", "tj", "ta"),
    "unit": ("unit", "units"),
    "limit": ("static_limit", "limit", "datasheet_limit", "spec_limit", "usl"),
    "parameter": ("test_parameter", "parameter", "param", "measurement"),
    "value": ("value", "reading", "measured_value", "result"),
}
NORMAL_LABELS = ("", "NORMAL", "OK", "PASS", "GOOD", "NONE")
TRUE_STRINGS = {"true", "1", "yes", "y", "t", "defective", "fail", "failed"}
FUZZY_CUTOFF = 0.8
MAX_ISSUES = 2000


class TableError(ValueError):
    def __init__(self, message: str, column_map: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.column_map = column_map or []


@dataclass
class Col:
    header: str
    role: str                    # id | lot | interval | reading | flag | label | temperature | unit | limit | parameter | value | ignored
    param: Optional[str] = None
    hour: Optional[int] = None
    unit: Optional[str] = None   # unit found in the header
    how: str = "exact"           # exact | alias | fuzzy | bare-interval | ignored
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


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
    column_map: List[Dict[str, Any]] = field(default_factory=list)
    units: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    needs_unit_confirmation: bool = False
    conditions: Dict[str, Any] = field(default_factory=dict)
    rows_total: int = 0
    rows_rejected: int = 0
    duplicate_part_ids: int = 0
    non_numeric_cells: int = 0
    missing_cells: int = 0
    part_rows: Dict[str, int] = field(default_factory=dict)  # part ID -> first file line

    @property
    def insufficient_parts(self) -> int:
        return int(self.df.loc[self.df["insufficient_data"], "component_id"].nunique()) if len(self.df) else 0

    def summary(self) -> Dict[str, Any]:
        return {"layout": self.layout, "parameters": self.params, "has_labels": self.has_labels,
                "has_168h": self.has_168h, "n_parts": self.n_parts, "n_lots": self.n_lots,
                "rows_total": self.rows_total, "rows_rejected": self.rows_rejected,
                "duplicate_part_ids": self.duplicate_part_ids, "non_numeric_cells": self.non_numeric_cells,
                "missing_cells": self.missing_cells, "insufficient_data_parts": self.insufficient_parts,
                "column_map": self.column_map, "units": self.units,
                "needs_unit_confirmation": self.needs_unit_confirmation, "conditions_in_file": self.conditions,
                "n_issues": len(self.issues), "issues": self.issues[:500]}


# ------------------------------------------------------------------ header interpretation
_ALL_PARAM_WORDS = {w: p for p, words in PARAM_WORDS.items() for w in words}


def _words(text: str) -> List[str]:
    text = text.lower().replace("µ", "u").replace("μ", "u")
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", text)


def match_parameter(words: Iterable[str]) -> Tuple[Optional[str], str]:
    """(parameter, how) from header/value words: exact alias first, then difflib fuzzy match."""
    words = list(words)
    for p in PARAM_WORDS:  # IDDQ and delay are checked before the generic leakage words
        if any(w in PARAM_WORDS[p] for w in words):
            return p, "alias"
    joined = "".join(words)
    for p in PARAMETERS:
        if joined in (p.replace("_", ""), p):
            return p, "exact"
    for w in words:
        if len(w) < 4:
            continue
        m = difflib.get_close_matches(w, [x for x in _ALL_PARAM_WORDS if len(x) >= 4], n=1, cutoff=FUZZY_CUTOFF)
        if m:
            return _ALL_PARAM_WORDS[m[0]], f"fuzzy ({w!r} ~ {m[0]!r})"
    return None, ""


def interpret_header(header: str, default_param: str) -> Col:
    raw = header.strip()
    low = raw.lower().replace("µ", "u").replace("μ", "u")
    unit = None
    m = re.search(r"[\(\[]\s*([a-z]+)\s*[\)\]]", low)
    if m and m.group(1) in UNIT_WORDS:
        unit = m.group(1)
        low = low[: m.start()] + low[m.end():]
    words = _words(low)
    key = "_".join(words)
    for p in PARAMETERS:  # canonical names: leakage_current_ua_24h etc.
        mm = re.fullmatch(rf"{p}_(\d+)(?:_h)?", key)
        if mm:
            return _reading(raw, p, int(mm.group(1)), unit or CANONICAL_UNIT[p].lower(), "exact")
    for role, aliases in ROLE_ALIASES.items():
        if key in aliases:
            return Col(raw, role, unit=unit, how="exact" if key == aliases[0] else "alias")

    numbers = [w for w in words if re.fullmatch(r"\d+(?:\.\d+)?", w)]
    alpha = [w for w in words if not re.fullmatch(r"\d+(?:\.\d+)?", w)]
    if unit is None:
        trailing = [w for w in alpha if w in UNIT_WORDS and w not in ("a", "s")]
        if trailing:
            unit = trailing[-1]
    if len(numbers) == 1:
        hour = float(numbers[0])
        content = [w for w in alpha if w not in FILLER_WORDS and w not in UNIT_WORDS]
        if not content:
            return _reading(raw, default_param, hour, unit, "bare-interval")
        p, how = match_parameter(content)
        if p:
            return _reading(raw, p, hour, unit, how)
    return Col(raw, "ignored", how="ignored", note="not recognised")


def _reading(raw: str, p: str, hour: float, unit: Optional[str], how: str) -> Col:
    if hour not in INTERVALS:
        return Col(raw, "ignored", param=p, how="ignored", note=f"interval {hour:g}h is not one of 0/24/96/168h")
    if unit is not None and unit not in TO_CANONICAL[p]:
        return Col(raw, "ignored", param=p, how="ignored", note=f"unit {unit!r} does not fit {p}")
    return Col(raw, "reading", param=p, hour=int(hour), unit=unit, how=how)


# ------------------------------------------------------------------ cell parsing
def parse_number(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """(value, problem) with problem None | 'missing' | 'non_numeric' | 'negative'."""
    s = raw.strip() if raw is not None else ""
    if s == "" or s.lower() in ("na", "n/a", "nan", "null", "none", "-"):
        return None, "missing"
    try:
        v = float(s)
    except ValueError:
        return None, "non_numeric"
    if not np.isfinite(v):
        return None, "non_numeric"
    if v < 0:
        return None, "negative"
    return v, None


def _open(source) -> TextIO:
    if isinstance(source, str):
        return io.StringIO(source)
    return source


class _HashingReader(io.TextIOBase):
    """Wraps a text stream, hashing everything read through it (sha256 of the UTF-8 text)."""

    def __init__(self, inner: TextIO):
        self.inner, self.h = inner, hashlib.sha256()

    def readline(self, size: int = -1) -> str:
        s = self.inner.readline(size)
        self.h.update(s.encode())
        return s

    def __iter__(self):
        return self

    def __next__(self) -> str:
        s = self.readline()
        if not s:
            raise StopIteration
        return s


def read_table(source, default_parameter: Optional[str] = None,
               unit_overrides: Optional[Dict[str, str]] = None) -> Table:
    """Parse CSV text or a text stream. `default_parameter` names the parameter of bare interval columns
    (T0, 0h); `unit_overrides` = {parameter: unit} takes precedence over units in the file."""
    from ml_engine.conditions import normalise_parameter

    stream = _HashingReader(_open(source))
    first = stream.readline()
    while first and not first.strip():
        first = stream.readline()
    if not first:
        raise TableError("the file is empty")
    try:
        dialect = csv.Sniffer().sniff(first, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    def rows():
        yield from csv.reader([first], dialect)
        yield from csv.reader(stream, dialect)

    it = rows()
    header = [h for h in next(it)]
    issues: List[Dict[str, Any]] = []
    counts = {"rows_total": 0, "rows_rejected": 0, "duplicate_part_ids": 0, "non_numeric_cells": 0, "missing_cells": 0}

    def issue(row, message, severity="error", part_id=None, column=None):
        if len(issues) < MAX_ISSUES:
            issues.append({k: v for k, v in {"row": row, "part_id": part_id, "column": column, "message": message,
                                              "severity": severity}.items() if v is not None})

    overrides = {normalise_parameter(k): v.lower().replace("µ", "u") for k, v in (unit_overrides or {}).items() if v}
    default_param = normalise_parameter(default_parameter) or "leakage_current_ua"
    cols = [interpret_header(h, default_param) for h in header]
    roles = {c.role: i for i, c in reversed(list(enumerate(cols))) if c.role not in ("reading", "ignored")}
    if "parameter" in roles and "value" in roles:
        layout = "tidy"
    elif "interval" in roles:
        layout = "long"
        for i, c in enumerate(cols):  # in a long file, parameter-named columns are readings with no interval
            if c.role == "ignored":
                p, how = match_parameter([w for w in _words(c.header) if w not in UNIT_WORDS and w not in FILLER_WORDS])
                if p:
                    u = next((w for w in _words(c.header) if w in TO_CANONICAL[p]), None)
                    cols[i] = Col(c.header, "reading", param=p, unit=u, how=how)
    else:
        layout = "wide"
    if "id" not in roles:
        raise TableError(f"no part-ID column found (headers: {header}); expected e.g. part_id, serial_number",
                         [c.as_dict() for c in cols])

    seen_reading: Dict[Tuple[str, Optional[int]], int] = {}
    for i, c in enumerate(cols):
        if c.role == "reading":
            k = (c.param, c.hour)
            if k in seen_reading:
                cols[i] = Col(c.header, "ignored", param=c.param, how="ignored",
                              note=f"duplicate of column {cols[seen_reading[k]].header!r}")
                issue(1, f"column {c.header!r} maps to the same reading as {cols[seen_reading[k]].header!r}; ignored",
                      "warning", column=c.header)
            else:
                seen_reading[k] = i
    for c in cols:
        if c.role == "ignored":
            issue(1, f"column {c.header!r} ignored: {c.note}", "warning", column=c.header)

    id_i, lot_i = roles["id"], roles.get("lot")
    rec_id: List[str] = []
    rec_lot: List[str] = []
    rec_hour: List[int] = []
    rec_param: List[str] = []
    rec_val: List[float] = []
    rec_row: List[int] = []
    rec_unit: List[Optional[str]] = []
    rec_bare: List[bool] = []
    ignored_intervals: Dict[str, int] = {}
    meta_rows: Dict[str, Dict[str, str]] = {}
    lot_values: Dict[str, List[str]] = {r: [] for r in ("temperature", "unit", "limit", "parameter")}
    seen_ids: Dict[Any, int] = {}
    reading_cols = [(i, c) for i, c in enumerate(cols) if c.role == "reading"]

    def cell(r: List[str], i: Optional[int]) -> str:
        return r[i].strip() if i is not None and i < len(r) else ""

    line = 1
    for r in it:
        line += 1
        if not any(x.strip() for x in r) or r[0].lstrip().startswith("#"):
            continue
        counts["rows_total"] += 1
        pid = cell(r, id_i)
        if not pid:
            counts["rows_rejected"] += 1
            issue(line, "empty part ID; row rejected")
            continue
        lot = cell(r, lot_i) or "FILE"
        if layout == "wide":
            key: Any = pid
        elif layout == "long":
            key = (pid, cell(r, roles["interval"]))
        else:
            key = (pid, cell(r, roles["interval"]), cell(r, roles["parameter"]).lower())
        if key in seen_ids:
            counts["rows_rejected"] += 1
            counts["duplicate_part_ids"] += 1
            issue(line, f"duplicate part ID (first seen on line {seen_ids[key]}); row rejected", part_id=pid)
            continue
        seen_ids[key] = line
        for role in lot_values:
            if role in roles and cell(r, roles[role]):
                lot_values[role].append(cell(r, roles[role]))
        m = meta_rows.setdefault(pid, {})
        for role in ("flag", "label", "temperature"):
            if role in roles and cell(r, roles[role]) and role not in m:
                m[role] = cell(r, roles[role])

        if layout == "wide":
            items = [(c.param, c.hour, cell(r, i), c.header, c.unit, c.how == "bare-interval") for i, c in reading_cols]
        else:
            hv, hp = parse_number(cell(r, roles["interval"]))
            if hv is None or hv not in INTERVALS:
                if hv is None:
                    issue(line, f"interval {cell(r, roles['interval'])!r} is not a number; row ignored", part_id=pid)
                else:
                    ignored_intervals[f"{hv:g}"] = ignored_intervals.get(f"{hv:g}", 0) + 1
                continue
            if layout == "long":
                items = [(c.param, int(hv), cell(r, i), c.header, c.unit, False) for i, c in reading_cols]
            else:
                pname = cell(r, roles["parameter"])
                p, _ = match_parameter(_words(pname))
                if p is None:
                    issue(line, f"parameter {pname!r} not recognised; row ignored", part_id=pid)
                    continue
                u = cell(r, roles["unit"]).lower().replace("µ", "u") if "unit" in roles else None
                items = [(p, int(hv), cell(r, roles["value"]), cols[roles["value"]].header, u or None, False)]
        for p, h, raw, colname, unit, bare in items:
            v, problem = parse_number(raw)
            if problem == "missing":
                counts["missing_cells"] += 1
            elif problem:
                counts["non_numeric_cells"] += 1
                issue(line, f"{'negative' if problem == 'negative' else 'non-numeric'} value {raw!r}; treated as missing",
                      part_id=pid, column=colname)
            rec_id.append(pid)
            rec_lot.append(lot)
            rec_hour.append(h)
            rec_param.append(p)
            rec_val.append(np.nan if v is None else v)
            rec_row.append(line)
            rec_unit.append(unit)
            rec_bare.append(bare)

    for hv, n in ignored_intervals.items():
        issue(1, f"{n} row(s) at interval {hv}h ignored (only 0/24/96/168h are used)", "warning")
    if not rec_id:
        raise TableError("no readings found: check that the file has part-ID and reading columns",
                         [c.as_dict() for c in cols])

    long = pd.DataFrame({"component_id": rec_id, "lot_id": rec_lot, "interval_hours": rec_hour, "param": rec_param,
                         "value": np.asarray(rec_val, float), "row": rec_row, "unit": rec_unit})

    # ---- units: override > header/row unit > unit column (for the monitored parameter) > canonical (assumed)
    conditions: Dict[str, Any] = {}
    for role, key in (("temperature", "temperature_c"), ("limit", "static_limit"), ("parameter", "test_parameter"),
                      ("unit", "unit")):
        vals = lot_values[role]
        if not vals or (layout == "tidy" and role in ("parameter", "unit")):
            continue  # in a tidy file these columns vary per row
        common = max(set(vals), key=vals.count)
        if len(set(vals)) > 1:
            issue(1, f"column {cols[roles[role]].header!r} has {len(set(vals))} different values; using the most "
                     f"common one ({common!r})", "warning", column=cols[roles[role]].header)
        if key in ("temperature_c", "static_limit"):
            v, _ = parse_number(common)
            if v is None:
                issue(1, f"{key} value {common!r} is not numeric; ignored", column=cols[roles[role]].header)
            else:
                conditions[key] = v
        else:
            conditions[key] = common
    try:
        monitored = normalise_parameter(conditions.get("test_parameter")) if conditions.get("test_parameter") else None
    except ValueError as exc:
        issue(1, str(exc), column="test_parameter")
        monitored = None
    bare = np.asarray(rec_bare, bool)
    if bare.any() and monitored and not default_parameter and monitored != default_param:
        # bare interval columns (T0, 0h) belong to the file's own test_parameter
        long.loc[bare, "param"] = monitored
        for c in cols:
            if c.how == "bare-interval":
                c.param = monitored
    file_unit = str(conditions.get("unit", "")).lower().replace("µ", "u") or None

    units: Dict[str, Dict[str, Any]] = {}
    needs_confirm = False
    params_present = [p for p in PARAMETERS if p in set(long["param"])]
    for p in params_present:
        sel = long["param"] == p
        if p in overrides:
            chosen = {u: "override" for u in [overrides[p]]}
            long.loc[sel, "unit"] = overrides[p]
        else:
            fill = file_unit if (file_unit and (monitored == p or len(params_present) == 1)
                                 and file_unit in TO_CANONICAL[p]) else None
            src = "unit column" if fill else "assumed canonical"
            chosen = {}
            for u in long.loc[sel, "unit"].dropna().unique():
                chosen[u] = "file header" if layout != "tidy" else "unit column"
            if long.loc[sel, "unit"].isna().any():
                u0 = fill or CANONICAL_UNIT[p].lower()
                long.loc[sel & long["unit"].isna(), "unit"] = u0
                chosen.setdefault(u0, src)
        bad_units = [u for u in chosen if u not in TO_CANONICAL[p]]
        if bad_units:
            raise TableError(f"unit(s) {bad_units} are not valid for {p} (accepted: {sorted(TO_CANONICAL[p])})")
        factors = long.loc[sel, "unit"].map(TO_CANONICAL[p])
        long.loc[sel, "value"] = long.loc[sel, "value"] * factors
        early = long.loc[sel & (long["interval_hours"] == 0), "value"]
        med = float(early.median()) if early.notna().any() else float("nan")
        lo, hi = PLAUSIBLE[p]
        implausible = bool(np.isfinite(med) and not lo <= med <= hi)
        assumed = any(s == "assumed canonical" for s in chosen.values())
        converted = any(u != CANONICAL_UNIT[p].lower() for u in chosen)
        units[p] = {"canonical": CANONICAL_UNIT[p], "detected": {u: s for u, s in chosen.items()},
                    "converted": converted, "median_0h_canonical": None if not np.isfinite(med) else round(med, 6),
                    "plausible_range": [lo, hi], "implausible": implausible}
        if implausible:
            issue(1, f"{p}: 0h median {med:.4g} {CANONICAL_UNIT[p]} is outside the plausible range {lo:g}-{hi:g} "
                     f"{CANONICAL_UNIT[p]}; check the unit ({'assumed' if assumed else 'as given'})", "warning", column=p)
        needs_confirm |= converted or implausible

    wide = long.groupby(["component_id", "interval_hours", "param"], sort=False)["value"].first().unstack("param")
    wide = wide.reset_index()
    wide.columns.name = None
    params = [p for p in PARAMETERS if p in wide.columns
              and wide.loc[wide["interval_hours"] == 0, p].notna().any()
              and wide.loc[wide["interval_hours"] == 24, p].notna().any()]
    dropped = [p for p in params_present if p not in params]
    for p in dropped:
        issue(1, f"{p} has no 0h or no 24h readings; not used", "warning", column=p)
        wide = wide.drop(columns=[p])
    if not params:
        raise TableError("no parameter has both 0h and 24h readings", [c.as_dict() for c in cols])
    # a part may be listed with one lot on some rows and another on others: keep the first lot
    first_lot = long.drop_duplicates("component_id").set_index("component_id")["lot_id"]
    wide["lot_id"] = wide["component_id"].map(first_lot)

    has_labels = False
    meta = pd.DataFrame.from_dict(meta_rows, orient="index")
    if "flag" in meta.columns:
        has_labels = True
        wide["ground_truth_flag"] = wide["component_id"].map(meta["flag"].astype(str).str.strip().str.lower()
                                                               .isin(TRUE_STRINGS)).fillna(False).astype(bool)
    if "label" in meta.columns:
        lab = meta["label"].astype(str).str.strip().str.upper()
        wide["ground_truth_label"] = wide["component_id"].map(lab).fillna("")
        if not has_labels:
            has_labels = True
            wide["ground_truth_flag"] = ~wide["ground_truth_label"].isin(NORMAL_LABELS)
    if "temperature" in meta.columns:
        wide["temperature_c"] = wide["component_id"].map(pd.to_numeric(meta["temperature"], errors="coerce"))
    elif "temperature_c" in conditions:
        wide["temperature_c"] = conditions["temperature_c"]

    early = wide[wide["interval_hours"].isin((0, 24))].dropna(subset=params)
    complete = early.groupby("component_id")["interval_hours"].nunique()
    ok_ids = set(complete[complete == 2].index)
    wide["insufficient_data"] = ~wide["component_id"].isin(ok_ids)
    first_row = long.groupby("component_id")["row"].min()
    for cid in sorted(set(wide["component_id"]) - ok_ids, key=lambda c: first_row.get(c, 0)):
        issue(int(first_row.get(cid, 0)), "missing a 0h/24h value; the part cannot be scored (REVIEW)",
              "warning", part_id=cid)
    wide = wide.sort_values(["component_id", "interval_hours"]).reset_index(drop=True)

    column_map = [c.as_dict() for c in cols]
    return Table(df=wide, params=params, layout=layout, has_labels=has_labels,
                 has_168h=bool(wide.loc[wide["interval_hours"] == 168, params].notna().any(axis=None)),
                 n_parts=int(wide["component_id"].nunique()), n_lots=int(wide["lot_id"].nunique()),
                 issues=issues, sha256=stream.h.hexdigest(), column_map=column_map, units=units,
                 needs_unit_confirmation=bool(needs_confirm), conditions=conditions,
                 part_rows={str(k): int(v) for k, v in first_row.items()}, **counts)
