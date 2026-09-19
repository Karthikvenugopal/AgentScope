"""Sequential, resumable experiment execution with predeclared failure rules."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal, cast

from app.agents.external import ClaudeCodeAgent, CodexAgent
from app.experiments.models import (
    ExperimentConfiguration,
    ExperimentSpec,
    RawExperimentRun,
)
from app.experiments.planner import build_schedule, validate_frozen_inputs
from app.experiments.repository import ExperimentRepository
from app.harness.artifacts import ArtifactStore
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.models.run import RunResult, RunStatus
from app.providers.models import ProviderName
from app.providers.runtime import ProviderRuntime
from app.storage.repository import PostgresRunRepository
from app.strategies.models import StrategyConfiguration
from app.telemetry.metrics import RunMetrics

INFRASTRUCTURE_MARKERS = (
    "provider_runtime_unavailable",
    "provider_unavailable",
    "provider_container_start_failed",
    "authentication",
    "credential",
    "rate limit",
    "rate_limit",
    "429",
    "service unavailable",
    "service_unavailable",
    "docker could not start",
    "docker daemon",
    "database",
    "connection refused",
    "temporary failure in name resolution",
)


def classify_result(result: RunResult) -> tuple[str, str]:
    """Apply the predeclared outcome policy without looking at treatment results."""
    if result.persistence_error:
        return "infrastructure_failure", "infrastructure_failure"
    reason = (result.failure_reason or "").lower()
    if result.status is RunStatus.TIMED_OUT and "overall run timeout exceeded" in reason:
        return "valid", "benchmark_failure"
    provider_errors = " ".join(
        str(event.model_dump(mode="json")).lower()
        for event in result.events
        if event.event_type == "provider_process_failed"
    )
    if any(marker in f"{reason} {provider_errors}" for marker in INFRASTRUCTURE_MARKERS):
        return "infrastructure_failure", "infrastructure_failure"
    if result.status is RunStatus.COMPLETED and result.verification and result.verification.passed:
        return "valid", "benchmark_success"
    # Task timeout, provider process crash during a launched session, malformed
    # role output, and official verification failure are treatment outcomes.
    return "valid", "benchmark_failure"


class ExperimentRunner:
    def __init__(
        self,
        *,
        root: Path,
        run_repository: PostgresRunRepository,
        experiment_repository: ExperimentRepository,
        provider_runtime: ProviderRuntime,
        runner_image: str = "agentscope-runner:py312",
    ) -> None:
        self.root = root
        self.benchmark_root = root / "benchmarks"
        self.catalog = TaskCatalog(self.benchmark_root)
        self.run_repository = run_repository
        self.experiments = experiment_repository
        self.providers = provider_runtime
        self.runner_image = runner_image

    async def initialize(self, spec: ExperimentSpec) -> dict[str, Any]:
        frozen = await asyncio.to_thread(
            validate_frozen_inputs, spec, self.benchmark_root
        )
        availability: dict[str, Any] = {}
        for provider_id in spec.provider_requirements:
            probe = await self.providers.probe(ProviderName(provider_id), refresh=True)
            if not probe.available:
                raise ValueError(f"required provider unavailable: {provider_id} ({probe.reason})")
            availability[provider_id] = probe.model_dump(mode="json")
        provenance = {
            **frozen,
            "agentscope_version": _agentscope_version(self.root),
            "agentscope_commit": None,
            "provider_versions": availability,
            "runner_image": self.runner_image,
            "runner_image_id": await asyncio.to_thread(_image_id, self.runner_image),
            "provider_image": self.providers.image,
            "provider_image_id": await asyncio.to_thread(_image_id, self.providers.image),
            "experiment_spec_hash": spec.spec_hash,
            "pricing": spec.pricing.model_dump(mode="json") if spec.pricing else None,
        }
        await asyncio.to_thread(
            self.experiments.create, spec, provenance, build_schedule(spec)
        )
        await asyncio.to_thread(self.experiments.recover, spec.experiment_id)
        return provenance

    async def run(self, spec: ExperimentSpec, *, max_new_runs: int | None = None) -> dict[str, Any]:
        await self.initialize(spec)
        completed_now = 0
        configurations = {configuration.id: configuration for configuration in spec.configurations}
        while max_new_runs is None or completed_now < max_new_runs:
            budget_reason = await asyncio.to_thread(self._budget_reason, spec)
            if budget_reason:
                await asyncio.to_thread(self.experiments.pause, spec.experiment_id, budget_reason)
                break
            entry = await asyncio.to_thread(self.experiments.claim, spec.experiment_id)
            if entry is None:
                await asyncio.to_thread(self.experiments.finish_if_complete, spec.experiment_id)
                break
            configuration = configurations[entry["configuration_id"]]
            attempt = int(entry["attempt_number"])
            run_id = _run_id(spec.experiment_id, int(entry["scheduled_order"]), attempt)
            started = datetime.now(UTC)
            result = await asyncio.to_thread(self.run_repository.get, run_id)
            if result is None:
                live = await self._execute(spec, configuration, entry, run_id)
                raw = raw_run(spec, entry, live, configuration, run_id)
                validity, classification = classify_result(live)
                failure_reason = live.failure_reason
                finished = live.finished_at
            else:
                raw = raw_stored_run(spec, entry, result, configuration, run_id)
                validity = raw.validity
                classification = raw.classification
                failure_reason = result.summary.get("failure_reason")
                finished = result.summary.get("finished_at") or datetime.now(UTC)
                if not isinstance(finished, datetime):
                    finished = datetime.fromisoformat(str(finished))
            raw = raw.model_copy(
                update={
                    "validity": validity,
                    "classification": classification,
                    "replacement_for_run_id": entry["replacement_for_run_id"],
                }
            )
            await asyncio.to_thread(
                self.experiments.record_attempt,
                experiment_id=spec.experiment_id,
                scheduled_order=int(entry["scheduled_order"]),
                attempt_number=attempt,
                run_id=run_id,
                validity=validity,
                classification=classification,
                replacement_for_run_id=entry["replacement_for_run_id"],
                started_at=started,
                finished_at=finished,
                failure_reason=failure_reason,
                classification_note=None,
                payload=raw.model_dump(mode="json"),
            )
            if validity == "infrastructure_failure":
                if attempt > spec.infrastructure_retry_limit:
                    await asyncio.to_thread(
                        self.experiments.pause,
                        spec.experiment_id,
                        "infrastructure retry limit reached at schedule "
                        f"{entry['scheduled_order']}",
                    )
                    break
                if spec.infrastructure_backoff_seconds:
                    await asyncio.sleep(spec.infrastructure_backoff_seconds)
                continue
            completed_now += 1
        await asyncio.to_thread(self.experiments.finish_if_complete, spec.experiment_id)
        status = await asyncio.to_thread(self.experiments.get, spec.experiment_id)
        assert status is not None
        return status

    async def _execute(
        self,
        spec: ExperimentSpec,
        configuration: ExperimentConfiguration,
        entry: dict[str, Any],
        run_id: str,
    ) -> RunResult:
        harness = SingleAgentHarness(
            catalog=self.catalog,
            workspace_factory=DockerWorkspaceFactory(image=self.runner_image),
            artifact_store=ArtifactStore(self.root / "artifacts"),
            repository=self.run_repository,
            limits=spec.limits,
            provider_runtime=self.providers,
        )
        agent = (
            CodexAgent(configuration.model)
            if configuration.provider == "codex"
            else ClaudeCodeAgent(configuration.model)
        )
        role_configuration = None
        if configuration.strategy != "single":
            role_configuration = StrategyConfiguration.model_validate(
                {
                    "planner": {"agent": configuration.planner},
                    "implementer": {"agent": configuration.implementer},
                    "implementers": {
                        "agent": configuration.implementer,
                        "count": configuration.implementer_count or 3,
                    },
                    "reviewer": {"agent": configuration.reviewer},
                }
            )
        return await harness.run(
            entry["task_id"],
            agent,
            run_id=run_id,
            strategy=configuration.strategy,
            strategy_configuration=role_configuration,
            provenance_context={
                "experiment_id": spec.experiment_id,
                "spec_hash": spec.spec_hash,
                "configuration_id": configuration.id,
                "scheduled_order": entry["scheduled_order"],
                "repetition": entry["repetition"],
            },
        )

    def _budget_reason(self, spec: ExperimentSpec) -> str | None:
        runs = self.experiments.raw_runs(spec.experiment_id)
        valid = [run for run in runs if run.validity == "valid"]
        if spec.budget.max_total_runs is not None and len(valid) >= spec.budget.max_total_runs:
            if len(valid) < spec.run_count:
                return "max_total_runs reached"
        invocations = sum(run.provider_invocations or 0 for run in runs)
        if (
            spec.budget.max_provider_invocations is not None
            and invocations >= spec.budget.max_provider_invocations
        ):
            return "max_provider_invocations reached"
        tokens = sum(run.total_tokens or 0 for run in runs)
        if spec.budget.max_tokens is not None and tokens >= spec.budget.max_tokens:
            return "max_tokens reached"
        cost = sum(run.estimated_provider_cost or 0 for run in runs)
        if (
            spec.budget.max_estimated_cost is not None
            and cost >= spec.budget.max_estimated_cost
        ):
            return "max_estimated_cost reached"
        return None


def raw_run(
    spec: ExperimentSpec,
    entry: dict[str, Any],
    result: RunResult,
    configuration: ExperimentConfiguration,
    run_id: str,
) -> RawExperimentRun:
    validity, classification = classify_result(result)
    metrics = result.metrics
    orchestration = result.orchestration
    provider_sessions: list[str] = []
    if orchestration:
        provider_sessions.extend(
            execution.provider_metadata.session_id
            for execution in orchestration.executions
            if execution.provider_metadata and execution.provider_metadata.session_id
        )
    provider = result.provenance.get("provider")
    # Multi-agent executions already enumerate every role session. The run-level
    # provider metadata mirrors the final role and must not be counted twice.
    if not orchestration and isinstance(provider, dict) and provider.get("session_id"):
        provider_sessions.append(str(provider["session_id"]))
    candidates = [
        execution
        for execution in orchestration.executions
        if orchestration and execution.candidate_id is not None
    ] if orchestration else []
    strategy_metrics = orchestration.metrics if orchestration else None
    verification = result.verification
    return RawExperimentRun(
        experiment_id=spec.experiment_id,
        scheduled_order=int(entry["scheduled_order"]),
        task_id=str(entry["task_id"]),
        configuration_id=configuration.id,
        strategy=configuration.strategy,
        repetition=int(entry["repetition"]),
        run_id=run_id,
        validity=cast(Literal["valid", "infrastructure_failure"], validity),
        classification=cast(
            Literal[
                "benchmark_success",
                "benchmark_failure",
                "infrastructure_failure",
                "protocol_excluded",
            ],
            classification,
        ),
        official_success=verification.passed if verification and validity == "valid" else None,
        official_tests_passed=verification.passed_tests if verification else None,
        official_tests_total=verification.total_tests if verification else None,
        task_wall_time_ms=metrics.total_wall_time_ms if metrics else result.duration_ms,
        strategy_wall_time_ms=(
            strategy_metrics.strategy_wall_time_ms
            if strategy_metrics
            else metrics.agent_execution_time_ms if metrics else None
        ),
        summed_provider_execution_time_ms=(
            strategy_metrics.summed_provider_execution_time_ms
            if strategy_metrics
            else _provider_duration(result)
        ),
        provider_invocations=(
            strategy_metrics.provider_invocations
            if strategy_metrics
            else sum(event.event_type == "provider_session_started" for event in result.events)
        ),
        provider_tool_calls=metrics.provider_tool_calls if metrics else None,
        input_tokens=metrics.inference.input_tokens if metrics else None,
        output_tokens=metrics.inference.output_tokens if metrics else None,
        total_tokens=metrics.inference.total_tokens if metrics else None,
        files_modified=metrics.files_modified if metrics else len(result.files_modified),
        lines_added=metrics.lines_added if metrics else None,
        lines_removed=metrics.lines_removed if metrics else None,
        patch_bytes=metrics.patch_bytes if metrics else len(result.git_diff.encode()),
        corrections=orchestration.corrections if orchestration else None,
        correction_changed_patch=orchestration.correction_changed_patch if orchestration else None,
        correction_improved_visible_tests=(
            orchestration.correction_improved_visible_tests if orchestration else None
        ),
        candidate_count=orchestration.candidate_count if orchestration else None,
        candidate_failures=sum(candidate.status != "completed" for candidate in candidates),
        candidate_patch_sizes=tuple(len(candidate.patch.encode()) for candidate in candidates),
        peak_concurrent_provider_processes=(
            strategy_metrics.peak_concurrent_provider_processes if strategy_metrics else 1
        ),
        concurrency_factor=strategy_metrics.concurrency_factor if strategy_metrics else None,
        selected_candidate=orchestration.selected_candidate if orchestration else None,
        provider_session_ids=tuple(provider_sessions),
        estimated_provider_cost=_estimated_cost(spec, configuration, metrics),
    )


def _estimated_cost(
    spec: ExperimentSpec,
    configuration: ExperimentConfiguration,
    metrics: RunMetrics | None,
) -> float | None:
    if spec.pricing is None or metrics is None or len(configuration.providers) != 1:
        return None
    if metrics.inference.input_tokens is None or metrics.inference.output_tokens is None:
        return None
    provider = next(iter(configuration.providers))
    price = spec.pricing.providers[provider]
    return (
        metrics.inference.input_tokens * price.input_usd_per_million_tokens
        + metrics.inference.output_tokens * price.output_usd_per_million_tokens
    ) / 1_000_000


def raw_stored_run(
    spec: ExperimentSpec,
    entry: dict[str, Any],
    stored: Any,
    configuration: ExperimentConfiguration,
    run_id: str,
) -> RawExperimentRun:
    # Recovery path only: reconstruct the same typed result from immutable storage.
    summary = stored.summary
    result = RunResult.model_validate(
        {
            **summary,
            "events": stored.events,
            "verification": stored.verification,
            "metrics": stored.metrics,
            "artifact_metadata": stored.artifacts,
            "git_diff": "",
            "artifacts": summary.get("artifacts"),
        }
    )
    return raw_run(spec, entry, result, configuration, run_id)


def _provider_duration(result: RunResult) -> float | None:
    provider = result.provenance.get("provider")
    if isinstance(provider, dict) and provider.get("duration_ms") is not None:
        return float(provider["duration_ms"])
    return None


def _run_id(experiment_id: str, order: int, attempt: int) -> str:
    return f"{experiment_id[:48]}-{order:03d}-a{attempt}"


def _image_id(image: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _agentscope_version(root: Path) -> str:
    try:
        installed = version("agentscope-benchmark")
        if installed not in {"0.3.0", "0.7.0", "0.8.0"}:
            return installed
    except PackageNotFoundError:
        pass
    pyproject = (root / "backend/pyproject.toml").read_text(encoding="utf-8")
    for line in pyproject.splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    return "unknown"
