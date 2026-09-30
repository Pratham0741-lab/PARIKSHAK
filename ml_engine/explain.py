"""
Per-part explanations built ONLY from the numbers the models produced for that part.

Inputs are the persisted prediction (scores, learned thresholds, forecasts, prediction
intervals, safety-slope derivation, Module A decomposition, Module B TreeSHAP contributions)
and the part's observed readings. Nothing here is a template filled with constants: every
number in the text is read from those inputs, and the "largest contributor" statements name
the features with the largest absolute contribution.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from ml_engine.features import PARAMETERS
from ml_engine.verdict_engine import ScreeningVerdictEngine

UNIT = {"leakage_current_ua": "uA", "iddq_ma": "mA", "propagation_delay_ns": "ns"}
NAME = {"leakage_current_ua": "leakage current", "iddq_ma": "IDDQ", "propagation_delay_ns": "propagation delay"}
PRED_FIELD = {"leakage_current_ua": "pred_leakage_168h", "iddq_ma": "pred_iddq_168h", "propagation_delay_ns": "pred_delay_168h"}

_SUFFIX = [
    ("_v0_over_lot_median", "0h value / lot median"),
    ("_v24_over_lot_median", "24h value / lot median"),
    ("_v0_lot_median", "lot median at 0h"),
    ("_v24_lot_median", "lot median at 24h"),
    ("_delta_lot_median", "lot median 0-24h change"),
    ("_v0_lot_mad", "lot spread at 0h"),
    ("_v24_lot_mad", "lot spread at 24h"),
    ("_delta_lot_mad", "lot spread of 0-24h change"),
    ("_v0_lot_z", "0h robust z vs lot"),
    ("_v24_lot_z", "24h robust z vs lot"),
    ("_delta_lot_z", "0-24h change robust z vs lot"),
    ("_lot_dist24", "24h distance from lot median"),
    ("_lot_delta", "0-24h change vs lot median change"),
    ("_rel_delta", "relative 0-24h change"),
    ("_slope24", "0-24h slope"),
    ("_ratio", "24h/0h ratio"),
    ("_delta", "0-24h change"),
    ("_v0", "0h reading"),
    ("_v24", "24h reading"),
]


def feature_label(feature: str) -> str:
    for p in PARAMETERS:
        if feature.startswith(p):
            rest = feature[len(p):]
            for suf, text in _SUFFIX:
                if rest == suf:
                    return f"{NAME[p]}: {text}"
    return re.sub(r"_", " ", feature)


def _fmt(x: Optional[float], nd: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def module_b_contributions(details: Dict[str, Any], parameter: str) -> List[Dict[str, Any]]:
    """Signed contributions for one parameter, with the multiplicative effect for log-ratio targets."""
    contrib = (details or {}).get("module_b_contributions") or {}
    entry = contrib.get(parameter)
    if not entry:
        return []
    target = contrib.get("target", "raw")
    out = []
    for item in entry["top"]:
        v = float(item["value"])
        row = {"feature": item["feature"], "label": feature_label(item["feature"]), "value": v, "target_space": target}
        if target == "log_ratio":
            row["effect_pct_on_forecast"] = 100.0 * (math.exp(v) - 1.0)
        out.append(row)
    if entry.get("other"):
        out.append({"feature": "__other__", "label": "all other features", "value": float(entry["other"]),
                    "target_space": target})
    return out


def build_explanation(pred: Dict[str, Any], readings: List[Dict[str, Any]], serial: str, lot_number: str) -> Dict[str, Any]:
    details = pred.get("details") or {}
    limits = ScreeningVerdictEngine.datasheet_limits()

    # ---------------- Module A
    ma = details.get("module_a") or {}
    a_params = ma.get("per_parameter") or {}
    a_rows = [
        {"parameter": p, **a_params[p]} for p in PARAMETERS if p in a_params
    ]
    a_top = max(a_rows, key=lambda r: abs(r["contribution"] or 0.0)) if a_rows else None
    ta = pred.get("threshold_a")
    a_flag = bool(pred.get("module_a_flag"))

    # ---------------- Module B
    ss = details.get("safety_slope") or {}
    per_b = ss.get("per_parameter") or {}
    driver = ss.get("driver_parameter") or "leakage_current_ua"
    k = ss.get("k")
    intervals = (details.get("prediction_interval") or {}).get("per_parameter") or {}
    b_rows = []
    for p in PARAMETERS:
        d = per_b.get(p, {})
        iv = intervals.get(p, {})
        b_rows.append({
            "parameter": p,
            "forecast_168h": pred.get(PRED_FIELD[p]),
            "interval_lower": iv.get("lower"),
            "interval_upper": iv.get("upper"),
            "predicted_rate": d.get("predicted_rate"),
            "lot_median_rate": d.get("lot_median_rate"),
            "lot_spread": d.get("lot_spread"),
            "safety_slope": d.get("safety_slope"),
            "z": d.get("z"),
            "exceeds_safety_slope": d.get("exceeds_safety_slope"),
            "rate_unit": d.get("unit"),
        })
    b_contrib = module_b_contributions(details, driver)
    b_real = [c for c in b_contrib if c["feature"] != "__other__"]
    b_top = max(b_real, key=lambda c: abs(c["value"])) if b_real else None

    # ---------------- static limit
    observed = {p: max((r[p] for r in readings if r["interval_hours"] in (0, 24)), default=None) for p in PARAMETERS}
    observed_breach = {p: (observed[p] is not None and observed[p] > limits[p]) for p in PARAMETERS}
    forecast_breach = {p: (pred.get(PRED_FIELD[p]) is not None and pred[PRED_FIELD[p]] >= limits[p]) for p in PARAMETERS}

    # ---------------- plain language (every number comes from the inputs above)
    lines = [f"{serial} (lot {lot_number}): verdict {pred.get('verdict')}. {pred.get('verdict_reason', '')}"]
    if a_top is not None:
        lines.append(
            f"Module A (lot-relative outlier): score {_fmt(pred.get('module_a_score'), 2)} "
            f"{'>=' if a_flag else '<'} learned threshold {_fmt(ta, 2) if ta is not None else 'off'}. "
            f"Largest Module A contributor: {a_top['parameter']} ({NAME[a_top['parameter']]}) at "
            f"{a_top['robust_z']:+.1f} lot-MADs from the lot median "
            f"({_fmt(a_top['value_0_24h_mean'], 3)} {UNIT[a_top['parameter']]} mean of 0h/24h vs lot median "
            f"{_fmt(a_top['lot_median'], 3)} {UNIT[a_top['parameter']]})."
        )
    d = next(r for r in b_rows if r["parameter"] == driver)
    if d["forecast_168h"] is not None:
        lines.append(
            f"Module B (drift): forecast 168h {NAME[driver]} {_fmt(d['forecast_168h'])} {UNIT[driver]} "
            f"(90% interval {_fmt(d['interval_lower'])} to {_fmt(d['interval_upper'])}); predicted drift "
            f"{_fmt(d['predicted_rate'], 5)} {d['rate_unit']} vs this lot's safety slope {_fmt(d['safety_slope'], 5)} "
            f"{d['rate_unit']} (lot median {_fmt(d['lot_median_rate'], 5)} + k={_fmt(k, 2)} x spread "
            f"{_fmt(d['lot_spread'], 5)}): {'EXCEEDS' if d['exceeds_safety_slope'] else 'within'} the safety slope."
        )
    if b_top is not None:
        eff = b_top.get("effect_pct_on_forecast")
        lines.append(
            f"Largest Module B contributor to the {NAME[driver]} forecast: {b_top['feature']} ({b_top['label']}), "
            f"contribution {b_top['value']:+.4f}" + (f" ({eff:+.1f}% on the forecast)." if eff is not None else ".")
        )
    lp = "leakage_current_ua"
    lines.append(
        f"Static limit ({limits[lp]:g} {UNIT[lp]} leakage): highest observed 0h/24h reading "
        f"{_fmt(observed[lp])} {UNIT[lp]} ({'BREACHED' if observed_breach[lp] else 'passes'}); "
        f"168h forecast {'reaches' if forecast_breach[lp] else 'stays below'} the limit."
    )

    return {
        "serial_number": serial,
        "lot_number": lot_number,
        "verdict": pred.get("verdict"),
        "verdict_reason": pred.get("verdict_reason"),
        "summary": " ".join(lines),
        "module_a": {
            "score": pred.get("module_a_score"),
            "threshold": ta,
            "flag": a_flag,
            "decision_statistic": ma.get("decision_statistic"),
            "contributions": a_rows,
            "diagnostics": ma.get("diagnostics"),
            "top_contributor": a_top["parameter"] if a_top else None,
        },
        "module_b": {
            "score": pred.get("module_b_score"),
            "threshold_k": pred.get("threshold_b"),
            "flag": bool(pred.get("module_b_flag")),
            "driver_parameter": driver,
            "per_parameter": b_rows,
            "contributions": b_contrib,
            "contribution_target_space": b_contrib[0]["target_space"] if b_contrib else None,
            "top_contributor": b_top["feature"] if b_top else None,
            "interval_coverage_target": (details.get("prediction_interval") or {}).get("coverage_target"),
        },
        "static_limit": {
            "limits": limits,
            "max_observed_0_24h": observed,
            "observed_breach": observed_breach,
            "forecast_breach": forecast_breach,
        },
    }
