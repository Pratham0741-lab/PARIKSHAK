"""
Pydantic Schemas for Component listing, profile, and readings.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.review import ReviewItem


class ReadingItem(BaseModel):
    """Component measurement at a discrete test interval."""
    model_config = ConfigDict(from_attributes=True)

    interval_hours: int = Field(..., description="Burn-in test interval (0, 24, 96, 168)")
    leakage_current_ua: Optional[float] = Field(None, description="Measured leakage in uA (null if the parameter is absent)")
    iddq_ma: Optional[float] = Field(None, description="Measured IDDQ in mA (null if the parameter is absent)")
    propagation_delay_ns: Optional[float] = Field(None, description="Measured delay in ns (null if the parameter is absent)")
    imputed_fields: Optional[List[str]] = Field(None, description="Parameters imputed at ingest (display only)")
    recorded_at: datetime = Field(..., description="Timestamp of measurement acquisition")


class ModelPredictionItem(BaseModel):
    """Component screening model prediction and triage details."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    module_a_score: Optional[float] = Field(None, description="Module A lot-outlier decision score")
    module_a_mahalanobis: Optional[float] = Field(None, description="Mahalanobis distance")
    module_a_flag: bool = Field(..., description="True if flagged as spatial outlier")
    pred_leakage_168h: Optional[float] = Field(None, description="Forecasted 168h leakage in uA")
    pred_iddq_168h: Optional[float] = Field(None, description="Forecasted 168h IDDQ in mA")
    pred_delay_168h: Optional[float] = Field(None, description="Forecasted 168h delay in ns")
    drift_slope_ua_per_hr: Optional[float] = Field(None, description="Implied drift rate in uA/hr")
    module_b_flag: bool = Field(..., description="True if early drift alert triggered")
    module_b_score: Optional[float] = Field(None, description="Module B decision score (drift z vs lot safety slope)")
    threshold_a: Optional[float] = Field(None, description="Learned Module A threshold (null = module disabled)")
    threshold_b: Optional[float] = Field(None, description="Learned Module B threshold k (null = module disabled)")
    safety_slope_ua_per_hr: Optional[float] = Field(None, description="Calculated lot safety slope for leakage")
    details: Optional[Dict[str, Any]] = Field(None, description="Derivations, intervals and contributions")
    cv_fold: Optional[int] = Field(None, description="Out-of-fold provenance (lot fold that produced this prediction)")
    verdict: str = Field(..., description="Triage verdict: PASS, REVIEW, or REJECT")
    verdict_reason: str = Field(..., description="Rule justification")
    created_at: datetime


class ComponentListItem(BaseModel):
    """Brief component metadata for tabular search and queue rendering."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID
    lot_number: str
    serial_number: str
    ground_truth_label: Optional[str] = None
    ground_truth_flag: Optional[bool] = None
    is_datasheet_breached: bool
    verdict: Optional[str] = None
    module_a_score: Optional[float] = None
    pred_leakage_168h: Optional[float] = None
    drift_slope_ua_per_hr: Optional[float] = None


class PaginatedComponentsResponse(BaseModel):
    """Paginated collection of components with search filters."""
    total: int = Field(..., description="Total items matching filter")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total available pages")
    items: List[ComponentListItem] = Field(..., description="Components matching criteria")


class ComponentProfileResponse(BaseModel):
    """Comprehensive component inspection profile including time-series, bands, and predictions."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID
    lot_number: str
    wafer_id: Optional[str] = None
    serial_number: str
    ground_truth_label: Optional[str] = None
    ground_truth_flag: Optional[bool] = None
    is_datasheet_breached: bool
    insufficient_data: bool = False
    readings: List[ReadingItem] = Field(default_factory=list, description="Raw readings time series")
    prediction: Optional[ModelPredictionItem] = Field(None, description="Screening prediction record")
    reviews: List[ReviewItem] = Field(default_factory=list, description="Inspector audit history")
    lot_envelope: Optional[Dict[str, Any]] = Field(None, description="Lot median and MAD envelopes")
