"""Initial finalized runs, ordered traces, verification, metrics and artifacts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_verified_runs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(80), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_reason", sa.String),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed','failed','timed_out','verification_failed')",
            name="ck_run_terminal_status",
        ),
        sa.CheckConstraint("finished_at >= started_at", name="ck_run_time_order"),
    )
    op.create_index("ix_runs_task_id", "runs", ["task_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_table(
        "trace_events",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sequence_number", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.String(100), nullable=False, unique=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.CheckConstraint("sequence_number > 0", name="ck_event_positive_sequence"),
    )
    op.create_index("ix_trace_events_event_type", "trace_events", ["event_type"])
    op.create_table(
        "verifications",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("exit_code", sa.Integer),
        sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column("passed_tests", sa.Integer),
        sa.Column("failed_tests", sa.Integer),
        sa.Column("total_tests", sa.Integer),
        sa.Column("timed_out", sa.Boolean, nullable=False),
        sa.Column("failure_reason", sa.String),
        sa.Column("payload", JSONB, nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_verification_duration"),
    )
    op.create_table(
        "run_metrics",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("total_wall_time_ms", sa.Float, nullable=False),
        sa.Column("agent_execution_time_ms", sa.Float, nullable=False),
        sa.Column("verification_time_ms", sa.Float, nullable=False),
        sa.Column("tool_calls", sa.Integer, nullable=False),
        sa.Column("per_tool", JSONB, nullable=False),
        sa.Column("inference", JSONB, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.CheckConstraint("tool_calls >= 0", name="ck_metrics_tool_calls"),
    )
    op.create_table(
        "artifacts",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("artifact_type", sa.String(30), primary_key=True),
        sa.Column("path", sa.String, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("run_id", "path", name="uq_artifact_path"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifact_size"),
    )


def downgrade():
    for table in ("artifacts", "run_metrics", "verifications", "trace_events", "runs"):
        op.drop_table(table)
