"""Durable submission state and incremental trace journal.

Revision ID: 0003_run_jobs
Revises: 0002_completion_guard
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_run_jobs"
down_revision = "0002_completion_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_jobs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(80), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("failure_reason", sa.String()),
        sa.CheckConstraint(
            "status IN ('queued','running','verifying','completed','failed','timed_out',"
            "'verification_failed')",
            name="ck_job_status",
        ),
    )
    op.create_index("ix_run_jobs_status", "run_jobs", ["status"])
    op.create_table(
        "run_job_events",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("run_jobs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sequence_number", sa.Integer(), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("sequence_number > 0", name="ck_job_event_sequence"),
    )


def downgrade() -> None:
    op.drop_table("run_job_events")
    op.drop_table("run_jobs")
