"""Queryable role executions and bounded strategy outcomes.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003_run_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sub_executions",
        sa.Column("execution_id", sa.String(100), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_execution_id", sa.String(100), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100)),
        sa.Column("candidate_id", sa.String(10)),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_execution_duration"),
    )
    for column in ("run_id", "role", "provider"):
        op.create_index(f"ix_sub_executions_{column}", "sub_executions", [column])
    op.create_table(
        "strategy_results",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("selected_candidate", sa.String(10)),
        sa.Column("reviewer_decision", sa.String(20)),
        sa.Column("corrections", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("peak_concurrent_agents", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("corrections BETWEEN 0 AND 1", name="ck_one_correction"),
    )


def downgrade() -> None:
    op.drop_table("strategy_results")
    op.drop_table("sub_executions")
