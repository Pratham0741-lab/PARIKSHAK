"""
Pydantic Schemas for Lot and Statistical Distribution endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LotSummary(BaseModel):
    """Aggregated Lot summary statistics with triage counts."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique Lot identifier")
    lot_number: str = Field(..., description="Manufacturing lot number")
    wafer_id: Optional[str] = Field(None, description="Source semiconductor wafer identifier")
    status: str = Field(..., description="Current processing lifecycle status")
    source: str = Field("SYNTHETIC", description="SYNTHETIC (labelled generator data) or CSV_INGEST")
    total_components: int = Field(..., description="Total component count in lot")
    pass_count: int = Field(0, description="Components triaged as PASS")
    review_count: int = Field(0, description="Components triaged as REVIEW")
    reject_count: int = Field(0, description="Components triaged as REJECT")
    created_at: datetime = Field(..., description="Lot initialization timestamp")


class IntervalStats(BaseModel):
    """Statistical summary of a parameter at a specific burn-in interval."""
    interval_hours: int = Field(..., description="Burn-in test interval in hours (0, 24, 96, 168)")
    min: float = Field(..., description="Minimum reading value")
    p25: float = Field(..., description="25th percentile (Q1)")
    median: float = Field(..., description="Median (Q2)")
    p75: float = Field(..., description="75th percentile (Q3)")
    max: float = Field(..., description="Maximum reading value")
    mad: float = Field(..., description="Median Absolute Deviation")


class ParameterDistribution(BaseModel):
    """Distribution envelope for a specific parameter across all burn-in intervals."""
    parameter: str = Field(..., description="Internal parameter identifier")
    label: str = Field(..., description="Human-readable label with units")
    unit: str = Field(..., description="Measurement unit (uA, mA, ns)")
    datasheet_max: float = Field(..., description="Absolute maximum allowable datasheet limit")
    intervals: List[IntervalStats] = Field(..., description="Statistical values at each interval")


class LotDistributionResponse(BaseModel):
    """Full lot-level distribution envelope for box-plot and band rendering."""
    lot_id: uuid.UUID = Field(..., description="Unique Lot identifier")
    lot_number: str = Field(..., description="Manufacturing lot number")
    wafer_id: Optional[str] = Field(None, description="Source wafer ID")
    parameters: List[ParameterDistribution] = Field(..., description="Distributions per parameter")
