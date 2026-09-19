"""Conservative CLI event normalization; unsupported boundaries stay unavailable."""

import json
from dataclasses import dataclass, field
from typing import Any

from app.providers.models import ProviderFailure, ProviderName
from app.providers.security import Redactor
from app.telemetry.events import ProviderEventType


@dataclass
class Observation:
    event_type: ProviderEventType
    native_type: str
    payload: dict[str, Any] = field(default_factory=dict)


def error_code(value: str) -> str:
    text = value.lower()
    if any(
        s in text for s in ("unauthorized", "authentication", "401", "api key", "login", "oauth")
    ):
        return "authentication_unavailable"
    if any(s in text for s in ("rate limit", "429", "usage limit")):
        return "provider_rate_limit"
    if any(s in text for s in ("context", "model not", "invalid model")):
        return "provider_model_error"
    return "provider_api_failure"


class EventParser:
    def __init__(self, provider: ProviderName, redactor: Redactor) -> None:
        self.provider = provider
        self.redactor = redactor
        self.session_id: str | None = None
        self.model: str | None = None
        self.completed = False
        self.failure: str | None = None

    def parse(self, line: bytes) -> list[Observation]:
        try:
            raw = json.loads(line)
            if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
                raise ValueError
            # Sanitize before retention, including unknown future provider payloads.
            data: dict[str, Any] = self.redactor.payload(raw)
            return self._codex(data) if self.provider == ProviderName.CODEX else self._claude(data)
        except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
            raise ProviderFailure("malformed_provider_event") from None

    def _codex(self, data: dict[str, Any]) -> list[Observation]:
        native = data["type"]
        kind: ProviderEventType = "provider_message"
        payload: dict[str, Any] = {"native": data}
        if native == "thread.started":
            self.session_id = safe_identifier(data.get("thread_id"))
            kind = "provider_session_started"
        elif native == "turn.completed":
            self.completed = True
            kind = "provider_usage"
            payload["usage"] = usage(data.get("usage", {}), codex=True)
        elif native in ("turn.failed", "error"):
            self.failure = error_code(json.dumps(data))
            kind = "provider_process_failed"
            # Auth errors can contain private account details even without a token.
            payload = {"error_code": self.failure}
        elif native.startswith("item."):
            item = data.get("item", {})
            category = item.get("type")
            tools = {
                "command_execution": "run_command",
                "file_change": "edit_file",
                "mcp_tool_call": "mcp_tool",
                "web_search": "web_search",
            }
            if category in tools:
                payload.update(
                    tool=tools[category],
                    native_category=category,
                    tool_id=safe_identifier(item.get("id")),
                )
                if native == "item.started":
                    kind = "provider_tool_call_started"
                elif native == "item.completed":
                    kind = "provider_tool_call_completed"
                    payload["success"] = (
                        item["exit_code"] == 0
                        if type(item.get("exit_code")) is int
                        else True
                        if item.get("status") == "completed"
                        else False
                        if item.get("status") == "failed"
                        else None
                    )
        return [Observation(kind, native, payload)]

    def _claude(self, data: dict[str, Any]) -> list[Observation]:
        native = data["type"]
        kind: ProviderEventType = "provider_message"
        payload: dict[str, Any] = {"native": data}
        observations: list[Observation] = []
        if native == "system" and data.get("subtype") == "init":
            self.session_id = safe_identifier(data.get("session_id"))
            self.model = safe_identifier(data.get("model"))
            kind = "provider_session_started"
            # Do not retain account/MCP/settings diagnostics from startup.
            payload = {"session_id": self.session_id, "model": self.model}
        elif native == "result":
            self.completed = not data.get("is_error", False) and data.get("subtype") == "success"
            if not self.completed:
                self.failure = error_code(json.dumps(data))
                return [
                    Observation(
                        "provider_process_failed",
                        native,
                        {
                            "error_code": self.failure,
                            "diagnostic": data.get("errors", data.get("result", "")),
                        },
                    )
                ]
            self.session_id = safe_identifier(data.get("session_id")) or self.session_id
            kind = "provider_usage"
            payload["usage"] = usage(data.get("usage", {}), codex=False)
        elif native in ("assistant", "user"):
            if data.get("error"):
                self.failure = error_code(json.dumps(data))
                return [
                    Observation("provider_process_failed", native, {"error_code": self.failure})
                ]
            message_id = (
                safe_identifier(data.get("message", {}).get("id"))
                if native == "assistant"
                else None
            )
            payload["native_message_id"] = message_id
            for block in data.get("message", {}).get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    tools = {
                        "Bash": "run_command",
                        "Read": "read_file",
                        "Edit": "edit_file",
                        "Write": "write_file",
                        "Grep": "search_code",
                        "Glob": "list_directory",
                    }
                    observations.append(
                        Observation(
                            "provider_tool_call_started",
                            native,
                            {
                                "tool": tools.get(name, "provider_tool"),
                                "native_category": name,
                                "tool_id": safe_identifier(block.get("id")),
                                "native_message_id": message_id,
                                "native": block,
                            },
                        )
                    )
                elif block.get("type") == "tool_result":
                    observations.append(
                        Observation(
                            "provider_tool_call_completed",
                            native,
                            {
                                "tool_id": safe_identifier(block.get("tool_use_id")),
                                "success": not block.get("is_error", False),
                                "native": block,
                            },
                        )
                    )
        # Preserve the actual message envelope once, in addition to normalized
        # tool edges. A message can contain both text and several tool blocks.
        return [Observation(kind, native, payload), *observations]


def safe_identifier(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= 200:
        return value
    return None


def usage(raw: dict[str, Any], *, codex: bool) -> dict[str, int | None]:
    mapping = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cached_input_tokens": "cached_input_tokens" if codex else "cache_read_input_tokens",
        "cache_creation_input_tokens": "cache_write_input_tokens"
        if codex
        else "cache_creation_input_tokens",
        "reasoning_tokens": "reasoning_output_tokens",
    }
    result: dict[str, int | None] = {}
    for target, source in mapping.items():
        value = raw.get(source)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("invalid usage")
        result[target] = value
    return result
