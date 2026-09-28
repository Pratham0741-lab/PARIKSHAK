"""
Pydantic Schemas for Local Explainability Engine outputs.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class DriftMetrics(BaseModel):
    """Drift and 168h forecast metrics."""
    drift_slope_ua_per_hr: float = Field(..., description="Estimated or projected leakage drift rate")
    pred_leakage_168h: float = Field(..., description="Forecasted 168h leakage in uA")
    pred_iddq_168h: float = Field(..., description="Forecasted 168h IDDQ in mA")
    pred_delay_168h: float = Field(..., description="Forecasted 168h delay in ns")
    module_b_flag: bool = Field(..., description="True if early drift alert triggered")


class LotComparison(BaseModel):
    """Lot-relative comparison scores."""
    module_a_score: float = Field(..., description="Composite lot anomaly score [0, 1]")
    module_a_mahalanobis: float = Field(..., description="Mahalanobis distance from lot center")
    module_a_flag: bool = Field(..., description="True if flagged as spatial outlier")
    initial_0h_max_z_mad: float = Field(..., description="Peak MAD excursion at t=0h")


class ExplanationResponse(BaseModel):
    """Complete structured output from the Local Deterministic Explainability Engine."""
    component_id: uuid.UUID = Field(..., description="Component UUID")
    serial_number: str = Field(..., description="Serial number")
    lot_number: str = Field(..., description="Parent lot number")
    wafer_id: str = Field(..., description="Wafer ID")
    risk_category: str = Field(
        ...,
        description="Assigned risk: CRITICAL_RUNAWAY, LATENT_LOT_OUTLIER, SUBTLE_DEGRADATION, or NOMINAL",
    )
    primary_parameter: str = Field(..., description="Key parameter driving anomaly or excursion")
    recommended_action: str = Field(
        ...,
        description="Recommended action: QUARANTINE_FLIGHT_HARDWARE, HOLD_FOR_96H_CHECK, or PASS_FLIGHT_READY",
    )
    verdict: str = Field(..., description="Screening verdict: PASS, REVIEW, or REJECT")
    verdict_reason: str = Field(..., description="Deterministic rule trace")
    executive_summary: str = Field(..., description="High-level engineering summary")
    technical_justification: str = Field(..., description="Detailed Markdown audit report")
    parameter_metrics: Dict[str, Any] = Field(..., description="Per-parameter interval stats and Z_MAD")
    drift_metrics: DriftMetrics = Field(..., description="Forecasted degradation trajectory")
    lot_comparison: LotComparison = Field(..., description="Spatial lot covariance metrics")
