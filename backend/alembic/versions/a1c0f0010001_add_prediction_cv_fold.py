"""add cv_fold to model_predictions (out-of-fold provenance)

Revision ID: a1c0f0010001
Revises: 10f51a62d3a8
Create Date: 2026-09-30 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c0f0010001"
down_revision: Union[str, Sequence[str], None] = "10f51a62d3a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_predictions", sa.Column("cv_fold", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_predictions", "cv_fold")
