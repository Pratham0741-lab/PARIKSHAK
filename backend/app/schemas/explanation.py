"""
Schemas for per-part explanations generated from the model's own outputs (ml_engine/explain.py).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ModuleAContribution(BaseModel):
    parameter: str
    robust_z: Optional[float] = Field(None, description="Part vs own-lot median, in lot-MAD units (mean of 0h/24h)")
    contribution: Optional[float] = Field(None, description="max(0, robust_z): additive share of the Module A score")
    value_0_24h_mean: Optional[float] = None
    lot_median: Optional[float] = None
    lot_mad: Optional[float] = None


class ModuleAExplanation(BaseModel):
    score: Optional[float]
    threshold: Optional[float] = Field(None, description="Learned threshold (null = module disabled)")
    flag: bool
    decision_statistic: Optional[str] = None
    contributions: List[ModuleAContribution]
    diagnostics: Optional[Dict[str, Any]] = None
    top_contributor: Optional[str] = None


class ModuleBParameter(BaseModel):
    parameter: str
    forecast_168h: Optional[float] = None
    interval_lower: Optional[float] = None
    interval_upper: Optional[float] = None
    predicted_rate: Optional[float] = None
    lot_median_rate: Optional[float] = None
    lot_spread: Optional[float] = None
    safety_slope: Optional[float] = None
    z: Optional[float] = None
    exceeds_safety_slope: Optional[bool] = None
    rate_unit: Optional[str] = None


class FeatureContribution(BaseModel):
    feature: str
    label: str
    value: float = Field(..., description="Signed TreeSHAP contribution in the model's target space")
    target_space: str
    effect_pct_on_forecast: Optional[float] = Field(None, description="Multiplicative effect on the 168h forecast (log-ratio target)")


class ModuleBExplanation(BaseModel):
    score: Optional[float]
    threshold_k: Optional[float] = None
    flag: bool
    driver_parameter: str
    per_parameter: List[ModuleBParameter]
    contributions: List[FeatureContribution]
    contribution_target_space: Optional[str] = None
    top_contributor: Optional[str] = None
    interval_coverage_target: Optional[float] = None


class StaticLimitStatus(BaseModel):
    limits: Dict[str, float]
    max_observed_0_24h: Dict[str, Optional[float]]
    observed_breach: Dict[str, bool]
    forecast_breach: Dict[str, bool]


class ExplanationResponse(BaseModel):
    component_id: uuid.UUID
    serial_number: str
    lot_number: str
    verdict: Optional[str]
    verdict_reason: Optional[str]
    summary: str = Field(..., description="Plain-language justification generated from this part's model outputs")
    module_a: ModuleAExplanation
    module_b: ModuleBExplanation
    static_limit: StaticLimitStatus
    cv_fold: Optional[int] = Field(None, description="Out-of-fold provenance of the prediction")
