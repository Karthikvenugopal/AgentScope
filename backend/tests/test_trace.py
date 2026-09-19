from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.telemetry.events import AgentStartedEvent, RunStartedEvent
from app.telemetry.recorder import TraceRecorder


async def test_trace_recorder_orders_concurrent_events_monotonically() -> None:
    fixed = datetime(2026, 1, 2, tzinfo=UTC)
    recorder = TraceRecorder("ordered", clock=lambda: fixed)

    await asyncio.gather(
        *(recorder.emit(AgentStartedEvent, agent_name=f"agent-{index}") for index in range(20))
    )

    assert [event.sequence_number for event in recorder.events] == list(range(1, 21))
    assert [event.event_id for event in recorder.events] == [
        f"ordered:{index:06d}" for index in range(1, 21)
    ]


async def test_trace_events_are_json_serializable() -> None:
    recorder = TraceRecorder("json-run")
    event = await recorder.emit(
        RunStartedEvent,
        task_id="task",
        agent_name="mock",
        limits={"max_agent_turns": 3},
    )

    serialized = json.dumps(event.model_dump(mode="json"))

    assert '"event_type": "run_started"' in serialized
    assert '"sequence_number": 1' in serialized
