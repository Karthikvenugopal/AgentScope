"""The original single-agent loop, preserved behind the strategy boundary."""

import asyncio
from dataclasses import dataclass
from time import monotonic

from app.agents import AgentContext, AgentTurnStatus, CodingAgent
from app.harness.limits import RunLimitExceeded, RunLimits
from app.harness.tools.registry import ToolRegistry
from app.models.task import Task
from app.telemetry.events import (
    AgentCompletedEvent,
    AgentStartedEvent,
    AgentTurnCompletedEvent,
    AgentTurnStartedEvent,
)
from app.telemetry.recorder import TraceRecorder


class AgentExecutionError(RuntimeError):
    """The agent explicitly failed a turn."""


@dataclass
class SingleContext:
    task: Task
    agent: CodingAgent
    tools: ToolRegistry
    recorder: TraceRecorder
    limits: RunLimits
    turns: int = 0
    summary: str = ""


class SingleAgentStrategy:
    async def execute(self, context: SingleContext) -> SingleContext:
        agent, task, recorder = context.agent, context.task, context.recorder
        base = AgentContext(run_id=recorder.run_id)
        await recorder.emit(AgentStartedEvent, agent_name=agent.name)
        started = monotonic()
        await agent.start(task, base)
        for turn in range(1, context.limits.max_agent_turns + 1):
            context.turns = turn
            await recorder.emit(AgentTurnStartedEvent, turn_number=turn)
            turn_started = monotonic()
            try:
                reply = await agent.run_turn(
                    task, context.tools, base.model_copy(update={"turn_number": turn})
                )
            except (Exception, asyncio.CancelledError) as exc:
                await recorder.emit(
                    AgentTurnCompletedEvent,
                    turn_number=turn,
                    turn_status=AgentTurnStatus.FAILED.value,
                    duration_ms=(monotonic() - turn_started) * 1000,
                    summary=f"{type(exc).__name__}: {exc}",
                )
                raise
            await recorder.emit(
                AgentTurnCompletedEvent,
                turn_number=turn,
                turn_status=reply.status.value,
                duration_ms=(monotonic() - turn_started) * 1000,
                summary=reply.summary,
            )
            context.summary = reply.summary
            if reply.status is AgentTurnStatus.FAILED:
                raise AgentExecutionError(reply.summary)
            if reply.status is AgentTurnStatus.COMPLETED:
                break
        else:
            raise RunLimitExceeded(
                f"maximum agent turn limit exceeded: {context.limits.max_agent_turns}"
            )
        await recorder.emit(
            AgentCompletedEvent,
            summary=context.summary,
            turns=context.turns,
            tool_calls=context.tools.tool_calls,
            duration_ms=(monotonic() - started) * 1000,
        )
        return context
