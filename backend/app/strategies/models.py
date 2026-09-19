"""Bounded strategy contracts and persistable execution hierarchy."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.providers.models import ProviderMetadata, ProviderOptions
from app.telemetry.metrics import InferenceMetrics

StrategyName = Literal["single", "planner_implementer_reviewer", "parallel_implementers"]
Role = Literal["planner", "implementer", "reviewer", "correction"]


class RoleConfiguration(ProviderOptions):
    agent: Literal["mock", "codex", "claude-code"] = "mock"


class ImplementersConfiguration(RoleConfiguration):
    count: Literal[2, 3] = 3


class StrategyConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    planner: RoleConfiguration = Field(default_factory=RoleConfiguration)
    implementer: RoleConfiguration = Field(default_factory=RoleConfiguration)
    implementers: ImplementersConfiguration = Field(default_factory=ImplementersConfiguration)
    reviewer: RoleConfiguration = Field(default_factory=RoleConfiguration)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis: str = Field(max_length=16000)
    steps: list[str] = Field(min_length=1, max_length=30)
    files_likely_relevant: list[str] = Field(default_factory=list, max_length=100)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "revise"]
    issues: list[str] = Field(default_factory=list, max_length=30)
    suggested_changes: list[str] = Field(default_factory=list, max_length=30)
    selected_candidate: str | None = None
    rationale: str = Field(default="", max_length=16000)


class SubExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: str
    parent_execution_id: str
    role: Role
    provider: str
    candidate_id: str | None = None
    status: Literal["completed", "failed", "timed_out"]
    started_at: datetime
    finished_at: datetime
    duration_ms: float = Field(ge=0)
    provider_metadata: ProviderMetadata | None = None
    inference: InferenceMetrics = Field(default_factory=InferenceMetrics)
    tool_calls: int = 0
    output: str = ""
    failure_reason: str | None = None
    patch: str = ""
    files_changed: tuple[str, ...] = ()
    visible_test_exit_code: int | None = None
    visible_test_output: str = ""
    visible_test_timed_out: bool = False
    visible_test_output_truncated: bool = False


class RoleMetrics(BaseModel):
    invocations: int
    duration_ms: float
    tool_calls: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class StrategyMetrics(BaseModel):
    strategy_wall_time_ms: float = 0
    summed_execution_time_ms: float = 0
    summed_provider_execution_time_ms: float | None = None
    wall_clock_provider_execution_time_ms: float | None = None
    peak_concurrent_agents: int = 0
    peak_concurrent_provider_processes: int | None = None
    concurrency_factor: float | None = None
    concurrency_factor_provenance: Literal["derived"] = "derived"
    provider_invocations: int = 0
    provider_tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    per_role: dict[str, RoleMetrics] = Field(default_factory=dict)
    estimated_cost: float | None = None


class StrategyResult(BaseModel):
    strategy: StrategyName
    executions: list[SubExecution] = Field(default_factory=list)
    plan: Plan | None = None
    review: Review | None = None
    selected_candidate: str | None = None
    corrections: int = 0
    correction_changed_patch: bool | None = None
    correction_improved_visible_tests: bool | None = None
    # No pre-correction hidden verification is performed. Counterfactual is unmeasured.
    correction_changed_official_result: bool | None = None
    candidate_count: int = 0
    metrics: StrategyMetrics = Field(default_factory=StrategyMetrics)
