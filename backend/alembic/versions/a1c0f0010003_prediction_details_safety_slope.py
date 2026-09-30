"""model_predictions: safety_slope_ua_per_hr and details JSONB (derivations, intervals, contributions)

Revision ID: a1c0f0010003
Revises: a1c0f0010002
Create Date: 2026-09-30 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1c0f0010003"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_predictions", sa.Column("safety_slope_ua_per_hr", sa.Float(), nullable=True))
    op.add_column("model_predictions", sa.Column("details", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_predictions", "details")
    op.drop_column("model_predictions", "safety_slope_ua_per_hr")
