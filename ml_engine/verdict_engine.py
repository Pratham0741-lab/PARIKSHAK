"""
Unified Verdict Layer for ISRO SIH26170 Screening & Analytics.
Applies deterministic safety, outlier, and drift rules to triage components
into PASS, REVIEW, or REJECT with rule-trace justifications.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
import pandas as pd


class ScreeningVerdictEngine:
    """
    Deterministic rule-based verdict engine implementing high-reliability aerospace triage.
    Tuned for maximum Recall and minimum False Negatives on space-grade components.
    """

    # Absolute Datasheet Specification Ceilings
    DATASHEET_LEAKAGE_MAX_UA: float = 50.0
    DATASHEET_IDDQ_MAX_MA: float = 5.0
    DATASHEET_DELAY_MAX_NS: float = 8.0

    # Module A Score Thresholds
    MODULE_A_REJECT_THRESHOLD: float = 0.85
    MODULE_A_REVIEW_THRESHOLD: float = 0.50

    # Module B Drift Thresholds
    DRIFT_SLOPE_RUNAWAY_UA_HR: float = 0.20   # Extreme drift -> REJECT
    DRIFT_SLOPE_ELEVATED_UA_HR: float = 0.12  # Moderate drift -> REVIEW
    PRED_LEAKAGE_ELEVATED_UA: float = 35.0    # Soft degradation ceiling -> REVIEW

    def evaluate_component(
        self,
        is_datasheet_breached: bool,
        module_a_score: float,
        module_a_flag: bool,
        pred_leakage_168h: float,
        pred_iddq_168h: float,
        pred_delay_168h: float,
        drift_slope_ua_per_hr: float,
        module_b_flag: bool,
    ) -> Tuple[str, str]:
        """
        Evaluates a single component across physical specifications, spatial lot metrics,
        and temporal drift forecasts.

        Returns:
            Tuple[verdict ('PASS' | 'REVIEW' | 'REJECT'), verdict_reason]
        """
        # ======================================================================
        # Priority 1: REJECT Rules (Gross Failures & Catastrophic Projections)
        # ======================================================================
        if is_datasheet_breached:
            return (
                "REJECT",
                "RULE_BREACH: Hardware measurement exceeded absolute datasheet ceiling during burn-in.",
            )

        if pred_leakage_168h >= self.DATASHEET_LEAKAGE_MAX_UA:
            return (
                "REJECT",
                f"RULE_PRED_CEILING: Projected 168h leakage ({pred_leakage_168h:.2f} uA) breaches 50 uA ceiling.",
            )

        if pred_iddq_168h >= self.DATASHEET_IDDQ_MAX_MA:
            return (
                "REJECT",
                f"RULE_PRED_CEILING: Projected 168h IDDQ ({pred_iddq_168h:.2f} mA) breaches 5.0 mA ceiling.",
            )

        if pred_delay_168h >= self.DATASHEET_DELAY_MAX_NS:
            return (
                "REJECT",
                f"RULE_PRED_CEILING: Projected 168h delay ({pred_delay_168h:.2f} ns) breaches 8.0 ns ceiling.",
            )

        if drift_slope_ua_per_hr >= self.DRIFT_SLOPE_RUNAWAY_UA_HR:
            return (
                "REJECT",
                f"RULE_RUNAWAY_DRIFT: Severe leakage drift rate ({drift_slope_ua_per_hr:.4f} uA/hr) indicates runaway kinetics.",
            )

        if module_a_score >= self.MODULE_A_REJECT_THRESHOLD:
            return (
                "REJECT",
                f"RULE_EXTREME_OUTLIER: Module A spatial anomaly score ({module_a_score:.3f}) exceeds critical limit 0.85.",
            )

        # ======================================================================
        # Priority 2: REVIEW Rules (Latent Anomalies, Kinetic Drift, Borderline)
        # ======================================================================
        review_reasons: List[str] = []

        if module_a_flag or (module_a_score >= self.MODULE_A_REVIEW_THRESHOLD):
            review_reasons.append(
                f"Module A lot outlier flagged (score={module_a_score:.3f})"
            )

        if pred_leakage_168h >= self.PRED_LEAKAGE_ELEVATED_UA:
            review_reasons.append(
                f"Forecasted 168h leakage ({pred_leakage_168h:.2f} uA) exceeds safety margin (35 uA)"
            )

        if drift_slope_ua_per_hr >= self.DRIFT_SLOPE_ELEVATED_UA_HR:
            review_reasons.append(
                f"Elevated drift slope ({drift_slope_ua_per_hr:.4f} uA/hr)"
            )

        if module_b_flag and not review_reasons:
            review_reasons.append("Module B early drift warning triggered")

        if review_reasons:
            return ("REVIEW", "RULE_BORDERLINE: " + "; ".join(review_reasons) + ".")

        # ======================================================================
        # Priority 3: PASS Rules (Normal Envelope, Stable Kinetics)
        # ======================================================================
        return (
            "PASS",
            "RULE_NOMINAL: Component within lot baseline envelope; drift kinetics stable through 168h forecast.",
        )

    def evaluate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Evaluates an entire dataframe of component screening predictions.

        Expected columns in df:
            - is_datasheet_breached (optional, defaults to False)
            - module_a_score
            - module_a_flag
            - pred_leakage_168h
            - pred_iddq_168h
            - pred_delay_168h
            - drift_slope_ua_per_hr
            - module_b_flag

        Returns:
            pd.DataFrame: Adds 'verdict' and 'verdict_reason' columns.
        """
        verdicts: List[str] = []
        reasons: List[str] = []

        # Prefer the breach observed on readings available at decision time (0h/24h).
        breach_col = next(
            (c for c in ("observed_static_breach", "is_datasheet_breached") if c in df.columns), None
        )

        for _, row in df.iterrows():
            breached = bool(row[breach_col]) if breach_col else False
            v, r = self.evaluate_component(
                is_datasheet_breached=breached,
                module_a_score=float(row["module_a_score"]),
                module_a_flag=bool(row["module_a_flag"]),
                pred_leakage_168h=float(row["pred_leakage_168h"]),
                pred_iddq_168h=float(row["pred_iddq_168h"]),
                pred_delay_168h=float(row["pred_delay_168h"]),
                drift_slope_ua_per_hr=float(row["drift_slope_ua_per_hr"]),
                module_b_flag=bool(row["module_b_flag"]),
            )
            verdicts.append(v)
            reasons.append(r)

        result_df = df.copy()
        result_df["verdict"] = verdicts
        result_df["verdict_reason"] = reasons
        return result_df
