"""Typed, provider-neutral events for one coding-agent run."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.models import VerificationResult
from app.providers.models import ProviderMetadata

ProviderEventType = Literal[
    "provider_session_started",
    "provider_tool_call_started",
    "provider_tool_call_completed",
    "provider_message",
    "provider_usage",
    "provider_session_completed",
    "provider_process_failed",
    "provider_output_truncated",
]


class BaseTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    run_id: str
    sequence_number: int = Field(ge=1)
    timestamp: datetime
    execution_id: str | None = None
    parent_execution_id: str | None = None
    role: str | None = None
    candidate_id: str | None = None


class RunStartedEvent(BaseTraceEvent):
    event_type: Literal["run_started"] = "run_started"
    task_id: str
    agent_name: str
    limits: dict[str, Any]


class AgentStartedEvent(BaseTraceEvent):
    event_type: Literal["agent_started"] = "agent_started"
    agent_name: str


class AgentTurnStartedEvent(BaseTraceEvent):
    event_type: Literal["agent_turn_started"] = "agent_turn_started"
    turn_number: int = Field(ge=1)


class AgentTurnCompletedEvent(BaseTraceEvent):
    event_type: Literal["agent_turn_completed"] = "agent_turn_completed"
    turn_number: int = Field(ge=1)
    turn_status: str
    duration_ms: float = Field(ge=0)
    summary: str


class ToolCallStartedEvent(BaseTraceEvent):
    event_type: Literal["tool_call_started"] = "tool_call_started"
    tool: str
    arguments: dict[str, Any]


class ToolCallCompletedEvent(BaseTraceEvent):
    event_type: Literal["tool_call_completed"] = "tool_call_completed"
    tool: str
    duration_ms: float = Field(ge=0)
    success: Literal[True] = True
    output: dict[str, Any] | None = None


class ToolCallFailedEvent(BaseTraceEvent):
    event_type: Literal["tool_call_failed"] = "tool_call_failed"
    tool: str
    duration_ms: float = Field(ge=0)
    success: Literal[False] = False
    error: str


class FileModifiedEvent(BaseTraceEvent):
    event_type: Literal["file_modified"] = "file_modified"
    path: str
    operation: Literal["created", "edited", "written"]
    size_bytes: int = Field(ge=0)


class CommandExecutedEvent(BaseTraceEvent):
    event_type: Literal["command_executed"] = "command_executed"
    purpose: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = Field(ge=0)
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


class TestExecutedEvent(BaseTraceEvent):
    event_type: Literal["test_executed"] = "test_executed"
    command: tuple[str, ...]
    exit_code: int
    duration_ms: float = Field(ge=0)
    timed_out: bool


class AgentCompletedEvent(BaseTraceEvent):
    event_type: Literal["agent_completed"] = "agent_completed"
    summary: str
    turns: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    duration_ms: float | None = Field(default=None, ge=0)


class VerificationStartedEvent(BaseTraceEvent):
    event_type: Literal["verification_started"] = "verification_started"
    verifier: str


class VerificationCompletedEvent(BaseTraceEvent):
    event_type: Literal["verification_completed"] = "verification_completed"
    result: VerificationResult


class VerificationFailedEvent(BaseTraceEvent):
    event_type: Literal["verification_failed"] = "verification_failed"
    result: VerificationResult


class RunCompletedEvent(BaseTraceEvent):
    event_type: Literal["run_completed"] = "run_completed"
    duration_ms: float = Field(ge=0)
    files_modified: tuple[str, ...]


class RunFailedEvent(BaseTraceEvent):
    event_type: Literal["run_failed"] = "run_failed"
    duration_ms: float = Field(ge=0)
    failure_reason: str


class RunTimedOutEvent(BaseTraceEvent):
    event_type: Literal["run_timed_out"] = "run_timed_out"
    duration_ms: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    failure_reason: str


class ProviderTraceEvent(BaseTraceEvent):
    event_type: ProviderEventType = "provider_message"
    provider: str
    native_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: ProviderMetadata | None = None


class StrategyTraceEvent(BaseTraceEvent):
    event_type: Literal[
        "strategy_started",
        "strategy_completed",
        "planner_started",
        "planner_completed",
        "implementer_started",
        "implementer_completed",
        "reviewer_started",
        "reviewer_completed",
        "correction_requested",
        "correction_started",
        "correction_completed",
        "parallel_group_started",
        "parallel_candidate_started",
        "parallel_candidate_completed",
        "candidate_selected",
        "candidate_tests_completed",
    ]
    provider: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


AnyTraceEvent = Annotated[
    RunStartedEvent
    | AgentStartedEvent
    | AgentTurnStartedEvent
    | AgentTurnCompletedEvent
    | ToolCallStartedEvent
    | ToolCallCompletedEvent
    | ToolCallFailedEvent
    | FileModifiedEvent
    | CommandExecutedEvent
    | TestExecutedEvent
    | AgentCompletedEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunTimedOutEvent
    | VerificationStartedEvent
    | VerificationCompletedEvent
    | VerificationFailedEvent
    | ProviderTraceEvent
    | StrategyTraceEvent,
    Field(discriminator="event_type"),
]
