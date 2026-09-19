"""Versioned experiment specification and persisted analysis models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.harness.limits import RunLimits
from app.strategies.models import StrategyName

ExperimentId = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
]
ProviderId = Literal["codex", "claude-code"]


class ExperimentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ExperimentId
    strategy: StrategyName
    provider: ProviderId
    planner: ProviderId | None = None
    implementer: ProviderId | None = None
    reviewer: ProviderId | None = None
    implementer_count: Literal[2, 3] | None = None
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

    @model_validator(mode="after")
    def strategy_shape(self) -> ExperimentConfiguration:
        roles = (self.planner, self.implementer, self.reviewer)
        if self.strategy == "single":
            if any(role is not None for role in roles) or self.implementer_count is not None:
                raise ValueError("single configuration cannot define roles or worker count")
            return self
        if any(role is None for role in roles):
            raise ValueError("multi-agent configuration requires every role provider")
        if self.strategy == "planner_implementer_reviewer" and self.implementer_count is not None:
            raise ValueError("staged configuration cannot define implementer_count")
        if self.strategy == "parallel_implementers" and self.implementer_count is None:
            raise ValueError("parallel configuration requires implementer_count")
        return self

    @property
    def providers(self) -> frozenset[ProviderId]:
        return frozenset(
            provider
            for provider in (self.provider, self.planner, self.implementer, self.reviewer)
            if provider is not None
        )

    @property
    def maximum_provider_invocations(self) -> int:
        if self.strategy == "single":
            return 1
        if self.strategy == "planner_implementer_reviewer":
            return 4  # planner, implementer, reviewer, at most one correction
        return 2 + int(self.implementer_count or 0)

    @property
    def maximum_internal_concurrency(self) -> int:
        return int(self.implementer_count or 1)


class ExperimentBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_total_runs: int | None = Field(default=None, ge=1)
    max_provider_invocations: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_estimated_cost: float | None = Field(default=None, ge=0)


class ProviderPricing(BaseModel):
    """Explicit, versioned token pricing; never inferred from provider identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_usd_per_million_tokens: float = Field(ge=0)
    output_usd_per_million_tokens: float = Field(ge=0)


class PricingConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    providers: dict[ProviderId, ProviderPricing] = Field(min_length=1)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    experiment_id: ExperimentId
    name: str = Field(min_length=1, max_length=160)
    research_question: str = Field(min_length=1, max_length=2000)
    benchmark_name: Literal["AgentScope Benchmark"]
    benchmark_version: Literal["0.1"]
    benchmark_manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    task_ids: tuple[str, ...] = Field(min_length=1)
    configurations: tuple[ExperimentConfiguration, ...] = Field(min_length=1)
    repetitions: int = Field(ge=1, le=10)
    random_seed: int
    bootstrap_seed: int
    execution_order: Literal["stratified_random"] = "stratified_random"
    experiment_run_concurrency: Literal[1] = 1
    provider_requirements: tuple[ProviderId, ...] = Field(min_length=1)
    limits: RunLimits = Field(default_factory=RunLimits)
    budget: ExperimentBudget = Field(default_factory=ExperimentBudget)
    pricing: PricingConfiguration | None = None
    infrastructure_retry_limit: int = Field(default=2, ge=0, le=5)
    infrastructure_backoff_seconds: float = Field(default=10, ge=0, le=300)
    created_at: datetime
    notes: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def coherent(self) -> ExperimentSpec:
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task IDs must be unique")
        configuration_ids = [configuration.id for configuration in self.configurations]
        if len(set(configuration_ids)) != len(configuration_ids):
            raise ValueError("configuration IDs must be unique")
        required = frozenset(self.provider_requirements)
        configured = frozenset().union(*(c.providers for c in self.configurations))
        if required != configured:
            raise ValueError("provider_requirements must exactly match configured providers")
        if self.budget.max_total_runs is not None and self.budget.max_total_runs < self.run_count:
            raise ValueError("max_total_runs cannot be below the planned matrix size")
        if self.budget.max_estimated_cost is not None and self.pricing is None:
            raise ValueError("max_estimated_cost requires explicit pricing")
        if self.pricing is not None and configured - self.pricing.providers.keys():
            raise ValueError("pricing must cover every configured provider")
        return self

    @property
    def run_count(self) -> int:
        return len(self.task_ids) * len(self.configurations) * self.repetitions

    @property
    def estimated_provider_invocations(self) -> int:
        return (
            len(self.task_ids)
            * self.repetitions
            * sum(
                configuration.maximum_provider_invocations
                for configuration in self.configurations
            )
        )

    @property
    def maximum_internal_concurrency(self) -> int:
        return max(c.maximum_internal_concurrency for c in self.configurations)

    @property
    def spec_hash(self) -> str:
        data = self.model_dump(mode="json")
        # Preserve hashes of schema-v1 specs created before optional pricing was
        # introduced. Explicit pricing remains part of the immutable hash.
        if data.get("pricing") is None:
            data.pop("pricing", None)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


class ScheduleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scheduled_order: int = Field(ge=1)
    task_id: str
    configuration_id: str
    repetition: int = Field(ge=1)


class RawExperimentRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str
    scheduled_order: int
    task_id: str
    configuration_id: str
    strategy: StrategyName | None = None
    repetition: int
    run_id: str
    validity: Literal["valid", "infrastructure_failure", "protocol_excluded"]
    classification: Literal[
        "benchmark_success",
        "benchmark_failure",
        "infrastructure_failure",
        "protocol_excluded",
    ]
    replacement_for_run_id: str | None = None
    official_success: bool | None = None
    official_tests_passed: int | None = None
    official_tests_total: int | None = None
    task_wall_time_ms: float | None = None
    strategy_wall_time_ms: float | None = None
    summed_provider_execution_time_ms: float | None = None
    provider_invocations: int | None = None
    provider_tool_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    files_modified: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    patch_bytes: int | None = None
    corrections: int | None = None
    correction_changed_patch: bool | None = None
    correction_improved_visible_tests: bool | None = None
    candidate_count: int | None = None
    candidate_failures: int | None = None
    candidate_patch_sizes: tuple[int, ...] = ()
    peak_concurrent_provider_processes: int | None = None
    concurrency_factor: float | None = None
    selected_candidate: str | None = None
    provider_session_ids: tuple[str, ...] = ()
    estimated_provider_cost: float | None = None


def load_spec(path: Path | str) -> ExperimentSpec:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read experiment specification: {source}") from exc
    if not isinstance(raw, dict):
        raise ValueError("experiment specification must be a mapping")
    return ExperimentSpec.model_validate(raw)
