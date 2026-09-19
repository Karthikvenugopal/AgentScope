"""Measured run metrics. None always means unavailable, never measured zero."""

from pydantic import BaseModel, ConfigDict, Field

from app.providers.models import MetricSource


class InferenceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_calls: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    mean_ttft_ms: float | None = Field(default=None, ge=0)
    mean_itl_ms: float | None = Field(default=None, ge=0)
    output_tokens_per_second: float | None = Field(default=None, ge=0)
    model_latency_ms: float | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    time_to_first_provider_output_ms: float | None = Field(default=None, ge=0)
    provenance: dict[str, MetricSource] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_wall_time_ms: float
    agent_execution_time_ms: float
    verification_time_ms: float
    agent_turns: int
    tool_calls: int
    successful_tool_calls: int
    failed_tool_calls: int
    per_tool: dict[str, int]
    files_modified: int
    lines_added: int
    lines_removed: int
    patch_bytes: int
    commands_executed: int
    agent_test_runs: int
    agent_test_time_ms: float
    retries: int = 0
    tool_failures: int
    timeouts: int
    output_truncations: int
    verification_passed: bool | None
    verification_duration_ms: float | None
    official_tests_passed: int | None
    official_tests_failed: int | None
    official_tests_total: int | None
    inference: InferenceMetrics = Field(default_factory=InferenceMetrics)
    provider_tool_calls: int | None = None
    provider_per_tool: dict[str, int] = Field(default_factory=dict)
