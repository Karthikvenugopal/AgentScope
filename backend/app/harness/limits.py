"""Deterministic safety limits applied to a single-agent run."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_agent_turns: int = Field(default=20, ge=1, le=10_000)
    max_tool_calls: int = Field(default=100, ge=1, le=100_000)
    command_timeout_seconds: float = Field(default=60.0, gt=0, le=86_400)
    overall_timeout_seconds: float = Field(default=600.0, gt=0, le=86_400)
    max_file_write_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_captured_output_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)


class RunLimitExceeded(RuntimeError):
    """A hard run limit was reached and the agent must stop."""
