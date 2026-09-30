"""screening_runs table; per-prediction module_b_score and thresholds

Revision ID: a1c0f0010002
Revises: a1c0f0010001
Create Date: 2026-09-30 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1c0f0010002"
down_revision: Union[str, Sequence[str], None] = "a1c0f0010001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screening_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("cost_config", postgresql.JSONB(), nullable=False),
        sa.Column("final_thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("fold_thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("held_out_metrics", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_path", sa.String(512), nullable=True),
    )
    op.add_column("model_predictions", sa.Column("module_b_score", sa.Float(), nullable=True))
    op.add_column("model_predictions", sa.Column("threshold_a", sa.Float(), nullable=True))
    op.add_column("model_predictions", sa.Column("threshold_b", sa.Float(), nullable=True))
    op.add_column("model_predictions", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_model_predictions_run_id", "model_predictions", ["run_id"])
    op.create_foreign_key(
        "fk_model_predictions_run_id", "model_predictions", "screening_runs", ["run_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_model_predictions_run_id", "model_predictions", type_="foreignkey")
    op.drop_index("ix_model_predictions_run_id", table_name="model_predictions")
    for c in ("run_id", "threshold_b", "threshold_a", "module_b_score"):
        op.drop_column("model_predictions", c)
    op.drop_table("screening_runs")
