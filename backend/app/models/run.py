"""
ScreeningRun: provenance of a screening pipeline execution (thresholds, costs, held-out metrics).
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class ScreeningRun(Base):
    __tablename__ = "screening_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False, doc="How the persisted predictions were produced")
    cost_config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    final_thresholds: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, doc="Thresholds of the model fitted on all labelled lots (used for new/ingested lots)"
    )
    fold_thresholds: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, doc="Per-fold thresholds")
    held_out_metrics: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
