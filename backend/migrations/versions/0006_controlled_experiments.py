"""add controlled experiment entities

Revision ID: 0006_controlled_experiments
Revises: 0005_benchmark_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_controlled_experiments"
down_revision: str | None = "0005_benchmark_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.String(64), primary_key=True),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("research_question", sa.String(), nullable=False),
        sa.Column("benchmark_name", sa.String(100), nullable=False),
        sa.Column("benchmark_version", sa.String(30), nullable=False),
        sa.Column("benchmark_manifest_hash", sa.String(64), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pause_reason", sa.String()),
        sa.CheckConstraint(
            "status IN ('planned','running','paused','completed')",
            name="ck_experiment_status",
        ),
    )
    op.create_index("ix_experiments_status", "experiments", ["status"])
    op.create_table(
        "experiment_configs",
        sa.Column(
            "experiment_id",
            sa.String(64),
            sa.ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("configuration_id", sa.String(64), primary_key=True),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_experiment_configs_strategy", "experiment_configs", ["strategy"])
    op.create_index("ix_experiment_configs_provider", "experiment_configs", ["provider"])
    op.create_table(
        "experiment_schedule",
        sa.Column(
            "experiment_id",
            sa.String(64),
            sa.ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scheduled_order", sa.Integer(), primary_key=True),
        sa.Column("configuration_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(80), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("valid_run_id", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "experiment_id",
            "configuration_id",
            "task_id",
            "repetition",
            name="uq_experiment_repetition",
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed')",
            name="ck_experiment_schedule_status",
        ),
        sa.CheckConstraint("repetition > 0", name="ck_experiment_repetition_positive"),
        sa.CheckConstraint("scheduled_order > 0", name="ck_experiment_order_positive"),
    )
    op.create_index("ix_experiment_schedule_task_id", "experiment_schedule", ["task_id"])
    op.create_index("ix_experiment_schedule_status", "experiment_schedule", ["status"])
    op.create_table(
        "experiment_runs",
        sa.Column("attempt_id", sa.String(100), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(64),
            sa.ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_order", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False, unique=True),
        sa.Column("validity", sa.String(30), nullable=False),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("replacement_for_run_id", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_reason", sa.String()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "experiment_id", "scheduled_order", "attempt_number", name="uq_experiment_attempt"
        ),
        sa.CheckConstraint(
            "validity IN ('valid','infrastructure_failure')",
            name="ck_experiment_run_validity",
        ),
        sa.CheckConstraint(
            "classification IN ('benchmark_success','benchmark_failure','infrastructure_failure')",
            name="ck_experiment_run_classification",
        ),
    )
    op.create_index("ix_experiment_runs_experiment_id", "experiment_runs", ["experiment_id"])
    op.create_index("ix_experiment_runs_validity", "experiment_runs", ["validity"])


def downgrade() -> None:
    op.drop_table("experiment_runs")
    op.drop_table("experiment_schedule")
    op.drop_table("experiment_configs")
    op.drop_table("experiments")
