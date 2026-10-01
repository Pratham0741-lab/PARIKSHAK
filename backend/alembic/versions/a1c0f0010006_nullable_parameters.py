"""burn_in_readings: parameter columns nullable (single-parameter ingest)

Revision ID: a1c0f0010006
Revises: a1c0f0010005
Create Date: 2026-10-01 16:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1c0f0010006"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")


def upgrade() -> None:
    for c in COLUMNS:
        op.alter_column("burn_in_readings", c, nullable=True)


def downgrade() -> None:
    for c in COLUMNS:
        op.alter_column("burn_in_readings", c, nullable=False)
