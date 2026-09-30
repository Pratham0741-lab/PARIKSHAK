"""
ModelPrediction ORM Model for Phase 2 Analytical & Screening Outputs.
Stores Module A outlier metrics, Module B 168h drift predictions, and final Verdict triage.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.component import Component


class ScreeningVerdict(str, enum.Enum):
    """Unified triage decision for component disposition."""
    PASS = "PASS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class ModelPrediction(Base):
    """
    Represents the unified screening inference record for a component,
    combining spatial lot-level outlier detection (Module A),
    temporal 168h degradation forecasting (Module B), and rule-based disposition.
    """
    __tablename__ = "model_predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the prediction record (UUIDv4)",
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key pointing to the evaluated Component",
    )

    # Module A: Spatial Lot-Adaptive Outlier Metrics
    module_a_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Composite normalized lot outlier score [0.0, 1.0]",
    )
    module_a_mahalanobis: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Robust covariance-shrunk Mahalanobis distance in parametric feature space",
    )
    module_a_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="True if flagged as a spatial lot outlier by Module A",
    )

    # Module B: Early 168h Drift Forecasts (from 0h/24h readings)
    pred_leakage_168h: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="LightGBM predicted leakage current at 168h in microamperes (uA)",
    )
    pred_iddq_168h: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="LightGBM predicted IDDQ supply current at 168h in milliamperes (mA)",
    )
    pred_delay_168h: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="LightGBM predicted propagation delay at 168h in nanoseconds (ns)",
    )
    drift_slope_ua_per_hr: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Forecasted leakage drift rate in microamperes per hour (uA/hr)",
    )
    module_b_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="True if forecasted to violate safety ceiling or excessive drift rate",
    )

    cv_fold: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Lot-level cross-validation fold whose model produced this out-of-fold prediction",
    )

    # Unified Verdict Layer
    verdict: Mapped[ScreeningVerdict] = mapped_column(
        SAEnum(ScreeningVerdict, name="screening_verdict_enum", native_enum=True),
        nullable=False,
        index=True,
        doc="Final component disposition verdict: PASS, REVIEW, or REJECT",
    )
    verdict_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Deterministic justification and rule trace for the verdict",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp of prediction pipeline execution",
    )

    # Relationships
    component: Mapped["Component"] = relationship(
        "Component",
        back_populates="prediction",
    )

    __table_args__ = (
        UniqueConstraint("component_id", name="uq_prediction_component"),
        Index("ix_predictions_verdict_module_a", "verdict", "module_a_flag"),
        Index("ix_predictions_verdict_module_b", "verdict", "module_b_flag"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelPrediction(component_id={self.component_id}, "
            f"verdict='{self.verdict}', score_a={self.module_a_score:.3f}, "
            f"pred_leak={self.pred_leakage_168h:.2f}uA)>"
        )
