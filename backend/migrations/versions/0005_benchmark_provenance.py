"""add queryable benchmark provenance

Revision ID: 0005_benchmark_provenance
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_benchmark_provenance"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "task_source", sa.String(length=30), nullable=False, server_default="agentscope"
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "task_dataset",
            sa.String(length=160),
            nullable=False,
            server_default="AgentScope Benchmark",
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "dataset_version", sa.String(length=100), nullable=False, server_default="0.1"
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "task_hash", sa.String(length=64), nullable=False, server_default="unknown"
        ),
    )
    op.create_index("ix_runs_task_source", "runs", ["task_source"])
    op.create_index("ix_runs_task_dataset", "runs", ["task_dataset"])
    op.create_index("ix_runs_task_hash", "runs", ["task_hash"])
    op.alter_column("runs", "task_source", server_default=None)
    op.alter_column("runs", "task_dataset", server_default=None)
    op.alter_column("runs", "dataset_version", server_default=None)
    op.alter_column("runs", "task_hash", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_runs_task_hash", table_name="runs")
    op.drop_index("ix_runs_task_dataset", table_name="runs")
    op.drop_index("ix_runs_task_source", table_name="runs")
    op.drop_column("runs", "task_hash")
    op.drop_column("runs", "dataset_version")
    op.drop_column("runs", "task_dataset")
    op.drop_column("runs", "task_source")
