"""Deterministic aggregation over ordered trace events and the frozen patch."""

from collections import Counter

from app.models.run import RunResult
from app.providers.models import MetricSource
from app.telemetry.metrics import RunMetrics
from app.telemetry.provider_metrics import provider_metrics


class RunMetricsAggregator:
    def aggregate(self, run: RunResult) -> RunMetrics:
        events = run.events
        per_tool = Counter(e.tool for e in events if e.event_type == "tool_call_started")
        successful = sum(e.event_type == "tool_call_completed" for e in events)
        failed = sum(e.event_type == "tool_call_failed" for e in events)
        commands = [e for e in events if e.event_type == "command_executed"]
        tests = [e for e in events if e.event_type == "test_executed"]
        verification = run.verification
        agent_start = next((e.timestamp for e in events if e.event_type == "agent_started"), None)
        agent_end = next((e.timestamp for e in events if e.event_type == "agent_completed"), None)
        if agent_end is None:
            agent_end = next(
                (e.timestamp for e in events if e.event_type in {"run_failed", "run_timed_out"}),
                run.finished_at,
            )
        agent_time = (
            max(0.0, (agent_end - agent_start).total_seconds() * 1000) if agent_start else 0.0
        )
        monotonic_agent_time = next(
            (
                e.duration_ms
                for e in events
                if e.event_type == "agent_completed" and e.duration_ms is not None
            ),
            None,
        )
        if monotonic_agent_time is not None:
            agent_time = monotonic_agent_time
        added = removed = 0
        in_hunk = False
        for line in run.git_diff.splitlines():
            if line.startswith("diff --git "):
                in_hunk = False
            elif line.startswith("@@ "):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                added += 1
            elif in_hunk and line.startswith("-"):
                removed += 1
        command_timeouts = sum(c.timed_out for c in commands)
        verification_timeout = int(verification is not None and verification.timed_out)
        run_timeout = int(any(e.event_type == "run_timed_out" for e in events))
        inference, provider_tools, provider_success, provider_failed = provider_metrics(events)
        if run.orchestration is not None:
            workload = run.orchestration.metrics
            # A provider with no usage must not disappear from aggregate null semantics.
            inference = inference.model_copy(
                update={
                    "input_tokens": workload.input_tokens,
                    "output_tokens": workload.output_tokens,
                    "total_tokens": workload.total_tokens,
                    "time_to_first_provider_output_ms": None,
                }
            )
            additive = (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cached_input_tokens",
                "cache_creation_input_tokens",
                "reasoning_tokens",
            )
            updates: dict[str, object] = {}
            sources = dict(inference.provenance)
            for key in additive:
                values = [getattr(e.inference, key) for e in run.orchestration.executions]
                known = bool(values) and all(type(value) is int for value in values)
                updates[key] = sum(values) if known else None
                sources[key] = MetricSource(
                    provenance="derived" if known else "unavailable",
                    source="sum_per_execution_usage" if known else None,
                )
            sources["time_to_first_provider_output_ms"] = MetricSource(provenance="unavailable")
            inference = inference.model_copy(update={**updates, "provenance": sources})
        return RunMetrics(
            total_wall_time_ms=run.duration_ms,
            agent_execution_time_ms=agent_time,
            verification_time_ms=verification.duration_ms if verification else 0.0,
            agent_turns=sum(e.event_type == "agent_turn_started" for e in events),
            tool_calls=sum(per_tool.values()) + sum(provider_tools.values()),
            successful_tool_calls=successful + provider_success,
            failed_tool_calls=failed + provider_failed,
            per_tool=dict(sorted(per_tool.items())),
            files_modified=len(run.files_modified),
            lines_added=added,
            lines_removed=removed,
            patch_bytes=len(run.git_diff.encode("utf-8")),
            commands_executed=len(commands) + provider_tools.get("run_command", 0),
            agent_test_runs=len(tests),
            agent_test_time_ms=sum(t.duration_ms for t in tests),
            retries=sum(
                1
                for e in events
                if e.event_type == "provider_message"
                and e.payload.get("native", {}).get("subtype") == "api_retry"
            ),
            tool_failures=failed + provider_failed,
            timeouts=command_timeouts
            + verification_timeout
            + (run_timeout if not command_timeouts and not verification_timeout else 0),
            output_truncations=sum(e.event_type == "provider_output_truncated" for e in events)
            + sum(int(c.stdout_truncated) + int(c.stderr_truncated) for c in commands)
            + (
                int(verification.stdout_truncated) + int(verification.stderr_truncated)
                if verification
                else 0
            ),
            verification_passed=verification.passed if verification else None,
            verification_duration_ms=verification.duration_ms if verification else None,
            official_tests_passed=verification.passed_tests if verification else None,
            official_tests_failed=verification.failed_tests if verification else None,
            official_tests_total=verification.total_tests if verification else None,
            inference=inference,
            provider_tool_calls=sum(provider_tools.values())
            if run.agent_name != "mock"
            or (
                run.orchestration is not None
                and any(execution.provider != "mock" for execution in run.orchestration.executions)
            )
            else None,
            provider_per_tool=provider_tools,
        )
