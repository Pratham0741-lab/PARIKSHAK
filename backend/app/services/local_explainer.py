"""
Local Deterministic Explainability Engine for Aerospace Burn-In Screening.
Provides 100% deterministic, audit-ready engineering explanations using robust
lot statistics (Median / MAD), Mahalanobis decomposition, and LightGBM drift metrics
without any external LLM or third-party API dependencies.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd


class DeterministicExplainer:
    """
    Deterministic rule-based explainability engine for component screening.
    Deconstructs spatial lot-relative excursions and temporal drift trajectories
    into aerospace-grade engineering justifications and risk categorizations.
    """

    # Absolute Datasheet Specification Limits
    DATASHEET_LEAKAGE_MAX_UA: float = 50.0
    DATASHEET_IDDQ_MAX_MA: float = 5.0
    DATASHEET_DELAY_MAX_NS: float = 8.0

    # Risk Thresholds
    DRIFT_SLOPE_RUNAWAY_UA_HR: float = 0.20
    OUTLIER_MAD_THRESHOLD: float = 4.0
    MAHALANOBIS_SUBTLE_THRESHOLD: float = 3.0
    MODULE_A_REJECT_THRESHOLD: float = 0.85

    PARAMETERS = [
        ("leakage_current_ua", "Leakage Current (uA)", 50.0),
        ("iddq_ma", "IDDQ Current (mA)", 5.0),
        ("propagation_delay_ns", "Propagation Delay (ns)", 8.0),
    ]

    INTERVALS = [0, 24, 96, 168]

    def compute_lot_statistics(
        self,
        lot_readings: Union[pd.DataFrame, List[Dict[str, Any]]],
    ) -> Dict[str, Dict[int, Dict[str, float]]]:
        """
        Calculates robust location (Median) and scale (MAD) for each parameter
        at each test interval across all components in the lot.

        Returns:
            Dict[param, Dict[interval, {'median': float, 'mad': float, 'min': float, 'p25': float, 'p75': float, 'max': float}]]
        """
        if isinstance(lot_readings, list):
            df = pd.DataFrame(lot_readings)
        else:
            df = lot_readings.copy()

        stats: Dict[str, Dict[int, Dict[str, float]]] = {}

        for param, _, _ in self.PARAMETERS:
            stats[param] = {}
            if param not in df.columns:
                continue

            for interval in self.INTERVALS:
                sub = df[df["interval_hours"] == interval]
                if sub.empty:
                    continue

                vals = sub[param].to_numpy(dtype=float)
                med = float(np.median(vals))
                abs_dev = np.abs(vals - med)
                mad = float(np.median(abs_dev))
                if mad < 1e-6:
                    mad = 1e-6

                q25 = float(np.percentile(vals, 25))
                q75 = float(np.percentile(vals, 75))
                val_min = float(np.min(vals))
                val_max = float(np.max(vals))

                stats[param][interval] = {
                    "median": med,
                    "mad": mad,
                    "min": val_min,
                    "p25": q25,
                    "p75": q75,
                    "max": val_max,
                }

        return stats

    def explain_component(
        self,
        component_data: Dict[str, Any],
        component_readings: List[Dict[str, Any]],
        lot_statistics: Optional[Dict[str, Dict[int, Dict[str, float]]]] = None,
        prediction_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a deterministic, mathematically grounded explanation for a component.

        Args:
            component_data: Serial number, lot id/number, wafer id, ground truth, breach flag.
            component_readings: List of reading dicts for 0h, 24h, 96h, 168h.
            lot_statistics: Optional precomputed lot envelope stats.
            prediction_data: ModelPrediction dictionary with scores and forecasted values.

        Returns:
            Structured dictionary matching ComponentExplanation.
        """
        serial = component_data.get("serial_number", "UNKNOWN")
        lot_num = component_data.get("lot_number", "UNKNOWN")
        wafer_id = component_data.get("wafer_id", "UNKNOWN")
        is_breached = bool(component_data.get("is_datasheet_breached", False))

        readings_by_interval: Dict[int, Dict[str, float]] = {}
        for r in component_readings:
            interval = int(r["interval_hours"])
            readings_by_interval[interval] = {
                "leakage_current_ua": float(r["leakage_current_ua"]),
                "iddq_ma": float(r["iddq_ma"]),
                "propagation_delay_ns": float(r["propagation_delay_ns"]),
            }

        # Prediction values
        pred = prediction_data or {}
        module_a_score = float(pred.get("module_a_score", 0.0))
        module_a_mahalanobis = float(pred.get("module_a_mahalanobis", 0.0))
        module_a_flag = bool(pred.get("module_a_flag", False))
        pred_leakage_168h = float(pred.get("pred_leakage_168h", readings_by_interval.get(24, {}).get("leakage_current_ua", 0.0)))
        pred_iddq_168h = float(pred.get("pred_iddq_168h", readings_by_interval.get(24, {}).get("iddq_ma", 0.0)))
        pred_delay_168h = float(pred.get("pred_delay_168h", readings_by_interval.get(24, {}).get("propagation_delay_ns", 0.0)))
        drift_slope = float(pred.get("drift_slope_ua_per_hr", 0.0))
        module_b_flag = bool(pred.get("module_b_flag", False))
        verdict = str(pred.get("verdict", "PASS"))
        verdict_reason = str(pred.get("verdict_reason", "Nominal"))

        # Calculate drift slopes if not in prediction
        if drift_slope == 0.0 and 0 in readings_by_interval and 24 in readings_by_interval:
            v0 = readings_by_interval[0]["leakage_current_ua"]
            v24 = readings_by_interval[24]["leakage_current_ua"]
            drift_slope = (v24 - v0) / 24.0

        # Compute Z_MAD metrics across parameters and intervals
        param_metrics: Dict[str, Dict[str, Any]] = {}
        max_abs_z = -1.0
        primary_param = "leakage_current_ua"
        z_0h_by_param: Dict[str, float] = {}

        for param, label, ceiling in self.PARAMETERS:
            param_metrics[param] = {
                "label": label,
                "ceiling": ceiling,
                "intervals": {},
                "max_abs_z_mad": 0.0,
                "has_breach": False,
            }

            for interval in self.INTERVALS:
                if interval not in readings_by_interval:
                    continue

                val = readings_by_interval[interval][param]
                if val >= ceiling:
                    param_metrics[param]["has_breach"] = True
                    is_breached = True

                med = None
                mad = None
                z_mad = 0.0

                if lot_statistics and param in lot_statistics and interval in lot_statistics[param]:
                    med = lot_statistics[param][interval]["median"]
                    mad = lot_statistics[param][interval]["mad"]
                    denom = max(mad, 1e-6)
                    z_mad = (val - med) / denom

                param_metrics[param]["intervals"][interval] = {
                    "value": round(val, 4),
                    "lot_median": round(med, 4) if med is not None else None,
                    "lot_mad": round(mad, 4) if mad is not None else None,
                    "z_mad": round(z_mad, 3),
                }

                if abs(z_mad) > param_metrics[param]["max_abs_z_mad"]:
                    param_metrics[param]["max_abs_z_mad"] = abs(z_mad)

                if interval == 0:
                    z_0h_by_param[param] = z_mad

            if param_metrics[param]["max_abs_z_mad"] > max_abs_z:
                max_abs_z = param_metrics[param]["max_abs_z_mad"]
                primary_param = param

        # If leakage has extreme drift slope, prioritize leakage as primary
        if drift_slope >= 0.12:
            primary_param = "leakage_current_ua"

        # Check if datasheet was breached on any parameter
        for p, meta in param_metrics.items():
            if meta["has_breach"]:
                primary_param = p
                break

        # Risk Classification Logic
        # 1. CRITICAL_RUNAWAY: Drift >= 0.20 uA/hr or pred 168h leakage >= 50 or hardware breach
        # 2. LATENT_LOT_OUTLIER: Initial 0h reading >= 4.0 MAD above lot median
        # 3. SUBTLE_DEGRADATION: Elevated Mahalanobis (>= 3.0) or multi-param shift or module_a_flag
        # 4. NOMINAL: Normal lot envelope
        max_0h_z = max(z_0h_by_param.values()) if z_0h_by_param else 0.0
        multi_param_elevated = sum(1 for z in z_0h_by_param.values() if z >= 2.0) >= 2

        if (
            is_breached
            or drift_slope >= self.DRIFT_SLOPE_RUNAWAY_UA_HR
            or pred_leakage_168h >= self.DATASHEET_LEAKAGE_MAX_UA
            or pred_iddq_168h >= self.DATASHEET_IDDQ_MAX_MA
            or pred_delay_168h >= self.DATASHEET_DELAY_MAX_NS
        ):
            risk_category = "CRITICAL_RUNAWAY"
            recommended_action = "QUARANTINE_FLIGHT_HARDWARE"
        elif max_0h_z >= self.OUTLIER_MAD_THRESHOLD or module_a_score >= self.MODULE_A_REJECT_THRESHOLD:
            risk_category = "LATENT_LOT_OUTLIER"
            if verdict == "REJECT" or max_0h_z >= 5.0:
                recommended_action = "QUARANTINE_FLIGHT_HARDWARE"
            else:
                recommended_action = "HOLD_FOR_96H_CHECK"
        elif (
            module_a_mahalanobis >= self.MAHALANOBIS_SUBTLE_THRESHOLD
            or module_a_flag
            or multi_param_elevated
            or verdict == "REVIEW"
            or drift_slope >= 0.10
        ):
            risk_category = "SUBTLE_DEGRADATION"
            recommended_action = "HOLD_FOR_96H_CHECK"
        else:
            risk_category = "NOMINAL"
            recommended_action = "PASS_FLIGHT_READY"

        # Generate Executive Summary
        executive_summary = self._generate_executive_summary(
            serial=serial,
            lot_number=lot_num,
            risk_category=risk_category,
            primary_param=primary_param,
            drift_slope=drift_slope,
            pred_leakage_168h=pred_leakage_168h,
            max_0h_z=max_0h_z,
            module_a_mahalanobis=module_a_mahalanobis,
            verdict=verdict,
            recommended_action=recommended_action,
            is_breached=is_breached,
        )

        # Generate Technical Markdown Justification
        technical_justification = self._generate_technical_justification(
            serial=serial,
            lot_number=lot_num,
            wafer_id=wafer_id,
            risk_category=risk_category,
            primary_param=primary_param,
            param_metrics=param_metrics,
            drift_slope=drift_slope,
            pred_leakage_168h=pred_leakage_168h,
            pred_iddq_168h=pred_iddq_168h,
            pred_delay_168h=pred_delay_168h,
            module_a_score=module_a_score,
            module_a_mahalanobis=module_a_mahalanobis,
            module_a_flag=module_a_flag,
            module_b_flag=module_b_flag,
            verdict=verdict,
            verdict_reason=verdict_reason,
            recommended_action=recommended_action,
            is_breached=is_breached,
        )

        return {
            "component_id": component_data.get("id"),
            "serial_number": serial,
            "lot_number": lot_num,
            "wafer_id": wafer_id,
            "risk_category": risk_category,
            "primary_parameter": primary_param,
            "recommended_action": recommended_action,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "executive_summary": executive_summary,
            "technical_justification": technical_justification,
            "parameter_metrics": param_metrics,
            "drift_metrics": {
                "drift_slope_ua_per_hr": round(drift_slope, 4),
                "pred_leakage_168h": round(pred_leakage_168h, 3),
                "pred_iddq_168h": round(pred_iddq_168h, 3),
                "pred_delay_168h": round(pred_delay_168h, 3),
                "module_b_flag": module_b_flag,
            },
            "lot_comparison": {
                "module_a_score": round(module_a_score, 4),
                "module_a_mahalanobis": round(module_a_mahalanobis, 4),
                "module_a_flag": module_a_flag,
                "initial_0h_max_z_mad": round(max_0h_z, 3),
            },
        }

    def _generate_executive_summary(
        self,
        serial: str,
        lot_number: str,
        risk_category: str,
        primary_param: str,
        drift_slope: float,
        pred_leakage_168h: float,
        max_0h_z: float,
        module_a_mahalanobis: float,
        verdict: str,
        recommended_action: str,
        is_breached: bool,
    ) -> str:
        """Constructs a plain-language aerospace inspection summary."""
        param_label = {
            "leakage_current_ua": "leakage current",
            "iddq_ma": "IDDQ supply current",
            "propagation_delay_ns": "propagation delay",
        }.get(primary_param, primary_param)

        if risk_category == "CRITICAL_RUNAWAY":
            if is_breached:
                return (
                    f"Component {serial} (Lot {lot_number}) failed screening due to an absolute datasheet limit breach. "
                    f"Physical readings breached mission safety ceilings. "
                    f"Classified as CRITICAL_RUNAWAY. Triage status: {verdict}. Disposition: {recommended_action}."
                )
            return (
                f"Component {serial} (Lot {lot_number}) exhibits severe {param_label} drift rate of "
                f"{drift_slope:.4f} uA/hr, projected to reach {pred_leakage_168h:.2f} uA at 168h "
                f"(exceeding the 50.0 uA mission ceiling). "
                f"Classified as CRITICAL_RUNAWAY. Recommended action: {recommended_action}."
            )
        elif risk_category == "LATENT_LOT_OUTLIER":
            return (
                f"Component {serial} (Lot {lot_number}) displays a significant initial baseline anomaly at t=0h "
                f"({max_0h_z:.1f} MAD units above lot median in {param_label}). "
                f"Classified as LATENT_LOT_OUTLIER. Identified as a spatial lot outlier. Triage status: {verdict}. "
                f"Recommended action: {recommended_action}."
            )
        elif risk_category == "SUBTLE_DEGRADATION":
            return (
                f"Component {serial} (Lot {lot_number}) presents subtle multivariate parametric shifts "
                f"(Mahalanobis distance D_M={module_a_mahalanobis:.2f}) despite remaining within single-parameter margins. "
                f"Classified as SUBTLE_DEGRADATION. Triage status: {verdict}. Recommended action: {recommended_action}."
            )
        else:
            return (
                f"Component {serial} (Lot {lot_number}) exhibits nominal parametric performance across all burn-in intervals. "
                f"Drift kinetics remain stable (slope: {drift_slope:.4f} uA/hr) within lot baseline bounds. "
                f"Classified as NOMINAL. Triage status: {verdict}. Recommended action: {recommended_action}."
            )

    def _generate_technical_justification(
        self,
        serial: str,
        lot_number: str,
        wafer_id: str,
        risk_category: str,
        primary_param: str,
        param_metrics: Dict[str, Any],
        drift_slope: float,
        pred_leakage_168h: float,
        pred_iddq_168h: float,
        pred_delay_168h: float,
        module_a_score: float,
        module_a_mahalanobis: float,
        module_a_flag: bool,
        module_b_flag: bool,
        verdict: str,
        verdict_reason: str,
        recommended_action: str,
        is_breached: bool,
    ) -> str:
        """Constructs an exhaustive technical Markdown audit report."""
        lines: List[str] = [
            f"# Engineering Screening Justification: {serial}",
            f"**Lot Number:** `{lot_number}` | **Wafer ID:** `{wafer_id}` | **Risk Category:** `{risk_category}`",
            f"**Triage Verdict:** `{verdict}` | **Recommended Disposition:** `{recommended_action}`",
            "",
            "## 1. Parametric Measurements & Lot Statistics (MAD Analysis)",
            "Values benchmarked against robust lot location (Median) and scale (MAD):",
            "",
            "| Parameter | Interval | Component Value | Lot Median | Lot MAD | Excursion (Z_MAD) | Absolute Ceiling | Status |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]

        for param, meta in param_metrics.items():
            label = meta["label"]
            ceiling = meta["ceiling"]
            for interval in self.INTERVALS:
                if interval in meta["intervals"]:
                    idata = meta["intervals"][interval]
                    val = idata["value"]
                    med = idata["lot_median"] if idata["lot_median"] is not None else "N/A"
                    mad = idata["lot_mad"] if idata["lot_mad"] is not None else "N/A"
                    z = idata["z_mad"]
                    
                    if val >= ceiling:
                        status = "**BREACH**"
                    elif abs(z) >= 4.0:
                        status = "OUTLIER"
                    elif abs(z) >= 2.5:
                        status = "ELEVATED"
                    else:
                        status = "NOMINAL"

                    lines.append(
                        f"| {label} | {interval}h | {val} | {med} | {mad} | {z:+.2f} MAD | {ceiling} | {status} |"
                    )

        lines.extend([
            "",
            "## 2. Early Drift & Degradation Kinetics (Module B)",
            f"- **Implied Drift Velocity:** `{drift_slope:.4f} uA/hr` (Runaway limit: `{self.DRIFT_SLOPE_RUNAWAY_UA_HR:.2f} uA/hr`)",
            f"- **Projected 168h Leakage:** `{pred_leakage_168h:.2f} uA` (Ceiling: `50.0 uA`)",
            f"- **Projected 168h IDDQ:** `{pred_iddq_168h:.2f} mA` (Ceiling: `5.0 mA`)",
            f"- **Projected 168h Delay:** `{pred_delay_168h:.2f} ns` (Ceiling: `8.0 ns`)",
            f"- **Module B Drift Flag:** `{'ACTIVE (HIGH RISK)' if module_b_flag else 'INACTIVE'}`",
            "",
            "## 3. Spatial Lot Covariance & Outlier Decomposition (Module A)",
            f"- **Composite Module A Score:** `{module_a_score:.4f}` (Reject threshold: `{self.MODULE_A_REJECT_THRESHOLD:.2f}`)",
            f"- **Ledoit-Wolf Mahalanobis Distance (D_M):** `{module_a_mahalanobis:.4f}` (Threshold: `{self.MAHALANOBIS_SUBTLE_THRESHOLD:.2f}`)",
            f"- **Module A Spatial Flag:** `{'ACTIVE (LOT OUTLIER)' if module_a_flag else 'INACTIVE'}`",
            f"- **Primary Driving Parameter:** `{primary_param}`",
            "",
            "## 4. Deterministic Decision Rule Trace",
            f"- **Rule Triggered:** `{verdict_reason}`",
            f"- **Hardware Datasheet Breached:** `{'YES' if is_breached else 'NO'}`",
            f"- **Safety Assessment:** `{recommended_action}` approved for QA flight review.",
        ])

        return "\n".join(lines)
