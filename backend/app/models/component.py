"""
Component ORM Model for individual semiconductor units.
"""

import enum
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.lot import Lot
    from backend.app.models.prediction import ModelPrediction
    from backend.app.models.reading import BurnInReading
    from backend.app.models.review import InspectorReview


class GroundTruthLabel(str, enum.Enum):
    """
    Ground truth classification labels for burn-in testing emulation.
    """
    NORMAL = "NORMAL"
    LEVEL_OUTLIER = "LEVEL_OUTLIER"
    STEEP_DRIFT = "STEEP_DRIFT"
    LATE_DRIFT = "LATE_DRIFT"
    SUBTLE_MULTIVARIATE = "SUBTLE_MULTIVARIATE"


class Component(Base):
    """
    Represents an individual physical semiconductor component tracked through burn-in.
    """
    __tablename__ = "components"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the component (UUIDv4)",
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key pointing to the parent manufacturing Lot",
    )
    serial_number: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Part serial number (e.g. SN-00101)",
    )
    ground_truth_label: Mapped[Optional[GroundTruthLabel]] = mapped_column(
        SAEnum(GroundTruthLabel, name="ground_truth_label_enum", native_enum=True),
        nullable=True,
        index=True,
        doc="Ground-truth classification of physical defect or normality",
    )
    ground_truth_flag: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        index=True,
        doc="Boolean anomaly indicator (True if defective/outlier, False if normal)",
    )
    is_datasheet_breached: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Flag indicating if any parameter violated absolute datasheet specification limits",
    )

    insufficient_data: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="True if a 0h or 24h reading was missing/invalid at ingest (no Module A/B score)",
    )

    # Relationships
    lot: Mapped["Lot"] = relationship(
        "Lot",
        back_populates="components",
    )
    readings: Mapped[List["BurnInReading"]] = relationship(
        "BurnInReading",
        back_populates="component",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BurnInReading.interval_hours",
        doc="Time-series burn-in screening readings for this component",
    )
    prediction: Mapped[Optional["ModelPrediction"]] = relationship(
        "ModelPrediction",
        back_populates="component",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        doc="Unified screening model prediction and verdict",
    )
    reviews: Mapped[List["InspectorReview"]] = relationship(
        "InspectorReview",
        back_populates="component",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InspectorReview.reviewed_at.desc()",
        doc="QA inspector audit review history for this component",
    )

    __table_args__ = (
        UniqueConstraint("lot_id", "serial_number", name="uq_component_lot_serial"),
        Index("ix_components_lot_id_flag", "lot_id", "ground_truth_flag"),
    )

    def __repr__(self) -> str:
        return (
            f"<Component(id={self.id}, serial='{self.serial_number}', "
            f"label='{self.ground_truth_label}', breached={self.is_datasheet_breached})>"
        )
