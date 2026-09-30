"""
Integration and schema tests for SQLAlchemy 2.0 ORM models.
Validates UUID primary keys, foreign keys, cascade deletes,
composite unique constraints, and async sessions.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.database import AsyncSessionLocal, SessionLocal
from backend.app.models import (
    BurnInReading,
    Component,
    GroundTruthLabel,
    Lot,
    LotStatus,
)


def test_lot_lifecycle_and_enum() -> None:
    """Verifies Lot creation, UUID generation, and status enum."""
    with SessionLocal() as session:
        test_lot_num = f"LOT-TEST-{uuid.uuid4().hex[:6]}"
        lot = Lot(
            lot_number=test_lot_num,
            wafer_id="WAF-TEST-01A",
            status=LotStatus.INGESTED,
        )
        session.add(lot)
        session.commit()
        session.refresh(lot)

        assert lot.id is not None
        assert isinstance(lot.id, uuid.UUID)
        assert lot.status == LotStatus.INGESTED
        assert lot.created_at is not None

        # Clean up
        session.delete(lot)
        session.commit()


def test_component_and_readings_relationship() -> None:
    """Verifies foreign key relationships, bidirectional mapping, and reading acquisition."""
    with SessionLocal() as session:
        lot = Lot(lot_number=f"LOT-REL-{uuid.uuid4().hex[:6]}", status=LotStatus.SCREENED)
        session.add(lot)
        session.commit()
        session.refresh(lot)

        comp = Component(
            lot_id=lot.id,
            serial_number=f"{lot.lot_number}-SN0001",
            ground_truth_label=GroundTruthLabel.LEVEL_OUTLIER,
            ground_truth_flag=True,
            is_datasheet_breached=False,
        )
        session.add(comp)
        session.commit()
        session.refresh(comp)

        reading = BurnInReading(
            component_id=comp.id,
            interval_hours=24,
            leakage_current_ua=14.52,
            iddq_ma=1.55,
            propagation_delay_ns=4.31,
        )
        session.add(reading)
        session.commit()

        # Query back via relationships
        session.refresh(comp)
        session.refresh(lot)
        assert len(lot.components) == 1
        assert lot.components[0].serial_number == comp.serial_number
        assert len(comp.readings) == 1
        assert comp.readings[0].interval_hours == 24
        assert comp.readings[0].leakage_current_ua == 14.52

        # Clean up
        session.delete(lot)
        session.commit()


def test_cascade_delete_enforcement() -> None:
    """Verifies that deleting a Lot automatically cascades to its Components and BurnInReadings."""
    with SessionLocal() as session:
        lot = Lot(lot_number=f"LOT-CASCADE-{uuid.uuid4().hex[:6]}", status=LotStatus.INGESTED)
        session.add(lot)
        session.commit()
        session.refresh(lot)

        comp = Component(
            lot_id=lot.id,
            serial_number=f"{lot.lot_number}-SN9999",
            ground_truth_label=GroundTruthLabel.NORMAL,
            ground_truth_flag=False,
        )
        session.add(comp)
        session.commit()
        session.refresh(comp)

        reading = BurnInReading(
            component_id=comp.id,
            interval_hours=0,
            leakage_current_ua=11.5,
            iddq_ma=1.45,
            propagation_delay_ns=4.12,
        )
        session.add(reading)
        session.commit()

        comp_id = comp.id
        reading_id = reading.id

        # Delete parent Lot
        session.delete(lot)
        session.commit()

    # Query in a fresh session to verify database-level cascade
    with SessionLocal() as verify_session:
        deleted_comp = verify_session.get(Component, comp_id)
        assert deleted_comp is None

        deleted_reading = verify_session.get(BurnInReading, reading_id)
        assert deleted_reading is None


def test_unique_constraint_component_serial_per_lot() -> None:
    """Verifies that duplicate serial numbers within the same lot raise an IntegrityError."""
    with SessionLocal() as session:
        lot = Lot(lot_number=f"LOT-UQ-{uuid.uuid4().hex[:6]}", status=LotStatus.INGESTED)
        session.add(lot)
        session.commit()
        session.refresh(lot)

        comp1 = Component(lot_id=lot.id, serial_number="DUPLICATE-SN")
        session.add(comp1)
        session.commit()

        comp2 = Component(lot_id=lot.id, serial_number="DUPLICATE-SN")
        session.add(comp2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(lot)
        session.commit()


def test_unique_constraint_reading_interval_per_component() -> None:
    """Verifies that duplicate interval readings for the same component raise an IntegrityError."""
    with SessionLocal() as session:
        lot = Lot(lot_number=f"LOT-UQR-{uuid.uuid4().hex[:6]}", status=LotStatus.INGESTED)
        session.add(lot)
        session.commit()
        session.refresh(lot)

        comp = Component(lot_id=lot.id, serial_number="SN-SINGLE")
        session.add(comp)
        session.commit()
        session.refresh(comp)

        r1 = BurnInReading(
            component_id=comp.id,
            interval_hours=96,
            leakage_current_ua=12.0,
            iddq_ma=1.5,
            propagation_delay_ns=4.2,
        )
        session.add(r1)
        session.commit()

        r2 = BurnInReading(
            component_id=comp.id,
            interval_hours=96,  # Duplicate interval for same component
            leakage_current_ua=13.0,
            iddq_ma=1.6,
            propagation_delay_ns=4.3,
        )
        session.add(r2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(lot)
        session.commit()


@pytest.mark.asyncio
async def test_async_session_queries() -> None:
    """Verifies asyncpg asynchronous engine and session functionality."""
    async with AsyncSessionLocal() as async_session:
        result = await async_session.scalar(select(func.count()).select_from(Lot))
        assert result is not None
        assert isinstance(result, int)
