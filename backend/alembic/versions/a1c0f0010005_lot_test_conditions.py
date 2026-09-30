"""lots: burn-in test conditions (temperature, parameter, unit, limit), assumed flags, provenance

Revision ID: a1c0f0010005
Revises: a1c0f0010004
Create Date: 2026-09-30 20:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c0f0010005"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lots", sa.Column("temperature_c", sa.Float(), nullable=True))
    op.add_column("lots", sa.Column("test_parameter", sa.String(32), nullable=True))
    op.add_column("lots", sa.Column("unit", sa.String(16), nullable=True))
    op.add_column("lots", sa.Column("static_limit", sa.Float(), nullable=True))
    op.add_column("lots", sa.Column("conditions_assumed", postgresql.JSONB(), nullable=True))
    op.add_column("lots", sa.Column("source_detail", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    for c in ("source_detail", "conditions_assumed", "static_limit", "unit", "test_parameter", "temperature_c"):
        op.drop_column("lots", c)
