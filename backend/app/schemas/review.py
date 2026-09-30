"""
Pydantic Schemas for QA Inspector Review Audit Trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.review import ReviewDisposition


class ReviewActionRequest(BaseModel):
    """Payload submitted by a QA inspector to override or affirm component disposition."""
    inspector_id: str = Field(..., min_length=2, max_length=64, description="Operator badge or engineer ID")
    disposition: ReviewDisposition = Field(..., description="Action taken: ACCEPTED, QUARANTINED, or RE_TEST")
    inspector_notes: str = Field(..., min_length=5, description="Engineering rationale justifying the disposition")


class ReviewItem(BaseModel):
    """Audit review item representation."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    component_id: uuid.UUID
    inspector_id: str
    original_verdict: str
    disposition: str
    inspector_notes: str
    reviewed_at: datetime


class ReviewActionResponse(BaseModel):
    """Response returned upon successfully recording an inspector audit action."""
    review_id: uuid.UUID = Field(..., description="Unique review audit record UUID")
    component_id: uuid.UUID = Field(..., description="Component UUID")
    inspector_id: str = Field(..., description="Reviewing inspector ID")
    original_verdict: str = Field(..., description="Verdict prior to review")
    disposition: str = Field(..., description="Inspector disposition recorded")
    inspector_notes: str = Field(..., description="Inspector justification")
    reviewed_at: datetime = Field(..., description="Review submission timestamp")
    status: str = Field("SUCCESS", description="Operation status")
