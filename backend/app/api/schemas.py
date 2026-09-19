"""Stable public DTOs; internal paths and verifier output are never serialized."""

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from app.harness.limits import RunLimits
from app.models.run import RunStatus
from app.models.task import RepositorySpec, TaskId
from app.providers.models import ProviderMetadata
from app.storage.repository import StoredRun
from app.strategies.models import ImplementersConfiguration, RoleConfiguration, StrategyResult
from app.telemetry.metrics import RunMetrics

ResourceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunConfiguration(RunLimits):
    """Only controlled resource limits are configurable; no commands or paths."""

    model_config = ConfigDict(extra="forbid", strict=True)
    max_agent_turns: int = Field(default=20, ge=1, le=100)
    max_tool_calls: int = Field(default=100, ge=1, le=1000)
    command_timeout_seconds: float = Field(default=60, gt=0, le=300)
    overall_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    max_file_write_bytes: int = Field(default=1_000_000, ge=1, le=1_000_000)
    max_captured_output_bytes: int = Field(default=1_000_000, ge=1, le=1_000_000)
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    planner: RoleConfiguration | None = None
    implementer: RoleConfiguration | None = None
    implementers: ImplementersConfiguration | None = None
    reviewer: RoleConfiguration | None = None


class CreateRunRequest(APIModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "task_id": "incorrect_api_response",
                    "agent": "mock",
                    "strategy": "single",
                    "configuration": {},
                }
            ]
        },
    )
    task_id: TaskId
    agent: str = Field(
        default="mock",
        min_length=1,
        max_length=100,
        description="mock, codex, claude-code; check /agents for availability",
    )
    strategy: str = Field(
        default="single",
        min_length=1,
        max_length=50,
        description="single, planner_implementer_reviewer, parallel_implementers",
    )
    configuration: RunConfiguration = Field(default_factory=RunConfiguration)


class QueuedRun(APIModel):
    run_id: str
    status: Literal["queued"] = "queued"


class ErrorDetail(APIModel):
    code: str
    message: str


class ErrorResponse(APIModel):
    error: ErrorDetail


class Health(APIModel):
    status: Literal["alive"] = "alive"


class Readiness(APIModel):
    status: Literal["ready", "not_ready"]
    database: Literal["healthy", "unavailable"]


class TaskMetadata(APIModel):
    id: str
    title: str
    description: str
    version: str
    tags: tuple[str, ...]
    language: str
    difficulty: str
    source: str
    dataset: str
    dataset_version: str
    task_hash: str | None


class TaskDetail(TaskMetadata):
    repository: RepositorySpec
    setup_command: str | None
    test_command: str
    timeout_seconds: int
    expected_behavior: str


class VerificationSummary(APIModel):
    passed: bool
    exit_code: int | None
    passed_tests: int | None
    failed_tests: int | None
    total_tests: int | None
    duration_ms: float
    timed_out: bool


class ArtifactSummary(APIModel):
    type: str
    size_bytes: int
    sha256: str


class RunSummary(APIModel):
    run_id: str
    task_id: str
    agent: str
    strategy: str
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    failure_reason: str | None
    failure_code: (
        Literal["run_execution_failure", "verification_failed", "run_timed_out"] | None
    ) = None


class RunDetail(RunSummary):
    orchestration: StrategyResult | None = None
    provider: ProviderMetadata | None = None
    verification: VerificationSummary | None = None
    metrics: RunMetrics | None = None
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class RunPage(APIModel):
    items: list[RunSummary]
    limit: int
    offset: int


class PublicTraceEvent(APIModel):
    """Ordered event envelope. Payload excludes private verifier diagnostics."""

    event_id: str
    run_id: str
    sequence_number: int
    timestamp: datetime
    event_type: str
    payload: dict[str, JsonValue]


class TracePage(APIModel):
    events: list[PublicTraceEvent]
    next_after_sequence: int


def summary(row: dict[str, Any]) -> RunSummary:
    failure_code = None
    if row.get("failure_reason"):
        failure_code = {
            "verification_failed": "verification_failed",
            "timed_out": "run_timed_out",
        }.get(row["status"], "run_execution_failure")
    return RunSummary(
        run_id=str(row["run_id"]),
        task_id=str(row["task_id"]),
        strategy=str(row["strategy"]),
        status=RunStatus(str(row["status"])),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        agent=row["agent_name"],
        failure_reason="Run did not complete successfully" if row.get("failure_reason") else None,
        failure_code=cast(
            'Literal["run_execution_failure", "verification_failed", "run_timed_out"] | None',
            failure_code,
        ),
    )


def detail(run: StoredRun | dict[str, Any]) -> RunDetail:
    if not isinstance(run, StoredRun):
        return RunDetail(**summary(run).model_dump())
    verification = None
    if run.verification:
        verification = VerificationSummary.model_validate(
            {key: getattr(run.verification, key) for key in VerificationSummary.model_fields}
        )
    orchestration = run.summary.get("orchestration")
    if orchestration is not None:
        orchestration = StrategyResult.model_validate(orchestration)
        for execution in orchestration.executions:
            if execution.failure_reason:
                execution.failure_reason = "Role execution failed; inspect local diagnostics"
    return RunDetail(
        **summary(run.summary).model_dump(),
        verification=verification,
        metrics=run.metrics,
        orchestration=orchestration,
        provider=ProviderMetadata.model_validate(run.summary["provenance"]["provider"])
        if run.summary.get("provenance", {}).get("provider")
        else None,
        artifacts=[
            ArtifactSummary(type=a.artifact_type, size_bytes=a.size_bytes, sha256=a.sha256)
            for a in run.artifacts
        ],
    )


def public_event(event: dict[str, Any]) -> PublicTraceEvent:
    common = {
        key: event[key]
        for key in ("event_id", "run_id", "sequence_number", "timestamp", "event_type")
    }
    payload = {k: v for k, v in event.items() if k not in common}
    if event["event_type"] == "provider_process_failed":
        payload["payload"] = {"error_code": event.get("payload", {}).get("error_code")}
    if event["event_type"] in ("verification_completed", "verification_failed"):
        payload = {"result": {k: event["result"][k] for k in VerificationSummary.model_fields}}
    elif event["event_type"] == "verification_started":
        payload = {}
    # Internal exception strings may contain paths or connection details.
    for key in ("failure_reason", "error"):
        if key in payload:
            payload[key] = "Execution failed; inspect local diagnostics"
    if event["event_type"] == "agent_turn_completed" and payload.get("turn_status") == "failed":
        payload["summary"] = "Agent turn failed"
    return PublicTraceEvent(**common, payload=payload)
