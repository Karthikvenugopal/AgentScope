"""Structured single-agent run results and local artifact metadata."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.models import VerificationResult
from app.strategies.models import StrategyResult
from app.telemetry.events import AnyTraceEvent
from app.telemetry.metrics import RunMetrics


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    VERIFICATION_FAILED = "verification_failed"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class WorkspaceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime: str
    isolated: bool
    retained: bool
    host_path: str
    image: str | None = None


class ArtifactPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_directory: str
    trace: str
    patch: str
    run: str


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task_id: str
    agent_name: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: float = Field(ge=0)
    workspace: WorkspaceMetadata | None
    events: tuple[AnyTraceEvent, ...]
    agent_turns: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    files_modified: tuple[str, ...]
    git_diff: str
    failure_reason: str | None = None
    artifacts: ArtifactPaths | None = None
    verification: VerificationResult | None = None
    metrics: RunMetrics | None = None
    strategy: str = "single"
    configuration: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    artifact_metadata: tuple[ArtifactMetadata, ...] = ()
    persistence_error: str | None = None
    orchestration: StrategyResult | None = None


class ArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: str
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


RunResult.model_rebuild()
