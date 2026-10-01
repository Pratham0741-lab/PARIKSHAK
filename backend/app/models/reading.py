"""
Burn-In Screening Reading ORM Model for parametric measurements across test intervals.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.component import Component


class BurnInReading(Base):
    """
    Represents parametric electronic measurements taken for a component
    at a specific burn-in screening interval (0h, 24h, 96h, 168h).
    """
    __tablename__ = "burn_in_readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the reading (UUIDv4)",
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key reference to the parent Component",
    )
    interval_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Burn-in test interval milestone in hours (typically 0, 24, 96, 168)",
    )
    leakage_current_ua: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Subthreshold / gate leakage current measured in microamperes (uA)",
    )
    iddq_ma: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Quiescent supply current measured in milliamperes (mA)",
    )
    propagation_delay_ns: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Critical path propagation delay measured in nanoseconds (ns)",
    )
    imputed_fields: Mapped[Optional[List[str]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Parameters whose value was missing/invalid at ingest and imputed with the lot median",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when reading was acquired from ATE test harness",
    )

    # Relationships
    component: Mapped["Component"] = relationship(
        "Component",
        back_populates="readings",
    )

    __table_args__ = (
        UniqueConstraint(
            "component_id",
            "interval_hours",
            name="uq_reading_component_interval",
        ),
        Index(
            "ix_readings_component_interval",
            "component_id",
            "interval_hours",
        ),
        CheckConstraint(
            "interval_hours >= 0",
            name="chk_interval_hours_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BurnInReading(component_id={self.component_id}, t={self.interval_hours}h, "
            f"leakage={self.leakage_current_ua:.2f}uA, iddq={self.iddq_ma:.3f}mA, "
            f"delay={self.propagation_delay_ns:.3f}ns)>"
        )
