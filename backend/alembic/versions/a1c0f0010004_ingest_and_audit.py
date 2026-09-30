"""ingest support (nullable ground truth, imputed fields, insufficient data, lot source) and audit_events

Revision ID: a1c0f0010004
Revises: a1c0f0010003
Create Date: 2026-09-30 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1c0f0010004"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRED_FIELDS = ("module_a_score", "module_a_mahalanobis", "pred_leakage_168h", "pred_iddq_168h",
               "pred_delay_168h", "drift_slope_ua_per_hr")


def upgrade() -> None:
    op.alter_column("components", "ground_truth_label", nullable=True)
    op.alter_column("components", "ground_truth_flag", nullable=True)
    op.add_column("components", sa.Column("insufficient_data", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("burn_in_readings", sa.Column("imputed_fields", postgresql.JSONB(), nullable=True))
    op.add_column("lots", sa.Column("source", sa.String(32), nullable=False, server_default="SYNTHETIC"))
    for f in PRED_FIELDS:
        op.alter_column("model_predictions", f, nullable=True)
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lots.id", ondelete="CASCADE"), nullable=True),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("components.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_lot_id", "audit_events", ["lot_id"])
    op.create_index("ix_audit_events_component_id", "audit_events", ["component_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    for f in PRED_FIELDS:
        op.alter_column("model_predictions", f, nullable=False)
    op.drop_column("lots", "source")
    op.drop_column("burn_in_readings", "imputed_fields")
    op.drop_column("components", "insufficient_data")
    op.alter_column("components", "ground_truth_flag", nullable=False)
    op.alter_column("components", "ground_truth_label", nullable=False)
