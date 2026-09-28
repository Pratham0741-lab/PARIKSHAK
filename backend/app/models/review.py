"""
InspectorReview ORM Model for QA Review Audit Trail.
Tracks human inspector overrides, dispositions, and rationale with immutable timestamps.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base
from backend.app.models.prediction import ScreeningVerdict

if TYPE_CHECKING:
    from backend.app.models.component import Component


class ReviewDisposition(str, enum.Enum):
    """Inspector QA disposition decisions."""
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    RE_TEST = "RE_TEST"


class InspectorReview(Base):
    """
    Immutable audit trail record documenting a QA inspector's human review,
    manual verdict override or affirmation, and engineering justification.
    """
    __tablename__ = "inspector_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the review entry (UUIDv4)",
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key pointing to the reviewed Component",
    )
    inspector_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Operator badge or engineer identifier (e.g. ENG-ISRO-412)",
    )
    original_verdict: Mapped[ScreeningVerdict] = mapped_column(
        SAEnum(ScreeningVerdict, name="screening_verdict_enum", create_type=False),
        nullable=False,
        doc="Model-generated verdict at the time of human review",
    )
    disposition: Mapped[ReviewDisposition] = mapped_column(
        SAEnum(ReviewDisposition, name="review_disposition_enum", native_enum=True),
        nullable=False,
        index=True,
        doc="Final human inspector disposition: ACCEPTED, QUARANTINED, or RE_TEST",
    )
    inspector_notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Mandatory QA engineering justification and disposition rationale",
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Immutable timestamp of inspector review submission",
    )

    # Relationship
    component: Mapped["Component"] = relationship(
        "Component",
        back_populates="reviews",
    )

    __table_args__ = (
        Index("ix_reviews_component_date", "component_id", "reviewed_at"),
        Index("ix_reviews_inspector_disposition", "inspector_id", "disposition"),
    )

    def __repr__(self) -> str:
        return (
            f"<InspectorReview(id={self.id}, component_id={self.component_id}, "
            f"inspector='{self.inspector_id}', disposition='{self.disposition}')>"
        )
