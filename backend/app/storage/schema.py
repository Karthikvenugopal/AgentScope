"""SQLAlchemy 2 schema: queryable run columns plus typed JSONB domain payloads."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
runs = Table(
    "runs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("task_id", String(80), nullable=False, index=True),
    Column("task_source", String(30), nullable=False, index=True),
    Column("task_dataset", String(160), nullable=False, index=True),
    Column("dataset_version", String(100), nullable=False),
    Column("task_hash", String(64), nullable=False, index=True),
    Column("agent_name", String(100), nullable=False),
    Column("strategy", String(50), nullable=False),
    Column("status", String(30), nullable=False, index=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("failure_reason", String),
    Column("configuration", JSONB, nullable=False),
    Column("provenance", JSONB, nullable=False),
    Column("summary", JSONB, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    CheckConstraint(
        "status IN ('completed','failed','timed_out','verification_failed')",
        name="ck_run_terminal_status",
    ),
    CheckConstraint("finished_at >= started_at", name="ck_run_time_order"),
)
events = Table(
    "trace_events",
    metadata,
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("sequence_number", Integer, primary_key=True),
    Column("event_id", String(100), nullable=False, unique=True),
    Column("event_type", String(50), nullable=False, index=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("sequence_number > 0", name="ck_event_positive_sequence"),
)
verifications = Table(
    "verifications",
    metadata,
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("passed", Boolean, nullable=False),
    Column("exit_code", Integer),
    Column("duration_ms", Float, nullable=False),
    Column("passed_tests", Integer),
    Column("failed_tests", Integer),
    Column("total_tests", Integer),
    Column("timed_out", Boolean, nullable=False),
    Column("failure_reason", String),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("duration_ms >= 0", name="ck_verification_duration"),
)
metrics = Table(
    "run_metrics",
    metadata,
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("total_wall_time_ms", Float, nullable=False),
    Column("agent_execution_time_ms", Float, nullable=False),
    Column("verification_time_ms", Float, nullable=False),
    Column("tool_calls", Integer, nullable=False),
    Column("per_tool", JSONB, nullable=False),
    Column("inference", JSONB, nullable=False),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("tool_calls >= 0", name="ck_metrics_tool_calls"),
)
artifacts = Table(
    "artifacts",
    metadata,
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("artifact_type", String(30), primary_key=True),
    Column("path", String, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    UniqueConstraint("run_id", "path", name="uq_artifact_path"),
    CheckConstraint("size_bytes >= 0", name="ck_artifact_size"),
)

# Submission state is deliberately separate from immutable, verified run records.
jobs = Table(
    "run_jobs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("task_id", String(80), nullable=False),
    Column("agent_name", String(100), nullable=False),
    Column("strategy", String(50), nullable=False),
    Column("status", String(30), nullable=False, index=True),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("configuration", JSONB, nullable=False),
    Column("failure_reason", String),
    CheckConstraint(
        "status IN ('queued','running','verifying','completed','failed','timed_out',"
        "'verification_failed')",
        name="ck_job_status",
    ),
)

executions = Table(
    "sub_executions",
    metadata,
    Column("execution_id", String(100), primary_key=True),
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False, index=True),
    Column("parent_execution_id", String(100), nullable=False),
    Column("role", String(30), nullable=False, index=True),
    Column("provider", String(100), nullable=False, index=True),
    Column("provider_version", String(100)),
    Column("candidate_id", String(10)),
    Column("selected", Boolean, nullable=False),
    Column("status", String(30), nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("duration_ms >= 0", name="ck_execution_duration"),
)
strategy_results = Table(
    "strategy_results",
    metadata,
    Column("run_id", ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("selected_candidate", String(10)),
    Column("reviewer_decision", String(20)),
    Column("corrections", Integer, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("peak_concurrent_agents", Integer, nullable=False),
    Column("metrics", JSONB, nullable=False),
    CheckConstraint("corrections BETWEEN 0 AND 1", name="ck_one_correction"),
)
job_events = Table(
    "run_job_events",
    metadata,
    Column("run_id", ForeignKey("run_jobs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("sequence_number", Integer, primary_key=True),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("sequence_number > 0", name="ck_job_event_sequence"),
)

experiments = Table(
    "experiments",
    metadata,
    Column("experiment_id", String(64), primary_key=True),
    Column("spec_hash", String(64), nullable=False),
    Column("name", String(160), nullable=False),
    Column("research_question", String, nullable=False),
    Column("benchmark_name", String(100), nullable=False),
    Column("benchmark_version", String(30), nullable=False),
    Column("benchmark_manifest_hash", String(64), nullable=False),
    Column("random_seed", BigInteger, nullable=False),
    Column("status", String(20), nullable=False, index=True),
    Column("spec", JSONB, nullable=False),
    Column("provenance", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("pause_reason", String),
    CheckConstraint(
        "status IN ('planned','running','paused','completed')",
        name="ck_experiment_status",
    ),
)

experiment_configs = Table(
    "experiment_configs",
    metadata,
    Column(
        "experiment_id",
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("configuration_id", String(64), primary_key=True),
    Column("strategy", String(50), nullable=False, index=True),
    Column("provider", String(40), nullable=False, index=True),
    Column("configuration", JSONB, nullable=False),
)

experiment_schedule = Table(
    "experiment_schedule",
    metadata,
    Column(
        "experiment_id",
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("scheduled_order", Integer, primary_key=True),
    Column("configuration_id", String(64), nullable=False),
    Column("task_id", String(80), nullable=False, index=True),
    Column("repetition", Integer, nullable=False),
    Column("status", String(20), nullable=False, index=True),
    Column("valid_run_id", String(64)),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    UniqueConstraint(
        "experiment_id",
        "configuration_id",
        "task_id",
        "repetition",
        name="uq_experiment_repetition",
    ),
    CheckConstraint(
        "status IN ('pending','running','completed')",
        name="ck_experiment_schedule_status",
    ),
    CheckConstraint("repetition > 0", name="ck_experiment_repetition_positive"),
    CheckConstraint("scheduled_order > 0", name="ck_experiment_order_positive"),
)

experiment_runs = Table(
    "experiment_runs",
    metadata,
    Column("attempt_id", String(100), primary_key=True),
    Column(
        "experiment_id",
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("scheduled_order", Integer, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("run_id", String(64), nullable=False, unique=True),
    Column("validity", String(30), nullable=False, index=True),
    Column("classification", String(40), nullable=False),
    Column("replacement_for_run_id", String(64)),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("failure_reason", String),
    Column("classification_note", String),
    Column("payload", JSONB, nullable=False),
    UniqueConstraint(
        "experiment_id", "scheduled_order", "attempt_number", name="uq_experiment_attempt"
    ),
    CheckConstraint(
        "validity IN ('valid','infrastructure_failure','protocol_excluded')",
        name="ck_experiment_run_validity",
    ),
    CheckConstraint(
        "classification IN "
        "('benchmark_success','benchmark_failure','infrastructure_failure','protocol_excluded')",
        name="ck_experiment_run_classification",
    ),
)
