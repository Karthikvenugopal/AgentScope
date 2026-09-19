from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.evaluation.models import VerificationResult
from app.models.run import RunResult, RunStatus
from app.telemetry.aggregation import RunMetricsAggregator
from app.telemetry.events import (
    AgentCompletedEvent,
    AgentStartedEvent,
    AgentTurnStartedEvent,
    CommandExecutedEvent,
    ToolCallCompletedEvent,
    ToolCallFailedEvent,
    ToolCallStartedEvent,
)
from app.telemetry.events import TestExecutedEvent as ExecutedTestEvent
from app.telemetry.recorder import TraceRecorder


async def test_metrics_derive_counts_durations_patch_and_unavailable_inference() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    now = start
    trace = TraceRecorder("metrics", clock=lambda: now)
    await trace.emit(AgentStartedEvent, agent_name="mock")
    await trace.emit(AgentTurnStartedEvent, turn_number=1)
    await trace.emit(ToolCallStartedEvent, tool="read_file", arguments={})
    await trace.emit(ToolCallCompletedEvent, tool="read_file", duration_ms=5)
    await trace.emit(ToolCallStartedEvent, tool="run_tests", arguments={})
    await trace.emit(
        CommandExecutedEvent,
        purpose="task_tests",
        command=("pytest",),
        exit_code=-9,
        stdout="partial",
        stderr="",
        duration_ms=10,
        timed_out=True,
        stdout_truncated=True,
        stderr_truncated=False,
    )
    await trace.emit(
        ExecutedTestEvent, command=("pytest",), exit_code=-9, duration_ms=10, timed_out=True
    )
    await trace.emit(ToolCallFailedEvent, tool="run_tests", duration_ms=10, error="timed out")
    now += timedelta(milliseconds=20)
    await trace.emit(AgentCompletedEvent, summary="done", turns=1, tool_calls=2)
    run = RunResult(
        run_id="metrics",
        task_id="task",
        agent_name="mock",
        status=RunStatus.COMPLETED,
        started_at=start,
        finished_at=now,
        duration_ms=30,
        workspace=None,
        events=trace.events,
        agent_turns=1,
        tool_calls=2,
        files_modified=("app.py",),
        git_diff=(
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
        ),
        verification=VerificationResult(passed=True, exit_code=0, duration_ms=8),
    )
    metrics = RunMetricsAggregator().aggregate(run)
    assert metrics.agent_execution_time_ms == 20
    assert metrics.verification_time_ms == 8
    assert metrics.total_wall_time_ms == 30
    assert metrics.per_tool == {"read_file": 1, "run_tests": 1}
    assert metrics.tool_calls == 2 and metrics.successful_tool_calls == 1
    assert metrics.failed_tool_calls == metrics.tool_failures == 1
    assert metrics.agent_test_runs == metrics.commands_executed == 1
    assert metrics.agent_test_time_ms == 10
    assert metrics.lines_added == metrics.lines_removed == 1
    assert metrics.patch_bytes == len(run.git_diff.encode())
    assert metrics.timeouts == metrics.output_truncations == 1
    assert metrics.official_tests_passed is None
    assert all(
        value is None for value in metrics.inference.model_dump(exclude={"provenance"}).values()
    )
    assert metrics == RunMetricsAggregator().aggregate(run)
    # UTC jumps cannot inflate a measured monotonic agent duration.
    measured_events = tuple(
        e.model_copy(update={"duration_ms": 7.0}) if e.event_type == "agent_completed" else e
        for e in run.events
    )
    assert (
        RunMetricsAggregator()
        .aggregate(run.model_copy(update={"events": measured_events}))
        .agent_execution_time_ms
        == 7.0
    )
