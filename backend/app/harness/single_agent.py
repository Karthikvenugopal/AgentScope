"""Single-agent execution, independent verification, and finalization."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from app.agents import CodingAgent
from app.evaluation.models import VerificationErrorCode, VerificationResult
from app.evaluation.verifier import AdaptiveBenchmarkVerifier, BenchmarkVerifier, source_digest
from app.execution import Workspace
from app.harness.artifacts import ArtifactStore
from app.harness.finalization import finalize
from app.harness.limits import RunLimits
from app.harness.snapshot import RepositorySnapshot
from app.harness.task_catalog import TaskCatalog
from app.harness.tools.base import ToolContext
from app.harness.tools.registry import ToolRegistry
from app.harness.workspace_factory import DockerWorkspaceFactory, WorkspaceFactory
from app.models.run import RunResult, RunStatus, WorkspaceMetadata
from app.providers.models import ProviderMetadata, ProviderName
from app.providers.runtime import ProviderRuntime
from app.storage.repository import RunRepository
from app.strategies.models import StrategyConfiguration, StrategyName, StrategyResult
from app.strategies.runtime import StrategyAgent
from app.strategies.single import SingleAgentStrategy, SingleContext
from app.telemetry.aggregation import RunMetricsAggregator
from app.telemetry.events import (
    AnyTraceEvent,
    CommandExecutedEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    RunTimedOutEvent,
    VerificationCompletedEvent,
    VerificationFailedEvent,
    VerificationStartedEvent,
)
from app.telemetry.recorder import TraceRecorder


class SetupCommandTimedOut(RuntimeError):
    """The trusted benchmark setup command exceeded its command budget."""


class SingleAgentHarness:
    """Own workspace, tool, limit, trace, patch, artifact, and cleanup lifecycle."""

    def __init__(
        self,
        *,
        catalog: TaskCatalog,
        workspace_factory: WorkspaceFactory | None = None,
        artifact_store: ArtifactStore | None = None,
        limits: RunLimits | None = None,
        verifier: BenchmarkVerifier | None = None,
        repository: RunRepository | None = None,
        provider_runtime: ProviderRuntime | None = None,
    ) -> None:
        self.catalog = catalog
        self.workspace_factory = workspace_factory or DockerWorkspaceFactory()
        self.artifact_store = artifact_store or ArtifactStore()
        self.limits = limits or RunLimits()
        self.verifier = verifier or AdaptiveBenchmarkVerifier(
            catalog,
            self.workspace_factory,
            max_output_bytes=self.limits.max_captured_output_bytes,
        )
        self.repository = repository
        self.provider_runtime = provider_runtime

    async def run(
        self,
        task_id: str,
        agent: CodingAgent,
        *,
        run_id: str | None = None,
        keep_workspace: bool = False,
        event_observer: Callable[[AnyTraceEvent], Awaitable[None]] | None = None,
        strategy: StrategyName = "single",
        strategy_configuration: StrategyConfiguration | None = None,
        provenance_context: dict[str, object] | None = None,
    ) -> RunResult:
        resolved_run_id = run_id or uuid.uuid4().hex
        started_at = datetime.now(UTC)
        started_monotonic = monotonic()
        recorder = TraceRecorder(resolved_run_id, observer=event_observer)
        artifacts = self.artifact_store.paths(resolved_run_id)
        await recorder.emit(
            RunStartedEvent,
            task_id=task_id,
            agent_name=agent.name,
            limits=self.limits.model_dump(mode="json"),
        )

        workspace: Workspace | None = None
        workspace_metadata: WorkspaceMetadata | None = None
        registry: ToolRegistry | None = None
        turns = 0
        git_diff = ""
        files_modified: tuple[str, ...] = ()
        failure_reason: str | None = None
        status = RunStatus.RUNNING
        verification: VerificationResult | None = None
        provenance: dict[str, object] = {}
        verification_started = 0.0
        effective_timeout = self.limits.overall_timeout_seconds
        orchestration = StrategyResult(strategy=strategy) if strategy != "single" else None
        submitted_agent = agent

        try:
            async with asyncio.timeout(self.limits.overall_timeout_seconds) as deadline:
                task = await asyncio.to_thread(self.catalog.get, task_id)
                effective_timeout = min(self.limits.overall_timeout_seconds, task.timeout_seconds)
                deadline.reschedule(
                    asyncio.get_running_loop().time()
                    + effective_timeout
                    - (monotonic() - started_monotonic)
                )
                repository = await asyncio.to_thread(self.catalog.resolve_repository, task)
                hidden = await asyncio.to_thread(self.catalog.resolve_verification, task)
                provenance = {
                    "agentscope_commit": await asyncio.to_thread(_agentscope_commit),
                    "task_version": task.version,
                    "benchmark": task.provenance.model_dump(mode="json"),
                    "source": task.repository.model_dump(mode="json"),
                    "source_sha256": await asyncio.to_thread(source_digest, repository),
                    "verification_sha256": await asyncio.to_thread(source_digest, hidden),
                    **({"experiment": provenance_context} if provenance_context else {}),
                }
                execution_factory = self.workspace_factory
                if task.environment.image and isinstance(
                    self.workspace_factory, DockerWorkspaceFactory
                ):
                    execution_factory = replace(
                        self.workspace_factory, image=task.environment.image
                    )
                workspace = await execution_factory.create(
                    repository,
                    run_id=resolved_run_id,
                    keep_workspace=keep_workspace,
                )
                if not workspace.execution_is_isolated:
                    raise RuntimeError("single-agent harness requires an isolated workspace")
                workspace_metadata = WorkspaceMetadata(
                    runtime=execution_factory.runtime_name,
                    isolated=True,
                    retained=keep_workspace,
                    host_path=str(workspace.host_path),
                    image=execution_factory.image,
                )

                if task.setup_command:
                    await self._run_setup(workspace, task.setup_command, recorder)

                snapshot = await RepositorySnapshot.capture(workspace)
                tool_context = ToolContext(
                    workspace=workspace,
                    task=task,
                    limits=self.limits,
                    recorder=recorder,
                    snapshot=snapshot,
                )

                async def execute_provider(
                    provider: ProviderName, model: str | None
                ) -> ProviderMetadata:
                    if self.provider_runtime is None or workspace is None:
                        raise RuntimeError("isolated provider execution is not configured")
                    return await self.provider_runtime.execute(
                        provider,
                        model,
                        task.model_copy(update={"verification": None}),
                        workspace,
                        self.limits,
                        recorder,
                    )

                registry = ToolRegistry(tool_context, provider_execute=execute_provider)
                if orchestration is not None:
                    agent = StrategyAgent(
                        result=orchestration,
                        configuration=strategy_configuration or StrategyConfiguration(),
                        baseline=workspace,
                        factory=execution_factory,
                        providers=self.provider_runtime,
                        limits=self.limits,
                        recorder=recorder,
                    )
                single_context = SingleContext(
                    task.model_copy(update={"verification": None}),
                    agent,
                    registry,
                    recorder,
                    self.limits,
                )
                try:
                    await SingleAgentStrategy().execute(single_context)
                finally:
                    turns = single_context.turns
                await workspace.freeze()
                final_diff = await registry.final_diff()
                git_diff = final_diff.diff
                files_modified = final_diff.files_changed
                provenance["candidate_sha256"] = await asyncio.to_thread(
                    source_digest,
                    workspace.host_path,
                )
                status = RunStatus.VERIFYING
                verification_started = monotonic()
                await recorder.emit(VerificationStartedEvent, verifier=type(self.verifier).__name__)
                try:
                    verification = await self.verifier.verify(task, workspace)
                except Exception as exc:
                    verification = VerificationResult(
                        passed=False,
                        duration_ms=(monotonic() - verification_started) * 1000,
                        error_code=VerificationErrorCode.INFRASTRUCTURE,
                        failure_reason=f"verifier crashed: {type(exc).__name__}: {exc}",
                    )
                await recorder.emit(
                    VerificationCompletedEvent if verification.passed else VerificationFailedEvent,
                    result=verification,
                )
                status = (
                    RunStatus.COMPLETED if verification.passed else RunStatus.VERIFICATION_FAILED
                )
                failure_reason = verification.failure_reason
        except SetupCommandTimedOut as exc:
            status = RunStatus.TIMED_OUT
            failure_reason = str(exc)
        except TimeoutError:
            if status is RunStatus.VERIFYING:
                verification = VerificationResult(
                    passed=False,
                    timed_out=True,
                    duration_ms=(monotonic() - verification_started) * 1000,
                    failure_reason="overall timeout during verification",
                    error_code=VerificationErrorCode.TIMEOUT,
                )
                await recorder.emit(VerificationFailedEvent, result=verification)
            status = RunStatus.TIMED_OUT
            failure_reason = f"overall run timeout exceeded: {effective_timeout}s"
        except asyncio.CancelledError:
            status = RunStatus.FAILED
            failure_reason = "run cancelled"
        except Exception as exc:
            status = RunStatus.FAILED
            failure_reason = f"{type(exc).__name__}: {exc}"
        finally:
            if workspace is not None:
                try:
                    await asyncio.shield(workspace.close())
                except Exception as exc:
                    cleanup_failure = f"workspace cleanup failed: {exc}"
                    failure_reason = (
                        f"{failure_reason}; {cleanup_failure}"
                        if failure_reason
                        else cleanup_failure
                    )
                    if status is RunStatus.COMPLETED:
                        status = RunStatus.FAILED

        finished_at = datetime.now(UTC)
        duration_ms = (monotonic() - started_monotonic) * 1000
        if status is RunStatus.COMPLETED:
            await recorder.emit(
                RunCompletedEvent,
                duration_ms=duration_ms,
                files_modified=files_modified,
            )
        elif status is RunStatus.TIMED_OUT:
            await recorder.emit(
                RunTimedOutEvent,
                duration_ms=duration_ms,
                timeout_seconds=effective_timeout,
                failure_reason=failure_reason or "run timed out",
            )
        else:
            await recorder.emit(
                RunFailedEvent,
                duration_ms=duration_ms,
                failure_reason=failure_reason or "run failed",
            )

        result = RunResult(
            run_id=resolved_run_id,
            task_id=task_id,
            agent_name=submitted_agent.name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            workspace=workspace_metadata,
            events=recorder.events,
            agent_turns=turns,
            tool_calls=registry.tool_calls if registry else 0,
            files_modified=files_modified,
            git_diff=git_diff,
            failure_reason=failure_reason,
            artifacts=artifacts,
            verification=verification,
            configuration={
                "limits": self.limits.model_dump(mode="json"),
                "image": self.workspace_factory.image,
                "agent": agent.configuration(),
            },
            provenance=provenance,
            strategy=strategy,
            orchestration=orchestration,
        )
        if strategy_configuration is not None:
            result = result.model_copy(
                update={
                    "configuration": {
                        **result.configuration,
                        "roles": strategy_configuration.model_dump(mode="json"),
                    }
                }
            )
        provider_metadata = next(
            (
                e.metadata
                for e in reversed(recorder.events)
                if hasattr(e, "metadata")
                and e.event_type in {"provider_session_completed", "provider_process_failed"}
                and e.metadata is not None
            ),
            None,
        )
        if provider_metadata is not None:
            result = result.model_copy(
                update={
                    "provenance": {
                        **provenance,
                        "provider": provider_metadata.model_dump(mode="json"),
                    }
                }
            )
        result = result.model_copy(update={"metrics": RunMetricsAggregator().aggregate(result)})
        if result.metrics is not None:
            result = result.model_copy(
                update={
                    "tool_calls": result.metrics.tool_calls
                    if orchestration is not None
                    else result.tool_calls + (result.metrics.provider_tool_calls or 0),
                }
            )
        finalization = asyncio.create_task(finalize(result, self.artifact_store, self.repository))
        try:
            return await asyncio.shield(finalization)
        except asyncio.CancelledError:
            # A database thread cannot be cancelled safely halfway through commit.
            # Finish the same transaction and return its actual outcome.
            return await finalization

    async def _run_setup(
        self,
        workspace: Workspace,
        setup_command: str,
        recorder: TraceRecorder,
    ) -> None:
        command = tuple(shlex.split(setup_command))
        if not command:
            return
        result = await workspace.execute(
            command,
            timeout_seconds=self.limits.command_timeout_seconds,
            max_output_bytes=self.limits.max_captured_output_bytes,
        )
        await recorder.emit(
            CommandExecutedEvent,
            purpose="task_setup",
            command=result.command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
        )
        if result.timed_out:
            raise SetupCommandTimedOut("task setup command timed out")
        if result.exit_code != 0:
            raise RuntimeError(f"task setup command failed with exit code {result.exit_code}")


def _agentscope_commit() -> str | None:
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
