"""Aggregate native observations without inventing model request boundaries."""

from collections import Counter

from app.providers.models import MetricSource
from app.telemetry.events import AnyTraceEvent, ProviderTraceEvent
from app.telemetry.metrics import InferenceMetrics


def provider_metrics(
    events: tuple[AnyTraceEvent, ...],
) -> tuple[InferenceMetrics, dict[str, int], int, int]:
    native = [e for e in events if isinstance(e, ProviderTraceEvent)]
    measured: dict[str, int | float | None] = {}
    provenance = {
        key: MetricSource(provenance="unavailable")
        for key in InferenceMetrics.model_fields
        if key != "provenance"
    }
    usage = [e for e in native if e.event_type == "provider_usage"]
    for key in (
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
        "reasoning_tokens",
    ):
        values = [e.payload.get("usage", {}).get(key) for e in usage]
        if values and all(type(v) is int for v in values):
            measured[key] = sum(values)
            provenance[key] = MetricSource(
                provenance="measured" if len(values) == 1 else "derived",
                source="provider_usage" if len(values) == 1 else "sum_provider_usage",
            )
    if measured.get("input_tokens") is not None and measured.get("output_tokens") is not None:
        # Codex input includes cache reads; Claude reports cache reads/writes separately.
        total: int | float | None = (measured["input_tokens"] or 0) + (
            measured["output_tokens"] or 0
        )
        claude_usage = [e for e in usage if e.provider == "claude-code"]
        if claude_usage:
            for key in ("cached_input_tokens", "cache_creation_input_tokens"):
                values = [e.payload.get("usage", {}).get(key) for e in claude_usage]
                if not all(type(v) is int for v in values):
                    total = None
                    break
                total = (total or 0) + sum(values)
        if total is not None:
            measured["total_tokens"] = total
            provenance["total_tokens"] = MetricSource(
                provenance="derived", source="sum_disjoint_usage_categories"
            )
    for event in native:
        if event.metadata and event.metadata.time_to_first_provider_output_ms is not None:
            measured["time_to_first_provider_output_ms"] = (
                event.metadata.time_to_first_provider_output_ms
            )
            provenance["time_to_first_provider_output_ms"] = MetricSource(
                provenance="measured", source="process_launch_to_first_stdout_bytes_monotonic"
            )
    tools: dict[str, str] = {}
    outcomes: dict[str, bool] = {}
    for event in native:
        tool_id = event.payload.get("tool_id")
        if isinstance(tool_id, str):
            tool_id = f"{event.execution_id or event.run_id}:{tool_id}"
            if isinstance(event.payload.get("tool"), str):
                tools[tool_id] = event.payload["tool"]
            if (
                event.event_type == "provider_tool_call_completed"
                and type(event.payload.get("success")) is bool
            ):
                outcomes[tool_id] = event.payload["success"]
    return (
        InferenceMetrics.model_validate({**measured, "provenance": provenance}),
        dict(Counter(tools.values())),
        sum(outcomes.values()),
        sum(not value for value in outcomes.values()),
    )
