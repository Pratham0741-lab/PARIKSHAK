"""
Lot ORM Model for semiconductor manufacturing batches.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Enum as SAEnum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.component import Component


class LotStatus(str, enum.Enum):
    """Lifecycle status of a manufacturing lot in the screening pipeline."""
    INGESTED = "INGESTED"
    SCREENED = "SCREENED"
    REVIEW_PENDING = "REVIEW_PENDING"


class Lot(Base):
    """
    Represents a manufacturing batch/lot of semiconductor components undergoing burn-in screening.
    """
    __tablename__ = "lots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the lot (UUIDv4)",
    )
    lot_number: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique lot tracking number (e.g. LOT-2026-X89)",
    )
    wafer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Originating silicon wafer identifier (e.g. WAF-420-B)",
    )
    status: Mapped[LotStatus] = mapped_column(
        SAEnum(LotStatus, name="lot_status_enum", native_enum=True),
        nullable=False,
        default=LotStatus.INGESTED,
        index=True,
        doc="Current burn-in screening lifecycle status",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the lot was ingested into the system",
    )

    # Relationship to components with cascade delete
    components: Mapped[List["Component"]] = relationship(
        "Component",
        back_populates="lot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        doc="Components belonging to this lot",
    )

    def __repr__(self) -> str:
        return f"<Lot(id={self.id}, lot_number='{self.lot_number}', status='{self.status}')>"
