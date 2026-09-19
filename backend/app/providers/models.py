"""Capabilities and observations, not assumptions about model internals."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderName(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude-code"


class ProviderCapabilities(BaseModel):
    structured_output: bool = True
    streaming_events: bool = True
    token_usage: bool = True
    per_request_usage: bool = False
    model_selection: bool = True
    tool_events: bool = True
    session_ids: bool = True
    token_stream_timestamps: bool = False
    model_request_boundaries: bool = False
    session_continuation: bool = True


class ProviderAvailability(BaseModel):
    id: str
    available: bool
    version: str | None = None
    reason: str | None = None
    capabilities: ProviderCapabilities | None = None


class MetricSource(BaseModel):
    provenance: Literal["measured", "derived", "unavailable"]
    source: str | None = None


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: ProviderName
    version: str
    image: str
    image_id: str
    model: str | None = None
    session_id: str | None = None
    exit_code: int | None = None
    duration_ms: float | None = None
    time_to_first_provider_output_ms: float | None = None
    process_started_at: datetime | None = None
    process_finished_at: datetime | None = None
    process_duration_ms: float | None = None


class ProviderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ProviderFailure(RuntimeError):
    """Only a safe stable code is allowed in exceptions crossing the harness boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
