"""Minimal provider-neutral tool protocol and execution context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel

from app.execution import CommandResult, Workspace
from app.harness.limits import RunLimits
from app.harness.snapshot import RepositorySnapshot
from app.harness.tools.models import ToolName, ToolOutput
from app.models.task import Task
from app.telemetry.events import CommandExecutedEvent
from app.telemetry.recorder import TraceRecorder


class ToolExecutionError(RuntimeError):
    """A recoverable tool failure exposed to the agent as structured output."""

    def __init__(self, message: str, *, output: ToolOutput | None = None) -> None:
        super().__init__(message)
        self.output = output


class AgentTool(Protocol):
    name: ToolName
    input_model: type[BaseModel]

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput: ...


class ToolContext:
    def __init__(
        self,
        *,
        workspace: Workspace,
        task: Task,
        limits: RunLimits,
        recorder: TraceRecorder,
        snapshot: RepositorySnapshot,
    ) -> None:
        self.workspace = workspace
        self.task = task
        self.limits = limits
        self.recorder = recorder
        self.snapshot = snapshot

    async def run_isolated_command(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float | None,
        purpose: str,
    ) -> CommandResult:
        if not self.workspace.execution_is_isolated:
            raise ToolExecutionError("agent commands require an isolated workspace runtime")
        timeout = timeout_seconds or self.limits.command_timeout_seconds
        if timeout > self.limits.command_timeout_seconds:
            raise ToolExecutionError("requested command timeout exceeds the per-command run limit")
        result = await self.workspace.execute(
            tuple(command),
            timeout_seconds=timeout,
            max_output_bytes=self.limits.max_captured_output_bytes,
        )
        await self.recorder.emit(
            CommandExecutedEvent,
            purpose=purpose,
            command=result.command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
        )
        return result
