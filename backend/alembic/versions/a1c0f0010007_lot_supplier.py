"""lots: optional supplier

Revision ID: a1c0f0010007
Revises: a1c0f0010006
Create Date: 2026-10-01 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c0f0010007"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lots", sa.Column("supplier", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("lots", "supplier")
