"""Trace-wrapped, limit-aware registry for all agent-visible tools."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any, cast

from pydantic import BaseModel

from app.harness.limits import RunLimitExceeded
from app.harness.tools.base import AgentTool, ToolContext, ToolExecutionError
from app.harness.tools.implementations import BUILTIN_TOOLS
from app.harness.tools.models import (
    GitDiffOutput,
    ToolDefinition,
    ToolExecutionResult,
    ToolName,
)
from app.providers.models import ProviderMetadata, ProviderName
from app.telemetry.events import (
    ToolCallCompletedEvent,
    ToolCallFailedEvent,
    ToolCallStartedEvent,
)


class ToolRegistry:
    """Provider-neutral name/schema dispatch over controlled capabilities."""

    def __init__(
        self,
        context: ToolContext,
        tools: tuple[AgentTool, ...] | None = None,
        provider_execute: Callable[[ProviderName, str | None], Awaitable[ProviderMetadata]]
        | None = None,
    ) -> None:
        self._context = context
        configured_tools = tools or cast(tuple[AgentTool, ...], BUILTIN_TOOLS)
        self._tools = {tool.name: tool for tool in configured_tools}
        self.tool_calls = 0
        self._provider_execute = provider_execute

    async def run_provider(self, provider: ProviderName, model: str | None) -> ProviderMetadata:
        if self._provider_execute is None:
            raise RuntimeError("isolated provider execution is not configured")
        return await self._provider_execute(provider, model)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            ToolDefinition(
                name=name,
                input_schema=tool.input_model.model_json_schema(),
            )
            for name, tool in sorted(self._tools.items(), key=lambda item: item[0].value)
        )

    async def execute(
        self,
        name: ToolName | str,
        arguments: Mapping[str, Any] | BaseModel | None = None,
    ) -> ToolExecutionResult:
        label = name.value if isinstance(name, ToolName) else name
        raw_arguments = _json_mapping(arguments)
        await self._context.recorder.emit(
            ToolCallStartedEvent,
            tool=label,
            arguments=raw_arguments,
        )
        started = monotonic()

        if self.tool_calls >= self._context.limits.max_tool_calls:
            error = f"maximum tool call limit exceeded: {self._context.limits.max_tool_calls}"
            await self._context.recorder.emit(
                ToolCallFailedEvent,
                tool=label,
                duration_ms=(monotonic() - started) * 1000,
                error=error,
            )
            raise RunLimitExceeded(error)
        self.tool_calls += 1

        try:
            tool_name = ToolName(label)
            tool = self._tools[tool_name]
            request = tool.input_model.model_validate(raw_arguments)
            output = await tool.execute(request, self._context)
        except Exception as exc:
            duration_ms = (monotonic() - started) * 1000
            error = str(exc)
            failed_output = exc.output if isinstance(exc, ToolExecutionError) else None
            await self._context.recorder.emit(
                ToolCallFailedEvent,
                tool=label,
                duration_ms=duration_ms,
                error=error,
            )
            return ToolExecutionResult(
                tool=label,
                success=False,
                output=failed_output,
                error=error,
                duration_ms=duration_ms,
            )

        duration_ms = (monotonic() - started) * 1000
        await self._context.recorder.emit(
            ToolCallCompletedEvent,
            tool=label,
            duration_ms=duration_ms,
            output=output.model_dump(mode="json"),
        )
        return ToolExecutionResult(
            tool=label,
            success=True,
            output=output,
            duration_ms=duration_ms,
        )

    async def final_diff(self) -> GitDiffOutput:
        patch, changed = await self._context.snapshot.diff(self._context.workspace)
        return GitDiffOutput(diff=patch, files_changed=changed)


def _json_mapping(arguments: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, BaseModel):
        return arguments.model_dump(mode="json")
    # Normalize provider-supplied mappings now so trace export cannot fail later.
    return cast(dict[str, Any], json.loads(json.dumps(dict(arguments), default=str)))
