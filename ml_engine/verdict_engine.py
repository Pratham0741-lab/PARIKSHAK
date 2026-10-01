"""
Unified verdict layer for SIH26170 screening.

Decision = union of Module A and Module B (plus specification rules):

  REJECT  - a datasheet limit is already breached on an observed reading (static check), or
            Module B forecasts a datasheet breach at 168h, or BOTH modules flag the part.
  REVIEW  - exactly one of Module A (score_a >= threshold_a) or Module B (score_b >= threshold_b) flags.
  PASS    - otherwise.

threshold_a / threshold_b are NOT constants: they are chosen by FN-weighted cost minimisation on
out-of-fold validation predictions (evaluation/thresholds.py) and persisted with the model. The
datasheet limits are specification values, not tuned thresholds.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import pandas as pd

from ml_engine.features import PARAMETERS

UNITS = {"leakage_current_ua": "uA", "iddq_ma": "mA", "propagation_delay_ns": "ns"}
PRED_COLUMN = {
    "leakage_current_ua": "pred_leakage_168h",
    "iddq_ma": "pred_iddq_168h",
    "propagation_delay_ns": "pred_delay_168h",
}


class ScreeningVerdictEngine:
    # Datasheet specification ceilings (absolute limits from the part datasheet).
    DATASHEET_LEAKAGE_MAX_UA: float = 50.0
    DATASHEET_IDDQ_MAX_MA: float = 5.0
    DATASHEET_DELAY_MAX_NS: float = 8.0

    @classmethod
    def datasheet_limits(cls) -> Dict[str, float]:
        return {
            "leakage_current_ua": cls.DATASHEET_LEAKAGE_MAX_UA,
            "iddq_ma": cls.DATASHEET_IDDQ_MAX_MA,
            "propagation_delay_ns": cls.DATASHEET_DELAY_MAX_NS,
        }

    def predicted_breaches(self, preds: Dict[str, float]) -> List[str]:
        return [p for p, lim in self.datasheet_limits().items() if preds[p] >= lim]

    def evaluate_component(
        self,
        observed_breach: bool,
        predictions_168h: Dict[str, float],
        module_a_score: float,
        threshold_a: float,
        module_b_score: float,
        threshold_b: float,
        module_b_label: str = "drift z (predicted rate vs lot safety slope)",
        limits: Dict[str, float] | None = None,
    ) -> Tuple[str, str]:
        limits = {**self.datasheet_limits(), **(limits or {})}
        a_flag = module_a_score >= threshold_a
        b_flag = module_b_score >= threshold_b
        ta = "off" if math.isinf(threshold_a) else f"{threshold_a:.3f}"
        tb = "off" if math.isinf(threshold_b) else f"{threshold_b:.4f}"
        a_txt = f"Module A lot-outlier score {module_a_score:.3f} {'>=' if a_flag else '<'} threshold {ta}"
        b_txt = f"Module B {module_b_label} {module_b_score:.4f} {'>=' if b_flag else '<'} threshold {tb}"

        if observed_breach:
            return "REJECT", "RULE_STATIC_LIMIT: an observed reading exceeds a datasheet limit."
        breached = [p for p, lim in limits.items() if predictions_168h.get(p) is not None
                    and not math.isnan(predictions_168h[p]) and predictions_168h[p] >= lim]
        if breached:
            parts = [f"{p} forecast {predictions_168h[p]:.3f} {UNITS[p]} >= limit {limits[p]:g} {UNITS[p]}" for p in breached]
            return "REJECT", "RULE_PRED_LIMIT: " + "; ".join(parts) + "."
        if a_flag and b_flag:
            return "REJECT", f"RULE_BOTH_MODULES: {a_txt}; {b_txt}."
        if a_flag:
            return "REVIEW", f"RULE_MODULE_A: {a_txt}; {b_txt}."
        if b_flag:
            return "REVIEW", f"RULE_MODULE_B: {b_txt}; {a_txt}."
        return "PASS", f"RULE_NOMINAL: {a_txt}; {b_txt}; no datasheet limit observed or forecast."

    def evaluate_dataframe(self, df: pd.DataFrame, threshold_a: float, threshold_b: float,
                           limits: Dict[str, float] | None = None) -> pd.DataFrame:
        verdicts, reasons = [], []
        for _, row in df.iterrows():
            v, r = self.evaluate_component(
                observed_breach=bool(row.get("observed_static_breach", False)),
                predictions_168h={p: float(row[PRED_COLUMN[p]]) for p in PARAMETERS},
                module_a_score=float(row["module_a_score"]),
                threshold_a=threshold_a,
                module_b_score=float(row["module_b_score"]),
                threshold_b=threshold_b,
                limits=limits,
            )
            verdicts.append(v)
            reasons.append(r)
        out = df.copy()
        out["verdict"] = verdicts
        out["verdict_reason"] = reasons
        return out
