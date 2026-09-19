"""Lossless AgentScope envelope inside Harbor's current ATIF v1.8 structure."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.telemetry.events import AnyTraceEvent


class ATIFError(ValueError):
    pass


def export_atif(
    events: tuple[AnyTraceEvent, ...],
    *,
    run_id: str,
    agent_name: str,
    agent_version: str = "0.8.0",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> dict[str, Any]:
    """Export native events without discarding hierarchy or provider payloads."""
    grouped: dict[str | None, list[AnyTraceEvent]] = defaultdict(list)
    for event in events:
        grouped[event.execution_id].append(event)

    def trajectory(
        scoped: list[AnyTraceEvent], trajectory_id: str, role: str | None
    ) -> dict[str, Any]:
        steps = [
            {
                "step_id": index,
                "timestamp": event.timestamp.isoformat(),
                "source": "agent",
                "message": event.event_type,
                "llm_call_count": 0,
                "extra": {
                    "agentscope_event": event.model_dump(mode="json"),
                    "role": role,
                },
            }
            for index, event in enumerate(scoped, 1)
        ]
        if not steps:
            steps = [
                {
                    "step_id": 1,
                    "source": "agent",
                    "message": "AgentScope hierarchy container",
                    "llm_call_count": 0,
                    "extra": {"role": role},
                }
            ]
        return {
            "schema_version": "ATIF-v1.8",
            "session_id": run_id,
            "trajectory_id": trajectory_id,
            "agent": {
                "name": agent_name,
                "version": agent_version,
                "extra": {"producer": "AgentScope", "role": role},
            },
            "steps": steps,
            "notes": (
                "AgentScope native trace is authoritative; events are losslessly "
                "embedded in step.extra.agentscope_event."
            ),
        }

    root = trajectory(grouped.pop(None, []), run_id, None)
    children: list[dict[str, Any]] = []
    for execution_id, scoped in sorted(grouped.items(), key=lambda item: item[0] or ""):
        assert execution_id is not None
        role = next((event.role for event in scoped if event.role is not None), None)
        children.append(trajectory(scoped, execution_id, role))
    if children:
        root["subagent_trajectories"] = children
    root["final_metrics"] = {
        "total_prompt_tokens": input_tokens,
        "total_completion_tokens": output_tokens,
        "total_steps": len(events),
        "extra": {
            "agentscope_event_count": len(events),
            "hierarchical": bool(children),
        },
    }
    return root


def import_agentscope_events(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover events only from an AgentScope lossless ATIF envelope.

    Generic ATIF can be inspected by external tooling but is not promoted to an
    AgentScope native trace because its ordering and hierarchy semantics differ.
    """
    if document.get("schema_version") not in {"ATIF-v1.7", "ATIF-v1.8"}:
        raise ATIFError("only ATIF v1.7/v1.8 hierarchy can preserve AgentScope traces")
    trajectories = [document, *(document.get("subagent_trajectories") or [])]
    recovered: list[dict[str, Any]] = []
    for trajectory in trajectories:
        for step in trajectory.get("steps") or []:
            event = (step.get("extra") or {}).get("agentscope_event")
            if event is not None:
                if not isinstance(event, dict):
                    raise ATIFError("embedded AgentScope event must be an object")
                recovered.append(event)
    if not recovered:
        raise ATIFError("ATIF document has no lossless AgentScope event envelopes")
    return sorted(recovered, key=lambda event: int(event["sequence_number"]))
