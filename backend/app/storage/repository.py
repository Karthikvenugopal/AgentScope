"""Small synchronous repository boundary; harness calls it in a worker thread."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.dialects.postgresql import insert

from app.evaluation.models import VerificationResult
from app.models.run import ArtifactMetadata, RunResult, RunStatus
from app.storage import schema
from app.telemetry.events import AnyTraceEvent
from app.telemetry.metrics import RunMetrics


class StoredRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: dict[str, Any]
    events: tuple[AnyTraceEvent, ...]
    verification: VerificationResult | None
    metrics: RunMetrics
    artifacts: tuple[ArtifactMetadata, ...]


class RunRepository(Protocol):
    def save(self, run: RunResult) -> None: ...
    def get(self, run_id: str) -> StoredRun | None: ...
    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]: ...


class RunConflictError(ValueError):
    """A finalized run ID was reused for different contents."""


class PostgresRunRepository:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required")
        self.engine = engine

    @classmethod
    def from_url(cls, url: str) -> PostgresRunRepository:
        return cls(create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5}))

    def save(self, run: RunResult) -> None:
        if run.status not in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.VERIFICATION_FAILED,
        }:
            raise ValueError("only finalized runs may be persisted")
        if run.status is RunStatus.COMPLETED and (
            run.verification is None or not run.verification.passed
        ):
            raise ValueError("completed run requires successful official verification")
        if run.metrics is None:
            raise ValueError("metrics are required before persistence")
        if [e.sequence_number for e in run.events] != list(range(1, len(run.events) + 1)):
            raise ValueError("trace sequence must be contiguous and ordered")
        if any(e.run_id != run.run_id for e in run.events):
            raise ValueError("trace run IDs must match the parent run")
        fingerprint = hashlib.sha256(
            json.dumps(run.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        summary = run.model_dump(
            mode="json",
            exclude={"events", "git_diff", "metrics", "verification", "artifact_metadata"},
        )
        benchmark = run.provenance.get("benchmark", {})
        if not isinstance(benchmark, dict):
            raise ValueError("benchmark provenance is required")
        task_hash = benchmark.get("task_hash")
        if not isinstance(task_hash, str) or len(task_hash) != 64:
            raise ValueError("frozen task hash is required")
        with self.engine.begin() as connection:
            statement = (
                insert(schema.runs)
                .values(
                    run_id=run.run_id,
                    task_id=run.task_id,
                    task_source=benchmark.get("source", "agentscope"),
                    task_dataset=benchmark.get("dataset", "AgentScope Benchmark"),
                    dataset_version=benchmark.get("dataset_version", "0.1"),
                    task_hash=task_hash,
                    agent_name=run.agent_name,
                    strategy=run.strategy,
                    status=run.status.value,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    failure_reason=run.failure_reason,
                    configuration=run.configuration,
                    provenance=run.provenance,
                    summary=summary,
                    content_sha256=fingerprint,
                )
                .on_conflict_do_nothing(index_elements=["run_id"])
                .returning(schema.runs.c.run_id)
            )
            if connection.execute(statement).scalar_one_or_none() is None:
                previous = connection.execute(
                    select(schema.runs.c.content_sha256).where(
                        schema.runs.c.run_id == run.run_id,
                    )
                ).scalar_one()
                if previous != fingerprint:
                    raise RunConflictError("run ID already has different finalized contents")
                return
            if run.events:
                connection.execute(
                    schema.events.insert(),
                    [
                        dict(
                            run_id=run.run_id,
                            sequence_number=e.sequence_number,
                            event_id=e.event_id,
                            event_type=e.event_type,
                            timestamp=e.timestamp,
                            payload=e.model_dump(mode="json"),
                        )
                        for e in run.events
                    ],
                )
            if run.verification is not None:
                v = run.verification
                connection.execute(
                    schema.verifications.insert().values(
                        run_id=run.run_id,
                        passed=v.passed,
                        exit_code=v.exit_code,
                        duration_ms=v.duration_ms,
                        passed_tests=v.passed_tests,
                        failed_tests=v.failed_tests,
                        total_tests=v.total_tests,
                        timed_out=v.timed_out,
                        failure_reason=v.failure_reason,
                        payload=v.model_dump(mode="json"),
                    )
                )
            m = run.metrics
            connection.execute(
                schema.metrics.insert().values(
                    run_id=run.run_id,
                    total_wall_time_ms=m.total_wall_time_ms,
                    agent_execution_time_ms=m.agent_execution_time_ms,
                    verification_time_ms=m.verification_time_ms,
                    tool_calls=m.tool_calls,
                    per_tool=m.per_tool,
                    inference=m.inference.model_dump(mode="json"),
                    payload=m.model_dump(mode="json"),
                )
            )
            if run.artifact_metadata:
                connection.execute(
                    schema.artifacts.insert(),
                    [{"run_id": run.run_id, **a.model_dump()} for a in run.artifact_metadata],
                )
            if run.orchestration is not None:
                strategy = run.orchestration
                connection.execute(
                    schema.strategy_results.insert().values(
                        run_id=run.run_id,
                        selected_candidate=strategy.selected_candidate,
                        reviewer_decision=strategy.review.decision if strategy.review else None,
                        corrections=strategy.corrections,
                        candidate_count=strategy.candidate_count,
                        peak_concurrent_agents=strategy.metrics.peak_concurrent_agents,
                        metrics=strategy.metrics.model_dump(mode="json"),
                    )
                )
                for execution in strategy.executions:
                    connection.execute(
                        schema.executions.insert().values(
                            execution_id=execution.execution_id,
                            run_id=run.run_id,
                            parent_execution_id=execution.parent_execution_id,
                            role=execution.role,
                            provider=execution.provider,
                            provider_version=execution.provider_metadata.version
                            if execution.provider_metadata
                            else None,
                            candidate_id=execution.candidate_id,
                            selected=execution.candidate_id is not None
                            and execution.candidate_id == strategy.selected_candidate,
                            status=execution.status,
                            duration_ms=execution.duration_ms,
                            payload=execution.model_dump(mode="json"),
                        )
                    )

    def get(self, run_id: str) -> StoredRun | None:
        with self.engine.connect() as connection:
            summary = connection.execute(
                select(schema.runs.c.summary).where(
                    schema.runs.c.run_id == run_id,
                )
            ).scalar_one_or_none()
            if summary is None:
                return None
            trace = (
                connection.execute(
                    select(schema.events.c.payload)
                    .where(
                        schema.events.c.run_id == run_id,
                    )
                    .order_by(schema.events.c.sequence_number)
                )
                .scalars()
                .all()
            )
            verification = connection.execute(
                select(schema.verifications.c.payload).where(
                    schema.verifications.c.run_id == run_id,
                )
            ).scalar_one_or_none()
            metrics = connection.execute(
                select(schema.metrics.c.payload).where(
                    schema.metrics.c.run_id == run_id,
                )
            ).scalar_one()
            artifacts = (
                connection.execute(
                    select(schema.artifacts)
                    .where(
                        schema.artifacts.c.run_id == run_id,
                    )
                    .order_by(schema.artifacts.c.artifact_type)
                )
                .mappings()
                .all()
            )
            return StoredRun.model_validate(
                dict(
                    summary=summary,
                    events=trace,
                    verification=verification,
                    metrics=metrics,
                    artifacts=[
                        {k: v for k, v in row.items() if k != "run_id"} for row in artifacts
                    ],
                )
            )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(schema.runs.c.summary)
                    .order_by(
                        schema.runs.c.started_at.desc(),
                        schema.runs.c.run_id,
                    )
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [dict(row) for row in rows]
